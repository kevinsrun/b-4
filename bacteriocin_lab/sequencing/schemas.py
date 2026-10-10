"""Pydantic transport and scientific contracts for universal sequencing integrations."""

from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectorCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str
    supported: bool = True


class ConnectorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: str
    name: str
    vendor: Literal["illumina", "nanopore", "pacbio", "local", "lims"]
    auth_type: Literal["none", "api_key", "oauth2", "token", "directory_path"]
    description: str
    capabilities: list[str]
    supported_file_types: list[str]
    documentation_url: str | None = None


class ConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    auto_sync: bool = False
    sync_interval_seconds: int = Field(default=300, ge=30, le=86400)


class ConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    auto_sync: bool | None = None
    sync_interval_seconds: int | None = Field(default=None, ge=30, le=86400)


class SequencingConnection(BaseModel):
    connection_id: str
    connector_id: str
    name: str
    vendor: str
    status: Literal["connected", "disconnected", "error", "unverified"]
    config_summary: dict[str, Any]  # Redacted configuration safe for transport
    auto_sync: bool
    sync_interval_seconds: int
    last_sync_at: str | None = None
    discovered_runs_count: int = 0
    discovered_datasets_count: int = 0
    error_message: str | None = None
    created_at: str


class SequencingRun(BaseModel):
    run_id: str
    connection_id: str
    vendor: str
    external_run_id: str
    run_name: str
    instrument_model: str | None = None
    sequencing_method: str = "unknown"
    project_name: str | None = None
    sample_count: int = 0
    status: Literal["running", "completed", "failed", "aborted", "unknown"]
    started_at: str | None = None
    completed_at: str | None = None
    dataset_count: int = 0
    total_size_bytes: int = 0
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    last_synced_at: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class SequencingDataset(BaseModel):
    dataset_id: str
    run_id: str
    connection_id: str
    sample_id: str | None = None
    sample_name: str | None = None
    file_name: str
    file_path: str
    file_format: Literal[
        "fastq",
        "fastq_gz",
        "fasta",
        "fasta_gz",
        "bam",
        "cram",
        "vcf",
        "vcf_gz",
        "fast5",
        "pod5",
        "other",
    ]
    file_size_bytes: int
    checksum: str | None = None
    checksum_algorithm: Literal["sha256", "md5"] | None = None
    read_type: Literal[
        "paired_end_R1",
        "paired_end_R2",
        "single_end",
        "long_read",
        "hifi_ccs",
        "raw_signal",
        "unknown",
    ] = "unknown"
    is_complete: bool = True
    stability_verified: bool = True
    import_status: Literal["available", "queued", "importing", "imported", "failed"] = "available"
    local_storage_path: str | None = None
    analysis_eligibility: dict[str, Any] = Field(default_factory=dict)
    discovered_at: str


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_subfolder: str | None = Field(default=None, max_length=100)
    verify_checksum: bool = True


class ImportJob(BaseModel):
    import_id: str
    dataset_id: str
    run_id: str
    connection_id: str
    status: Literal[
        "queued",
        "transferring",
        "verifying_checksum",
        "completed",
        "failed",
        "cancelled",
    ]
    bytes_transferred: int = 0
    total_bytes: int = 0
    transfer_rate_bps: float | None = None
    started_at: str
    completed_at: str | None = None
    destination_path: str | None = None
    checksum_verified: bool | None = None
    error_message: str | None = None


class SyncResult(BaseModel):
    connection_id: str
    status: Literal["succeeded", "failed", "partial"]
    runs_discovered: int
    runs_updated: int
    datasets_discovered: int
    sync_duration_seconds: float
    timestamp: str
    errors: list[str] = Field(default_factory=list)


class AnalysisHandoffStage(BaseModel):
    stage_id: str
    name: str
    required: bool
    status: Literal["ready", "pending_prerequisite", "completed", "unsupported"]
    description: str


class AnalysisHandoffResponse(BaseModel):
    dataset_id: str
    file_format: str
    data_type: Literal[
        "raw_short_reads",
        "raw_long_reads",
        "assembled_contigs",
        "translated_proteins",
        "unsupported",
    ]
    direct_amp_eligible: bool = False
    pipeline_stages: list[AnalysisHandoffStage]
    recommendation: str
    prerequisite_notice: str
    extracted_peptides_preview: list[dict[str, Any]] = Field(default_factory=list)
