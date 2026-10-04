"use client";

/**
 * The bench: run a dose sweep against the simulator directly.
 *
 * The sweep spans 0.25× to 4× the predicted MIC because that is the window
 * where the outcome is not already known — far above or below it returns the
 * answer you have. Each point is a separate simulated experiment, batched
 * through the simulator's own `run_experiments`, which isolates per-spec
 * failures instead of losing the sweep.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { DoseResponse, type DosePoint } from "@/components/charts/dose-response";
import { FactorSensitivity } from "@/components/charts/factor-sensitivity";
import { Provenance } from "@/components/provenance";
import { Empty, Failure, Field, Id, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { humanizeFactor, sig } from "@/lib/format";
import type { ExperimentResult, KnowledgeRecord } from "@/lib/types";

interface Reference {
  id: string;
  name: string;
  sequence: string;
  species: string;
}

const DENSITIES = [1e4, 1e6, 1e8];
const TIMES = [6, 18, 24];

/**
 * Sweeps start from the candidate agent's own curated records, fetched from the
 * API. The front end keeps no copy of a sequence: one source of truth means a
 * sweep run here is comparable with what a discovery run produces.
 */
function toReference(record: KnowledgeRecord): Reference | null {
  if (!record.sequence) return null;
  return {
    id: record.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    name: record.name,
    sequence: record.sequence,
    species: record.known_targets?.[0] ?? "Listeria monocytogenes",
  };
}

export default function ExperimentsPage() {
  const [references, setReferences] = useState<Reference[]>([]);
  const [sourceName, setSourceName] = useState<string | null>(null);
  const [reference, setReference] = useState<Reference | null>(null);
  const [density, setDensity] = useState(1e6);
  const [hours, setHours] = useState(18);
  const [results, setResults] = useState<ExperimentResult[]>([]);
  const [anchorMic, setAnchorMic] = useState<number | null>(null);
  const [state, setState] = useState<"idle" | "probing" | "sweeping" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .referenceBacteriocins()
      .then((r) => {
        const list = r.records.map(toReference).filter((x): x is Reference => x !== null);
        setReferences(list);
        setSourceName(r.source_name);
        setReference((current) => current ?? list[0] ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const candidateRegistry = useMemo(
    () =>
      reference
        ? {
            [reference.id]: {
              candidate_id: reference.id,
              name: reference.name,
              sequence: reference.sequence,
            },
          }
        : {},
    [reference],
  );

  const spec = useCallback(
    (doseUm: number, index: number) => ({
      experiment_id: `sweep-${reference?.id ?? "none"}-${index}`,
      candidate_id: reference?.id,
      target: { species: reference?.species },
      conditions: {
        bacteriocin_concentration: { value: doseUm, unit: "uM" },
        target_cell_density: { value: density, unit: "cfu_per_ml" },
        ph: 7.0,
        temperature_c: 37.0,
        medium: "bhi",
        incubation_time: hours,
        growth_phase: "exponential",
        assay_domain: "simulated_in_vitro",
        assay_type: "microtiter_growth_inhibition",
      },
    }),
    [reference, density, hours],
  );

  const sweep = useCallback(async () => {
    if (!reference) return;
    setError(null);
    setState("probing");
    setResults([]);
    try {
      // One probe at a nominal dose, only to read the MIC the model predicts,
      // so the sweep can be centred on this candidate's own transition.
      const probe = await api.experiment({ spec: spec(1, 0), candidate_registry: candidateRegistry });
      const mic = probe.measurement?.predicted_mic_um ?? null;
      setAnchorMic(mic);

      const centre = mic && Number.isFinite(mic) && mic > 0 ? mic : 1;
      const multipliers = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4];
      setState("sweeping");
      const batch = await api.experiments({
        specs: multipliers.map((m, i) => spec(centre * m, i + 1)),
        candidate_registry: candidateRegistry,
      });
      setResults(batch.results);
      setState("done");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The sweep failed.");
      setState("idle");
    }
  }, [spec, candidateRegistry, reference]);

  useEffect(() => {
    setResults([]);
    setState("idle");
    setAnchorMic(null);
  }, [reference, density, hours]);

  const points: DosePoint[] = results
    .map((r) => {
      const dose = r.conditions?.bacteriocin_concentration;
      const doseValue = typeof dose === "object" && dose ? dose.value : (dose as number | null);
      const ci = r.measurement?.ci95_inhibition_fraction;
      return {
        dose: doseValue ?? 0,
        inhibition: r.measurement?.predicted_inhibition_fraction ?? null,
        low: Array.isArray(ci) ? (ci[0] ?? null) : null,
        high: Array.isArray(ci) ? (ci[1] ?? null) : null,
        log10Reduction: r.measurement?.predicted_log10_reduction_vs_control ?? null,
        confidence: r.confidence ?? null,
      };
    })
    .filter((p) => p.dose > 0)
    .sort((a, b) => a.dose - b.dose);

  const atMic = results.find((r) => {
    const ratio = r.measurement?.dose_over_mic;
    return ratio !== null && ratio !== undefined && Math.abs(ratio - 1) < 0.3;
  });

  /**
   * The MIC the model reports is not quite constant across the sweep — it is
   * re-derived per experiment, and decay over the incubation shifts it. The
   * reference line therefore comes from the sweep's own median rather than
   * from the single probe, so the line and the table cannot contradict
   * each other.
   */
  const mics = results
    .map((r) => r.measurement?.predicted_mic_um)
    .filter((m): m is number => typeof m === "number" && Number.isFinite(m))
    .sort((a, b) => a - b);
  const medianMic = mics.length ? mics[Math.floor(mics.length / 2)] : anchorMic;
  const micSpread = mics.length > 1 ? mics[mics.length - 1] / mics[0] : 1;

  // An interval covering most of the axis is the model saying it cannot
  // resolve the outcome at that dose, which is worth saying in words.
  const widestBand = Math.max(
    0,
    ...points.map((p) => (p.low !== null && p.high !== null ? p.high - p.low : 0)),
  );
  const busy = state === "probing" || state === "sweeping";

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <h1 className="text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[38px]">
          Experiments
        </h1>
        <p className="mt-3 max-w-[66ch] text-[14px] leading-relaxed text-muted">
          Run a dose sweep against the simulator. The sweep is centred on the
          MIC the model predicts for this candidate, from a quarter of it to
          four times it, because that is the band where the result is not
          already obvious.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Provenance kind="simulation" />
          <span className="text-[12.5px] text-faint">
            Predictions, not measurements. Incubation time is a real variable
            here — the model integrates peptide decay against regrowth, so 6 h
            and 24 h of the same conditions are different experiments.
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-5 px-4 pb-10 sm:px-6">
        <Panel title="Sweep setup">
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="space-y-4">
              <Chooser
                label="Candidate"
                hint="sequence is passed to the simulator, so the prediction is specific to it"
                options={references.map((r) => ({ key: r.id, label: r.name }))}
                value={reference?.id ?? ""}
                onChange={(key) => setReference(references.find((r) => r.id === key) ?? null)}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <Chooser
                  label="Target cell density"
                  hint="CFU/mL, per decade"
                  options={DENSITIES.map((d) => ({ key: String(d), label: `1e${Math.log10(d)}` }))}
                  value={String(density)}
                  onChange={(key) => setDensity(Number(key))}
                />
                <Chooser
                  label="Incubation time"
                  hint="hours"
                  options={TIMES.map((t) => ({ key: String(t), label: `${t} h` }))}
                  value={String(hours)}
                  onChange={(key) => setHours(Number(key))}
                />
              </div>
              <p className="num text-[11px] leading-relaxed text-faint">
                target {reference?.species ?? "—"}, pH 7.0, 37 °C, BHI
                {sourceName && <span className="ml-3">knowledge source {sourceName}</span>}
              </p>
            </div>
            <div className="flex flex-col justify-between gap-4 md:w-[16rem]">
              <div className="break-all border border-line bg-ink px-3 py-2.5">
                <div className="text-[11px] text-faint">sequence</div>
                {reference ? (
                  <Sequence sequence={reference.sequence} />
                ) : (
                  <p className="num mt-1 text-[11px] text-faint">loading…</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => void sweep()}
                disabled={busy || !reference}
                className="border border-cyan/60 bg-cyan/12 px-4 py-2.5 text-[13.5px] text-cyan transition-colors hover:bg-cyan/20 disabled:cursor-not-allowed disabled:border-line disabled:bg-transparent disabled:text-faint"
              >
                {state === "probing"
                  ? "Finding the MIC…"
                  : state === "sweeping"
                    ? "Running 8 experiments…"
                    : "Run dose sweep"}
              </button>
            </div>
          </div>
        </Panel>

        {error && <Failure message={error} />}

        {!results.length && !busy && !error && (
          <div className="border border-line bg-panel">
            <Empty>
              Pick a candidate and run the sweep. Eight simulated experiments
              around its predicted MIC, with the uncertainty on each.
            </Empty>
          </div>
        )}

        {points.length > 0 && (
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Panel
              title={`${reference?.name ?? "Candidate"} against ${reference?.species ?? "target"}`}
              aside={<Provenance kind="simulation" />}
            >
              <DoseResponse
                points={points}
                mic={medianMic}
                label={`1e${Math.log10(density)} CFU/mL, ${hours} h incubation`}
              />
              {widestBand > 0.8 && (
                <p className="mt-3 max-w-[70ch] border-t border-line pt-3 text-[11.5px] leading-relaxed text-faint">
                  The interval spans almost the whole axis at the lower doses.
                  That is the model reporting that it cannot resolve the
                  outcome there, not a rendering fault — below the MIC a small
                  error in the potency prior moves the predicted response from
                  nothing to everything.
                </p>
              )}
              {micSpread > 1.2 && (
                <p className="mt-2 max-w-[70ch] text-[11.5px] leading-relaxed text-faint">
                  The MIC is re-derived for each experiment and ranged over{" "}
                  <span className="num">{sig(mics[0], 2)}</span>–
                  <span className="num">{sig(mics[mics.length - 1], 2)} µM</span>{" "}
                  across this sweep; the rule marks the median.
                </p>
              )}
            </Panel>

            <div className="space-y-5">
              <Panel title="At the transition">
                {atMic ? (
                  <>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-5">
                      <Field
                        label="Predicted MIC"
                        value={`${sig(atMic.measurement?.predicted_mic_um, 3)} µM`}
                        hint={
                          medianMic && Math.abs(medianMic - (atMic.measurement?.predicted_mic_um ?? 0)) > 1e-9
                            ? `this experiment's own value; the sweep's median is ${sig(medianMic, 3)} µM`
                            : undefined
                        }
                      />
                      <Field
                        label="log₁₀ reduction"
                        value={sig(atMic.measurement?.predicted_log10_reduction_vs_control, 3)}
                      />
                      <Field label="Confidence" value={sig(atMic.confidence, 2)} />
                      <Field
                        label="Free peptide"
                        value={`${sig(atMic.measurement?.free_peptide_concentration_um, 3)} µM`}
                        hint="after binding and decay"
                      />
                    </div>
                    <p className="mt-4 border-t border-line pt-3 text-[12px] leading-relaxed text-faint">
                      Confidence is at its lowest here on purpose. Near the MIC
                      a small change in dose moves the outcome a lot, so a wide
                      interval at this point is the model behaving correctly.
                    </p>
                  </>
                ) : (
                  <Empty>No sweep point landed close enough to the MIC to report.</Empty>
                )}
              </Panel>

              {atMic?.important_factors && (
                <Panel title="What drove it">
                  <FactorSensitivity factors={atMic.important_factors} max={6} />
                </Panel>
              )}
            </div>
          </div>
        )}

        {results.length > 0 && (
          <Panel title="Every point in the sweep" bodyClassName="">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[46rem] border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    {[
                      "dose µM",
                      "dose ÷ MIC",
                      "inhibition",
                      "95% interval",
                      "log₁₀ reduction",
                      "confidence",
                      "assumed",
                      "result",
                    ].map((head) => (
                      <th
                        key={head}
                        scope="col"
                        className="px-3 py-2 text-[11px] font-normal text-faint"
                      >
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="num">
                  {results.map((r) => {
                    const dose = r.conditions?.bacteriocin_concentration;
                    const doseValue =
                      typeof dose === "object" && dose ? dose.value : (dose as number | null);
                    const ci = r.measurement?.ci95_inhibition_fraction;
                    const imputed = r.conditions?.imputed_fields ?? [];
                    return (
                      <tr key={r.result_id} className="border-b border-line/50 last:border-b-0">
                        <td className="px-3 py-2 text-[11.5px] text-text">{sig(doseValue, 3)}</td>
                        <td className="px-3 py-2 text-[11.5px] text-muted">
                          {sig(r.measurement?.dose_over_mic, 2)}
                        </td>
                        <td className="px-3 py-2 text-[11.5px] text-muted">
                          {sig(r.measurement?.predicted_inhibition_fraction, 3)}
                        </td>
                        <td className="px-3 py-2 text-[11.5px] text-faint">
                          {Array.isArray(ci) && ci.length === 2
                            ? `${sig(ci[0], 2)} – ${sig(ci[1], 2)}`
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-[11.5px] text-muted">
                          {sig(r.measurement?.predicted_log10_reduction_vs_control, 3)}
                        </td>
                        <td className="px-3 py-2 text-[11.5px] text-muted">{sig(r.confidence, 2)}</td>
                        <td className="px-3 py-2 text-[11px] text-amber" title={imputed.map(humanizeFactor).join(", ")}>
                          {imputed.length || "—"}
                        </td>
                        <td className="px-3 py-2">
                          <Id>{r.result_id}</Id>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </>
  );
}

function Chooser({
  label,
  hint,
  options,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div>
      <div className="text-[11.5px] text-faint">
        {label}
        {hint && <span className="ml-1.5 text-faint/75">{hint}</span>}
      </div>
      <div className="mt-1 flex flex-wrap">
        {options.map((option, i) => (
          <button
            key={option.key}
            type="button"
            onClick={() => onChange(option.key)}
            className={`num border px-2.5 py-1.5 text-[12px] transition-colors ${
              value === option.key
                ? "border-cyan/50 bg-cyan/10 text-cyan"
                : "border-line text-muted hover:text-text"
            } ${i > 0 ? "-ml-px" : ""}`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Residues coloured by class: basic, acidic, cysteine, hydrophobic. */
function Sequence({ sequence }: { sequence: string }) {
  return (
    <p className="num mt-1 text-[11px] leading-[1.6] tracking-tight">
      {sequence.split("").map((residue, i) => (
        <span
          key={i}
          className={
            "KRH".includes(residue)
              ? "text-cyan"
              : "DE".includes(residue)
                ? "text-red"
                : residue === "C"
                  ? "text-amber"
                  : "text-muted"
          }
        >
          {residue}
        </span>
      ))}
    </p>
  );
}
