"use client";

/**
 * The loop console — the hero, and the site's one claim made visible.
 *
 * Seven stations in the order the loop visits them. A station lights when the
 * engine dispatches that agent and holds when it returns; the count beside it
 * is what that agent has put into the research state so far. All of it comes
 * from the run, so an idle console means nothing is running rather than that
 * the animation has not started.
 *
 * Why the loop is drawn as a closed circuit rather than a row: the last
 * station feeds the first. That return edge is the whole idea — the system
 * reads its own results before choosing the next experiment.
 */

import type { AgentRole, RunDigest } from "@/lib/types";
import type { StationState } from "@/lib/use-run";

interface Station {
  role: AgentRole;
  label: string;
  /** Which running total in the research state this station grows. */
  counts?: keyof RunDigest;
  unit?: string;
}

const STATIONS: Station[] = [
  { role: "evidence", label: "Evidence", counts: "knowledge_gaps", unit: "gaps" },
  { role: "candidate", label: "Candidates", counts: "candidates", unit: "proposed" },
  { role: "planner", label: "Planner", counts: "experiments", unit: "specs" },
  { role: "simulation", label: "Simulator", counts: "results", unit: "results" },
  { role: "analysis", label: "Analysis", counts: "findings", unit: "findings" },
  { role: "critic", label: "Critic", counts: "reviews", unit: "reviews" },
  { role: "knowledge", label: "State", counts: "scientific_history", unit: "events" },
];

export function LoopConsole({
  stations,
  digest,
  iteration,
  status,
  active,
}: {
  stations: Record<AgentRole, StationState>;
  digest: RunDigest | null;
  iteration: number;
  status: "idle" | "running" | "finished" | "error";
  active: AgentRole | null;
}) {
  return (
    <div className="relative border border-line bg-panel">
      <div className="graph-paper absolute inset-0 opacity-40" aria-hidden />
      {/* The sweep is the only ambient motion on the page and it runs solely
          while an agent is executing. */}
      <div className="relative h-[2px] overflow-hidden bg-line">
        {status === "running" && <div className="sweep absolute inset-0" />}
      </div>

      <div className="relative flex items-center justify-between gap-4 border-b border-line px-4 py-2.5">
        <h2 className="text-[13px] font-medium text-text">Discovery loop</h2>
        <div className="flex items-center gap-4">
          <span className="num text-[11px] text-faint">
            iteration <span className="text-muted">{iteration}</span>
          </span>
          <StatusWord status={status} active={active} />
        </div>
      </div>

      <ol className="relative">
        {STATIONS.map((station, index) => {
          const state = stations[station.role];
          const count = digest && station.counts ? digest[station.counts] : null;
          return (
            <li
              key={station.role}
              className={`flex items-center gap-3 border-b border-line/70 px-4 py-[11px] transition-colors ${
                state === "running" ? "bg-cyan/6" : ""
              }`}
            >
              <Lamp state={state} />
              <span
                className={`flex-1 text-[13px] ${
                  state === "idle" ? "text-faint" : "text-text"
                }`}
              >
                {station.label}
              </span>
              {count !== null && count !== undefined && (
                <span className="num text-[11.5px] text-muted">
                  {count}
                  {station.unit && <span className="ml-1 text-faint">{station.unit}</span>}
                </span>
              )}
              {/* The return edge, drawn only on the last station. */}
              {index === STATIONS.length - 1 && (
                <span className="num text-[10px] text-cyan/70" title="The state feeds the next plan">
                  ↺ feeds planner
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Lamp({ state }: { state: StationState }) {
  const base = "block h-[7px] w-[7px] shrink-0";
  if (state === "running")
    return <span className={`${base} station-live bg-cyan`} aria-label="running" />;
  if (state === "done") return <span className={`${base} bg-cyan/55`} aria-label="complete" />;
  if (state === "failed") return <span className={`${base} bg-red`} aria-label="failed" />;
  return <span className={`${base} border border-line-strong`} aria-label="idle" />;
}

function StatusWord({
  status,
  active,
}: {
  status: "idle" | "running" | "finished" | "error";
  active: AgentRole | null;
}) {
  if (status === "running")
    return (
      <span className="num text-[11px] text-cyan">
        {active ? `${active} executing` : "routing"}
      </span>
    );
  if (status === "finished") return <span className="num text-[11px] text-muted">complete</span>;
  if (status === "error") return <span className="num text-[11px] text-red">halted</span>;
  return <span className="num text-[11px] text-faint">idle</span>;
}
