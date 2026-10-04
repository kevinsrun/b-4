"use client";

import { Section } from "@/components/section";
import { Empty, Field, Id, Meter, Panel, Status } from "@/components/ui";
import { fixed, plain } from "@/lib/format";
import type { Hypothesis, ResearchState as State } from "@/lib/types";
import type { RunView } from "@/lib/use-run";

/**
 * The lab's memory.
 *
 * The rules the state enforces are reported here as the state reports them,
 * not softened: a hypothesis that went supported then weakened keeps both
 * states and is not described as false; an inconclusive result leaves a
 * hypothesis untouched; and a hypothesis whose last two decisive results
 * disagree is contested, which means unsettled rather than decided.
 */
export function ResearchStateSection({ run }: { run: RunView }) {
  const state = (run.detail?.state ?? null) as State | null;
  const hypotheses = state?.hypotheses ?? [];
  const digest = run.digest;

  const byStatus = hypotheses.reduce<Record<string, number>>((acc, h) => {
    acc[h.status] = (acc[h.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <Section
      heading="The state remembers what it believed, and when it changed"
      standfirst="History is never overwritten. The research state is an append-only, hash-chained log, so a belief that moved keeps both of its states and the experiment that moved it stays attached."
      aside={
        digest ? (
          <div className="flex gap-6">
            <Field label="iterations" value={digest.iteration} />
            <Field label="log events" value={digest.scientific_history} />
          </div>
        ) : null
      }
    >
      {!hypotheses.length ? (
        <div className="border border-line bg-panel">
          <Empty>
            {run.status === "running"
              ? "Hypotheses appear as the candidate agent proposes them."
              : "No state yet. A run populates the hypotheses, findings and open questions here."}
          </Empty>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
            {[
              ["supported", byStatus.supported ?? 0],
              ["open", byStatus.open ?? 0],
              ["weakened", byStatus.weakened ?? 0],
              ["contradicted", (byStatus.contradicted ?? 0) + (byStatus.rejected ?? 0)],
            ].map(([label, count]) => (
              <div key={String(label)} className="bg-panel px-4 py-3.5">
                <Field label={String(label)} value={String(count)} />
              </div>
            ))}
          </div>

          <Panel
            title={`Hypotheses (${hypotheses.length})`}
            aside={
              <span className="num text-[11px] text-faint">
                status, then prior → posterior
              </span>
            }
            bodyClassName=""
          >
            <ul className="divide-y divide-line/60">
              {hypotheses.slice(0, 12).map((h) => (
                <HypothesisRow key={h.hypothesis_id} hypothesis={h} />
              ))}
            </ul>
            {hypotheses.length > 12 && (
              <p className="border-t border-line px-4 py-2.5 text-[11.5px] text-faint">
                {hypotheses.length - 12} more in the run&rsquo;s full state.
              </p>
            )}
          </Panel>

          {state?.knowledge_gaps && state.knowledge_gaps.length > 0 && (
            <Panel title={`Still open (${state.knowledge_gaps.length})`}>
              <ul className="space-y-2">
                {state.knowledge_gaps.map((gap, i) => (
                  <li key={i} className="max-w-[80ch] text-[12.5px] leading-relaxed text-muted">
                    {gap}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}
    </Section>
  );
}

function HypothesisRow({ hypothesis }: { hypothesis: Hypothesis }) {
  const moved = Math.abs(hypothesis.posterior_probability - hypothesis.prior_plausibility) > 0.01;
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <Status status={hypothesis.status} />
        <Id>{hypothesis.hypothesis_id}</Id>
        <span className="num ml-auto text-[11px] text-faint">
          {fixed(hypothesis.prior_plausibility, 2)}
          <span className={moved ? "text-cyan" : ""}> → {fixed(hypothesis.posterior_probability, 2)}</span>
        </span>
      </div>
      <p className="mt-1.5 max-w-[84ch] text-[12.5px] leading-relaxed text-muted">
        {plain(hypothesis.statement)}
      </p>
      {hypothesis.falsified_if && (
        <p className="mt-1.5 max-w-[84ch] text-[11.5px] leading-snug text-faint">
          <span className="text-faint/80">Falsified if </span>
          {plain(hypothesis.falsified_if)}
        </p>
      )}
      <div className="mt-2 max-w-[14rem]">
        <Meter
          value={hypothesis.posterior_probability}
          tone={hypothesis.status === "weakened" ? "amber" : "cyan"}
          label={`posterior probability for ${hypothesis.hypothesis_id}`}
        />
      </div>
    </li>
  );
}
