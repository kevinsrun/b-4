/**
 * Thin typed client over the Python API.
 *
 * It fetches and nothing else: no caching of scientific values, no derived
 * fields, no fallback data. When the API is unreachable the error travels to
 * the component so the page can say the lab is not running, which is true and
 * useful, rather than render something that looks like a result.
 */

import type {
  AgentDescriptor,
  CandidateEnvelope,
  ExperimentResult,
  Health,
  KnowledgeRecord,
  LiteratureResponse,
  RunDetail,
  RunEvent,
  RunSummary,
  Selftest,
  TargetDesignResult,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      "The lab API is not reachable. Start it with: uv run bacterion-api",
      0,
      cause,
    );
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()) as unknown;
    } catch {
      detail = await response.text();
    }
    throw new ApiError(describeDetail(detail, response.status), response.status, detail);
  }
  return (await response.json()) as T;
}

/** Turn FastAPI's error shapes into one sentence a person can act on. */
function describeDetail(detail: unknown, status: number): string {
  if (detail && typeof detail === "object" && "detail" in detail) {
    const inner = (detail as { detail: unknown }).detail;
    if (typeof inner === "string") return inner;
    if (Array.isArray(inner)) {
      return inner
        .map((item) => {
          const e = item as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(e.loc) ? e.loc.slice(1).join(".") : "request";
          return `${field}: ${e.msg ?? "invalid"}`;
        })
        .join("; ");
    }
  }
  return `Request failed (HTTP ${status}).`;
}

export interface RunRequestBody {
  goal: string;
  species: string;
  gram: "positive" | "negative";
  strain?: string | null;
  target_cell_density?: number;
  ph?: number;
  temperature_c?: number;
  max_candidates?: number;
  max_iterations?: number;
  seed?: number | null;
}

export const api = {
  health: () => request<Health>("/api/health"),
  agents: () => request<{ agents: AgentDescriptor[]; loop: string[] }>("/api/agents"),
  selftest: () => request<Selftest>("/api/simulator/selftest"),
  backends: () => request<Record<string, Record<string, unknown>>>("/api/simulator/backends"),

  runs: () => request<{ runs: RunSummary[] }>("/api/runs"),
  run: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),
  runEvents: (runId: string, since = 0) =>
    request<{ run_id: string; status: string; events: RunEvent[] }>(
      `/api/runs/${runId}/events?since=${since}`,
    ),
  startRun: (body: RunRequestBody) =>
    request<RunSummary>("/api/runs", { method: "POST", body: JSON.stringify(body) }),

  referenceBacteriocins: () =>
    request<{ source_name: string; records: KnowledgeRecord[] }>("/api/reference-bacteriocins"),

  candidates: (body: {
    species: string;
    gram: "positive" | "negative";
    strain?: string | null;
    max_candidates?: number;
    desired_behavior?: Record<string, unknown>;
  }) => request<CandidateEnvelope>("/api/candidates", { method: "POST", body: JSON.stringify(body) }),

  evidence: (body: {
    question: string;
    bacteriocin?: string | null;
    target_organism?: string | null;
    target_strain?: string | null;
    max_results?: number;
    retrieve?: boolean;
  }) => request<LiteratureResponse>("/api/evidence", { method: "POST", body: JSON.stringify(body) }),

  designTarget: (body: {
    target_organism: string;
    target_strain?: string | null;
    context?: Record<string, unknown> | null;
    desired_properties?: Record<string, unknown> | null;
    max_known_candidates?: number;
    max_natural_variants?: number;
    max_designed_candidates?: number;
    seed?: number | null;
    known_threshold?: number;
    natural_threshold?: number;
  }) =>
    request<TargetDesignResult>("/api/design/target", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  experiment: (body: { spec: Record<string, unknown>; candidate_registry?: Record<string, unknown> }) =>
    request<ExperimentResult>("/api/simulator/experiment", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  experiments: (body: {
    specs: Record<string, unknown>[];
    candidate_registry?: Record<string, unknown>;
  }) =>
    request<{ results: ExperimentResult[] }>("/api/simulator/experiments", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
