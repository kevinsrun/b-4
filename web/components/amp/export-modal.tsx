"use client";

import { useState } from "react";
import type { PredictionReport } from "@/lib/amp-types";

interface ExportModalProps {
  report: PredictionReport | null;
  isOpen: boolean;
  onClose: () => void;
}

export function ExportModal({ report, isOpen, onClose }: ExportModalProps) {
  const [format, setFormat] = useState<"json" | "csv" | "markdown">("json");
  const [copied, setCopied] = useState(false);

  if (!isOpen || !report) return null;

  function generateJson(): string {
    return JSON.stringify(report, null, 2);
  }

  function generateCsv(): string {
    const headers = [
      "sequence_id",
      "sequence_length",
      "sequence_checksum",
      "model_id",
      "model_version",
      "model_variant",
      "raw_score",
      "score_interpretation",
      "classification_threshold",
      "predicted_class",
      "status",
      "duration_seconds",
      "cached",
      "dramp_match_count",
      "warnings",
      "timestamp",
    ];

    const rows: string[] = [headers.join(",")];

    for (const seq of report?.sequences ?? []) {
      for (const pred of seq.predictions) {
        const row = [
          `"${seq.sequence_id}"`,
          pred.native_scores ? Object.keys(pred.native_scores).length : "0",
          `"${seq.sequence_checksum}"`,
          `"${pred.model_id}"`,
          `"${pred.model_version}"`,
          `"${pred.model_variant ?? ""}"`,
          pred.raw_score !== null ? pred.raw_score.toFixed(6) : "",
          `"${pred.score_interpretation.replace(/"/g, '""')}"`,
          pred.threshold !== null && pred.threshold !== undefined ? pred.threshold.toString() : "",
          pred.binary_prediction !== null && pred.binary_prediction !== undefined
            ? pred.binary_prediction
              ? "AMP"
              : "Non-AMP"
            : "unclassified",
          `"${pred.status}"`,
          pred.duration_seconds.toFixed(4),
          pred.cached ? "true" : "false",
          seq.dramp_matches.length.toString(),
          `"${[...seq.warnings, ...pred.warnings].join("; ").replace(/"/g, '""')}"`,
          `"${pred.timestamp}"`,
        ];
        rows.push(row.join(","));
      }
    }

    return rows.join("\n");
  }

  function generateMarkdown(): string {
    const lines: string[] = [
      "# B-4 Bacteriocin Platform — AMP Inference Summary Report",
      "",
      `**Generated:** ${report?.timestamp}`,
      `**Report Schema:** ${report?.schema_version}`,
      `**Execution Status:** ${report?.status.toUpperCase()}`,
      `**Total Sequences:** ${report?.sequences.length}`,
      `**Execution Duration:** ${report?.execution.duration_seconds.toFixed(3)}s`,
      "",
      "## Scientific Limitations and Boundaries",
      "",
      "- Computational AMP predictions do NOT establish bacteriocin identity or experimental antimicrobial activity.",
      "- Model scores have independent training domains; no cross-model calibration is mathematically justified.",
      "- DRAMP matches represent reference database annotations, not independent experimental verification.",
      "",
      "## Sequence Results Table",
      "",
      "| Sequence ID | Length | Model | Variant | Raw Score | Score Interpretation | Threshold | Prediction | Status |",
      "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ];

    for (const seq of report?.sequences ?? []) {
      for (const pred of seq.predictions) {
        const scoreStr = pred.raw_score !== null ? pred.raw_score.toFixed(4) : "—";
        const predStr =
          pred.binary_prediction !== null && pred.binary_prediction !== undefined
            ? pred.binary_prediction
              ? "**AMP**"
              : "Non-AMP"
            : "—";
        lines.push(
          `| \`${seq.sequence_id}\` | — | ${pred.model_id} | ${pred.model_variant ?? "standard"} | ${scoreStr} | ${pred.score_interpretation} | ${pred.threshold ?? "—"} | ${predStr} | \`${pred.status}\` |`
        );
      }
    }

    return lines.join("\n");
  }

  const exportContent =
    format === "json" ? generateJson() : format === "csv" ? generateCsv() : generateMarkdown();

  function handleCopy() {
    navigator.clipboard.writeText(exportContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleDownload() {
    const mimeType =
      format === "json"
        ? "application/json"
        : format === "csv"
        ? "text/csv"
        : "text/markdown";
    const extension = format === "json" ? "json" : format === "csv" ? "csv" : "md";
    const blob = new Blob([exportContent], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `b4-amp-prediction-report-${new Date().toISOString().replace(/[:.]/g, "-")}.${extension}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col border border-line-strong bg-panel shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Export</span>
            <h3 className="text-[14px] font-medium text-text">Research Evidence & Structured Export</h3>
          </div>
          <button
            onClick={onClose}
            className="text-[12px] text-muted hover:text-text transition-colors"
          >
            ✕ Close
          </button>
        </header>

        <div className="flex items-center gap-2 border-b border-line bg-raised/40 px-5 py-2.5">
          <span className="text-[12px] text-muted mr-2">Format:</span>
          {(["json", "csv", "markdown"] as const).map((fmt) => (
            <button
              key={fmt}
              onClick={() => setFormat(fmt)}
              className={`px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors border ${
                format === fmt
                  ? "border-cyan/50 bg-cyan/10 text-cyan"
                  : "border-transparent text-muted hover:text-text hover:bg-raised"
              }`}
            >
              {fmt}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="border border-line bg-raised px-3 py-1 text-[11px] font-medium text-text transition-colors hover:border-cyan/40 hover:text-cyan"
            >
              {copied ? "✓ Copied" : "Copy to Clipboard"}
            </button>
            <button
              onClick={handleDownload}
              className="border border-cyan/40 bg-cyan/15 px-3 py-1 text-[11px] font-medium text-cyan transition-colors hover:bg-cyan/25"
            >
              Download File
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4">
          <pre className="num text-[11.5px] leading-relaxed text-text/90 font-mono bg-ink p-4 border border-line overflow-x-auto whitespace-pre">
            {exportContent}
          </pre>
        </div>

        <footer className="border-t border-line bg-raised/30 px-5 py-2.5 text-[11px] text-muted flex items-center justify-between">
          <span>Preserves model-specific score semantics and scientific warnings</span>
          <span className="num">
            {report.sequences.length} sequence{report.sequences.length === 1 ? "" : "s"} · {report.status}
          </span>
        </footer>
      </div>
    </div>
  );
}
