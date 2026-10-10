"use client";

/**
 * Loads one run's recorded state and draws its provenance graph.
 *
 * The knowledge agent's `summarize_current_state` projection deliberately
 * carries counts rather than identifiers — a summary hypothesis has
 * `n_supporting` but no `candidate_id` and no `evidence_ids`. The links only
 * exist on a run's full state (`/api/runs/{id}` → `state.hypotheses`), so that
 * is what this reads. Drawing the graph from the summary would have meant
 * inventing the edges.
 */

import { useCallback, useEffect, useState } from "react";

import { EvidenceNetwork } from "@/components/evidence-network";
import { Button } from "@/components/interactive";
import { Empty, Failure, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import type { Hypothesis, ResearchState, RunSummary } from "@/lib/types";

export function ProvenanceGraphPanel() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [state, setState] = useState<ResearchState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const { runs } = await api.runs();
        if (!live) return;
        // Newest first, and only runs that got far enough to record anything.
        const finished = runs.filter((r) => r.status === "finished");
        setRuns(finished);
        if (finished.length) setSelected(finished[finished.length - 1].run_id);
      } catch (cause) {
        if (live) setError(cause instanceof Error ? cause.message : "Could not list runs.");
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const load = useCallback(async (runId: string) => {
    setBusy(true);
    setError(null);
    try {
      const detail = await api.run(runId);
      const next = detail.state as ResearchState;
      setState(next && "hypotheses" in next ? next : null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read that run.");
      setState(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (selected) void load(selected);
  }, [selected, load]);

  const hypotheses = (state?.hypotheses ?? []) as Hypothesis[];

  return (
    <Panel
      title="Provenance graph"
      bodyClassName=""
      aside={
        <span className="num text-[11px] text-faint">candidate → hypothesis → evidence</span>
      }
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3 sm:px-5">
        <span className="text-[11.5px] text-faint">Run</span>
        {runs === null && !error && (
          <span className="num text-[11.5px] text-faint">loading…</span>
        )}
        {runs?.length === 0 && (
          <span className="text-[12px] text-muted">
            No completed run yet — start one from the simulator or the discovery page.
          </span>
        )}
        {runs?.map((run) => (
          <Button
            key={run.run_id}
            variant={selected === run.run_id ? "primary" : "secondary"}
            size="sm"
            onClick={() => setSelected(run.run_id)}
            aria-pressed={selected === run.run_id}
            className="num"
          >
            {run.run_id.slice(0, 8)}
          </Button>
        ))}
      </div>

      {error && (
        <div className="p-4 sm:p-5">
          <Failure message={error} />
        </div>
      )}

      {busy && !error && <Empty>Reading the run&rsquo;s recorded state…</Empty>}

      {!busy && !error && state && <EvidenceNetwork hypotheses={hypotheses} />}

      {!busy && !error && !state && runs !== null && runs.length > 0 && (
        <Empty>
          That run recorded no research state. A run that failed before its first
          agent reported has nothing to draw.
        </Empty>
      )}
    </Panel>
  );
}
