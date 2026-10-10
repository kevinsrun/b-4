/**
 * Centralized API client for Projects, Biological Samples, Sequence Records, and CRISPR Studies.
 */

import {
  ResearchProject,
  ProjectCreateRequest,
  BiologicalSample,
  SampleCreateRequest,
  AnnotatedSequence,
  CrisprObjective,
  CrisprObjectiveCreateRequest,
  SequenceComparisonRequest,
  SequenceComparisonResult,
} from "./project-types";
import {
  FIXTURE_PROJECTS,
  FIXTURE_SAMPLES,
  FIXTURE_SEQUENCES,
  FIXTURE_CRISPR_STUDIES,
} from "./project-fixtures";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

let runtimeProjects: ResearchProject[] = [...FIXTURE_PROJECTS];
let runtimeSamples: BiologicalSample[] = [...FIXTURE_SAMPLES];
let runtimeSequences: AnnotatedSequence[] = [...FIXTURE_SEQUENCES];
let runtimeCrisprStudies: CrisprObjective[] = [...FIXTURE_CRISPR_STUDIES];

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

export async function fetchProjects(): Promise<{ projects: ResearchProject[]; isLive: boolean }> {
  const res = await safeFetch<ResearchProject[]>(
    "/api/v1/projects",
    { method: "GET" },
    () => runtimeProjects
  );
  if (res.isLive) {
    runtimeProjects = res.data;
  }
  return { projects: res.data, isLive: res.isLive };
}

export async function fetchProject(
  projectId: string
): Promise<{ project: ResearchProject | null; isLive: boolean }> {
  const res = await safeFetch<ResearchProject>(
    `/api/v1/projects/${projectId}`,
    { method: "GET" },
    () => runtimeProjects.find((p) => p.project_id === projectId) || null as any
  );
  return { project: res.data, isLive: res.isLive };
}

export async function createProject(
  request: ProjectCreateRequest
): Promise<{ project: ResearchProject; isLive: boolean }> {
  const res = await safeFetch<ResearchProject>(
    "/api/v1/projects",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    () => {
      const newProj: ResearchProject = {
        project_id: `proj_${Date.now()}`,
        name: request.name,
        description: request.description,
        lead_investigator: request.lead_investigator,
        target_organism: request.target_organism,
        status: "active",
        sample_ids: [],
        sequencing_run_ids: [],
        dataset_ids: [],
        sequence_ids: [],
        amp_job_ids: [],
        crispr_study_ids: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      runtimeProjects = [newProj, ...runtimeProjects];
      return newProj;
    }
  );
  return { project: res.data, isLive: res.isLive };
}

export async function fetchProjectSamples(
  projectId: string
): Promise<{ samples: BiologicalSample[]; isLive: boolean }> {
  const res = await safeFetch<BiologicalSample[]>(
    `/api/v1/projects/${projectId}/samples`,
    { method: "GET" },
    () => runtimeSamples.filter((s) => s.project_id === projectId)
  );
  return { samples: res.data, isLive: res.isLive };
}

export async function fetchProjectSequences(
  projectId: string
): Promise<{ sequences: AnnotatedSequence[]; isLive: boolean }> {
  const res = await safeFetch<AnnotatedSequence[]>(
    `/api/v1/projects/${projectId}/sequences`,
    { method: "GET" },
    () => runtimeSequences.filter((s) => s.project_id === projectId)
  );
  return { sequences: res.data, isLive: res.isLive };
}

export async function fetchAllSequences(): Promise<{ sequences: AnnotatedSequence[]; isLive: boolean }> {
  return { sequences: runtimeSequences, isLive: false };
}

export async function fetchSequence(
  sequenceId: string
): Promise<{ sequence: AnnotatedSequence | null; isLive: boolean }> {
  const res = await safeFetch<AnnotatedSequence>(
    `/api/v1/sequences/${sequenceId}`,
    { method: "GET" },
    () => runtimeSequences.find((s) => s.sequence_id === sequenceId) || null as any
  );
  return { sequence: res.data, isLive: res.isLive };
}

export async function compareSequence(
  sequenceId: string,
  request: SequenceComparisonRequest
): Promise<{ comparison: SequenceComparisonResult; isLive: boolean }> {
  const res = await safeFetch<SequenceComparisonResult>(
    `/api/v1/sequences/${sequenceId}/compare`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    () => {
      const ref = runtimeSequences.find((s) => s.sequence_id === sequenceId);
      const refSeq = ref ? ref.sequence.toUpperCase() : "ACGT";
      const qSeq = request.query_sequence.toUpperCase();

      let mismatches = 0;
      const minLen = Math.min(refSeq.length, qSeq.length);
      const variants = [];

      for (let i = 0; i < minLen; i++) {
        if (refSeq[i] !== qSeq[i]) {
          mismatches++;
          variants.push({
            variant_id: `var_sim_${i + 1}`,
            reference_sequence_id: sequenceId,
            position: i + 1,
            reference_allele: refSeq[i],
            alternate_allele: qSeq[i],
            variant_type: "snv" as const,
            coordinate_system: "1_based" as const,
            predicted_effect: `Single substitution at ${i + 1}: ${refSeq[i]}>${qSeq[i]}`,
            evidence_citations: [],
            uncertainty_level: "low" as const,
            confidence_score: 1.0,
          });
        }
      }

      const identity = ((minLen - mismatches) / Math.max(refSeq.length, qSeq.length)) * 100.0;

      return {
        reference_id: sequenceId,
        reference_name: ref?.name || "Reference",
        query_name: request.query_name || "Query Sequence",
        length_reference: refSeq.length,
        length_query: qSeq.length,
        identity_percentage: Math.round(identity * 100) / 100,
        mismatches_count: mismatches,
        gaps_count: Math.abs(refSeq.length - qSeq.length),
        variants,
        alignment_chunks: [
          {
            type: mismatches === 0 ? "match" : "variant_bearing",
            ref_start: 1,
            ref_end: refSeq.length,
            query_start: 1,
            query_end: qSeq.length,
            ref_text: refSeq,
            query_text: qSeq,
          },
        ],
      };
    }
  );
  return { comparison: res.data, isLive: res.isLive };
}

export async function fetchCrisprStudies(
  projectId?: string
): Promise<{ studies: CrisprObjective[]; isLive: boolean }> {
  const url = projectId
    ? `/api/v1/projects/${projectId}/crispr-studies`
    : "/api/v1/crispr/studies";
  const res = await safeFetch<CrisprObjective[]>(url, { method: "GET" }, () => {
    if (projectId) return runtimeCrisprStudies.filter((s) => s.project_id === projectId);
    return runtimeCrisprStudies;
  });
  if (res.isLive) {
    runtimeCrisprStudies = res.data;
  }
  return { studies: res.data, isLive: res.isLive };
}

export async function fetchCrisprStudy(
  studyId: string
): Promise<{ study: CrisprObjective | null; isLive: boolean }> {
  const res = await safeFetch<CrisprObjective>(
    `/api/v1/crispr/studies/${studyId}`,
    { method: "GET" },
    () => runtimeCrisprStudies.find((s) => s.study_id === studyId) || null as any
  );
  return { study: res.data, isLive: res.isLive };
}

export async function createCrisprStudy(
  projectId: string,
  request: CrisprObjectiveCreateRequest
): Promise<{ study: CrisprObjective; isLive: boolean }> {
  const res = await safeFetch<CrisprObjective>(
    `/api/v1/projects/${projectId}/crispr-studies`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    () => {
      const newStudy: CrisprObjective = {
        study_id: `crispr_${Date.now()}`,
        project_id: projectId,
        sample_id: request.sample_id,
        title: request.title,
        investigation_purpose: request.investigation_purpose,
        target_gene: request.target_gene,
        target_sequence_id: request.target_sequence_id,
        reference_version: request.reference_version || "v1.0",
        target_regions: [],
        variants: [],
        specificity_considerations: request.specificity_considerations,
        experimental_findings_summary: null,
        review_status: "draft",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      runtimeCrisprStudies = [newStudy, ...runtimeCrisprStudies];
      return newStudy;
    }
  );
  return { study: res.data, isLive: res.isLive };
}
