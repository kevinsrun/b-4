/**
 * Centralized API client for Universal Sequencing Platform Integrations.
 *
 * Connects to `/api/v1/sequencing/*` with graceful fallback to verified contract fixtures
 * when the backend API is disconnected.
 */

import {
  ConnectorInfo,
  SequencingConnection,
  ConnectionCreateRequest,
  SequencingRun,
  SequencingDataset,
  ImportRequest,
  ImportJob,
  SyncResult,
  AnalysisHandoffResponse,
} from "./sequencing-types";
import {
  FIXTURE_CONNECTORS,
  FIXTURE_CONNECTIONS,
  FIXTURE_RUNS,
  FIXTURE_DATASETS,
  FIXTURE_HANDOFFS,
} from "./sequencing-fixtures";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// In-memory runtime state for offline/demo operation
let runtimeConnections: SequencingConnection[] = [...FIXTURE_CONNECTIONS];
let runtimeRuns: SequencingRun[] = [...FIXTURE_RUNS];
let runtimeDatasets: SequencingDataset[] = [...FIXTURE_DATASETS];
let runtimeImports: Record<string, ImportJob> = {};

async function safeFetch<T>(
  endpoint: string,
  options?: RequestInit,
  fallback?: () => T
): Promise<{ data: T; isLive: boolean; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(options?.headers || {}),
      },
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => "Unknown error");
      if (fallback) {
        return { data: fallback(), isLive: false, error: `HTTP ${res.status}: ${errText}` };
      }
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = (await res.json()) as T;
    return { data, isLive: true };
  } catch (err: any) {
    if (fallback) {
      return { data: fallback(), isLive: false, error: err?.message || "Backend offline" };
    }
    throw err;
  }
}

export async function fetchConnectors(): Promise<{ connectors: ConnectorInfo[]; isLive: boolean }> {
  const result = await safeFetch<ConnectorInfo[]>(
    "/api/v1/sequencing/connectors",
    { method: "GET" },
    () => FIXTURE_CONNECTORS
  );
  return { connectors: result.data, isLive: result.isLive };
}

export async function fetchConnections(): Promise<{ connections: SequencingConnection[]; isLive: boolean }> {
  const result = await safeFetch<SequencingConnection[]>(
    "/api/v1/sequencing/connections",
    { method: "GET" },
    () => runtimeConnections
  );
  if (result.isLive) {
    runtimeConnections = result.data;
  }
  return { connections: result.data, isLive: result.isLive };
}

export async function createConnection(
  request: ConnectionCreateRequest
): Promise<{ connection: SequencingConnection; isLive: boolean }> {
  const result = await safeFetch<SequencingConnection>(
    "/api/v1/sequencing/connections",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    () => {
      // Offline fallback creation
      const newConn: SequencingConnection = {
        connection_id: `conn_${Date.now()}`,
        connector_id: request.connector_id,
        name: request.name,
        vendor: request.connector_id.split("_")[0],
        status: "connected",
        config_summary: { ...request.config, api_token: request.config.api_token ? "********" : undefined },
        auto_sync: request.auto_sync || false,
        sync_interval_seconds: request.sync_interval_seconds || 300,
        discovered_runs_count: 1,
        discovered_datasets_count: 2,
        created_at: new Date().toISOString(),
      };
      runtimeConnections = [newConn, ...runtimeConnections];
      return newConn;
    }
  );
  return { connection: result.data, isLive: result.isLive };
}

export async function deleteConnection(connectionId: string): Promise<{ success: boolean; isLive: boolean }> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/sequencing/connections/${connectionId}`, {
      method: "DELETE",
    });
    if (res.ok) {
      runtimeConnections = runtimeConnections.filter((c) => c.connection_id !== connectionId);
      return { success: true, isLive: true };
    }
  } catch {}
  runtimeConnections = runtimeConnections.filter((c) => c.connection_id !== connectionId);
  return { success: true, isLive: false };
}

export async function syncConnection(
  connectionId: string
): Promise<{ result: SyncResult; isLive: boolean }> {
  const res = await safeFetch<SyncResult>(
    `/api/v1/sequencing/connections/${connectionId}/sync`,
    { method: "POST" },
    () => ({
      connection_id: connectionId,
      status: "succeeded",
      runs_discovered: 2,
      runs_updated: 2,
      datasets_discovered: 3,
      sync_duration_seconds: 0.85,
      timestamp: new Date().toISOString(),
      errors: [],
    })
  );
  return { result: res.data, isLive: res.isLive };
}

export async function fetchRuns(
  connectionId?: string,
  status?: string
): Promise<{ runs: SequencingRun[]; isLive: boolean }> {
  const params = new URLSearchParams();
  if (connectionId) params.set("connection_id", connectionId);
  if (status) params.set("status", status);

  const endpoint = `/api/v1/sequencing/runs${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await safeFetch<SequencingRun[]>(endpoint, { method: "GET" }, () => {
    let filtered = runtimeRuns;
    if (connectionId) filtered = filtered.filter((r) => r.connection_id === connectionId);
    if (status) filtered = filtered.filter((r) => r.status === status);
    return filtered;
  });
  if (res.isLive) {
    runtimeRuns = res.data;
  }
  return { runs: res.data, isLive: res.isLive };
}

export async function fetchRun(runId: string): Promise<{ run: SequencingRun | null; isLive: boolean }> {
  const res = await safeFetch<SequencingRun>(
    `/api/v1/sequencing/runs/${runId}`,
    { method: "GET" },
    () => runtimeRuns.find((r) => r.run_id === runId) || null as any
  );
  return { run: res.data, isLive: res.isLive };
}

export async function fetchRunDatasets(
  runId: string
): Promise<{ datasets: SequencingDataset[]; isLive: boolean }> {
  const res = await safeFetch<SequencingDataset[]>(
    `/api/v1/sequencing/runs/${runId}/datasets`,
    { method: "GET" },
    () => runtimeDatasets.filter((d) => d.run_id === runId)
  );
  return { datasets: res.data, isLive: res.isLive };
}

export async function fetchDatasets(
  connectionId?: string
): Promise<{ datasets: SequencingDataset[]; isLive: boolean }> {
  const params = new URLSearchParams();
  if (connectionId) params.set("connection_id", connectionId);

  const endpoint = `/api/v1/sequencing/datasets${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await safeFetch<SequencingDataset[]>(endpoint, { method: "GET" }, () => {
    if (connectionId) return runtimeDatasets.filter((d) => d.connection_id === connectionId);
    return runtimeDatasets;
  });
  if (res.isLive) {
    runtimeDatasets = res.data;
  }
  return { datasets: res.data, isLive: res.isLive };
}

export async function initiateImport(
  datasetId: string,
  request: ImportRequest = { verify_checksum: true }
): Promise<{ importJob: ImportJob; isLive: boolean }> {
  const res = await safeFetch<ImportJob>(
    `/api/v1/sequencing/datasets/${datasetId}/import`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    () => {
      const ds = runtimeDatasets.find((d) => d.dataset_id === datasetId);
      const imp: ImportJob = {
        import_id: `imp_${Date.now()}`,
        dataset_id: datasetId,
        run_id: ds?.run_id || "unknown",
        connection_id: ds?.connection_id || "unknown",
        status: "completed",
        bytes_transferred: ds?.file_size_bytes || 1024,
        total_bytes: ds?.file_size_bytes || 1024,
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        destination_path: `artifacts/sequencing/imported/${ds?.file_name || "file.fastq.gz"}`,
        checksum_verified: true,
      };
      runtimeImports[imp.import_id] = imp;
      // Mark dataset as imported
      if (ds) {
        ds.import_status = "imported";
        ds.local_storage_path = imp.destination_path;
      }
      return imp;
    }
  );
  return { importJob: res.data, isLive: res.isLive };
}

export async function fetchImport(importId: string): Promise<{ importJob: ImportJob | null; isLive: boolean }> {
  const res = await safeFetch<ImportJob>(
    `/api/v1/sequencing/imports/${importId}`,
    { method: "GET" },
    () => runtimeImports[importId] || null as any
  );
  return { importJob: res.data, isLive: res.isLive };
}

export async function fetchAnalysisHandoff(
  datasetId: string
): Promise<{ handoff: AnalysisHandoffResponse; isLive: boolean }> {
  const res = await safeFetch<AnalysisHandoffResponse>(
    `/api/v1/sequencing/datasets/${datasetId}/handoff`,
    { method: "GET" },
    () => {
      if (FIXTURE_HANDOFFS[datasetId]) {
        return FIXTURE_HANDOFFS[datasetId];
      }
      const ds = runtimeDatasets.find((d) => d.dataset_id === datasetId);
      return {
        dataset_id: datasetId,
        file_format: ds?.file_format || "fastq_gz",
        data_type: "raw_short_reads",
        direct_amp_eligible: false,
        recommendation:
          "Raw sequencing reads detected. Must undergo QC, assembly, and gene calling before peptide translation.",
        prerequisite_notice:
          "CRITICAL: Raw nucleotide reads cannot be classified by ampir or amPEPpy. Protein-level translation is mandatory before AMP inference.",
        pipeline_stages: [
          {
            stage_id: "qc",
            name: "Quality Control (FastQC)",
            required: true,
            status: "ready",
            description: "Assess per-base Phred scores and adapter levels.",
          },
          {
            stage_id: "assembly",
            name: "De Novo Assembly",
            required: true,
            status: "pending_prerequisite",
            description: "Assemble short reads into contigs.",
          },
          {
            stage_id: "gene_calling",
            name: "ORF Prediction (Prodigal)",
            required: true,
            status: "pending_prerequisite",
            description: "Predict prokaryotic CDS.",
          },
          {
            stage_id: "translation",
            name: "Peptide Translation",
            required: true,
            status: "pending_prerequisite",
            description: "Translate CDS into amino acid sequences.",
          },
          {
            stage_id: "amp_screening",
            name: "Bacteriocin & AMP Screening",
            required: true,
            status: "pending_prerequisite",
            description: "Forward translated candidates to ampir / amPEPpy.",
          },
        ],
        extracted_peptides_preview: [],
      };
    }
  );
  return { handoff: res.data, isLive: res.isLive };
}
