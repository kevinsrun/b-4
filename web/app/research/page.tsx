"use client";

/**
 * The run console: set an objective, start it, and read what came back.
 *
 * This is the page that does the work; the landing page is the same run with
 * prose around it.
 */

import { useEffect, useState } from "react";

import { RunLauncher } from "@/components/run-launcher";
import { LiveRun } from "@/components/sections/live-run";
import { ResearchStateSection } from "@/components/sections/research-state";
import { Results } from "@/components/sections/results";
import { Empty, Field, Id, Panel, Status } from "@/components/ui";
import { api, type RunRequestBody } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { useRun } from "@/lib/use-run";

export default function ResearchPage() {
  const run = useRun();
  const [history, setHistory] = useState<RunSummary[]>([]);
  const busy = run.starting || run.status === "running";

  // The run list is server state, so it is refetched rather than assembled
  // from what this tab happens to have seen.
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .runs()
        .then((r) => alive && setHistory(r.runs))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const start = (body: RunRequestBody) => {
    void run.start(body);
  };

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <h1 className="text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[38px]">
          Research console
        </h1>
        <p className="mt-3 max-w-[64ch] text-[14px] leading-relaxed text-muted">
          Describe a target and the loop decides the rest: which candidates are
          worth testing, which experiment to run first, and what the result
          changed. Runs are deterministic — the same objective and seed produce
          the same run.
        </p>
      </header>

      <div className="mx-auto max-w-[1180px] px-4 sm:px-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
          <RunLauncher onStart={start} busy={busy} />

          <Panel title="Runs this session" bodyClassName="">
            {history.length ? (
              <ul className="max-h-[24rem] divide-y divide-line/60 overflow-y-auto">
                {history.map((summary) => (
                  <li key={summary.run_id}>
                    <button
                      type="button"
                      onClick={() => run.follow(summary.run_id)}
                      className={`w-full px-4 py-2.5 text-left transition-colors hover:bg-raised/60 ${
                        run.runId === summary.run_id ? "bg-cyan/8" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <Status status={summary.status} />
                        <Id>{summary.run_id}</Id>
                        <span className="num ml-auto text-[10.5px] text-faint">
                          {summary.digest.results} results
                        </span>
                      </div>
                      <p className="mt-1 truncate text-[11.5px] text-muted">
                        {String(
                          (summary.request?.target as { species?: string } | undefined)?.species ??
                            "—",
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No runs yet in this server process.</Empty>
            )}
          </Panel>
        </div>

        {run.detail?.summary && Object.keys(run.detail.summary).length > 0 && (
          <div className="mt-5 grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["iterations", run.detail.summary.iterations_completed],
              ["candidates", run.detail.summary.total_candidates_screened],
              ["tested", run.detail.summary.tested_candidates],
              ["experiments", run.detail.summary.experiments_run],
              ["findings", run.detail.summary.findings_count],
              ["supported", run.detail.summary.supported_hypotheses],
            ].map(([label, value]) => (
              <div key={String(label)} className="bg-panel px-4 py-3.5">
                <Field label={String(label)} value={String(value ?? "—")} />
              </div>
            ))}
          </div>
        )}

        {run.detail && (
          <p className="num mt-4 text-[11.5px] text-faint">
            loop verdict <span className="text-muted">{run.detail.engine_status ?? "—"}</span>
            {run.detail.engine_run_id && (
              <span className="ml-5">
                engine run <span className="text-muted">{run.detail.engine_run_id}</span>
              </span>
            )}
          </p>
        )}
      </div>

      <div className="mt-6">
        <LiveRun run={run} />
        <Results run={run} />
        <ResearchStateSection run={run} />
      </div>
    </>
  );
}
