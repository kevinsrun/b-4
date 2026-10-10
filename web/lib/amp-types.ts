/**
 * Typed contracts for AMP prediction models, batch jobs, and DRAMP references.
 *
 * Exact mirror of backend Pydantic models in `bacteriocin_lab/amp/schemas.py`,
 * `catalog.py`, `dramp.py`, and `store.py`.
 */

export type ModelId = "ampir" | "ampeppy" | "amplify" | "ampscanner_v2" | "ai4amp" | "apin";

export type ModelStatus = "READY" | "PARTIAL" | "BLOCKED" | "UNKNOWN";

export type PredictionStatus = "succeeded" | "failed" | "timeout" | "unavailable" | "ineligible";

export type ReportStatus = "succeeded" | "partial_success" | "failed";

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "partial_success"
  | "failed"
  | "interrupted";

export interface SequenceInput {
  sequence_id: string;
  sequence: string;
}

export interface PredictRequest {
  sequences: SequenceInput[];
  models?: string[];
  ampir_model?: "mature" | "precursor";
  amplify_model?: "balanced";
  ampir_threshold?: number | null;
  timeout_seconds?: number;
}

export interface PredictionError {
  code: string;
  message: string;
  retryable?: boolean;
}

export interface BenchmarkValidation {
  status: "BLOCKED" | "VERIFIED" | "UNVERIFIED";
  applicability: string;
}

export interface Prediction {
  sequence_id: string;
  sequence_checksum: string;
  model_id: string;
  model_version: string;
  model_variant?: string | null;
  class_definition: string;
  benchmark_validation: BenchmarkValidation;
  native_scores: Record<string, number>;
  raw_score: number | null;
  score_interpretation: string;
  binary_prediction?: boolean | null;
  threshold?: number | null;
  threshold_interpretation?: string | null;
  status: PredictionStatus;
  timestamp: string;
  duration_seconds: number;
  cached: boolean;
  warnings: string[];
  error?: PredictionError | null;
  reproducibility: Record<string, unknown>;
}

export interface AgreementSummary {
  count_models_succeeded: number;
  positive_votes: number;
  negative_votes: number;
  disagreement: boolean;
  all_classified_models_agree: boolean;
}

export interface SequenceEvidence {
  sequence_id: string;
  sequence_checksum: string;
  predictions: Prediction[];
  agreement: AgreementSummary;
  dramp_matches: DRAMPRecord[];
  warnings: string[];
}

export interface ExecutionMetrics {
  duration_seconds: number;
  successful_predictions: number;
  unsuccessful_predictions: number;
  cache_hits: number;
  max_concurrent_model_processes: number;
  timeout_scope: string;
}

export interface PredictionReport {
  schema_version: string;
  status: ReportStatus;
  evidence_type: "computational-prediction";
  timestamp: string;
  sequences: SequenceEvidence[];
  execution: ExecutionMetrics;
  warnings: string[];
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  report?: PredictionReport | null;
  error?: {
    code: string;
    message: string;
  } | null;
}

export interface ModelVerificationProof {
  fingerprint: string;
  inference_passed: boolean;
  reference_agreement: boolean;
  timestamp: string;
  reference_scope: string;
  verified_variants: string[];
  evidence_path: string;
  evidence_sha256: string;
}

export interface ModelHealth {
  model_id: string;
  model_version: string;
  source: string;
  source_commit: string;
  publication: string;
  license: string;
  min_length: number | null;
  max_length: number | null;
  requires: string[];
  score_interpretation: string;
  limitations: string[];
  status: ModelStatus;
  available: boolean;
  reason?: string | null;
  blocker?: string | null;
  reproducibility?: Record<string, unknown> | null;
  verification?: ModelVerificationProof | null;
  pinned_artifacts?: Record<string, string>;
  independent_benchmark: string;
  class_definition: string;
}

export interface ModelResources {
  max_concurrent_model_processes: number;
  active_model_tasks: number;
  api_process_peak_rss_kib: number;
  rss_scope: string;
  cpu_seconds: number;
}

export interface ModelsHealthResponse {
  models: ModelHealth[];
  resources: ModelResources;
}

export interface DRAMPSourceProvenance {
  normalized_tsv_sha256: string;
  source_artifact_sha256: string;
  release_version_status: "verified_publication_snapshot" | "unresolved";
}

export interface DRAMPDatasetManifest {
  dataset_id: string;
  source: string;
  source_url: string;
  source_version: string;
  source_sha256: string;
  license: string;
  ingestion_revision: string;
  attribution: string;
  ingested_at: string;
  source_provenance?: DRAMPSourceProvenance;
}

export interface DRAMPRecord {
  record_id: string;
  sequence: string;
  sequence_checksum: string;
  metadata: Record<string, string | null>;
  provenance: DRAMPDatasetManifest;
  annotation_origin: string;
  evidence_type: "reference-database-annotation";
  experimental_verification: string;
}

export interface DRAMPSearchResponse {
  total: number;
  limit: number;
  offset: number;
  database_available: boolean;
  datasets: DRAMPDatasetManifest[];
  records: DRAMPRecord[];
}

export interface DRAMPSearchParams {
  sequence?: string;
  record_id?: string;
  dataset_id?: string;
  limit?: number;
  offset?: number;
}
