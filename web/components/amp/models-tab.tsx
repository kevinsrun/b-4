"use client";

import { useState } from "react";
import type { ModelHealth, ModelsHealthResponse } from "@/lib/amp-types";
import { Panel, Status, Id } from "@/components/ui";

interface ModelsTabProps {
  healthData: ModelsHealthResponse | null;
  onRefresh?: () => void;
  isBackendConnected: boolean;
}

export function ModelsTab({
  healthData,
  onRefresh,
  isBackendConnected,
}: ModelsTabProps) {
  const [selectedModelId, setSelectedModelId] = useState<string>("ampir");

  const models = healthData?.models ?? [];
  const activeModel = models.find((m) => m.model_id === selectedModelId) || models[0];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Registry & Diagnostics</p>
          <h2 className="mt-1 text-2xl font-medium tracking-tight text-text">
            AMP Model Registry & Runtime Health
          </h2>
          <p className="text-[12px] text-muted">
            Independent verification status for all six supported AMP classifier runtimes and adapters.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
            className="border border-line bg-raised px-3 py-1.5 text-[12px] font-medium text-muted hover:border-cyan/40 hover:text-text transition-colors"
          >
            ↻ Refresh Health Status
          </button>
        </div>
      </div>

      {/* System Resources Telemetry */}
      {healthData?.resources && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 border border-line bg-raised/20 p-3 text-[12px]">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-faint block">Max Concurrent Processes</span>
            <span className="num font-semibold text-text">{healthData.resources.max_concurrent_model_processes}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-faint block">Active Model Tasks</span>
            <span className="num font-semibold text-cyan">{healthData.resources.active_model_tasks}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-faint block">API Process Peak RSS</span>
            <span className="num font-semibold text-text">
              {(healthData.resources.api_process_peak_rss_kib / 1024).toFixed(1)} MiB
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-faint block">CPU Seconds</span>
            <span className="num font-semibold text-text">{healthData.resources.cpu_seconds.toFixed(2)}s</span>
          </div>
        </div>
      )}

      {/* Status Legend */}
      <div className="flex flex-wrap items-center gap-4 rounded-xs border border-line bg-panel p-3 text-[11px]">
        <span className="font-medium text-text">Status Semantics:</span>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-green" />
          <span className="text-muted"><strong className="text-green">READY</strong> — Actual end-to-end inference verified on host runtime</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber" />
          <span className="text-muted"><strong className="text-amber">PARTIAL</strong> — Adapter exists, but inference unverified locally</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-red" />
          <span className="text-muted"><strong className="text-red">BLOCKED</strong> — Model cannot execute (runtime incompatible or license unresolved)</span>
        </div>
      </div>

      {/* Six Model Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {models.map((model) => {
          const isSelected = model.model_id === selectedModelId;
          const statusBadge =
            model.status === "READY"
              ? "border-green/45 text-green bg-green/8"
              : model.status === "PARTIAL"
              ? "border-amber/45 text-amber bg-amber/8"
              : "border-red/45 text-red bg-red/8";

          return (
            <div
              key={model.model_id}
              onClick={() => setSelectedModelId(model.model_id)}
              className={`cursor-pointer border p-4 transition-all ${
                isSelected
                  ? "border-cyan bg-panel shadow-md ring-1 ring-cyan/40"
                  : "border-line bg-panel/70 hover:border-line-strong hover:bg-panel"
              }`}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-[14px] font-semibold text-text capitalize">
                  {model.model_id}
                </h3>
                <span className={`num border px-2 py-0.5 text-[10px] font-semibold ${statusBadge}`}>
                  {model.status}
                </span>
              </div>

              <div className="mt-2 text-[11.5px] text-muted space-y-1">
                <div>
                  Version: <span className="font-mono text-text">{model.model_version}</span>
                </div>
                <div>
                  Domain:{" "}
                  <span className="font-mono text-text">
                    {model.min_length !== null ? `≥${model.min_length}` : "≥1"}
                    {model.max_length !== null ? ` to ≤${model.max_length}` : ""} aa
                  </span>
                </div>
                <div>
                  License: <span className="text-text">{model.license}</span>
                </div>
              </div>

              {model.blocker ? (
                <div className="mt-3 border-t border-line/60 pt-2 text-[10.5px] text-red line-clamp-2">
                  ⚠ {model.blocker}
                </div>
              ) : model.verification ? (
                <div className="mt-3 border-t border-line/60 pt-2 text-[10.5px] text-green flex items-center justify-between">
                  <span>✓ Reference verified</span>
                  <span className="font-mono text-[9px] text-muted">
                    {model.verification.verified_variants.join(", ")}
                  </span>
                </div>
              ) : (
                <div className="mt-3 border-t border-line/60 pt-2 text-[10.5px] text-muted">
                  {model.reason || "Operational status under review"}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Selected Model Detailed Inspector */}
      {activeModel && (
        <Panel
          title={
            <div className="flex items-center gap-2">
              <span>Model Card:</span>
              <span className="font-bold capitalize">{activeModel.model_id}</span>
              <Status status={activeModel.status} />
            </div>
          }
          aside={
            <div className="flex items-center gap-3 text-[11px]">
              {activeModel.source && (
                <a
                  href={activeModel.source}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan hover:underline"
                >
                  Source Repository ↗
                </a>
              )}
              {activeModel.publication && (
                <a
                  href={activeModel.publication}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan hover:underline"
                >
                  Publication DOI ↗
                </a>
              )}
            </div>
          }
        >
          <div className="space-y-4">
            {/* Metadata Grid */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 border-b border-line pb-4 text-[12px]">
              <div>
                <span className="text-[10px] uppercase tracking-wider text-faint block">Source Revision</span>
                <Id>{activeModel.source_commit || "unpinned"}</Id>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-faint block">Class Definition</span>
                <span className="text-text text-[11.5px]">{activeModel.class_definition}</span>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-faint block">Independent Validation</span>
                <span className="text-amber text-[11.5px]">BLOCKED (biological applicability unproven)</span>
              </div>
            </div>

            {/* Score Semantics */}
            <div>
              <span className="text-[10px] uppercase tracking-wider text-faint block mb-1">
                Score Semantics & Interpretation
              </span>
              <p className="text-[12px] text-text bg-raised/40 p-2.5 border border-line font-mono">
                {activeModel.score_interpretation}
              </p>
            </div>

            {/* Runtime Requirements */}
            <div>
              <span className="text-[10px] uppercase tracking-wider text-faint block mb-1">
                Required Runtime Environment
              </span>
              <div className="flex flex-wrap gap-1.5">
                {activeModel.requires?.map((req) => (
                  <span
                    key={req}
                    className="border border-line bg-raised px-2 py-0.5 text-[11px] font-mono text-muted"
                  >
                    {req}
                  </span>
                ))}
              </div>
            </div>

            {/* Documented Limitations */}
            {activeModel.limitations?.length > 0 && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-faint block mb-1">
                  Documented Scientific Limitations
                </span>
                <ul className="list-disc pl-5 space-y-1 text-[11.5px] text-muted">
                  {activeModel.limitations.map((lim, i) => (
                    <li key={i}>{lim}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Blocker Banner if blocked */}
            {activeModel.blocker && (
              <div className="border border-red/40 bg-red/10 p-3 text-[12px] text-red space-y-1">
                <div className="font-medium">Execution Blocker:</div>
                <p className="text-[11.5px]">{activeModel.blocker}</p>
              </div>
            )}

            {/* Verification Proof Details if verified */}
            {activeModel.verification && (
              <div className="border border-green/40 bg-green/5 p-3 text-[12px] space-y-2">
                <div className="flex items-center justify-between text-green font-medium">
                  <span>Host Runtime Verification Proof</span>
                  <span className="text-[10px] font-mono text-muted">
                    {new Date(activeModel.verification.timestamp).toLocaleString()}
                  </span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-[11px] text-muted">
                  <div>
                    Fingerprint: <Id>{activeModel.verification.fingerprint.slice(0, 16)}...</Id>
                  </div>
                  <div>
                    Evidence File: <Id>{activeModel.verification.evidence_path}</Id>
                  </div>
                  <div>
                    Verified Variants:{" "}
                    <span className="text-text font-mono">
                      {activeModel.verification.verified_variants.join(", ")}
                    </span>
                  </div>
                  <div>
                    Reference Agreement: <span className="text-green font-semibold">PASSED</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </Panel>
      )}
    </div>
  );
}
