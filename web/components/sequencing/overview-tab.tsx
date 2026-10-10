"use client";

import {
  ConnectorInfo,
  SequencingConnection,
  SequencingRun,
  SequencingDataset,
} from "@/lib/sequencing-types";

interface OverviewTabProps {
  connectors: ConnectorInfo[];
  connections: SequencingConnection[];
  runs: SequencingRun[];
  datasets: SequencingDataset[];
  onNavigateTab: (tab: "runs" | "datasets" | "connections" | "imports") => void;
  onSelectRun: (runId: string) => void;
}

export function OverviewTab({
  connectors,
  connections,
  runs,
  datasets,
  onNavigateTab,
  onSelectRun,
}: OverviewTabProps) {
  function formatBytes(bytes: number) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  }

  const totalBytes = runs.reduce((acc, r) => acc + (r.total_size_bytes || 0), 0);
  const importedCount = datasets.filter((d) => d.import_status === "imported").length;

  return (
    <div className="space-y-8">
      {/* Hero Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Connected Platforms</span>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold font-mono text-text">{connections.length}</span>
            <span className="text-[11px] text-muted">/ {connectors.length} supported</span>
          </div>
          <span className="text-[11px] text-emerald-400 mt-1 block">
            Illumina • ONT • PacBio • Local
          </span>
        </div>

        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Discovered Runs</span>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold font-mono text-text">{runs.length}</span>
            <span className="text-[11px] text-muted">active & archived</span>
          </div>
          <span className="text-[11px] text-muted mt-1 block truncate">
            Across all instrument endpoints
          </span>
        </div>

        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Sequencing Datasets</span>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold font-mono text-text">{datasets.length}</span>
            <span className="text-[11px] text-emerald-400 font-mono">({importedCount} staged)</span>
          </div>
          <span className="text-[11px] text-muted mt-1 block">FASTQ, HiFi BAM, POD5</span>
        </div>

        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Total Remote Volume</span>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold font-mono text-accent">
              {formatBytes(totalBytes)}
            </span>
          </div>
          <span className="text-[11px] text-muted mt-1 block">Indexed metadata & files</span>
        </div>
      </div>

      {/* Scientific Workflow Architecture Card */}
      <div className="rounded-xl border border-line bg-surface/30 p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 pb-3">
          <div>
            <h3 className="text-sm font-semibold text-text">
              Universal Sequencing to Bacteriocin Discovery Pipeline
            </h3>
            <p className="text-[12px] text-muted">
              Standardized automated ingestion with strict biological handoff validation.
            </p>
          </div>
          <span className="rounded bg-accent/15 px-2.5 py-0.5 text-[11px] font-mono text-accent">
            Sequence Once → Analyze in B-4
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-3 pt-2">
          <div className="rounded-lg border border-line bg-card p-3">
            <span className="text-[10px] font-mono text-accent font-semibold block">STEP 1</span>
            <h4 className="font-semibold text-text text-[12px] mt-0.5">Automated Ingestion</h4>
            <p className="text-[11px] text-muted mt-1">
              BaseSpace v1pre3, MinKNOW folders, SMRT Link HiFi BAM, or allowlisted drops.
            </p>
          </div>

          <div className="rounded-lg border border-line bg-card p-3">
            <span className="text-[10px] font-mono text-accent font-semibold block">STEP 2</span>
            <h4 className="font-semibold text-text text-[12px] mt-0.5">Integrity & QC</h4>
            <p className="text-[11px] text-muted mt-1">
              Streaming SHA-256 calculation, file stability detection, and FastQC / NanoPlot metrics.
            </p>
          </div>

          <div className="rounded-lg border border-line bg-card p-3">
            <span className="text-[10px] font-mono text-accent font-semibold block">STEP 3</span>
            <h4 className="font-semibold text-text text-[12px] mt-0.5">Assembly & Gene Calling</h4>
            <p className="text-[11px] text-muted mt-1">
              SPAdes / Flye assembly and Prodigal / BAGEL4 ribosomal bacteriocin ORF discovery.
            </p>
          </div>

          <div className="rounded-lg border border-line bg-card p-3">
            <span className="text-[10px] font-mono text-accent font-semibold block">STEP 4</span>
            <h4 className="font-semibold text-text text-[12px] mt-0.5">Peptide Translation</h4>
            <p className="text-[11px] text-muted mt-1">
              6-frame or CDS amino acid translation (10-100 AA candidate short peptides).
            </p>
          </div>

          <div className="rounded-lg border border-line bg-card p-3 border-emerald-500/30 bg-emerald-500/5">
            <span className="text-[10px] font-mono text-emerald-400 font-semibold block">STEP 5</span>
            <h4 className="font-semibold text-text text-[12px] mt-0.5">AMP Prediction</h4>
            <p className="text-[11px] text-muted mt-1">
              Direct handoff into ampir and amPEPpy machine-learning inference workspace.
            </p>
          </div>
        </div>
      </div>

      {/* Recent Discovered Runs Preview */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-mono uppercase tracking-wider text-muted">
            Recently Discovered Runs
          </h3>
          <button
            onClick={() => onNavigateTab("runs")}
            className="text-xs font-mono text-accent hover:underline"
          >
            View all {runs.length} runs →
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {runs.slice(0, 3).map((r) => (
            <div
              key={r.run_id}
              onClick={() => onSelectRun(r.run_id)}
              className="rounded-xl border border-line bg-card p-4 hover:border-accent/40 cursor-pointer transition-all"
            >
              <div className="flex items-center justify-between">
                <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted border border-line/50">
                  {r.vendor}
                </span>
                <span className="text-[10px] font-mono text-emerald-400 uppercase">
                  {r.status}
                </span>
              </div>
              <h4 className="font-mono font-semibold text-text text-[13px] mt-2 truncate">
                {r.run_name}
              </h4>
              <p className="text-[11px] text-muted mt-0.5 truncate">
                {r.instrument_model} • {r.project_name || "General"}
              </p>
              <div className="mt-3 pt-2 border-t border-line/50 flex items-center justify-between text-[11px] font-mono text-muted">
                <span>{r.dataset_count} datasets</span>
                <span className="text-text font-medium">{formatBytes(r.total_size_bytes)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
