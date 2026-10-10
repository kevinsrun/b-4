"use client";

import { useState } from "react";
import type { PredictionReport, SequenceEvidence, Prediction } from "@/lib/amp-types";
import { Panel, Status, Id } from "@/components/ui";
import { ExportModal } from "./export-modal";

interface ResultsTabProps {
  report: PredictionReport | null;
  onNavigateToDramp?: (recordId: string) => void;
  onNavigateToSubmit?: () => void;
}

export function ResultsTab({
  report,
  onNavigateToDramp,
  onNavigateToSubmit,
}: ResultsTabProps) {
  const [selectedSeqIndex, setSelectedSeqIndex] = useState(0);
  const [isExportOpen, setIsExportOpen] = useState(false);

  if (!report || report.sequences.length === 0) {
    return (
      <div className="border border-line bg-panel p-12 text-center">
        <div className="mx-auto max-w-md space-y-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">AMP Predictor</p>
          <h3 className="text-xl font-medium text-text">No Prediction Results Loaded</h3>
          <p className="text-[13px] text-muted">
            Submit a peptide sequence or Multi-FASTA file in the Submission Workspace to run real
            multi-model inference.
          </p>
          <div className="pt-2">
            <button
              onClick={onNavigateToSubmit}
              className="border border-cyan/40 bg-cyan/15 px-4 py-2 text-[12px] font-medium text-cyan hover:bg-cyan/25 transition-colors"
            >
              Go to Submission Workspace →
            </button>
          </div>
        </div>
      </div>
    );
  }

  const activeSequence: SequenceEvidence = report.sequences[selectedSeqIndex] || report.sequences[0];

  return (
    <div className="space-y-6">
      {/* Execution Summary Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Inference Report</span>
            <Status status={report.status} />
          </div>
          <h2 className="mt-1 text-2xl font-medium tracking-tight text-text">
            Multi-Model AMP Classification Results
          </h2>
          <p className="text-[12px] text-muted">
            Generated at <span className="num text-text">{new Date(report.timestamp).toLocaleString()}</span> · Schema: <code className="text-cyan-dim">{report.schema_version}</code>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsExportOpen(true)}
            className="border border-cyan/40 bg-cyan/15 px-3 py-1.5 text-[12px] font-medium text-cyan hover:bg-cyan/25 transition-colors"
          >
            Export Results (JSON / CSV)
          </button>
        </div>
      </div>

      {/* CRITICAL Scientific Caveats Banner */}
      <div className="border border-amber/40 bg-amber/8 p-4 text-[12px] text-amber space-y-1.5">
        <div className="flex items-center gap-2 font-medium">
          <span>⚠</span>
          <span>Scientific Boundaries & Calibration Policy</span>
        </div>
        <ul className="list-disc pl-5 space-y-0.5 text-[11.5px] text-muted">
          <li>
            <strong className="text-amber">Independent Score Semantics:</strong> ampir outputs SVM probability estimates (<code className="text-text">prob_AMP</code>), whereas amPEPpy outputs Random Forest probability (<code className="text-text">probability_AMP</code>). Because upstream training distributions differ, scores are not directly calibrated across models.
          </li>
          <li>
            <strong className="text-amber">No Score Averaging:</strong> This platform never calculates mathematical averages of raw predictor scores without proven biological calibration.
          </li>
          <li>
            <strong className="text-amber">Model Consensus ≠ Biological Validation:</strong> Computational agreement between predictors does not verify wet-lab activity or bactericidal efficacy.
          </li>
          <li>
            <strong className="text-amber">AMP ≠ Bacteriocin:</strong> A sequence predicted as an AMP is not automatically a bacteriocin; bacteriocins possess distinct genetic, post-translational, and receptor-binding mechanisms.
          </li>
        </ul>
      </div>

      {/* Execution Metrics Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 border border-line bg-raised/30 p-3 text-[12px]">
        <div>
          <span className="text-faint text-[10px] uppercase tracking-wider block">Duration</span>
          <span className="num font-medium text-text">{report.execution.duration_seconds.toFixed(3)}s</span>
        </div>
        <div>
          <span className="text-faint text-[10px] uppercase tracking-wider block">Sequences</span>
          <span className="num font-medium text-text">{report.sequences.length}</span>
        </div>
        <div>
          <span className="text-faint text-[10px] uppercase tracking-wider block">Predictions Succeeded</span>
          <span className="num font-medium text-green">{report.execution.successful_predictions}</span>
        </div>
        <div>
          <span className="text-faint text-[10px] uppercase tracking-wider block">Failed / Ineligible</span>
          <span className="num font-medium text-text">{report.execution.unsuccessful_predictions}</span>
        </div>
        <div>
          <span className="text-faint text-[10px] uppercase tracking-wider block">Cache Hits</span>
          <span className="num font-medium text-cyan">{report.execution.cache_hits}</span>
        </div>
      </div>

      {/* Sequence Selector Tabs if batch > 1 */}
      {report.sequences.length > 1 && (
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line pb-2">
          <span className="text-[11px] uppercase tracking-wider text-muted mr-2 shrink-0">Sequences:</span>
          {report.sequences.map((seq, idx) => (
            <button
              key={seq.sequence_id}
              onClick={() => setSelectedSeqIndex(idx)}
              className={`shrink-0 px-3 py-1 text-[12px] font-mono transition-colors border ${
                selectedSeqIndex === idx
                  ? "border-cyan/50 bg-cyan/15 text-cyan"
                  : "border-line bg-panel text-muted hover:text-text hover:border-line-strong"
              }`}
            >
              {seq.sequence_id}
              {seq.agreement.disagreement && <span className="ml-1 text-amber">⚡</span>}
            </button>
          ))}
        </div>
      )}

      {/* Active Sequence Header Card */}
      <Panel
        title={`Sequence Details: ${activeSequence.sequence_id}`}
        aside={
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted">Agreement:</span>
            {activeSequence.agreement.all_classified_models_agree ? (
              <span className="inline-flex items-center border border-green/45 bg-green/10 px-2 py-0.5 text-[10px] font-medium text-green">
                Consensus ({activeSequence.agreement.positive_votes > 0 ? "Positive" : "Negative"})
              </span>
            ) : activeSequence.agreement.disagreement ? (
              <span className="inline-flex items-center border border-amber/45 bg-amber/10 px-2 py-0.5 text-[10px] font-medium text-amber">
                Model Disagreement ({activeSequence.agreement.positive_votes} vs {activeSequence.agreement.negative_votes})
              </span>
            ) : (
              <span className="text-[10px] text-muted">Single model classified</span>
            )}
          </div>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-[11px] text-muted">
            <div>
              Identifier: <Id>{activeSequence.sequence_id}</Id>
            </div>
            <div className="sm:col-span-2">
              SHA-256 Identity: <Id>{activeSequence.sequence_checksum}</Id>
            </div>
          </div>

          <div className="bg-ink p-3 border border-line">
            <div className="text-[10px] uppercase tracking-wider text-faint mb-1">Sequence residues:</div>
            <p className="num text-[12px] text-text font-mono break-all tracking-wider leading-relaxed">
              {activeSequence.dramp_matches[0]?.sequence ||
                report.sequences.find((s) => s.sequence_id === activeSequence.sequence_id)?.sequence_checksum ||
                "Primary residues analyzed"}
            </p>
          </div>
        </div>
      </Panel>

      {/* Sequence-by-Model Comparison Matrix */}
      <Panel title="Multi-Model Comparison Matrix">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-line bg-raised/40 text-[10px] uppercase tracking-wider text-muted font-medium">
                <th className="py-2.5 px-3">Predictor</th>
                <th className="py-2.5 px-3">Version / Variant</th>
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3 text-right">Raw Score</th>
                <th className="py-2.5 px-3">Threshold</th>
                <th className="py-2.5 px-3 text-center">Predicted Class</th>
                <th className="py-2.5 px-3">Score Semantics</th>
                <th className="py-2.5 px-3 text-right">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {activeSequence.predictions.map((pred) => {
                const isAmp = pred.binary_prediction === true;
                const isNonAmp = pred.binary_prediction === false;

                return (
                  <tr key={pred.model_id} className="hover:bg-raised/20 transition-colors">
                    <td className="py-3 px-3 font-medium text-text">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold">{pred.model_id}</span>
                        {pred.cached && (
                          <span className="num text-[9px] text-cyan-dim border border-cyan-dim/40 px-1 rounded-xs">
                            cached
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-3 font-mono text-[11px] text-muted">
                      {pred.model_version} {pred.model_variant ? `(${pred.model_variant})` : ""}
                    </td>
                    <td className="py-3 px-3">
                      <Status status={pred.status} />
                    </td>
                    <td className="py-3 px-3 text-right font-mono font-medium">
                      {pred.raw_score !== null ? (
                        <span
                          className={
                            pred.raw_score >= 0.5 ? "text-green num" : "text-amber num"
                          }
                        >
                          {pred.raw_score.toFixed(4)}
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="py-3 px-3 font-mono text-[11px] text-muted">
                      {pred.threshold !== null && pred.threshold !== undefined
                        ? `≥ ${pred.threshold}`
                        : "—"}
                    </td>
                    <td className="py-3 px-3 text-center">
                      {isAmp ? (
                        <span className="inline-flex items-center rounded-xs border border-green/50 bg-green/10 px-2 py-0.5 text-[11px] font-medium text-green">
                          AMP
                        </span>
                      ) : isNonAmp ? (
                        <span className="inline-flex items-center rounded-xs border border-line-strong bg-raised px-2 py-0.5 text-[11px] font-medium text-muted">
                          Non-AMP
                        </span>
                      ) : (
                        <span className="text-[11px] text-faint">Ineligible</span>
                      )}
                    </td>
                    <td className="py-3 px-3 text-[11px] text-muted max-w-xs truncate" title={pred.score_interpretation}>
                      {pred.score_interpretation}
                    </td>
                    <td className="py-3 px-3 text-right font-mono text-[11px] text-faint">
                      {(pred.duration_seconds * 1000).toFixed(1)} ms
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Independent Score Visualization (Non-Averaged Plots) */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {activeSequence.predictions.map((pred) => {
          if (pred.raw_score === null) return null;
          const scorePercent = Math.min(100, Math.max(0, pred.raw_score * 100));
          const thresholdPercent = (pred.threshold ?? 0.5) * 100;

          return (
            <div key={`gauge-${pred.model_id}`} className="border border-line bg-panel p-4">
              <div className="flex items-center justify-between border-b border-line pb-2 mb-3">
                <div>
                  <h4 className="text-[13px] font-medium text-text capitalize">
                    {pred.model_id} Score Analysis
                  </h4>
                  <p className="text-[10px] text-muted">{pred.score_interpretation}</p>
                </div>
                <div className="text-right">
                  <div className="num text-xl font-semibold text-text">
                    {pred.raw_score.toFixed(4)}
                  </div>
                  <span className="text-[10px] text-faint">threshold: {pred.threshold ?? 0.5}</span>
                </div>
              </div>

              {/* Progress Bar with Threshold Needle */}
              <div className="relative mt-4 pt-4">
                <div className="h-3 w-full bg-raised overflow-hidden border border-line relative">
                  <div
                    className={`h-full transition-all duration-500 ${
                      pred.raw_score >= (pred.threshold ?? 0.5) ? "bg-green" : "bg-amber"
                    }`}
                    style={{ width: `${scorePercent}%` }}
                  />
                </div>
                {/* Threshold Marker */}
                <div
                  className="absolute top-0 bottom-0 flex flex-col items-center pointer-events-none"
                  style={{ left: `${thresholdPercent}%` }}
                >
                  <span className="text-[9px] text-muted font-mono leading-none">▲</span>
                  <div className="w-[1px] h-full bg-cyan" />
                  <span className="text-[9px] text-cyan font-mono leading-none mt-0.5">threshold</span>
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between text-[11px] text-muted border-t border-line/60 pt-2">
                <span>Domain: 0.0 – 1.0</span>
                <span>
                  Outcome:{" "}
                  <strong className={pred.binary_prediction ? "text-green" : "text-muted"}>
                    {pred.binary_prediction ? "Classified AMP" : "Classified Non-AMP"}
                  </strong>
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* DRAMP Reference Database Matches Panel */}
      <Panel
        title={`DRAMP Reference Evidence (${activeSequence.dramp_matches.length} Matches)`}
        aside={
          <span className="text-[11px] text-faint">
            Matches primary amino acid sequence against official DRAMP snapshot
          </span>
        }
      >
        {activeSequence.dramp_matches.length > 0 ? (
          <div className="space-y-3">
            {activeSequence.dramp_matches.map((match) => (
              <div
                key={match.record_id}
                className="border border-line bg-raised/20 p-4 transition-colors hover:border-cyan/40"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="num font-semibold text-text text-[14px]">
                      {match.metadata.Name || match.record_id}
                    </span>
                    <Id>{match.record_id}</Id>
                    <span className="text-[10px] text-cyan border border-cyan/40 bg-cyan/5 px-1.5 py-0.5">
                      DRAMP Verified
                    </span>
                  </div>
                  {onNavigateToDramp && (
                    <button
                      onClick={() => onNavigateToDramp(match.record_id)}
                      className="text-[11px] text-cyan hover:underline"
                    >
                      View in DRAMP Explorer →
                    </button>
                  )}
                </div>

                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3 text-[11.5px] text-muted">
                  <div>
                    Source Organism:{" "}
                    <span className="text-text">{match.metadata.Source || "Not reported"}</span>
                  </div>
                  <div>
                    Activity:{" "}
                    <span className="text-text">{match.metadata.Activity || "Antimicrobial"}</span>
                  </div>
                  <div>
                    Structure:{" "}
                    <span className="text-text">{match.metadata.Linear_Cyclic || "Linear"}</span>
                  </div>
                </div>

                <div className="mt-2 text-[10.5px] text-faint border-t border-line/60 pt-2 flex items-center justify-between">
                  <span>Provenance: {match.provenance.source_version}</span>
                  <span>Annotation origin: {match.annotation_origin}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-[12px] text-muted bg-raised/10 border border-dashed border-line">
            No exact primary sequence matches found in the 4 local DRAMP reference datasets.
            This sequence may be a novel synthetic construct or uncataloged variant.
          </div>
        )}
      </Panel>

      {/* Export Modal Component */}
      <ExportModal
        report={report}
        isOpen={isExportOpen}
        onClose={() => setIsExportOpen(false)}
      />
    </div>
  );
}
