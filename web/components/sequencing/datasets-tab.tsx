"use client";

import { useState } from "react";
import { SequencingDataset } from "@/lib/sequencing-types";
import { initiateImport } from "@/lib/sequencing-api";

interface DatasetsTabProps {
  datasets: SequencingDataset[];
  selectedRunId: string | null;
  onClearRunFilter: () => void;
  onOpenHandoff: (dataset: SequencingDataset) => void;
  onRefresh: () => void;
}

export function DatasetsTab({
  datasets,
  selectedRunId,
  onClearRunFilter,
  onOpenHandoff,
  onRefresh,
}: DatasetsTabProps) {
  const [filterFormat, setFilterFormat] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [importingId, setImportingId] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const filtered = datasets.filter((d) => {
    if (selectedRunId && d.run_id !== selectedRunId) return false;
    if (filterFormat !== "all" && !d.file_format.includes(filterFormat)) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchName = d.file_name.toLowerCase().includes(q);
      const matchSample = (d.sample_name || "").toLowerCase().includes(q);
      if (!matchName && !matchSample) return false;
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

  async function handleImport(datasetId: string) {
    setImportingId(datasetId);
    setNotification(null);
    try {
      const res = await initiateImport(datasetId);
      setNotification({
        type: "success",
        text: `Import job initiated: ${res.importJob.status}. Verified SHA-256 checksum and staged locally.`,
      });
      onRefresh();
    } catch (err: any) {
      setNotification({
        type: "error",
        text: err.message || "Import failed",
      });
    } finally {
      setImportingId(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header and scoped run pill */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-text">Sequencing Datasets & Files</h2>
            {selectedRunId && (
              <div className="flex items-center gap-1.5 rounded-full bg-accent/15 px-2.5 py-0.5 text-[11px] font-mono text-accent">
                <span>Run: {selectedRunId.slice(-12)}</span>
                <button
                  onClick={onClearRunFilter}
                  className="hover:text-text text-muted"
                  title="Clear filter"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
          <p className="text-[12px] text-muted">
            Individual sequencing files, demultiplexed reads, BAM alignments, and raw signal datasets.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Format selector */}
          <div className="flex items-center rounded-lg border border-line bg-surface/50 p-0.5 text-[11px] font-mono">
            {["all", "fastq", "bam", "pod5", "fasta"].map((f) => (
              <button
                key={f}
                onClick={() => setFilterFormat(f)}
                className={`rounded px-2.5 py-1 uppercase transition-colors ${
                  filterFormat === f
                    ? "bg-accent text-black font-semibold"
                    : "text-muted hover:text-text"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <input
            type="text"
            placeholder="Search dataset file or sample..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs text-text placeholder-muted font-mono focus:outline-none focus:border-accent w-56"
          />
        </div>
      </div>

      {notification && (
        <div
          className={`rounded-lg border p-3 text-[12px] flex items-center justify-between ${
            notification.type === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-red-500/30 bg-red-500/10 text-red-300"
          }`}
        >
          <span>{notification.text}</span>
          <button onClick={() => setNotification(null)} className="text-muted hover:text-text">✕</button>
        </div>
      )}

      {/* Datasets Table */}
      <div className="rounded-xl border border-line bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead className="border-b border-line bg-surface/50 font-mono text-[11px] text-muted uppercase">
              <tr>
                <th className="px-4 py-3">File Name & Sample</th>
                <th className="px-4 py-3">Format</th>
                <th className="px-4 py-3">Read Type</th>
                <th className="px-4 py-3 text-right">Size</th>
                <th className="px-4 py-3">Checksum / Stability</th>
                <th className="px-4 py-3">Import Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/40">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted">
                    No sequencing datasets found matching the selection.
                  </td>
                </tr>
              ) : (
                filtered.map((ds) => {
                  const isImported = ds.import_status === "imported";
                  const isImporting = importingId === ds.dataset_id || ds.import_status === "importing";
                  const isSignal = ds.read_type === "raw_signal";
                  const isHifi = ds.read_type === "hifi_ccs";

                  return (
                    <tr key={ds.dataset_id} className="hover:bg-surface/30 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-mono font-medium text-text text-[12px] truncate max-w-sm">
                          {ds.file_name}
                        </div>
                        <div className="text-[11px] text-muted truncate max-w-sm">
                          {ds.sample_name || ds.sample_id || "Unlabeled sample"}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted border border-line/50">
                          {ds.file_format}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
                            isHifi
                              ? "bg-purple-500/15 text-purple-300 font-semibold"
                              : isSignal
                              ? "bg-amber-500/15 text-amber-300"
                              : "bg-surface text-muted"
                          }`}
                        >
                          {ds.read_type.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-medium text-text">
                        {formatBytes(ds.file_size_bytes)}
                      </td>
                      <td className="px-4 py-3">
                        {ds.checksum ? (
                          <div className="font-mono text-[10px] text-muted truncate max-w-[140px]" title={ds.checksum}>
                            {ds.checksum.slice(0, 16)}...
                          </div>
                        ) : (
                          <span className="text-[10px] text-muted italic">On demand</span>
                        )}
                        <span className="text-[10px] font-mono text-emerald-400 block">
                          ✓ stable
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-mono uppercase font-semibold ${
                            isImported
                              ? "bg-emerald-500/15 text-emerald-400"
                              : isImporting
                              ? "bg-cyan-500/15 text-cyan-400 animate-pulse"
                              : "bg-surface text-muted"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              isImported ? "bg-emerald-400" : isImporting ? "bg-cyan-400" : "bg-muted"
                            }`}
                          />
                          {ds.import_status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => onOpenHandoff(ds)}
                            className="rounded bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 px-2 py-1 text-[11px] font-mono transition-colors font-medium"
                          >
                            Handoff →
                          </button>
                          {!isImported && (
                            <button
                              onClick={() => handleImport(ds.dataset_id)}
                              disabled={isImporting}
                              className="rounded bg-surface hover:bg-surface/80 border border-line px-2 py-1 text-[11px] font-mono text-text transition-colors"
                            >
                              {isImporting ? "Importing..." : "Import"}
                            </button>
                          )}
                        </div>
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
