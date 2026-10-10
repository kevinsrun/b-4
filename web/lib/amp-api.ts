/**
 * Centralized typed client for the verified AMP inference and DRAMP services.
 *
 * Implements exact REST contracts against FastAPI endpoints mounted under
 * `/api/v1/amp` and `/api/v1/dramp`.
 */

import type {
  DRAMPRecord,
  DRAMPSearchParams,
  DRAMPSearchResponse,
  JobResponse,
  ModelHealth,
  ModelsHealthResponse,
  PredictionReport,
  PredictRequest,
} from "./amp-types";
import {
  FIXTURE_DRAMP_DATASETS,
  FIXTURE_DRAMP_RECORDS,
  FIXTURE_MODELS,
  FIXTURE_MODELS_HEALTH,
  getFixtureJobResponse,
  getFixturePredictionReport,
} from "./amp-fixtures";

export class AmpApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "AmpApiError";
  }
}

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    throw new AmpApiError(
      `Network connection failed: ${errorMsg}. Verify the B-4 FastAPI service is running.`,
      0,
      "NETWORK_ERROR",
      err,
    );
  }

  if (!response.ok) {
    let detail: unknown;
    let code: string | undefined;
    let message = `Request failed with HTTP status ${response.status}`;

    try {
      detail = await response.json();
      if (detail && typeof detail === "object" && "detail" in detail) {
        const d = (detail as { detail: unknown }).detail;
        if (typeof d === "string") {
          message = d;
        } else if (d && typeof d === "object") {
          const obj = d as { code?: string; message?: string };
          if (obj.code) code = obj.code;
          if (obj.message) message = obj.message;
        } else if (Array.isArray(d)) {
          message = d.map((item) => (item.msg ? String(item.msg) : JSON.stringify(item))).join("; ");
        }
      }
    } catch {
      message = await response.text();
    }

    throw new AmpApiError(message, response.status, code, detail);
  }

  return (await response.json()) as T;
}

export interface BackendConnectionStatus {
  connected: boolean;
  latencyMs?: number;
  message?: string;
  modelsCount?: number;
}

/** Check whether the FastAPI backend is operational and reachable. */
export async function checkBackendConnection(): Promise<BackendConnectionStatus> {
  const start = performance.now();
  try {
    const res = await fetch(`${BASE}/api/v1/amp/models`, {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      const data = (await res.json()) as { models?: ModelHealth[] };
      return {
        connected: true,
        latencyMs: Math.round(performance.now() - start),
        modelsCount: data.models?.length ?? 0,
      };
    }
    return {
      connected: false,
      latencyMs: Math.round(performance.now() - start),
      message: `HTTP ${res.status}: ${res.statusText}`,
    };
  } catch (err: unknown) {
    return {
      connected: false,
      message: err instanceof Error ? err.message : "Service unreachable",
    };
  }
}

/**
 * Predict AMP probability synchronously for a set of sequences.
 * POST /api/v1/amp/predict
 */
export async function predictAmp(
  request: PredictRequest,
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<PredictionReport> {
  try {
    return await fetchJson<PredictionReport>(`${BASE}/api/v1/amp/predict`, {
      method: "POST",
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      console.warn("Backend unavailable, using scientific demonstration fixture for predict:", err);
      return getFixturePredictionReport(request.sequences);
    }
    throw err;
  }
}

/**
 * Submit an asynchronous batch prediction job.
 * POST /api/v1/amp/batch
 */
export async function submitBatchAmp(
  request: PredictRequest,
  idempotencyKey?: string,
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<JobResponse> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }

  try {
    return await fetchJson<JobResponse>(`${BASE}/api/v1/amp/batch`, {
      method: "POST",
      body: JSON.stringify(request),
      headers,
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      console.warn("Backend unavailable, using scientific demonstration fixture for batch job:", err);
      const fakeJobId = `fixture-job-${Date.now().toString(36)}`;
      return getFixtureJobResponse(fakeJobId, request.sequences);
    }
    throw err;
  }
}

/**
 * Poll job status and completed prediction report.
 * GET /api/v1/amp/jobs/{job_id}
 */
export async function getAmpJob(
  jobId: string,
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<JobResponse> {
  try {
    return await fetchJson<JobResponse>(`${BASE}/api/v1/amp/jobs/${encodeURIComponent(jobId)}`, {
      method: "GET",
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      console.warn("Backend unavailable, using fixture job response:", err);
      return getFixtureJobResponse(jobId, [
        { sequence_id: "fixture_seq", sequence: "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK" },
      ]);
    }
    throw err;
  }
}

/**
 * Query model health and operational status.
 * GET /api/v1/amp/models/health
 */
export async function getAmpModelsHealth(
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<ModelsHealthResponse> {
  try {
    return await fetchJson<ModelsHealthResponse>(`${BASE}/api/v1/amp/models/health`, {
      method: "GET",
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      console.warn("Backend unavailable, returning fixture models health:", err);
      return FIXTURE_MODELS_HEALTH;
    }
    throw err;
  }
}

/**
 * Query model list.
 * GET /api/v1/amp/models
 */
export async function getAmpModels(
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<{ models: ModelHealth[] }> {
  try {
    return await fetchJson<{ models: ModelHealth[] }>(`${BASE}/api/v1/amp/models`, {
      method: "GET",
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      return { models: FIXTURE_MODELS };
    }
    throw err;
  }
}

/**
 * Search DRAMP reference records.
 * GET /api/v1/dramp/search
 */
export async function searchDramp(
  params: DRAMPSearchParams,
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<DRAMPSearchResponse> {
  const query = new URLSearchParams();
  if (params.sequence) query.set("sequence", params.sequence);
  if (params.record_id) query.set("record_id", params.record_id);
  if (params.dataset_id) query.set("dataset_id", params.dataset_id);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));

  try {
    return await fetchJson<DRAMPSearchResponse>(`${BASE}/api/v1/dramp/search?${query.toString()}`, {
      method: "GET",
      signal,
    });
  } catch (err) {
    if (useFixturesOnFailure) {
      console.warn("Backend unavailable, returning fixture DRAMP search:", err);
      let records = [...FIXTURE_DRAMP_RECORDS];
      if (params.record_id) {
        records = records.filter((r) =>
          r.record_id.toLowerCase().includes(params.record_id!.toLowerCase())
        );
      }
      if (params.sequence) {
        records = records.filter(
          (r) => r.sequence.includes(params.sequence!) || params.sequence!.includes(r.sequence)
        );
      }
      if (params.dataset_id) {
        records = records.filter((r) => r.provenance.dataset_id === params.dataset_id);
      }
      const limit = params.limit ?? 20;
      const offset = params.offset ?? 0;
      const sliced = records.slice(offset, offset + limit);
      return {
        total: records.length,
        limit,
        offset,
        database_available: true,
        datasets: FIXTURE_DRAMP_DATASETS,
        records: sliced,
      };
    }
    throw err;
  }
}

/**
 * Lookup a specific DRAMP record by its identifier.
 * GET /api/v1/dramp/records/{record_id}
 */
export async function getDrampRecord(
  recordId: string,
  useFixturesOnFailure = false,
  signal?: AbortSignal,
): Promise<DRAMPSearchResponse> {
  try {
    return await fetchJson<DRAMPSearchResponse>(
      `${BASE}/api/v1/dramp/records/${encodeURIComponent(recordId)}`,
      {
        method: "GET",
        signal,
      },
    );
  } catch (err) {
    if (useFixturesOnFailure) {
      const match = FIXTURE_DRAMP_RECORDS.filter(
        (r) => r.record_id.toLowerCase() === recordId.toLowerCase()
      );
      if (match.length > 0) {
        return {
          total: match.length,
          limit: 50,
          offset: 0,
          database_available: true,
          datasets: FIXTURE_DRAMP_DATASETS,
          records: match,
        };
      }
      throw new AmpApiError(
        `Record ${recordId} not found in fixture dataset`,
        404,
        "DRAMP_RECORD_NOT_FOUND"
      );
    }
    throw err;
  }
}
