"use client";

import { useMemo, useState } from "react";

import { FactorSensitivity } from "@/components/charts/factor-sensitivity";
import { IntervalPlot, rowsFromResults } from "@/components/charts/interval-plot";
import { Provenance, ProvenanceLegend } from "@/components/provenance";
import { Section } from "@/components/section";
import { Empty, Field, Id, Meter, Panel } from "@/components/ui";
import { fixed, humanizeFactor, percent, sig, titleCase } from "@/lib/format";
import type { ExperimentResult, ResearchState } from "@/lib/types";
import type { RunView } from "@/lib/use-run";

/**
 * What the run predicted.
 *
 * Three habits from the lab's own reading guidance are built into this section
 * rather than left to the reader:
 *
 *  1. imputed conditions are surfaced first, because a sensitive factor nobody
 *     specified means the prediction describes an assumed experiment;
 *  2. MIC and log₁₀ reduction lead, and the inhibition fraction is shown last
 *     with a note when it has saturated;
 *  3. confidence and the interval are presented as part of the answer, not as
 *     a footnote to it.
 */
export function Results({ run }: { run: RunView }) {
  const state = (run.detail?.state ?? null) as ResearchState | null;
  const results = state?.results ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const nameFor = useMemo(() => {
    const names = new Map((state?.candidates ?? []).map((c) => [c.candidate_id, c.name]));
    return (id: string | null | undefined) => (id && names.get(id)) || id || "unknown candidate";
  }, [state]);

  const rows = useMemo(() => rowsFromResults(results, nameFor), [results, nameFor]);
  const selected =
    results.find((r) => r.result_id === selectedId) ??
    [...results].sort(
      (a, b) =>
        (b.measurement?.predicted_log10_reduction_vs_control ?? -Infinity) -
        (a.measurement?.predicted_log10_reduction_vs_control ?? -Infinity),
    )[0] ??
    null;

  return (
    <Section
      heading="What it predicted, and how much to trust it"
      standfirst="These are simulator outputs. The simulator's priors are coarse and uncalibrated against any dataset, so a confident-looking number can still be wrong by a decade — which is exactly why the interval and the assumptions are shown next to every figure."
      aside={<Provenance kind="simulation" />}
    >
      {!results.length ? (
        <div className="rounded-[4px] border border-line bg-panel">
          <Empty>
            {run.status === "running"
              ? "The simulator has not returned yet. Predictions appear here as the loop produces them."
              : "No predictions yet. Run discovery and the experiments it chooses will be plotted here."}
          </Empty>
        </div>
      ) : (
        <div className="space-y-5">
          <Panel
            title={`Predicted log₁₀ reduction across ${results.length} experiment${
              results.length === 1 ? "" : "s"
            }`}
            aside={
              <span className="num text-[11px] text-faint">
                click a row for its uncertainty budget
              </span>
            }
          >
            <IntervalPlot
              rows={rows}
              selectedId={selected?.result_id ?? null}
              onSelect={setSelectedId}
            />
          </Panel>

          {selected && <ResultDetail result={selected} name={nameFor(selected.candidate_id)} />}

          <ProvenanceLegend className="border-t border-line pt-5" />
        </div>
      )}
    </Section>
  );
}

function ResultDetail({ result, name }: { result: ExperimentResult; name: string }) {
  const m = result.measurement ?? {};
  const imputed = result.conditions?.imputed_fields ?? [];
  const factors = result.important_factors ?? [];
  const sensitiveImputed = factors
    .filter((f) => (f.source ?? "").startsWith("imputed"))
    .sort((a, b) => Math.abs(b.sensitivity) - Math.abs(a.sensitivity))
    .slice(0, 3);
  const saturated = (m.predicted_inhibition_fraction ?? 0) > 0.97;
  const ci = m.ci95_inhibition_fraction;

  return (
    <div className="grid items-start gap-5 lg:grid-cols-2">
      <Panel
        title={
          <span className="flex flex-wrap items-baseline gap-x-2">
            {name}
            <Id>{result.result_id}</Id>
          </span>
        }
        aside={<Provenance evidenceType={result.evidence_type} />}
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3">
          <Field
            label="Predicted MIC"
            value={m.predicted_mic_um === null || m.predicted_mic_um === undefined ? "—" : `${sig(m.predicted_mic_um, 3)} µM`}
            hint="what the literature reports, so it is what this can be compared against"
          />
          <Field
            label="log₁₀ reduction"
            value={
              m.predicted_log10_reduction_vs_control === null ||
              m.predicted_log10_reduction_vs_control === undefined
                ? "—"
                : `${fixed(m.predicted_log10_reduction_vs_control, 2)} ± ${fixed(
                    m.uncertainty_log10_reduction,
                    2,
                  )}`
            }
            hint="vs untreated control"
          />
          <Field
            label="Dose ÷ MIC"
            value={fixed(m.dose_over_mic, 2)}
            hint={
              m.dose_over_mic !== null && m.dose_over_mic !== undefined
                ? m.dose_over_mic < 0.25 || m.dose_over_mic > 4
                  ? "outside the informative window"
                  : "inside the transition region"
                : undefined
            }
            tone={
              m.dose_over_mic !== null &&
              m.dose_over_mic !== undefined &&
              (m.dose_over_mic < 0.25 || m.dose_over_mic > 4)
                ? "amber"
                : "default"
            }
          />
          <Field
            label="Inhibition fraction"
            value={fixed(m.predicted_inhibition_fraction, 3)}
            hint={saturated ? "saturated — carries little signal here" : undefined}
            tone={saturated ? "amber" : "default"}
          />
          <Field
            label="95% interval"
            value={
              Array.isArray(ci) && ci.length === 2 ? `${fixed(ci[0], 2)} – ${fixed(ci[1], 2)}` : "—"
            }
            hint="on the inhibition fraction"
          />
          <Field label="Kill rate" value={m.kill_rate_per_h === null || m.kill_rate_per_h === undefined ? "—" : `${sig(m.kill_rate_per_h, 3)} /h`} />
        </div>

        <div className="mt-5 border-t border-line pt-4">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-[11.5px] text-faint">Confidence</span>
            <span className="num text-[11px] text-faint">
              lowest near the MIC transition, by design
            </span>
          </div>
          <div className="mt-2">
            <Meter value={result.confidence} label="model confidence" />
          </div>
          {result.uncertainty_components && result.uncertainty_components.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] text-faint">
                where the spread comes from, as σ on the logit
              </div>
              <ul className="mt-2 space-y-2">
                {[...result.uncertainty_components]
                  .sort((a, b) => b.sigma_logit - a.sigma_logit)
                  .map((component) => {
                    const widest = Math.max(
                      ...result.uncertainty_components!.map((c) => c.sigma_logit),
                    );
                    return (
                      <li key={component.source}>
                        <div className="flex items-baseline gap-2">
                          <span className="truncate text-[11.5px] text-muted">
                            {humanizeFactor(component.source)}
                          </span>
                          <span className="num ml-auto text-[11px] text-faint">
                            {fixed(component.sigma_logit, 2)}
                          </span>
                        </div>
                        <div className="mt-0.5 h-[2px] bg-raised">
                          <div
                            className="h-full bg-cyan/50"
                            style={{
                              width: `${(component.sigma_logit / (widest || 1)) * 100}%`,
                            }}
                          />
                        </div>
                        {component.rationale && (
                          <p className="mt-1 max-w-[68ch] text-[11px] leading-snug text-faint">
                            {component.rationale}
                          </p>
                        )}
                      </li>
                    );
                  })}
              </ul>
            </div>
          )}
        </div>

        <dl className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-line pt-3">
          <Meta label="backend" value={result.backend ?? "—"} />
          <Meta label="assay" value={result.assay_type ?? result.conditions?.assay_type ?? "—"} />
          <Meta label="model" value={result.model_version ?? "—"} />
          <Meta
            label="validated experimentally"
            value={result.validated_experimentally ? "true" : "false"}
          />
        </dl>
      </Panel>

      <div className="space-y-5">
        {imputed.length > 0 && (
          <Panel
            title="Conditions the model supplied"
            aside={<span className="num text-[11px] text-amber">{imputed.length} assumed</span>}
          >
            <p className="max-w-[60ch] text-[12.5px] leading-relaxed text-muted">
              The spec left these out, so the simulator filled them in. Where one
              of them is also a sensitive factor, this prediction describes an
              assumed experiment — fix the spec and re-run before concluding
              anything from it.
            </p>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {imputed.map((field) => (
                <li
                  key={field}
                  className="num border border-amber/35 bg-amber/8 px-1.5 py-[3px] text-[10.5px] text-amber"
                >
                  {humanizeFactor(field)}
                </li>
              ))}
            </ul>
            {sensitiveImputed.length > 0 && (
              <p className="mt-3 border-t border-line pt-3 text-[12px] leading-relaxed text-amber">
                Most consequential of these:{" "}
                {sensitiveImputed.map((f, i) => (
                  <span key={f.factor}>
                    {i > 0 && ", "}
                    <span className="num">{humanizeFactor(f.factor)}</span>
                  </span>
                ))}
                .
              </p>
            )}
          </Panel>
        )}

        <Panel title="What drove this prediction">
          <FactorSensitivity factors={factors} />
        </Panel>

        {result.warnings && result.warnings.length > 0 && (
          <Panel title={`Simulator warnings (${result.warnings.length})`}>
            <ul className="space-y-1.5">
              {result.warnings.map((warning, i) => (
                <li key={i} className="text-[12px] leading-snug text-muted">
                  {warning}
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-[10.5px] text-faint">{label}</dt>
      <dd className="num text-[10.5px] text-muted">{titleCase(value)}</dd>
    </div>
  );
}

export { percent };
