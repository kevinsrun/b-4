/**
 * Typed contracts for Project-Centered Research, Samples, Sequence Records, and CRISPR Studies.
 *
 * Mirrors backend Pydantic models in `bacteriocin_lab/projects/schemas.py`.
 */

export interface BiologicalSample {
  sample_id: string;
  project_id: string;
  sample_name: string;
  organism: string;
  strain?: string | null;
  gram_stain: "positive" | "negative" | "variable" | "unknown";
  isolation_source?: string | null;
  collection_date?: string | null;
  sequencing_run_ids: string[];
  dataset_ids: string[];
  created_at: string;
  metadata: Record<string, any>;
}

export interface SequenceAnnotation {
  annotation_id: string;
  feature_type:
    | "cds"
    | "core_peptide"
    | "leader_peptide"
    | "cleavage_site"
    | "modification_enzyme"
    | "immunity_protein"
    | "transporter"
    | "regulator"
    | "crispr_repeat"
    | "crispr_spacer"
    | "promoter"
    | "terminator";
  name: string;
  start: number;
  end: number;
  strand: "+" | "-";
  qualifiers: Record<string, any>;
  evidence_ids: string[];
}

export interface AnnotatedSequence {
  sequence_id: string;
  project_id: string;
  sample_id?: string | null;
  source_dataset_id?: string | null;
  name: string;
  molecule_type: "dna" | "protein" | "rna";
  sequence: string;
  length: number;
  description?: string | null;
  genomic_coordinates?: string | null;
  reference_version?: string | null;
  orientation: "5to3" | "3to5";
  annotations: SequenceAnnotation[];
  provenance: Record<string, any>;
  created_at: string;
}

export interface SequenceVariant {
  variant_id: string;
  reference_sequence_id: string;
  position: number;
  reference_allele: string;
  alternate_allele: string;
  variant_type: "snv" | "insertion" | "deletion" | "substitution";
  coordinate_system: "1_based" | "0_based";
  predicted_effect?: string | null;
  evidence_citations: string[];
  uncertainty_level: "low" | "medium" | "high" | "unconfirmed";
  confidence_score?: number | null;
}

export interface CrisprTargetRegion {
  target_id: string;
  study_id: string;
  target_name: string;
  locus_tag?: string | null;
  sequence_id: string;
  start_pos: number;
  end_pos: number;
  strand: "+" | "-";
  target_sequence: string;
  pam_motif?: string | null;
  orientation: string;
  annotations: string[];
  published_evidence: Array<{ pmid?: string; title?: string; authors?: string }>;
  validation_status: "computational_only" | "in_vitro_tested" | "literature_confirmed" | "unvalidated";
}

export interface CrisprObjective {
  study_id: string;
  project_id: string;
  sample_id?: string | null;
  title: string;
  investigation_purpose: string;
  target_gene: string;
  target_sequence_id: string;
  reference_version: string;
  target_regions: CrisprTargetRegion[];
  variants: SequenceVariant[];
  specificity_considerations?: string | null;
  experimental_findings_summary?: string | null;
  review_status: "draft" | "in_review" | "approved" | "archived";
  created_at: string;
  updated_at: string;
}

export interface ResearchProject {
  project_id: string;
  name: string;
  description: string;
  lead_investigator?: string | null;
  target_organism: string;
  status: "active" | "completed" | "archived";
  sample_ids: string[];
  sequencing_run_ids: string[];
  dataset_ids: string[];
  sequence_ids: string[];
  amp_job_ids: string[];
  crispr_study_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ProjectCreateRequest {
  name: string;
  description: string;
  lead_investigator?: string | null;
  target_organism: string;
}

export interface SampleCreateRequest {
  sample_name: string;
  organism: string;
  strain?: string | null;
  gram_stain: "positive" | "negative" | "variable" | "unknown";
  isolation_source?: string | null;
}

export interface CrisprObjectiveCreateRequest {
  title: string;
  investigation_purpose: string;
  target_gene: string;
  target_sequence_id: string;
  reference_version?: string;
  sample_id?: string | null;
  specificity_considerations?: string | null;
}

export interface SequenceComparisonRequest {
  reference_sequence_id: string;
  query_sequence: string;
  query_name?: string;
}

export interface SequenceComparisonResult {
  reference_id: string;
  reference_name: string;
  query_name: string;
  length_reference: number;
  length_query: number;
  identity_percentage: number;
  mismatches_count: number;
  gaps_count: number;
  variants: SequenceVariant[];
  alignment_chunks: Array<{
    type: "match" | "mismatch" | "insertion" | "deletion" | "variant_bearing";
    ref_start: number;
    ref_end: number;
    query_start: number;
    query_end: number;
    ref_text: string;
    query_text: string;
  }>;
}
