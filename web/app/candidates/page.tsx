"use client";

/**
 * Candidate design.
 *
 * Everything on this page is a proposal. The agent ranks and explains; it never
 * claims a candidate is active, and the page is labelled accordingly — the
 * score is an argument for testing something, not a result.
 *
 * Gram stain is a required choice here for the same reason the run form
 * requires it: without it the agent skips envelope-accessibility reasoning, and
 * a candidate that cannot reach the target can still rank well on information
 * gain alone.
 */

import { useCallback, useEffect, useState } from "react";

import { Provenance } from "@/components/provenance";
import { Empty, Failure, Field, Id, Meter, Panel, Uncertainties } from "@/components/ui";
import { api } from "@/lib/api";
import { fixed, plain, residueClass, sig, titleCase } from "@/lib/format";
import type { CandidateEnvelope, CandidateProposal } from "@/lib/types";

const TARGETS = [
  { species: "Listeria monocytogenes", gram: "positive" as const },
  { species: "Staphylococcus aureus", gram: "positive" as const },
  { species: "Enterococcus faecalis", gram: "positive" as const },
  { species: "Escherichia coli", gram: "negative" as const },
];

export default function CandidatesPage() {
  const [target, setTarget] = useState(TARGETS[0]);
  const [count, setCount] = useState(5);
  const [envelope, setEnvelope] = useState<CandidateEnvelope | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setEnvelope(
        await api.candidates({
          species: target.species,
          gram: target.gram,
          max_candidates: count,
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Candidate generation failed.");
      setEnvelope(null);
    } finally {
      setBusy(false);
    }
  }, [target, count]);

  useEffect(() => {
    void load();
  }, [load]);

  const proposals = (envelope?.decision?.candidates ?? []) as CandidateProposal[];

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[38px]">
            Candidates
          </h1>
          <Provenance kind="proposal" />
        </div>
        <p className="mt-3 max-w-[66ch] text-[14px] leading-relaxed text-muted">
          Ranked proposals for a target, each with the reasoning behind its score
          and a statement of what would rule it out. A high score argues that a
          candidate is worth an experiment. It is not a claim that the candidate
          works.
        </p>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-5 px-4 pb-10 sm:px-6">
        <Panel title="Target">
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <div className="text-[11.5px] text-faint">Organism and gram stain</div>
              <div className="mt-1 flex flex-wrap">
                {TARGETS.map((option, i) => (
                  <button
                    key={option.species}
                    type="button"
                    onClick={() => setTarget(option)}
                    className={`border px-2.5 py-1.5 text-[12px] transition-colors ${
                      target.species === option.species
                        ? "border-cyan/50 bg-cyan/10 text-cyan"
                        : "border-line text-muted hover:text-text"
                    } ${i > 0 ? "-ml-px" : ""}`}
                  >
                    <span className="italic">{option.species}</span>
                    <span className="num ml-1.5 text-[10.5px] opacity-70">{option.gram[0]}</span>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[11.5px] text-faint">How many</div>
              <div className="mt-1 flex">
                {[3, 5, 8].map((n, i) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setCount(n)}
                    className={`num border px-3 py-1.5 text-[12px] transition-colors ${
                      count === n
                        ? "border-cyan/50 bg-cyan/10 text-cyan"
                        : "border-line text-muted hover:text-text"
                    } ${i > 0 ? "-ml-px" : ""}`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
            {envelope && (
              <div className="ml-auto flex items-end gap-6">
                <Field label="agent confidence" value={fixed(envelope.confidence, 2)} />
                <Field
                  label="considered"
                  value={String(envelope.artifacts?.considered_count ?? "—")}
                />
              </div>
            )}
          </div>
        </Panel>

        {error && <Failure message={error} />}

        {busy && !proposals.length && (
          <div className="border border-line bg-panel">
            <Empty>Scoring candidates…</Empty>
          </div>
        )}

        {envelope?.warnings && envelope.warnings.length > 0 && (
          <div className="border border-amber/35 bg-amber/6 px-4 py-3">
            <ul className="space-y-1">
              {envelope.warnings.map((warning, i) => (
                <li key={i} className="text-[12px] leading-snug text-amber">
                  {plain(warning)}
                </li>
              ))}
            </ul>
          </div>
        )}

        <ol className="space-y-4">
          {proposals.map((proposal, index) => (
            <li key={proposal.candidate_id}>
              <ProposalCard proposal={proposal} rank={proposal.rank ?? index + 1} />
            </li>
          ))}
        </ol>

        {envelope?.uncertainties && envelope.uncertainties.length > 0 && (
          <Panel title="What the agent says it cannot know">
            <Uncertainties items={envelope.uncertainties} />
          </Panel>
        )}
      </div>
    </>
  );
}

const SCORE_KEYS = [
  ["promise", "prior reason to expect activity"],
  ["condition_fit", "suits the stated conditions"],
  ["information_gain", "how much an experiment would teach"],
  ["hypothesis_discrimination", "separates competing hypotheses"],
  ["novelty", "untested in this campaign"],
  ["uncertainty", "how unsure the agent is"],
] as const;

function ProposalCard({ proposal, rank }: { proposal: CandidateProposal; rank: number }) {
  const features = (proposal.features ?? {}) as {
    computed?: Record<string, unknown>;
    receptor?: string | null;
    bacteriocin_class?: string | null;
    producing_organism?: string | null;
  };
  const computed = features.computed ?? {};
  const score = (proposal.score ?? null) as
    | (Record<string, number | string[]> & { total?: number; rationale?: string[] })
    | null;
  const total = score?.total ?? proposal.score_total ?? null;
  const hypothesis = (proposal.hypotheses as { falsified_if?: string; statement?: string }[] | undefined)?.[0];
  const strengths = (proposal.expected_strengths as string[] | undefined) ?? [];
  const failureModes = (proposal.expected_failure_modes as string[] | undefined) ?? [];

  return (
    <article className="border border-line bg-panel">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line px-4 py-3">
        <span className="num text-[11px] text-cyan/70">{String(rank).padStart(2, "0")}</span>
        <h2 className="text-[15px] font-medium text-text">{titleCase(proposal.name)}</h2>
        {proposal.origin && (
          <span className="num text-[10.5px] text-faint">{proposal.origin}</span>
        )}
        <Id>{proposal.candidate_id}</Id>
        <div className="ml-auto flex items-center gap-5">
          <div className="w-28">
            <Meter value={total} label={`score for ${proposal.name}`} />
          </div>
          <Provenance kind="proposal" />
        </div>
      </header>

      <div className="grid gap-5 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
        <div className="min-w-0 space-y-4">
          {hypothesis?.statement && (
            <p className="max-w-[80ch] text-[13px] leading-relaxed text-text">
              {plain(hypothesis.statement)}
            </p>
          )}

          {hypothesis?.falsified_if && (
            <div className="border-l-2 border-amber/50 pl-3">
              <div className="text-[11px] text-faint">Ruled out if</div>
              <p className="mt-0.5 max-w-[76ch] text-[12.5px] leading-relaxed text-text">
                {plain(hypothesis.falsified_if)}
              </p>
            </div>
          )}

          {(strengths.length > 0 || failureModes.length > 0) && (
            <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {strengths.length > 0 && (
                <div>
                  <h3 className="text-[11.5px] text-faint">Reasons to test it</h3>
                  <ul className="mt-1.5 space-y-1.5">
                    {strengths.map((item, i) => (
                      <li key={i} className="max-w-[46ch] text-[12px] leading-snug text-muted">
                        {plain(item)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {failureModes.length > 0 && (
                <div>
                  <h3 className="text-[11.5px] text-amber/90">How it could fail</h3>
                  <ul className="mt-1.5 space-y-1.5">
                    {failureModes.map((item, i) => (
                      <li key={i} className="max-w-[46ch] text-[12px] leading-snug text-muted">
                        {plain(item)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {score?.rationale && score.rationale.length > 0 && (
            <details className="group border-t border-line pt-3">
              <summary className="cursor-pointer text-[11.5px] text-faint transition-colors hover:text-muted">
                Why it scored {fixed(total, 2)}
              </summary>
              <ul className="mt-2 space-y-1">
                {score.rationale.map((item, i) => (
                  <li key={i} className="max-w-[80ch] text-[12px] leading-snug text-muted">
                    {plain(item)}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {proposal.sequence && (
            <div>
              <div className="flex items-baseline gap-3">
                <span className="text-[11px] text-faint">sequence</span>
                <span className="num text-[10.5px] text-faint">
                  {proposal.sequence.length} residues
                </span>
                <span className="num ml-auto text-[10px] text-faint">
                  <span className="text-cyan">basic</span>{" "}
                  <span className="text-red">acidic</span>{" "}
                  <span className="text-amber">cysteine</span>
                </span>
              </div>
              <p className="num mt-1 break-all text-[11.5px] leading-[1.7] tracking-tight">
                {proposal.sequence.split("").map((residue, i) => (
                  <span key={i} className={residueClass(residue)}>
                    {residue}
                  </span>
                ))}
              </p>
            </div>
          )}
        </div>

        <dl className="grid grid-cols-2 gap-x-5 gap-y-4 lg:border-l lg:border-line lg:pl-5">
          <Field label="net charge" value={sig(computed.net_charge as number, 3)} />
          <Field label="mol. weight" value={`${sig(computed.molecular_weight as number, 4)} Da`} />
          <Field label="GRAVY" value={sig(computed.gravy as number, 3)} />
          <Field
            label="hydrophobic"
            value={sig(computed.hydrophobic_fraction as number, 2)}
          />
          <Field label="cysteines" value={String(computed.cysteine_count ?? "—")} />
          <Field label="confidence" value={fixed(proposal.confidence, 2)} />
          {features.receptor && (
            <div className="col-span-2">
              <Field label="known receptor" value={String(features.receptor)} />
            </div>
          )}

          {score && (
            <div className="col-span-2 border-t border-line pt-3">
              <div className="text-[11px] text-faint">score components</div>
              <ul className="mt-2 space-y-1.5">
                {SCORE_KEYS.filter(([key]) => typeof score[key] === "number").map(([key, meaning]) => (
                  <li key={key}>
                    <div className="flex items-baseline gap-2">
                      <span className="truncate text-[11px] text-muted" title={meaning}>
                        {titleCase(key)}
                      </span>
                      <span className="num ml-auto text-[11px] text-faint">
                        {fixed(score[key] as number, 2)}
                      </span>
                    </div>
                    <div className="mt-0.5 h-[2px] bg-raised">
                      <div
                        className="h-full bg-cyan/60"
                        style={{ width: `${Math.min(1, Math.max(0, score[key] as number)) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Two fields the agent sets and this page refuses to hide. */}
          <div className="col-span-2 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-3">
            <Field label="validation status" value={String(proposal.validation_status ?? "—")} tone="amber" />
            <Field
              label="sequence verified"
              value={proposal.sequence_verified ? "true" : "false"}
              tone={proposal.sequence_verified ? "default" : "amber"}
              hint={proposal.sequence_verified ? undefined : "not checked against a primary database"}
            />
          </div>
        </dl>
      </div>
    </article>
  );
}
