"use client";

/**
 * Follows one discovery run.
 *
 * The API also streams server-sent events, but this polls `/events?since=n`
 * instead: the index-based read cannot drop an event, it survives the Next dev
 * proxy buffering a stream, and at this cadence it is indistinguishable from a
 * stream to look at. Every event it reports came from the loop.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type RunRequestBody } from "./api";
import type { AgentRole, RunDetail, RunDigest, RunEvent, ScientificEvent } from "./types";

const POLL_MS = 400;
/**
 * The event stream carries counts, not the state itself, so the state is
 * fetched on a slower beat while the run is in flight. Without it the
 * predictions and the hypotheses would only appear once the run ended, which
 * is the least interesting moment to show them.
 */
const STATE_EVERY = 3;

export type StationState = "idle" | "running" | "done" | "failed";

export interface RunView {
  runId: string | null;
  /** Where the run is, as the API reports it. */
  status: "idle" | "running" | "finished" | "error";
  events: RunEvent[];
  /** The loop's own audit-log entries, newest last. */
  journal: ScientificEvent[];
  digest: RunDigest | null;
  stations: Record<AgentRole, StationState>;
  /** Which agent is executing right now, if any. */
  active: AgentRole | null;
  iteration: number;
  detail: RunDetail | null;
  error: string | null;
  starting: boolean;
}

const ROLES: AgentRole[] = [
  "evidence",
  "candidate",
  "planner",
  "simulation",
  "analysis",
  "critic",
  "knowledge",
];

const IDLE_STATIONS = Object.fromEntries(ROLES.map((r) => [r, "idle"])) as Record<
  AgentRole,
  StationState
>;

export function useRun() {
  const [view, setView] = useState<RunView>({
    runId: null,
    status: "idle",
    events: [],
    journal: [],
    digest: null,
    stations: IDLE_STATIONS,
    active: null,
    iteration: 0,
    detail: null,
    error: null,
    starting: false,
  });

  const cursor = useRef(0);
  const ticks = useRef(0);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (polling.current) {
      clearInterval(polling.current);
      polling.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  /** Attach to a run that already exists (a fresh one, or one from the list). */
  const follow = useCallback(
    (runId: string, { reset = true } = {}) => {
      stop();
      cursor.current = 0;
      ticks.current = 0;
      if (reset) {
        setView((v) => ({
          ...v,
          runId,
          status: "running",
          events: [],
          journal: [],
          digest: null,
          stations: IDLE_STATIONS,
          active: null,
          iteration: 0,
          detail: null,
          error: null,
          starting: false,
        }));
      }

      const tick = async () => {
        try {
          const batch = await api.runEvents(runId, cursor.current);
          cursor.current += batch.events.length;

          if (batch.events.length) {
            setView((v) => applyEvents(v, batch.events));
          }

          if (batch.status !== "running") {
            stop();
            const detail = await api.run(runId);
            setView((v) => ({
              ...v,
              status: detail.status === "error" ? "error" : "finished",
              detail,
              digest: detail.digest,
              error: detail.error,
              active: null,
              stations: finalStations(v.stations),
            }));
            return;
          }

          ticks.current += 1;
          if (ticks.current % STATE_EVERY === 0) {
            const detail = await api.run(runId);
            // Keep the status this hook derives from the event stream; only the
            // scientific state is taken from here.
            setView((v) => (v.runId === runId ? { ...v, detail } : v));
          }
        } catch (cause) {
          stop();
          setView((v) => ({
            ...v,
            status: "error",
            active: null,
            error:
              cause instanceof ApiError
                ? cause.message
                : "Lost contact with the lab API while the run was in flight.",
          }));
        }
      };

      void tick();
      polling.current = setInterval(() => void tick(), POLL_MS);
    },
    [stop],
  );

  const start = useCallback(
    async (body: RunRequestBody) => {
      setView((v) => ({ ...v, starting: true, error: null }));
      try {
        const summary = await api.startRun(body);
        follow(summary.run_id);
        return summary.run_id;
      } catch (cause) {
        setView((v) => ({
          ...v,
          starting: false,
          status: "error",
          error: cause instanceof ApiError ? cause.message : "Could not start the run.",
        }));
        return null;
      }
    },
    [follow],
  );

  return { ...view, start, follow };
}

function applyEvents(view: RunView, incoming: RunEvent[]): RunView {
  const stations = { ...view.stations };
  const journal = [...view.journal];
  let { digest, active, iteration } = view;

  for (const event of incoming) {
    switch (event.type) {
      case "agent_started":
        // A new iteration retires the previous pass, so the ring reads as one
        // lap rather than accumulating every station it has ever visited.
        if (event.iteration !== iteration) {
          for (const role of ROLES) if (stations[role] === "done") stations[role] = "idle";
          iteration = event.iteration;
        }
        stations[event.agent] = "running";
        active = event.agent;
        break;
      case "agent_finished":
        stations[event.agent] = "done";
        if (active === event.agent) active = null;
        if (event.digest) digest = event.digest;
        journal.push(...(event.events ?? []));
        break;
      case "agent_failed":
        stations[event.agent] = "failed";
        if (active === event.agent) active = null;
        break;
      case "run_finished":
        digest = event.digest;
        active = null;
        break;
      default:
        break;
    }
  }

  return {
    ...view,
    events: [...view.events, ...incoming],
    journal,
    digest,
    active,
    iteration,
    stations,
  };
}

function finalStations(stations: Record<AgentRole, StationState>): Record<AgentRole, StationState> {
  const out = { ...stations };
  for (const role of ROLES) if (out[role] === "running") out[role] = "done";
  return out;
}

export { ROLES };
