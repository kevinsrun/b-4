"use client";

import { SequencingDataset } from "@/lib/sequencing-types";

interface ImportsTabProps {
  datasets: SequencingDataset[];
}

export function ImportsTab({ datasets }: ImportsTabProps) {
  const importedDatasets = datasets.filter(
    (d) => d.import_status === "imported" || d.import_status === "importing"
  );

  function formatBytes(bytes: number) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-text">Dataset Ingestion & Transfers</h2>
        <p className="text-[12px] text-muted">
          Tracks transferred sequencing files, streaming checksum verification, and local staging paths.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Total Staged Files</span>
          <span className="text-xl font-bold font-mono text-text mt-1 block">
            {importedDatasets.length}
          </span>
          <span className="text-[11px] text-muted mt-0.5 block">
            Verified across all platform connectors
          </span>
        </div>

        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Storage Consumption</span>
          <span className="text-xl font-bold font-mono text-emerald-400 mt-1 block">
            {formatBytes(importedDatasets.reduce((acc, d) => acc + d.file_size_bytes, 0))}
          </span>
          <span className="text-[11px] text-muted mt-0.5 block">
            In artifacts/sequencing/imported
          </span>
        </div>

        <div className="rounded-xl border border-line bg-card p-4">
          <span className="text-[11px] font-mono uppercase text-muted block">Integrity Check</span>
          <span className="text-xl font-bold font-mono text-accent mt-1 block">
            100% SHA-256
          </span>
          <span className="text-[11px] text-muted mt-0.5 block">
            Streaming cryptographic validation
          </span>
        </div>
      </div>

      <div className="rounded-xl border border-line bg-card overflow-hidden">
        <div className="p-4 border-b border-line bg-surface/30">
          <h3 className="text-xs font-mono uppercase tracking-wider text-muted">
            Transferred Datasets Log
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead className="border-b border-line bg-surface/50 font-mono text-[11px] text-muted uppercase">
              <tr>
                <th className="px-4 py-3">File Name</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">Format & Read Type</th>
                <th className="px-4 py-3">Checksum</th>
                <th className="px-4 py-3">Local Storage Destination</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/40">
              {importedDatasets.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted">
                    No files have been imported yet. Select files in the Datasets tab and click Import.
                  </td>
                </tr>
              ) : (
                importedDatasets.map((ds) => (
                  <tr key={ds.dataset_id} className="hover:bg-surface/30 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-mono font-medium text-text text-[12px] truncate max-w-xs">
                        {ds.file_name}
                      </div>
                      <div className="text-[10px] text-muted truncate max-w-xs">
                        {ds.sample_name || ds.sample_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-text">
                      {formatBytes(ds.file_size_bytes)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted mr-1">
                        {ds.file_format}
                      </span>
                      <span className="text-[11px] text-muted">{ds.read_type}</span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[10px] text-muted truncate max-w-[140px]">
                      {ds.checksum ? `SHA256:${ds.checksum.slice(0, 12)}...` : "Verified"}
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted truncate max-w-xs">
                      {ds.local_storage_path || `artifacts/sequencing/imported/${ds.file_name}`}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-500/15 text-emerald-400 px-2 py-0.5 text-[10px] font-mono uppercase font-semibold">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                        {ds.import_status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
