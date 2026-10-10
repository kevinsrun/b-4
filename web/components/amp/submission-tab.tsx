"use client";

import { useId, useState } from "react";
import type { PredictRequest, PredictionReport, JobResponse, ModelHealth } from "@/lib/amp-types";
import {
  validateBatch,
  parseFasta,
  toFasta,
  type BatchValidationResult,
} from "@/lib/sequence-validator";
import { REFERENCE_PRESETS, type ReferencePreset } from "@/lib/amp-fixtures";
import { predictAmp, submitBatchAmp } from "@/lib/amp-api";
import { Panel, Status, Id } from "@/components/ui";

interface SubmissionTabProps {
  modelsHealth: ModelHealth[];
  isBackendConnected: boolean;
  useFixtures: boolean;
  onPredictionComplete: (report: PredictionReport) => void;
  onBatchSubmitted: (job: JobResponse) => void;
  initialSequences?: { sequence_id: string; sequence: string }[];
}

export function SubmissionTab({
  modelsHealth,
  isBackendConnected,
  useFixtures,
  onPredictionComplete,
  onBatchSubmitted,
  initialSequences,
}: SubmissionTabProps) {
  const [inputMode, setInputMode] = useState<"single" | "fasta" | "presets">("single");
  const defaultId = useId().replace(/[:]/g, "_");

  // Single sequence state
  const [singleId, setSingleId] = useState("nisin_a_mature");
  const [singleSeq, setSingleSeq] = useState("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK");

  // Multi-FASTA state
  const [fastaText, setFastaText] = useState(
    ">nisin_a_mature\nITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK\n\n>glfdiv_ref\nGLFDIVKKVVGALG\n\n>bovicin_hc5\nVGACGYGCSGCTGGCLCG"
  );

  // Model selection state
  const [selectedModels, setSelectedModels] = useState<Record<string, boolean>>({
    ampir: true,
    ampeppy: true,
    amplify: false,
    ampscanner_v2: false,
    ai4amp: false,
    apin: false,
  });

  // Variant & Execution options
  const [ampirVariant, setAmpirVariant] = useState<"mature" | "precursor">("mature");
  const [ampirThreshold, setAmpirThreshold] = useState<string>("0.5");
  const [timeoutSeconds, setTimeoutSeconds] = useState<number>(60);
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");

  // Running state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Derived current input sequences
  const currentSequences =
    inputMode === "single"
      ? [{ sequence_id: singleId.trim(), sequence: singleSeq.trim() }]
      : inputMode === "fasta"
      ? parseFasta(fastaText)
      : [{ sequence_id: singleId.trim(), sequence: singleSeq.trim() }];

  const validation: BatchValidationResult = validateBatch(currentSequences);

  function handleSelectPreset(preset: ReferencePreset) {
    setSingleId(preset.sequence_id);
    setSingleSeq(preset.sequence);
    setInputMode("single");
  }

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result;
      if (typeof content === "string") {
        setFastaText(content);
        setInputMode("fasta");
      }
    };
    reader.readAsText(file);
  }

  const activeModelList = Object.entries(selectedModels)
    .filter(([_, active]) => active)
    .map(([id]) => id);

  async function handleExecuteSync() {
    if (!validation.isValid) return;
    if (activeModelList.length === 0) {
      setSubmitError("Select at least one operational model to run predictions.");
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    const request: PredictRequest = {
      sequences: validation.sequences.map((s) => ({
        sequence_id: s.sequence_id,
        sequence: s.sequence,
      })),
      models: activeModelList,
      ampir_model: ampirVariant,
      ampir_threshold: ampirThreshold ? parseFloat(ampirThreshold) : undefined,
      timeout_seconds: timeoutSeconds,
    };

    try {
      const report = await predictAmp(request, useFixtures || !isBackendConnected);
      onPredictionComplete(report);
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleExecuteBatch() {
    if (!validation.isValid) return;
    if (activeModelList.length === 0) {
      setSubmitError("Select at least one operational model to run predictions.");
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    const key = idempotencyKey.trim() || `batch-${Date.now()}`;
    const request: PredictRequest = {
      sequences: validation.sequences.map((s) => ({
        sequence_id: s.sequence_id,
        sequence: s.sequence,
      })),
      models: activeModelList,
      ampir_model: ampirVariant,
      ampir_threshold: ampirThreshold ? parseFloat(ampirThreshold) : undefined,
      timeout_seconds: timeoutSeconds,
    };

    try {
      const job = await submitBatchAmp(request, key, useFixtures || !isBackendConnected);
      onBatchSubmitted(job);
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Mode Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-3">
        <div className="flex items-center gap-1 border border-line bg-raised/40 p-1">
          <button
            onClick={() => setInputMode("single")}
            className={`px-3 py-1 text-[12px] font-medium transition-colors ${
              inputMode === "single"
                ? "bg-cyan/15 text-cyan border border-cyan/40"
                : "text-muted hover:text-text border border-transparent"
            }`}
          >
            Individual Peptide
          </button>
          <button
            onClick={() => setInputMode("fasta")}
            className={`px-3 py-1 text-[12px] font-medium transition-colors ${
              inputMode === "fasta"
                ? "bg-cyan/15 text-cyan border border-cyan/40"
                : "text-muted hover:text-text border border-transparent"
            }`}
          >
            Multi-FASTA / Batch ({currentSequences.length})
          </button>
          <button
            onClick={() => setInputMode("presets")}
            className={`px-3 py-1 text-[12px] font-medium transition-colors ${
              inputMode === "presets"
                ? "bg-cyan/15 text-cyan border border-cyan/40"
                : "text-muted hover:text-text border border-transparent"
            }`}
          >
            Reference Library Presets
          </button>
        </div>

        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span>Residues: <strong className="num text-text">{validation.totalResidues}</strong></span>
          <span>·</span>
          <span>Sequences: <strong className="num text-text">{currentSequences.length}</strong>/128</span>
        </div>
      </div>

      {/* Input Workspaces */}
      {inputMode === "single" && (
        <Panel title="Single Sequence Entry" className="bg-panel">
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                  Sequence Identifier
                </label>
                <input
                  type="text"
                  value={singleId}
                  onChange={(e) => setSingleId(e.target.value)}
                  placeholder="e.g. nisin_a_mature"
                  className="w-full border border-line bg-ink px-3 py-2 text-[13px] text-text font-mono focus:border-cyan focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-faint">
                  Must match regex: <code className="text-cyan-dim">^[A-Za-z0-9_.:-]+$</code>
                </p>
              </div>

              <div className="sm:col-span-2">
                <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                  Canonical Amino Acid Sequence
                </label>
                <textarea
                  rows={3}
                  value={singleSeq}
                  onChange={(e) => setSingleSeq(e.target.value)}
                  placeholder="ACDEFGHIKLMNPQRSTVWY..."
                  className="w-full border border-line bg-ink px-3 py-2 text-[13px] text-text font-mono uppercase focus:border-cyan focus:outline-none"
                />
              </div>
            </div>

            {/* Sequence properties preview */}
            {validation.sequences[0] && (
              <div className="flex flex-wrap items-center gap-4 rounded-xs border border-line bg-raised/30 p-3 text-[11px] text-muted">
                <div>
                  Length: <span className="num font-medium text-text">{validation.sequences[0].length}</span> aa
                </div>
                <div>
                  SHA-256: <Id>{validation.sequences[0].checksum.slice(0, 16)}...</Id>
                </div>
                <div>
                  ampir:{" "}
                  {validation.sequences[0].length >= 10 ? (
                    <span className="text-green">Eligible (≥10 aa)</span>
                  ) : (
                    <span className="text-amber">Ineligible (&lt;10 aa)</span>
                  )}
                </div>
                <div>
                  amPEPpy: <span className="text-green">Eligible</span>
                </div>
              </div>
            )}
          </div>
        </Panel>
      )}

      {inputMode === "fasta" && (
        <Panel
          title="Multi-FASTA Sequence Upload"
          aside={
            <label className="cursor-pointer border border-line bg-raised px-2.5 py-1 text-[11px] font-medium text-muted hover:border-cyan/40 hover:text-cyan transition-colors">
              Upload .fasta file
              <input
                type="file"
                accept=".fasta,.fa,.txt"
                onChange={handleFileUpload}
                className="hidden"
              />
            </label>
          }
        >
          <div className="space-y-3">
            <textarea
              rows={8}
              value={fastaText}
              onChange={(e) => setFastaText(e.target.value)}
              placeholder=">sequence_1&#10;ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK&#10;&#10;>sequence_2&#10;GLFDIVKKVVGALG"
              className="w-full border border-line bg-ink p-3 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
            />
            <div className="flex items-center justify-between text-[11px] text-muted">
              <span>Standard FASTA headers starting with <code className="text-cyan">&gt;</code> are extracted as sequence IDs.</span>
              <button
                type="button"
                onClick={() => setFastaText(toFasta(validation.sequences.map((s) => ({ sequence_id: s.sequence_id, sequence: s.sequence }))))}
                className="text-cyan hover:underline"
              >
                Format / Re-chunk FASTA
              </button>
            </div>
          </div>
        </Panel>
      )}

      {inputMode === "presets" && (
        <Panel title="Standard Scientific Control Presets">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {REFERENCE_PRESETS.map((preset) => (
              <div
                key={preset.id}
                onClick={() => handleSelectPreset(preset)}
                className="cursor-pointer border border-line bg-raised/20 p-3 transition-colors hover:border-cyan/50 hover:bg-raised/60 group"
              >
                <div className="flex items-center justify-between">
                  <h4 className="text-[13px] font-medium text-text group-hover:text-cyan transition-colors">
                    {preset.name}
                  </h4>
                  <Status status={preset.category} />
                </div>
                <p className="mt-1 text-[11px] text-muted line-clamp-2">{preset.description}</p>
                <div className="mt-2 text-[10px] font-mono text-faint truncate">
                  {preset.sequence}
                </div>
                <div className="mt-2 flex items-center justify-between text-[10px] text-muted border-t border-line/60 pt-2">
                  <span>{preset.sequence.length} residues</span>
                  <span className="text-cyan">Load sequence →</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* Validation Feedback Banner */}
      {!validation.isValid && (
        <div className="border border-red/40 bg-red/10 p-3 text-[12px] text-red space-y-1">
          <div className="font-medium">Sequence Validation Issues Detected:</div>
          <ul className="list-disc pl-5 space-y-0.5 text-[11px]">
            {validation.issues.map((issue, idx) => (
              <li key={idx}>
                {issue.sequence_id ? `[${issue.sequence_id}] ` : ""}
                {issue.message}
              </li>
            ))}
            {validation.sequences
              .flatMap((s) => s.issues)
              .map((issue, idx) => (
                <li key={`seq-${idx}`}>
                  [{issue.sequence_id}] {issue.message}
                </li>
              ))}
          </ul>
        </div>
      )}

      {/* Predictor Eligibility & Execution Panel */}
      <Panel title="Operational Predictors & Inference Options">
        <div className="space-y-4">
          <p className="text-[12px] text-muted">
            Select verified operational models for execution. Models marked as BLOCKED or PARTIAL are
            disabled pending runtime resolution.
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {/* ampir */}
            <label className="flex items-start gap-3 border border-line bg-raised/30 p-3 cursor-pointer hover:border-cyan/40 transition-colors">
              <input
                type="checkbox"
                checked={selectedModels.ampir ?? false}
                onChange={(e) =>
                  setSelectedModels((prev) => ({ ...prev, ampir: e.target.checked }))
                }
                className="mt-0.5 accent-cyan"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-text">ampir</span>
                  <Status status="READY" />
                </div>
                <p className="mt-0.5 text-[11px] text-muted">Version 1.1.0 · R SVM probability estimation</p>
                <div className="mt-1 text-[10px] text-cyan-dim">Domain: ≥10 residues (mature recommended &lt;60 aa)</div>
              </div>
            </label>

            {/* amPEPpy */}
            <label className="flex items-start gap-3 border border-line bg-raised/30 p-3 cursor-pointer hover:border-cyan/40 transition-colors">
              <input
                type="checkbox"
                checked={selectedModels.ampeppy ?? false}
                onChange={(e) =>
                  setSelectedModels((prev) => ({ ...prev, ampeppy: e.target.checked }))
                }
                className="mt-0.5 accent-cyan"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-text">amPEPpy</span>
                  <Status status="READY" />
                </div>
                <p className="mt-0.5 text-[11px] text-muted">Version 1.1.0 · Random Forest probability_AMP</p>
                <div className="mt-1 text-[10px] text-cyan-dim">Domain: ≥1 residue</div>
              </div>
            </label>

            {/* AMPlify - BLOCKED */}
            <div className="flex items-start gap-3 border border-line/40 bg-ink/50 p-3 opacity-60">
              <input type="checkbox" disabled checked={false} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-faint">AMPlify</span>
                  <Status status="BLOCKED" />
                </div>
                <p className="mt-0.5 text-[11px] text-faint">v2.0.1 · Legacy TF 1.12 x86 AVX blocker</p>
                <p className="mt-1 text-[10px] text-red/80">Unavailable pending legacy runtime compatibility</p>
              </div>
            </div>

            {/* AMPScanner v2 - BLOCKED */}
            <div className="flex items-start gap-3 border border-line/40 bg-ink/50 p-3 opacity-60">
              <input type="checkbox" disabled checked={false} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-faint">AMPScanner v2</span>
                  <Status status="BLOCKED" />
                </div>
                <p className="mt-0.5 text-[11px] text-faint">021820 checkpoint · Legacy TF runtime blocker</p>
                <p className="mt-1 text-[10px] text-red/80">Unavailable pending legacy runtime compatibility</p>
              </div>
            </div>

            {/* AI4AMP - BLOCKED */}
            <div className="flex items-start gap-3 border border-line/40 bg-ink/50 p-3 opacity-60">
              <input type="checkbox" disabled checked={false} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-faint">AI4AMP</span>
                  <Status status="BLOCKED" />
                </div>
                <p className="mt-0.5 text-[11px] text-faint">PC6 neural classifier</p>
                <p className="mt-1 text-[10px] text-red/80">Disabled: code/weights license unresolved</p>
              </div>
            </div>

            {/* APIN - BLOCKED */}
            <div className="flex items-start gap-3 border border-line/40 bg-ink/50 p-3 opacity-60">
              <input type="checkbox" disabled checked={false} className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-faint">APIN</span>
                  <Status status="BLOCKED" />
                </div>
                <p className="mt-0.5 text-[11px] text-faint">On-demand trained neural classifier</p>
                <p className="mt-1 text-[10px] text-red/80">Disabled: training prohibited, no checkpoint</p>
              </div>
            </div>
          </div>

          {/* Predictor Parameters */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 border-t border-line pt-4">
            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                ampir Model Variant
              </label>
              <select
                value={ampirVariant}
                onChange={(e) => setAmpirVariant(e.target.value as "mature" | "precursor")}
                className="w-full border border-line bg-ink px-2.5 py-1.5 text-[12px] text-text focus:border-cyan focus:outline-none"
              >
                <option value="mature">mature (recommended for &lt;60 aa)</option>
                <option value="precursor">precursor (for full leader peptides)</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                ampir Classification Threshold
              </label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={ampirThreshold}
                onChange={(e) => setAmpirThreshold(e.target.value)}
                placeholder="0.5"
                className="w-full border border-line bg-ink px-2.5 py-1.5 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
                Per-Model Timeout (seconds)
              </label>
              <input
                type="number"
                min="1"
                max="120"
                value={timeoutSeconds}
                onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                className="w-full border border-line bg-ink px-2.5 py-1.5 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
              />
            </div>
          </div>

          {/* Batch Job Options */}
          <div className="border-t border-line pt-3">
            <label className="block text-[11px] font-medium text-muted uppercase tracking-wider mb-1">
              Batch Idempotency Key (Optional)
            </label>
            <input
              type="text"
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              placeholder="Leave blank for auto-generated UUID"
              className="w-full max-w-md border border-line bg-ink px-2.5 py-1.5 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
            />
          </div>

          {/* Error Message */}
          {submitError && (
            <div className="border border-red/40 bg-red/10 p-3 text-[12px] text-red">
              {submitError}
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <button
              type="button"
              disabled={isSubmitting || !validation.isValid || activeModelList.length === 0}
              onClick={handleExecuteSync}
              className="border border-cyan/40 bg-cyan/20 px-5 py-2 text-[13px] font-medium text-cyan transition-colors hover:bg-cyan/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? "Running Inference..." : `Predict Synchronously (${currentSequences.length} seq)`}
            </button>

            <button
              type="button"
              disabled={isSubmitting || !validation.isValid || activeModelList.length === 0}
              onClick={handleExecuteBatch}
              className="border border-line bg-raised px-4 py-2 text-[13px] font-medium text-text transition-colors hover:border-cyan/40 hover:text-cyan disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Submit Batch Job (202 Accepted)
            </button>

            <div className="ml-auto flex items-center gap-2 text-[11px] text-muted">
              <span>Target:</span>
              <Id>{isBackendConnected ? "Real FastAPI (8000)" : "Demonstration Fixture"}</Id>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}
