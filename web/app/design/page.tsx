"use client";

/**
 * Target-driven design.
 *
 * The designer answers "what should I put against this organism?" by climbing a
 * ladder: a bacteriocin already in the literature, then a variant observed in a
 * sequence database, and only then a sequence it generates itself. The ladder is
 * the point of this page, so it is drawn rather than implied — a run that stops
 * at the first rung is the good outcome, and a page that showed only the final
 * candidate list would hide that.
 *
 * The three rungs carry three different kinds of claim and this page keeps them
 * apart, per the lab's rule. A known sequence is literature-derived. A natural
 * variant's sequence is observed in a database, and the accessions that observed
 * it are shown next to it. A designed sequence is a proposal and nothing more.
 * Every predicted number, on all three rungs alike, comes from the simulator and
 * is tagged as such — so a designed candidate's card carries two tags that mean
 * different things, which is correct and deliberate.
 */

import { useCallback, useEffect, useState } from "react";

import { Provenance, ProvenanceLegend } from "@/components/provenance";
import { Empty, Failure, Field, Hairline, Id, Meter, Panel, Status, Uncertainties } from "@/components/ui";
import { api } from "@/lib/api";
import { fixed, plain, residueClass, scientific, sig, titleCase } from "@/lib/format";
import type {
  DesignedCandidate,
  DesignRecommendation,
  DesignScoreComponents,
  DesignSimulationMetrics,
  DesignTier,
  KnownDesignCandidate,
  NaturalVariantCandidate,
  TargetDesignResult,
} from "@/lib/types";

const TARGETS = [
  "Listeria monocytogenes",
  "Staphylococcus aureus",
  "Escherichia coli",
  "Pseudomonas aeruginosa",
];

/** What each rung means, in the order the designer tries them. */
const TIERS: { tier: DesignTier; label: string; blurb: string }[] = [
  {
    tier: "known",
    label: "Known bacteriocin",
    blurb: "Already characterised in the literature. Preferred: nothing is invented.",
  },
  {
    tier: "natural_variant",
    label: "Natural variant",
    blurb: "A substitution actually observed in sequence databases, with accessions.",
  },
  {
    tier: "computational_design",
    label: "Computational design",
    blurb: "A generated sequence. Only reached when the rungs below fall short.",
  },
];

export default function DesignPage() {
  const [organism, setOrganism] = useState(TARGETS[0]);
  const [strain, setStrain] = useState("");
  const [knownThreshold, setKnownThreshold] = useState(0.8);
  const [naturalThreshold, setNaturalThreshold] = useState(0.85);
  const [result, setResult] = useState<TargetDesignResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.designTarget({
          target_organism: organism,
          target_strain: strain.trim() || null,
          known_threshold: knownThreshold,
          natural_threshold: naturalThreshold,
          max_known_candidates: 5,
          max_natural_variants: 5,
          max_designed_candidates: 5,
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Design failed.");
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, [organism, strain, knownThreshold, naturalThreshold]);

  // The thresholds are what make the ladder interesting, so a change re-runs:
  // raising one is how you watch the designer escalate.
  useEffect(() => {
    void load();
  }, [load]);

  const counts: Record<DesignTier, number> = {
    known: result?.known_candidates.length ?? 0,
    natural_variant: result?.natural_variant_candidates.length ?? 0,
    computational_design: result?.designed_candidates.length ?? 0,
  };

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[38px]">
            Design
          </h1>
          <Provenance kind="proposal" />
        </div>
        <p className="mt-3 max-w-[70ch] text-[14px] leading-relaxed text-muted">
          Name an organism and the designer works up from what is already known.
          It only invents a sequence when a known bacteriocin and an observed
          natural variant both fall short of the score you set. Nothing here has
          been near a bench: the sequences are candidates and every number beside
          them is a prediction.
        </p>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-5 px-4 pb-16 sm:px-6">
        <Panel title="Target">
          <div className="flex flex-wrap items-end gap-x-7 gap-y-5">
            <div>
              <div className="text-[11.5px] text-faint">Organism</div>
              <div className="mt-1 flex flex-wrap">
                {TARGETS.map((option, i) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setOrganism(option)}
                    className={`border px-2.5 py-1.5 text-[12px] italic transition-colors ${
                      organism === option
                        ? "border-cyan/50 bg-cyan/10 text-cyan"
                        : "border-line text-muted hover:text-text"
                    } ${i > 0 ? "-ml-px" : ""}`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-[11.5px] text-faint" htmlFor="strain">
                Strain <span className="text-faint/70">(optional)</span>
              </label>
              <input
                id="strain"
                value={strain}
                onChange={(event) => setStrain(event.target.value)}
                placeholder="e.g. EGD-e"
                className="num mt-1 block w-36 border border-line bg-ink px-2 py-1.5 text-[12px] text-text placeholder:text-faint/60 focus:border-cyan/50 focus:outline-none"
              />
            </div>

            {/* Two dials, and they are the experiment: each is the bar a rung
                must clear before the designer stops climbing. */}
            <Threshold
              id="known-threshold"
              label="Known must score"
              value={knownThreshold}
              onChange={setKnownThreshold}
            />
            <Threshold
              id="natural-threshold"
              label="Variant must score"
              value={naturalThreshold}
              onChange={setNaturalThreshold}
            />

            <button
              type="button"
              onClick={() => void load()}
              disabled={busy}
              className="border border-cyan/60 bg-cyan/10 px-3 py-1.5 text-[13px] text-cyan transition-colors hover:bg-cyan/18 disabled:opacity-50"
            >
              {busy ? "Designing…" : "Re-run"}
            </button>
          </div>
        </Panel>

        {error && <Failure message={error} />}

        {busy && !result && (
          <div className="border border-line bg-panel">
            <Empty>Climbing the ladder — screening literature, then variants…</Empty>
          </div>
        )}

        {result && (
          <>
            <Ladder result={result} counts={counts} />

            {result.recommendations.length > 0 && (
              <Panel
                title="What it recommends"
                aside={<Provenance kind="simulation" />}
              >
                <Recommendations items={result.recommendations} />
              </Panel>
            )}

            {result.known_candidates.length > 0 && (
              <Panel
                title={`Known bacteriocins (${result.known_candidates.length})`}
                aside={<Provenance kind="literature" />}
                bodyClassName="divide-y divide-line"
              >
                {result.known_candidates.map((candidate) => (
                  <KnownCard key={candidate.candidate_id} candidate={candidate} />
                ))}
              </Panel>
            )}

            {result.natural_variant_candidates.length > 0 && (
              <Panel
                title={`Natural variants (${result.natural_variant_candidates.length})`}
                bodyClassName="divide-y divide-line"
              >
                {result.natural_variant_candidates.map((candidate) => (
                  <VariantCard key={candidate.candidate_id} candidate={candidate} />
                ))}
              </Panel>
            )}

            {result.designed_candidates.length > 0 && (
              <Panel
                title={`Computational designs (${result.designed_candidates.length})`}
                aside={<Provenance kind="proposal" />}
                bodyClassName="divide-y divide-line"
              >
                {result.designed_candidates.map((candidate) => (
                  <DesignCard key={candidate.candidate_id} candidate={candidate} />
                ))}
              </Panel>
            )}

            {result.recommended_next_experiment?.purpose && (
              <Panel title="Recommended next experiment" aside={<Provenance kind="simulation" />}>
                <NextExperiment experiment={result.recommended_next_experiment} />
              </Panel>
            )}

            <div className="grid gap-5 lg:grid-cols-2">
              {result.uncertainties.length > 0 && (
                <Panel title="What it says it cannot know">
                  <Uncertainties items={result.uncertainties} />
                </Panel>
              )}
              {result.limitations.length > 0 && (
                <Panel title="Declared limitations">
                  <ul className="space-y-2.5">
                    {result.limitations.map((item, i) => (
                      <li key={i} className="max-w-[72ch] text-[12.5px] leading-relaxed text-muted">
                        {plain(item)}
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}
            </div>

            <FutureConcept concept={result.future_production_concept} />

            <Panel title="Provenance of this run">
              <div className="flex flex-wrap gap-x-8 gap-y-4">
                {Object.entries(result.provenance).map(([key, value]) => (
                  <Field key={key} label={key.replace(/_/g, " ")} value={String(value)} />
                ))}
                <Field
                  label="literature screened"
                  value={String(result.evidence_summary.literature_candidates_screened ?? "—")}
                />
                <Field
                  label="variants identified"
                  value={String(result.evidence_summary.natural_variants_identified ?? "—")}
                />
                <Field
                  label="designs generated"
                  value={String(result.evidence_summary.computational_designs_generated ?? "—")}
                  hint="before ranking and pruning"
                />
              </div>
              <Hairline className="my-4" />
              <ProvenanceLegend />
            </Panel>
          </>
        )}
      </div>
    </>
  );
}

function Threshold({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div>
      <label className="text-[11.5px] text-faint" htmlFor={id}>
        {label} <span className="num text-text">{value.toFixed(2)}</span>
      </label>
      <input
        id={id}
        type="range"
        min={0.1}
        max={1}
        step={0.05}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-2 block w-36 accent-cyan"
      />
    </div>
  );
}

/**
 * The ladder. A rung that produced nothing was never needed, which is the
 * single most informative thing on the page, so it is stated in words rather
 * than shown as an empty list.
 */
function Ladder({
  result,
  counts,
}: {
  result: TargetDesignResult;
  counts: Record<DesignTier, number>;
}) {
  const reached = TIERS.filter((rung) => counts[rung.tier] > 0);
  const top = reached.length ? reached[reached.length - 1] : null;
  const escalated = counts.computational_design > 0;

  return (
    <Panel
      title="Escalation"
      aside={
        <span className="num text-[11px] text-faint">
          {result.target.organism}
          {result.target.gram ? ` · gram ${result.target.gram}` : ""}
        </span>
      }
    >
      <ol className="grid gap-3 sm:grid-cols-3">
        {TIERS.map((rung, index) => {
          const n = counts[rung.tier];
          const used = n > 0;
          const isTop = top?.tier === rung.tier;
          return (
            <li
              key={rung.tier}
              className={`border px-3 py-3 ${
                used ? "border-line-strong bg-raised/40" : "border-line border-dashed opacity-60"
              }`}
            >
              <div className="flex items-baseline gap-2">
                <span className="num text-[11px] text-cyan/70">{index + 1}</span>
                <h4 className="text-[13px] font-medium text-text">{rung.label}</h4>
                <span className="num ml-auto text-[13px] text-text">{used ? n : "—"}</span>
              </div>
              <p className="mt-1.5 max-w-[42ch] text-[11.5px] leading-snug text-faint">
                {rung.blurb}
              </p>
              {isTop && (
                <p className="mt-2 text-[11px] leading-snug text-cyan">
                  Stopped here.
                </p>
              )}
            </li>
          );
        })}
      </ol>

      <p className="mt-4 max-w-[86ch] text-[12.5px] leading-relaxed text-muted">
        {escalated ? (
          <>
            No known bacteriocin and no observed variant cleared the score you
            set, so the designer generated sequences. Those are proposals: the
            further up this ladder a candidate sits, the less is actually known
            about it.
          </>
        ) : counts.natural_variant > 0 ? (
          <>
            A known bacteriocin fell short but an observed natural variant
            cleared the bar, so nothing was invented. The variant&apos;s sequence
            exists in a database — only its activity against this target is
            predicted.
          </>
        ) : (
          <>
            A known bacteriocin cleared the bar, so the designer stopped at the
            first rung and invented nothing. Raise the threshold to make it climb.
          </>
        )}
      </p>
    </Panel>
  );
}

const TIER_LABEL: Record<DesignTier, string> = {
  known: "known",
  natural_variant: "variant",
  computational_design: "design",
};

function Recommendations({ items }: { items: DesignRecommendation[] }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[46rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-line text-[11px] text-faint">
            <th className="py-2 pr-3 font-normal">#</th>
            <th className="py-2 pr-3 font-normal">Candidate</th>
            <th className="py-2 pr-3 font-normal">Rung</th>
            <th className="py-2 pr-3 font-normal">Score</th>
            <th className="py-2 pr-3 font-normal">Predicted inhibition</th>
            <th className="py-2 pr-3 font-normal">Confidence</th>
            <th className="py-2 pr-3 font-normal">Evidence</th>
            <th className="py-2 font-normal">Validated</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.candidate_id ?? item.name}-${index}`} className="border-b border-line/60">
              <td className="num py-2.5 pr-3 text-[11px] text-cyan/70">
                {String(index + 1).padStart(2, "0")}
              </td>
              <td className="py-2.5 pr-3">
                <div className="text-[12.5px] text-text">{titleCase(item.name)}</div>
                {item.mutations.length > 0 && (
                  <div className="num mt-0.5 text-[10.5px] text-faint">
                    {item.mutations.join(", ")}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-3">
                <span className="num text-[10.5px] text-muted">{TIER_LABEL[item.tier]}</span>
              </td>
              <td className="num py-2.5 pr-3 text-[12px] text-text">{fixed(item.score, 3)}</td>
              <td className="py-2.5 pr-3">
                <div className="w-24">
                  <Meter value={item.predicted_inhibition} label={`predicted inhibition for ${item.name}`} />
                </div>
              </td>
              <td className="py-2.5 pr-3">
                <Status status={item.confidence} />
              </td>
              <td className="num py-2.5 pr-3 text-[12px] text-muted">
                {item.evidence_count ?? "—"}
              </td>
              {/* Always false. It is shown because a column of falses is the
                  honest answer to "has any of this been tested?" */}
              <td className="num py-2.5 text-[12px]">
                <span className={item.experimentally_validated ? "text-text" : "text-amber"}>
                  {item.experimentally_validated ? "true" : "false"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Sequence({ sequence }: { sequence: string }) {
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="text-[11px] text-faint">sequence</span>
        <span className="num text-[10.5px] text-faint">{sequence.length} residues</span>
      </div>
      <p className="num mt-1 break-all text-[11.5px] leading-[1.7] tracking-tight">
        {sequence.split("").map((residue, i) => (
          <span key={i} className={residueClass(residue)}>
            {residue}
          </span>
        ))}
      </p>
    </div>
  );
}

/** Predicted figures, always under a simulation tag. */
function Predictions({ metrics }: { metrics?: DesignSimulationMetrics }) {
  if (!metrics) return null;
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-4">
      <Field label="predicted inhibition" value={fixed(metrics.predicted_inhibition, 3)} tone="cyan" />
      <Field label="log₁₀ reduction" value={fixed(metrics.predicted_log10_reduction, 2)} tone="cyan" />
      <Field
        label="MIC"
        value={
          metrics.predicted_mic_um === null || metrics.predicted_mic_um === undefined
            ? "—"
            : `${scientific(metrics.predicted_mic_um)} µM`
        }
        tone="cyan"
      />
      <Field label="confidence" value={fixed(metrics.confidence, 3)} />
    </div>
  );
}

const COMPONENT_MEANING: Record<string, string> = {
  predicted_activity: "simulated activity against this target",
  target_match: "known to act on this organism",
  environmental_robustness: "holds up in the stated conditions",
  evidence_quality: "how much literature backs it",
  natural_support: "observed in nature",
  novelty_value: "untested, so informative",
  uncertainty_penalty: "deducted for what is unknown",
  unsupported_design_penalty: "deducted for unsupported invention",
};

function Components({ components }: { components: DesignScoreComponents }) {
  const entries = Object.entries(components).filter(
    ([, value]) => typeof value === "number" && value !== 0,
  ) as [string, number][];
  if (!entries.length) return null;
  return (
    <details className="group">
      <summary className="cursor-pointer text-[11.5px] text-faint transition-colors hover:text-muted">
        Score components
      </summary>
      <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <li key={key} className="flex items-baseline gap-2">
            <span className="truncate text-[11px] text-muted" title={COMPONENT_MEANING[key] ?? key}>
              {titleCase(key)}
            </span>
            <span
              className={`num ml-auto text-[11px] ${value < 0 ? "text-amber" : "text-faint"}`}
            >
              {value > 0 ? "+" : ""}
              {fixed(value, 3)}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function CardShell({
  title,
  id,
  score,
  tags,
  children,
}: {
  title: string;
  id: string;
  score: number;
  tags: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <article className="px-4 py-4 first:pt-0 last:pb-0">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <h3 className="text-[14px] font-medium text-text">{titleCase(title)}</h3>
        <Id>{id}</Id>
        <div className="ml-auto flex items-center gap-4">
          <div className="w-24">
            <Meter value={score} label={`score for ${title}`} />
          </div>
          {tags}
        </div>
      </header>
      <div className="mt-3.5 space-y-3.5">{children}</div>
    </article>
  );
}

function KnownCard({ candidate }: { candidate: KnownDesignCandidate }) {
  return (
    <CardShell
      title={candidate.name}
      id={candidate.candidate_id}
      score={candidate.score}
      tags={<Provenance evidenceType={candidate.provenance} />}
    >
      <div className="flex flex-wrap gap-x-7 gap-y-3">
        <Field label="class" value={candidate.bacteriocin_class?.replace(/_/g, " ") ?? "—"} />
        <Field
          label="citations"
          value={String(candidate.evidence_count ?? "—")}
          hint="abstracts, not verification"
        />
        <Field
          label="known targets"
          value={candidate.known_targets?.length ? candidate.known_targets.join(", ") : "—"}
        />
      </div>
      <Sequence sequence={candidate.sequence} />
      <Predictions metrics={candidate.simulation_metrics} />
      <Components components={candidate.components} />
    </CardShell>
  );
}

function VariantCard({ candidate }: { candidate: NaturalVariantCandidate }) {
  const accessions = candidate.observed_accessions ?? [];
  return (
    <CardShell
      title={candidate.name}
      id={candidate.candidate_id}
      score={candidate.score}
      /* Not a proposal: this substitution was observed. The accessions below
         are the whole claim, so the raw provenance string is shown as given. */
      tags={<span className="num text-[10px] text-muted">{candidate.provenance}</span>}
    >
      <div className="flex flex-wrap gap-x-7 gap-y-3">
        <Field label="substitution" value={candidate.mutation ?? "—"} tone="cyan" />
        <Field label="position" value={String(candidate.protein_position ?? "—")} />
        <Field label="parent" value={candidate.parent_candidate_id.replace(/_/g, " ")} />
        <Field
          label="observed in"
          value={accessions.length ? accessions.join(", ") : "—"}
          hint={accessions.length ? "database accessions" : "no accession reported"}
        />
      </div>
      <Sequence sequence={candidate.sequence} />
      <Predictions metrics={candidate.simulation_metrics} />
      <Components components={candidate.components} />
    </CardShell>
  );
}

const ORIGIN_LABEL: Record<string, string> = {
  natural_homolog: "seen in a homolog",
  conservative_substitution: "conservative swap",
  model_ranked_substitution: "model-ranked",
};

function DesignCard({ candidate }: { candidate: DesignedCandidate }) {
  const properties = candidate.rationale?.expected_properties ?? [];
  const support = candidate.rationale?.natural_variant_support ?? [];
  const uncertaintyParts = candidate.uncertainty?.components ?? [];
  const observed = candidate.mutations.some((m) => (m.supporting_accessions ?? []).length > 0);
  // A design reports its confidence under `uncertainty`, not with the simulator
  // metrics, so without this the row reads as a missing value.
  const metrics = {
    ...candidate.simulation_metrics,
    confidence: candidate.simulation_metrics?.confidence ?? candidate.uncertainty?.confidence,
  };

  return (
    <CardShell
      title={`Design ${candidate.candidate_id}`}
      id={candidate.candidate_id}
      score={candidate.score}
      tags={
        <>
          <Provenance kind="proposal" />
          {candidate.critic_verdict && <Status status={candidate.critic_verdict} />}
        </>
      }
    >
      <div className="flex flex-wrap gap-x-7 gap-y-3">
        <Field label="parent" value={candidate.parent_candidate_id.replace(/_/g, " ")} />
        <Field label="design class" value={candidate.design_class?.replace(/_/g, " ") ?? "—"} />
        <Field label="generation" value={String(candidate.generation ?? "—")} />
        <Field
          label="rationale status"
          value={candidate.rationale?.status ?? "hypothesis"}
          tone="amber"
        />
      </div>

      {candidate.mutations.length > 0 && (
        <div>
          <div className="text-[11px] text-faint">Mutations</div>
          <ul className="mt-1.5 space-y-1.5">
            {candidate.mutations.map((mutation, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                <span className="num text-[12px] text-cyan">
                  {mutation.reference}
                  {mutation.position}
                  {mutation.alternate}
                </span>
                <span className="text-[11px] text-faint">
                  {ORIGIN_LABEL[mutation.origin] ?? mutation.origin.replace(/_/g, " ")}
                </span>
                {mutation.supporting_accessions && mutation.supporting_accessions.length > 0 ? (
                  <span className="num text-[10.5px] text-muted">
                    {mutation.supporting_accessions.join(", ")}
                  </span>
                ) : (
                  // An invented substitution with nothing observing it is the
                  // weakest thing the designer emits. Say so on the line.
                  <span className="text-[10.5px] text-amber">nothing observed supports it</span>
                )}
                {mutation.rationale && (
                  <span className="max-w-[48ch] text-[11.5px] leading-snug text-muted">
                    {plain(mutation.rationale)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Sequence sequence={candidate.sequence} />
      <Predictions metrics={metrics} />

      <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {properties.length > 0 && (
          <div>
            <h4 className="text-[11.5px] text-faint">Expected, if the hypothesis holds</h4>
            <ul className="mt-1.5 space-y-1">
              {properties.map((item, i) => (
                <li key={i} className="num text-[11.5px] leading-snug text-muted">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          {support.length > 0 && (
            <>
              {/* The backend files these under "natural_variant_support" even
                  when no accession observes them, so the heading is only earned
                  when a mutation actually carries one. Calling an invented
                  substitution natural support would merge two kinds of claim. */}
              <h4 className="text-[11.5px] text-faint">
                {observed ? "Natural support" : "Substitutions in the rationale"}
              </h4>
              <p className="num mt-1.5 text-[11.5px] text-muted">{support.join(", ")}</p>
              {!observed && (
                <p className="mt-1 max-w-[40ch] text-[11px] leading-snug text-amber">
                  No database accession observes any of these.
                </p>
              )}
            </>
          )}
          {uncertaintyParts.length > 0 && (
            <>
              <h4 className="mt-3 text-[11.5px] text-faint">Sources of uncertainty</h4>
              <p className="mt-1.5 text-[11.5px] leading-snug text-muted">
                {uncertaintyParts.map((part) => part.replace(/_/g, " ")).join(" · ")}
              </p>
            </>
          )}
        </div>
      </div>

      {candidate.critic_notes && candidate.critic_notes.length > 0 && (
        <div className="border-l-2 border-amber/50 pl-3">
          <div className="text-[11px] text-faint">Critic</div>
          <ul className="mt-0.5 space-y-1">
            {candidate.critic_notes.map((note, i) => (
              <li key={i} className="max-w-[76ch] text-[12px] leading-relaxed text-muted">
                {plain(note)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Components components={candidate.components} />
    </CardShell>
  );
}

function NextExperiment({
  experiment,
}: {
  experiment: TargetDesignResult["recommended_next_experiment"];
}) {
  const concentrations = experiment.suggested_concentrations_um ?? [];
  return (
    <div className="space-y-3.5">
      <div className="flex flex-wrap gap-x-7 gap-y-3">
        <Field label="type" value={experiment.experiment_type?.replace(/_/g, " ") ?? "—"} />
        <Field label="candidate" value={experiment.candidate_id?.replace(/_/g, " ") ?? "—"} />
        <Field label="assay" value={experiment.recommended_assay?.replace(/_/g, " ") ?? "—"} />
      </div>
      {experiment.purpose && (
        <p className="max-w-[84ch] text-[12.5px] leading-relaxed text-muted">
          {plain(experiment.purpose)}
        </p>
      )}
      {concentrations.length > 0 && (
        <div>
          <div className="text-[11px] text-faint">Suggested concentrations (µM)</div>
          <div className="num mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-text">
            {concentrations.map((value, i) => (
              <span key={i}>{sig(value, 3)}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The production concept, which deliberately contains no protocol. It is shown
 * because the backend emits it, and shown as a closed door because that is what
 * it is — the notes say the work is out of scope, not pending.
 */
function FutureConcept({
  concept,
}: {
  concept: TargetDesignResult["future_production_concept"];
}) {
  const notes = concept.notes ?? [];
  return (
    <Panel
      title="Making it, eventually"
      aside={<Status status={concept.status ?? "requires_specialist_review"} />}
    >
      <div className="flex flex-wrap gap-x-7 gap-y-3">
        <Field label="producer compatibility" value={concept.producer_compatibility ?? "unknown"} tone="amber" />
      </div>
      {concept.candidate_peptide && (
        <div className="mt-3.5">
          <Sequence sequence={concept.candidate_peptide} />
        </div>
      )}
      {notes.length > 0 && (
        <ul className="mt-3.5 space-y-2">
          {notes.map((note, i) => (
            <li key={i} className="max-w-[80ch] text-[12.5px] leading-relaxed text-muted">
              {plain(note)}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
