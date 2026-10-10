"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SequencingDataset, AnalysisHandoffResponse } from "@/lib/sequencing-types";
import { fetchAnalysisHandoff } from "@/lib/sequencing-api";

interface HandoffModalProps {
  dataset: SequencingDataset | null;
  onClose: () => void;
}

export function HandoffModal({ dataset, onClose }: HandoffModalProps) {
  const router = useRouter();
  const [handoff, setHandoff] = useState<AnalysisHandoffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dataset) return;
    setLoading(true);
    setError(null);
    fetchAnalysisHandoff(dataset.dataset_id)
      .then((res) => setHandoff(res.handoff))
      .catch((err) => setError(err.message || "Failed to evaluate analysis handoff"))
      .finally(() => setLoading(false));
  }, [dataset]);

  if (!dataset) return null;

  function handleSendToPredictor(peptideSeq?: string) {
    // If a specific peptide is selected or preview available, transfer to /amp
    if (peptideSeq) {
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("bactrogen_amp_prefill_seq", peptideSeq);
      }
    }
    router.push("/amp");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-3xl rounded-xl border border-line bg-card shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-6 py-4 bg-surface/50">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-muted">
                Scientific Pipeline Handoff
              </span>
              <span className="rounded bg-accent/15 text-accent px-1.5 py-0.5 text-[10px] font-mono">
                {dataset.file_format.toUpperCase()}
              </span>
            </div>
            <h3 className="text-base font-semibold text-text mt-0.5 font-mono truncate max-w-lg">
              {dataset.file_name}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted hover:text-text hover:bg-surface transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 text-[13px]">
          {loading && (
            <div className="py-12 text-center text-muted flex flex-col items-center gap-2">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span>Evaluating dataset eligibility and bioinformatics dependencies...</span>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-300">
              <p className="font-medium">Analysis Handoff Error</p>
              <p className="text-[12px] mt-1">{error}</p>
            </div>
          )}

          {handoff && (
            <>
              {/* Scientific Advisory Notice */}
              <div
                className={`rounded-xl border p-4 ${
                  handoff.direct_amp_eligible
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-200"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 font-mono text-base font-bold">
                    {handoff.direct_amp_eligible ? "✓" : "!"}
                  </div>
                  <div>
                    <h4 className="font-semibold text-text text-sm">
                      {handoff.direct_amp_eligible
                        ? "Direct AMP Inference Eligible"
                        : "Mandatory Upstream Pipeline Steps Required"}
                    </h4>
                    <p className="mt-1 text-[12px] opacity-90 leading-relaxed">
                      {handoff.prerequisite_notice}
                    </p>
                    <p className="mt-1 text-[11px] opacity-75 font-mono">
                      Data Type: {handoff.data_type.replace(/_/g, " ")} | Recommendation:{" "}
                      {handoff.recommendation}
                    </p>
                  </div>
                </div>
              </div>

              {/* Multi-Stage Pipeline Progression */}
              <div>
                <h4 className="text-xs font-mono uppercase tracking-wider text-muted mb-3">
                  Bioinformatics Processing Pipeline
                </h4>
                <div className="space-y-2">
                  {handoff.pipeline_stages.map((stage, idx) => {
                    const isReady = stage.status === "ready";
                    const isPending = stage.status === "pending_prerequisite";
                    const isCompleted = stage.status === "completed";

                    return (
                      <div
                        key={stage.stage_id}
                        className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
                          isReady
                            ? "border-accent/40 bg-accent/5"
                            : isCompleted
                            ? "border-emerald-500/40 bg-emerald-500/5"
                            : "border-line/60 bg-surface/30 opacity-75"
                        }`}
                      >
                        <div
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-mono font-bold ${
                            isCompleted
                              ? "bg-emerald-500/20 text-emerald-400"
                              : isReady
                              ? "bg-accent/20 text-accent"
                              : "bg-surface text-muted"
                          }`}
                        >
                          {idx + 1}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-text text-[13px]">{stage.name}</span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
                                isCompleted
                                  ? "bg-emerald-500/20 text-emerald-400"
                                  : isReady
                                  ? "bg-accent/20 text-accent font-semibold"
                                  : "bg-surface text-muted"
                              }`}
                            >
                              {stage.status.replace(/_/g, " ")}
                            </span>
                          </div>
                          <p className="text-[12px] text-muted mt-0.5">{stage.description}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Extracted / Candidate Peptides Preview */}
              {handoff.extracted_peptides_preview.length > 0 && (
                <div className="rounded-xl border border-line bg-surface/40 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-mono uppercase tracking-wider text-muted">
                      Candidate Peptides for Bacteriocin Screening
                    </h4>
                    <span className="text-[11px] font-mono text-accent">
                      {handoff.extracted_peptides_preview.length} candidate(s) discovered
                    </span>
                  </div>

                  <div className="space-y-2">
                    {handoff.extracted_peptides_preview.map((pep) => (
                      <div
                        key={pep.id}
                        className="rounded-lg border border-line bg-card p-3 flex flex-wrap items-center justify-between gap-3"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-semibold text-text text-[12px]">
                              {pep.id}
                            </span>
                            <span className="rounded bg-surface px-1.5 py-0.2 text-[10px] font-mono text-muted">
                              {pep.length} AA
                            </span>
                          </div>
                          <p className="text-[11px] text-muted mt-0.5">{pep.description}</p>
                          <p className="text-[11px] font-mono text-emerald-400 mt-1 break-all bg-surface/60 px-2 py-1 rounded">
                            {pep.sequence}
                          </p>
                        </div>

                        <button
                          onClick={() => handleSendToPredictor(pep.sequence)}
                          className="rounded-lg bg-accent px-3 py-1.5 text-[11px] font-semibold text-black hover:brightness-110 transition-all font-mono whitespace-nowrap"
                        >
                          Screen with ampir & amPEPpy →
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between border-t border-line px-6 py-4 bg-surface/50">
          <div className="text-[11px] text-muted font-mono">
            Platform Rule: No automated averaging of heterogeneous predictor scores.
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="rounded-lg border border-line px-4 py-2 text-[12px] font-medium text-text hover:bg-surface transition-colors"
            >
              Close
            </button>
            <button
              onClick={() => handleSendToPredictor()}
              className="rounded-lg bg-surface border border-line px-4 py-2 text-[12px] font-medium text-text hover:bg-surface/80 transition-colors"
            >
              Open AMP Predictor Workspace
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
