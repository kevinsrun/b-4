"use client";

import { useState } from "react";
import { SequencingRun } from "@/lib/sequencing-types";

interface RunsTabProps {
  runs: SequencingRun[];
  onSelectRun: (runId: string) => void;
}

export function RunsTab({ runs, onSelectRun }: RunsTabProps) {
  const [filterVendor, setFilterVendor] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const filteredRuns = runs.filter((r) => {
    if (filterVendor !== "all" && r.vendor !== filterVendor) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchName = r.run_name.toLowerCase().includes(q);
      const matchId = r.external_run_id.toLowerCase().includes(q);
      const matchProject = (r.project_name || "").toLowerCase().includes(q);
      if (!matchName && !matchId && !matchProject) return false;
    }
    return true;
  });

  function formatBytes(bytes: number) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  }

  return (
    <div className="space-y-6">
      {/* Search and Filters Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-text">Discovered Sequencing Runs</h2>
          <p className="text-[12px] text-muted">
            Aggregated runs discovered across connected instruments and sequencing hubs.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Vendor Filter */}
          <div className="flex items-center rounded-lg border border-line bg-surface/50 p-0.5 text-[11px] font-mono">
            {["all", "illumina", "nanopore", "pacbio", "local"].map((v) => (
              <button
                key={v}
                onClick={() => setFilterVendor(v)}
                className={`rounded px-2.5 py-1 uppercase transition-colors ${
                  filterVendor === v
                    ? "bg-accent text-black font-semibold"
                    : "text-muted hover:text-text"
                }`}
              >
                {v}
              </button>
            ))}
          </div>

          {/* Search box */}
          <input
            type="text"
            placeholder="Search run, flow cell, project..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs text-text placeholder-muted font-mono focus:outline-none focus:border-accent w-56"
          />
        </div>
      </div>

      {/* Runs Table */}
      <div className="rounded-xl border border-line bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead className="border-b border-line bg-surface/50 font-mono text-[11px] text-muted uppercase">
              <tr>
                <th className="px-4 py-3">Platform / Vendor</th>
                <th className="px-4 py-3">Run Identifier</th>
                <th className="px-4 py-3">Instrument & Method</th>
                <th className="px-4 py-3">Project / Sample</th>
                <th className="px-4 py-3 text-right">Datasets</th>
                <th className="px-4 py-3 text-right">Total Size</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/40">
              {filteredRuns.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted">
                    No sequencing runs match the current criteria.
                  </td>
                </tr>
              ) : (
                filteredRuns.map((run) => {
                  const isCompleted = run.status === "completed";
                  const isRunning = run.status === "running";

                  return (
                    <tr
                      key={run.run_id}
                      className="hover:bg-surface/30 transition-colors cursor-pointer"
                      onClick={() => onSelectRun(run.run_id)}
                    >
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1.5 rounded bg-surface px-2 py-0.5 text-[10px] font-mono uppercase text-muted border border-line/50">
                          {run.vendor}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-mono font-medium text-text text-[12px] truncate max-w-xs">
                          {run.run_name}
                        </div>
                        <div className="text-[10px] font-mono text-muted truncate max-w-xs">
                          {run.external_run_id}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-text font-medium text-[12px]">
                          {run.instrument_model || "Generic Sequencer"}
                        </div>
                        <div className="text-[11px] text-muted truncate max-w-[180px]">
                          {run.sequencing_method}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-text text-[12px] truncate max-w-[160px]">
                          {run.project_name || "General Assay"}
                        </div>
                        <div className="text-[10px] font-mono text-muted">
                          {run.sample_count} sample(s)
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-text">
                        {run.dataset_count}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-muted">
                        {formatBytes(run.total_size_bytes)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-mono uppercase font-semibold ${
                            isCompleted
                              ? "bg-emerald-500/15 text-emerald-400"
                              : isRunning
                              ? "bg-cyan-500/15 text-cyan-400 animate-pulse"
                              : "bg-red-500/15 text-red-400"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              isCompleted
                                ? "bg-emerald-400"
                                : isRunning
                                ? "bg-cyan-400"
                                : "bg-red-400"
                            }`}
                          />
                          {run.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => onSelectRun(run.run_id)}
                          className="rounded bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[11px] font-mono text-text transition-colors"
                        >
                          Browse Datasets →
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
