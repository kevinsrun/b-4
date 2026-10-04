"use client";

import { useEffect, useRef, useState } from "react";

import { Section } from "@/components/section";
import { Empty, Failure, Id, Status } from "@/components/ui";
import { elapsed, plain } from "@/lib/format";
import type { RunView } from "@/lib/use-run";

/**
 * The run as it happens.
 *
 * The left column is the loop's own audit log — these summaries are written by
 * the engine, not composed here. The right column is the dispatch record: which
 * agent was called, how long it took, and the router's stated reason, which
 * only exists once the run has finished and the trace is available.
 */
export function LiveRun({ run }: { run: RunView }) {
  const journalRef = useRef<HTMLOListElement>(null);
  const count = run.journal.length;
  // Both panels are dense; either can be folded away once it has been read.
  const [showLog, setShowLog] = useState(true);
  const [showDispatch, setShowDispatch] = useState(true);

  useEffect(() => {
    const el = journalRef.current;
    if (el && run.status === "running") el.scrollTop = el.scrollHeight;
  }, [count, run.status]);

  return (
    <Section
      id="run"
      heading="Watch one run think"
      standfirst="Every line below was appended by the loop while it ran. The log is append-only: a belief that changes keeps both states, so you can read what the lab thought at each step and what changed it."
      aside={
        run.runId ? (
          <div className="flex items-center gap-3">
            <Status status={run.status} />
            <Id title={`run ${run.runId}`}>{run.runId}</Id>
          </div>
        ) : null
      }
    >
      {run.error && <Failure message={run.error} />}

      {!run.runId && !run.error ? (
        <div className="border border-line">
          <Empty>
            No run yet. Start one with Run discovery and this fills with the
            loop&rsquo;s own log as each agent reports back.
          </Empty>
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
          <div className="border border-line">
            <PanelToggle
              title="Scientific log"
              meta={`${count} events`}
              open={showLog}
              onToggle={() => setShowLog((v) => !v)}
            />
            {showLog && (
            <ol
              ref={journalRef}
              className="max-h-[26rem] divide-y divide-line/60 overflow-y-auto"
              aria-live="polite"
              aria-label="Scientific log"
            >
              {run.journal.map((event, i) => (
                <li key={`${event.event_id}-${i}`} className="px-4 py-2.5">
                  <div className="flex items-baseline gap-2">
                    <span className="num shrink-0 text-[10.5px] text-cyan/75">
                      i{event.iteration}
                    </span>
                    <span className="num shrink-0 text-[10.5px] text-faint">
                      {event.source_agent}
                    </span>
                    <span className="num ml-auto shrink-0 text-[10px] text-faint/80">
                      {event.event_type}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px] leading-snug text-muted">
                    {plain(event.summary)}
                  </p>
                </li>
              ))}
              {!count && (
                <li>
                  <Empty>Waiting for the first agent to report.</Empty>
                </li>
              )}
            </ol>
            )}
          </div>

          <div className="border border-line">
            <PanelToggle
              title="Dispatch"
              meta={run.detail?.execution_trace?.length ? "with routing reasons" : ""}
              open={showDispatch}
              onToggle={() => setShowDispatch((v) => !v)}
            />
            {showDispatch && (
            <>
            {run.detail?.execution_trace?.length ? (
              <ol className="max-h-[26rem] divide-y divide-line/60 overflow-y-auto">
                {run.detail.execution_trace.map((step) => (
                  <li key={step.trace_id} className="px-4 py-2.5">
                    <div className="flex items-baseline gap-2">
                      <span className="num shrink-0 text-[10.5px] text-cyan/75">
                        i{step.iteration}
                      </span>
                      <span className="text-[12.5px] text-text">{step.agent}</span>
                      <Status status={step.status} className="ml-auto" />
                    </div>
                    {step.routing_reason && (
                      <p className="mt-1 text-[11.5px] leading-snug text-faint">
                        {step.routing_reason}
                      </p>
                    )}
                    {step.error && (
                      <p className="mt-1 text-[11.5px] leading-snug text-red">{step.error}</p>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <ol className="max-h-[26rem] divide-y divide-line/60 overflow-y-auto">
                {run.events
                  .filter(
                    (e): e is Extract<typeof e, { type: "agent_finished" | "agent_failed" }> =>
                      e.type === "agent_finished" || e.type === "agent_failed",
                  )
                  .slice(-40)
                  .map((e) => (
                    <li key={e.seq} className="flex items-baseline gap-2 px-4 py-2">
                      <span className="num shrink-0 text-[10.5px] text-cyan/75">i{e.iteration}</span>
                      <span className="text-[12.5px] text-text">{e.agent}</span>
                      <span className="num ml-auto text-[10.5px] text-faint">
                        {elapsed(e.duration_ms)}
                      </span>
                    </li>
                  ))}
                {!run.events.length && (
                  <li>
                    <Empty>The router&rsquo;s stated reasons appear here once the run ends.</Empty>
                  </li>
                )}
              </ol>
            )}
            </>
            )}
          </div>
        </div>
      )}

      {run.detail && run.detail.errors.length > 0 && (
        <div className="mt-5 border border-amber/35 bg-amber/6 px-4 py-3">
          <h4 className="text-[12.5px] text-amber">
            The loop recorded {run.detail.errors.length} recoverable failure
            {run.detail.errors.length === 1 ? "" : "s"}
          </h4>
          <ul className="mt-1.5 space-y-1">
            {run.detail.errors.map((error, i) => (
              <li key={i} className="num text-[11.5px] leading-snug text-muted">
                {error}
              </li>
            ))}
          </ul>
          <p className="mt-2 max-w-[70ch] text-[11.5px] leading-snug text-faint">
            A failed attempt is not a negative finding — it produced no
            measurement, so nothing above was concluded from it.
          </p>
        </div>
      )}
    </Section>
  );
}

function PanelToggle({
  title,
  meta,
  open,
  onToggle,
}: {
  title: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="flex w-full items-center gap-3 border-b border-line px-4 py-2.5 text-left transition-colors hover:bg-raised/50"
    >
      <span
        aria-hidden
        className={`num text-[10px] text-faint transition-transform ${open ? "rotate-90" : ""}`}
      >
        &#9656;
      </span>
      <h3 className="text-[13px] font-medium text-text">{title}</h3>
      {meta && <span className="num ml-auto text-[11px] text-faint">{meta}</span>}
      <span className="sr-only">{open ? "Hide" : "Show"} {title}</span>
    </button>
  );
}
