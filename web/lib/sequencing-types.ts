/**
 * Typed contracts for Universal Sequencing Platform Integrations.
 *
 * Mirrors backend Pydantic models in `bacteriocin_lab/sequencing/schemas.py`.
 */

export type VendorType = "illumina" | "nanopore" | "pacbio" | "local" | "lims";

export type AuthType = "none" | "api_key" | "oauth2" | "token" | "directory_path";

export type ConnectionStatus = "connected" | "disconnected" | "error" | "unverified";

export type RunStatus = "running" | "completed" | "failed" | "aborted" | "unknown";

export type FileFormat =
  | "fastq"
  | "fastq_gz"
  | "fasta"
  | "fasta_gz"
  | "bam"
  | "cram"
  | "vcf"
  | "vcf_gz"
  | "fast5"
  | "pod5"
  | "other";

export type ReadType =
  | "paired_end_R1"
  | "paired_end_R2"
  | "single_end"
  | "long_read"
  | "hifi_ccs"
  | "raw_signal"
  | "unknown";

export type ImportStatus = "available" | "queued" | "importing" | "imported" | "failed";

export type ImportJobStatus =
  | "queued"
  | "transferring"
  | "verifying_checksum"
  | "completed"
  | "failed"
  | "cancelled";

export type DataType =
  | "raw_short_reads"
  | "raw_long_reads"
  | "assembled_contigs"
  | "translated_proteins"
  | "unsupported";

export interface ConnectorInfo {
  connector_id: string;
  name: string;
  vendor: VendorType;
  auth_type: AuthType;
  description: string;
  capabilities: string[];
  supported_file_types: string[];
  documentation_url?: string | null;
}

export interface SequencingConnection {
  connection_id: string;
  connector_id: string;
  name: string;
  vendor: string;
  status: ConnectionStatus;
  config_summary: Record<string, any>;
  auto_sync: boolean;
  sync_interval_seconds: number;
  last_sync_at?: string | null;
  discovered_runs_count: number;
  discovered_datasets_count: number;
  error_message?: string | null;
  created_at: string;
}

export interface ConnectionCreateRequest {
  connector_id: string;
  name: string;
  config: Record<string, any>;
  auto_sync?: boolean;
  sync_interval_seconds?: number;
}

export interface SequencingRun {
  run_id: string;
  connection_id: string;
  vendor: string;
  external_run_id: string;
  run_name: string;
  instrument_model?: string | null;
  sequencing_method: string;
  project_name?: string | null;
  sample_count: number;
  status: RunStatus;
  started_at?: string | null;
  completed_at?: string | null;
  dataset_count: number;
  total_size_bytes: number;
  source_metadata: Record<string, any>;
  last_synced_at: string;
  provenance: Record<string, any>;
}

export interface SequencingDataset {
  dataset_id: string;
  run_id: string;
  connection_id: string;
  sample_id?: string | null;
  sample_name?: string | null;
  file_name: string;
  file_path: string;
  file_format: FileFormat;
  file_size_bytes: number;
  checksum?: string | null;
  checksum_algorithm?: "sha256" | "md5" | null;
  read_type: ReadType;
  is_complete: boolean;
  stability_verified: boolean;
  import_status: ImportStatus;
  local_storage_path?: string | null;
  analysis_eligibility: Record<string, any>;
  discovered_at: string;
}

export interface ImportRequest {
  destination_subfolder?: string | null;
  verify_checksum?: boolean;
}

export interface ImportJob {
  import_id: string;
  dataset_id: string;
  run_id: string;
  connection_id: string;
  status: ImportJobStatus;
  bytes_transferred: number;
  total_bytes: number;
  transfer_rate_bps?: number | null;
  started_at: string;
  completed_at?: string | null;
  destination_path?: string | null;
  checksum_verified?: boolean | null;
  error_message?: string | null;
}

export interface SyncResult {
  connection_id: string;
  status: "succeeded" | "failed" | "partial";
  runs_discovered: number;
  runs_updated: number;
  datasets_discovered: number;
  sync_duration_seconds: number;
  timestamp: string;
  errors: string[];
}

export interface AnalysisHandoffStage {
  stage_id: string;
  name: string;
  required: boolean;
  status: "ready" | "pending_prerequisite" | "completed" | "unsupported";
  description: string;
}

export interface AnalysisHandoffResponse {
  dataset_id: string;
  file_format: string;
  data_type: DataType;
  direct_amp_eligible: boolean;
  pipeline_stages: AnalysisHandoffStage[];
  recommendation: string;
  prerequisite_notice: string;
  extracted_peptides_preview: Array<{
    id: string;
    sequence: string;
    length: number;
    description: string;
    ready_for_amp: boolean;
  }>;
}
