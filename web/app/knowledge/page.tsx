"use client";

/**
 * The research state.
 *
 * This is the only part of the system with a memory. Everything else answers a
 * question and forgets it; the knowledge agent keeps an append-only event log
 * whose history can be verified by hash, and the rules it enforces are the ones
 * that stop a campaign fooling itself — an inconclusive result leaves a
 * hypothesis exactly where it was, a failed attempt is not a negative finding,
 * and nothing is validated unless it came from a bench.
 *
 * Read-only, because writing to the log belongs to the loop. That is a property
 * of the API, not a limitation of this page, so the page does not offer edits
 * it would then have to refuse.
 *
 * The store is a directory on the machine running the API. Runs started from
 * the web interface keep their state in memory and never write to it, so an
 * empty answer here is usually correct rather than broken — and saying which it
 * is, is most of this page's job.
 */

import { useCallback, useEffect, useState } from "react";

import { ProvenanceGraphPanel } from "@/components/provenance-graph-panel";
import { Empty, Failure, Field, Id, Panel, Status } from "@/components/ui";
import { api } from "@/lib/api";
import { plain, titleCase } from "@/lib/format";
import type { KnowledgeEnvelope, KnowledgeOperation, KnowledgeSummary } from "@/lib/types";

const OPERATIONS: { id: KnowledgeOperation; label: string; blurb: string }[] = [
  { id: "summary", label: "Summary", blurb: "What the log says the campaign currently believes." },
  { id: "open-questions", label: "Open questions", blurb: "What it has not settled." },
  { id: "integrity", label: "Integrity", blurb: "Whether the history still hashes to itself." },
];

export default function KnowledgePage() {
  const [operation, setOperation] = useState<KnowledgeOperation>("summary");
  const [stateDir, setStateDir] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [envelope, setEnvelope] = useState<KnowledgeEnvelope | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setEnvelope(await api.knowledge(operation, submitted || null));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read the research state.");
      setEnvelope(null);
    } finally {
      setBusy(false);
    }
  }, [operation, submitted]);

  useEffect(() => {
    void load();
  }, [load]);

  const decision = envelope?.decision;
  // The agent answers 200 with an error inside the envelope when it has no
  // store to read, so a failed read is not an HTTP failure and is not shown as
  // one. It usually means no state directory, which is a setup fact.
  const agentError = decision?.status === "error" ? decision.error ?? "unreported error" : null;

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <h1 className="display display-lg text-balance text-cyan">
          Research state
        </h1>
        <p className="mt-3 max-w-[70ch] text-[14px] leading-relaxed text-muted">
          The campaign&apos;s memory: an append-only event log the loop writes and
          this page only reads. A hypothesis is never quietly upgraded — an
          inconclusive result leaves it untouched, and nothing counts as
          validated unless it came from a bench, which nothing here has.
        </p>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-5 px-4 pb-16 sm:px-6">
        <Panel title="Query">
          <div className="flex flex-wrap items-end gap-x-7 gap-y-5">
            <div>
              <div className="text-[11.5px] text-faint">Operation</div>
              <div className="mt-1 flex flex-wrap">
                {OPERATIONS.map((option, i) => (
                  <button
                    key={option.id}
                    type="button"
                    title={option.blurb}
                    onClick={() => setOperation(option.id)}
                    className={`border px-2.5 py-1.5 text-[12px] transition-colors ${
                      operation === option.id
                        ? "border-cyan/50 bg-cyan/10 text-cyan"
                        : "border-line text-muted hover:text-text"
                    } ${i > 0 ? "-ml-px" : ""}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setSubmitted(stateDir.trim());
              }}
            >
              <div>
                <label className="text-[11.5px] text-faint" htmlFor="state-dir">
                  State directory <span className="text-faint/70">(on the API host)</span>
                </label>
                <input
                  id="state-dir"
                  value={stateDir}
                  onChange={(event) => setStateDir(event.target.value)}
                  placeholder="defaults to BACTERIOCIN_STATE_DIR"
                  className="num mt-1 block w-72 border border-line bg-ink px-2 py-1.5 text-[12px] text-text placeholder:text-faint/60 rounded-[3px] transition-colors focus:border-cyan"
                />
              </div>
              <button
                type="submit"
                disabled={busy}
                className="border border-cyan/60 bg-cyan/10 px-3 py-1.5 text-[13px] text-cyan transition-colors hover:bg-cyan/18 disabled:opacity-50"
              >
                {busy ? "Reading…" : "Read"}
              </button>
            </form>
          </div>
        </Panel>

        {error && <Failure message={error} />}

        {agentError && (
          <div className="border border-amber/35 bg-amber/6 px-4 py-3">
            <p className="text-[13px] leading-snug text-amber">{plain(agentError)}</p>
            <p className="mt-1.5 max-w-[80ch] text-[12px] leading-relaxed text-muted">
              Point this at a store the loop has written, or start the API with{" "}
              <code className="num text-text">BACTERIOCIN_STATE_DIR</code> set. Runs started
              from the web interface keep their state in memory and never write here.
            </p>
          </div>
        )}

        {envelope && !agentError && operation === "summary" && (
          <SummaryView summary={(decision?.result ?? {}) as KnowledgeSummary} />
        )}

        {operation === "summary" && <ProvenanceGraphPanel />}

        {envelope && !agentError && operation !== "summary" && (
          <Panel title={titleCase(operation.replace(/-/g, " "))}>
            <Raw value={decision?.result} />
          </Panel>
        )}

        {envelope && (
          <Panel title="Envelope">
            <div className="flex flex-wrap gap-x-8 gap-y-4">
              <Field label="agent" value={envelope.agent} />
              <Field label="operation" value={decision?.operation ?? "—"} />
              <Field
                label="status"
                value={<Status status={decision?.status ?? "unknown"} />}
              />
              <Field label="confidence" value={envelope.confidence.toFixed(2)} />
              <Field label="model version" value={envelope.model_version ?? "—"} />
            </div>
            {envelope.warnings.length > 0 && (
              <ul className="mt-4 space-y-1 border-t border-line pt-3">
                {envelope.warnings.map((warning, i) => (
                  <li key={i} className="max-w-[86ch] text-[12px] leading-snug text-amber">
                    {plain(warning)}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {busy && !envelope && (
          <div className="rounded-[4px] border border-line bg-panel">
            <Empty>Reading the event log…</Empty>
          </div>
        )}
      </div>
    </>
  );
}

function SummaryView({ summary }: { summary: KnowledgeSummary }) {
  const counts = summary.counts ?? {};
  const empty = (summary.event_count ?? 0) === 0;

  return (
    <>
      <Panel title="State">
        <div className="flex flex-wrap gap-x-8 gap-y-4">
          <Field label="iteration" value={String(summary.iteration ?? "—")} />
          <Field label="events" value={String(summary.event_count ?? 0)} />
          <Field label="experiments" value={String(counts.experiments ?? 0)} />
          <Field label="results" value={String(counts.results ?? 0)} />
          <Field label="findings" value={String(counts.findings ?? 0)} />
          <Field label="evidence" value={String(counts.evidence ?? 0)} />
          <Field label="open questions" value={String(summary.n_open_questions ?? 0)} />
        </div>

        {summary.last_event_hash && (
          <div className="mt-4 flex flex-wrap items-baseline gap-2 border-t border-line pt-3">
            <span className="text-[11px] text-faint">last event hash</span>
            <Id>{summary.last_event_hash}</Id>
          </div>
        )}

        {/* The agent writes its own provenance sentence. It is the one line on
            this page that states what the campaign has actually earned, so it
            is shown as written rather than reworded. */}
        {summary.provenance && (
          <p className="mt-4 max-w-[86ch] border-t border-line pt-3 text-[12.5px] leading-relaxed text-muted">
            {plain(summary.provenance)}
          </p>
        )}

        {empty && (
          <p className="mt-3 max-w-[86ch] text-[12.5px] leading-relaxed text-faint">
            The log is empty. That is a real answer, not a failure: this store
            exists and nothing has been recorded into it yet.
          </p>
        )}
      </Panel>

      {summary.model_version_warning && (
        <div className="border border-amber/35 bg-amber/6 px-4 py-3">
          <p className="text-[12.5px] leading-snug text-amber">
            {plain(summary.model_version_warning)}
          </p>
        </div>
      )}

      {(summary.hypotheses ?? []).length > 0 && (
        <Panel title={`Hypotheses (${summary.hypotheses?.length})`}>
          <Raw value={summary.hypotheses} />
        </Panel>
      )}

      {(summary.open_questions ?? []).length > 0 && (
        <Panel title={`Open questions (${summary.open_questions?.length})`}>
          <Raw value={summary.open_questions} />
        </Panel>
      )}

      {(summary.rejected_candidates ?? []).length > 0 && (
        <Panel title={`Rejected candidates (${summary.rejected_candidates?.length})`}>
          <Raw value={summary.rejected_candidates} />
        </Panel>
      )}
    </>
  );
}

/**
 * The log's own records, shown as they are.
 *
 * These shapes are the knowledge agent's, not this interface's, and a reader
 * who has come this far wants the record rather than a rendering of it. A
 * prettified view would also be one more place for a field to go missing.
 */
function Raw({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <p className="text-[12.5px] text-faint">Nothing reported.</p>;
  }
  return (
    <pre className="num max-h-[32rem] overflow-auto whitespace-pre-wrap break-all text-[11.5px] leading-relaxed text-muted">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
