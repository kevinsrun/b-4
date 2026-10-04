/**
 * Shapes returned by the Python API.
 *
 * These mirror fields the agents actually emit — `bacteriocin_lab/agents/simulator/schemas.py`
 * and `bacteriocin_lab/orchestration/types.py` are the source of truth. Anything
 * optional here is optional there: a measurement the model could not produce is
 * absent rather than zero, and the UI has to render that absence as "not
 * reported" rather than invent a number for it.
 */

export type EvidenceType =
  | "simulation-derived"
  | "literature-derived"
  | "wet-lab-derived"
  | "computational-prediction";

export interface Quantity {
  value: number;
  unit?: string | null;
}

export interface Measurement {
  predicted_inhibition_fraction?: number | null;
  predicted_survival_fraction?: number | null;
  predicted_activity?: number | null;
  uncertainty?: number | null;
  primary_metric?: string | null;
  ci95_inhibition_fraction?: [number, number] | number[] | null;
  sigma_logit_inhibition?: number | null;
  /** What the literature reports, so it is what a prediction can be compared against. */
  predicted_mic_um?: number | null;
  /** Carries signal where the inhibition fraction has saturated near 1.0. */
  predicted_log10_reduction_vs_control?: number | null;
  uncertainty_log10_reduction?: number | null;
  predicted_log10_change_from_inoculum?: number | null;
  predicted_zone_diameter_mm?: number | null;
  free_peptide_concentration_um?: number | null;
  kill_rate_per_h?: number | null;
  dose_over_mic?: number | null;
}

export interface ImportantFactor {
  factor: string;
  sensitivity: number;
  direction?: string | null;
  value?: number | string | null;
  /** `imputed_default` means nobody specified this; the prediction assumed it. */
  source?: string | null;
  unit?: string | null;
}

export interface ResultConditions {
  bacteriocin_concentration?: Quantity | number | null;
  target_cell_density?: Quantity | number | null;
  ph?: number | null;
  temperature_c?: number | null;
  medium?: string | null;
  incubation_time?: number | null;
  incubation_time_unit?: string | null;
  growth_phase?: string | null;
  assay_domain?: string | null;
  assay_type?: string | null;
  /** Condition keys the simulator filled in because the spec left them out. */
  imputed_fields?: string[] | null;
  target?: { species?: string | null; strain?: string | null } | null;
  [key: string]: unknown;
}

export interface UncertaintyComponent {
  source: string;
  sigma_logit: number;
  rationale?: string | null;
}

export interface ExperimentResult {
  result_id: string;
  experiment_id: string;
  candidate_id?: string | null;
  hypothesis_id?: string | null;
  conditions: ResultConditions;
  measurement: Measurement;
  important_factors?: ImportantFactor[] | null;
  evidence_type: EvidenceType;
  model_version?: string | null;
  backend?: string | null;
  assay_type?: string | null;
  confidence?: number | null;
  /** The simulator's schema rejects `true` here. It is shown, not assumed. */
  validated_experimentally?: boolean | null;
  /** The uncertainty budget: where the spread comes from, and why. */
  uncertainty_components?: UncertaintyComponent[] | null;
  warnings?: string[] | null;
  status?: string | null;
  error?: string | null;
  created_at?: string | null;
}

export interface ExperimentSpec {
  experiment_id: string;
  candidate_id?: string | null;
  hypothesis_id?: string | null;
  target?: { species?: string | null; strain?: string | null } | null;
  conditions?: Record<string, unknown> | null;
  replicates?: number | null;
}

export interface Candidate {
  candidate_id: string;
  name: string;
  sequence?: string | null;
  source?: string | null;
  score_total: number;
  confidence: number;
  features?: Record<string, unknown> | null;
  falsified_if?: string | null;
  validation_status: string;
  rank: number;
}

export type HypothesisStatus = "open" | "supported" | "contradicted" | "weakened" | "rejected";

export interface Hypothesis {
  hypothesis_id: string;
  candidate_id?: string | null;
  statement: string;
  prediction?: string | null;
  status: HypothesisStatus;
  prior_plausibility: number;
  posterior_probability: number;
  falsified_if?: string | null;
  evidence_ids?: string[];
}

export interface Finding {
  finding_id: string;
  statement: string;
  status: "supported" | "contradicted" | "weakened" | "inconclusive";
  confidence: number;
  candidate_ids: string[];
  hypothesis_ids: string[];
  evidence_ids: string[];
  factor_sensitivities?: Record<string, number> | null;
  recommendations?: string[] | null;
}

export interface Review {
  review_id: string;
  status: string;
  critique: string;
  recommendation?: Record<string, unknown> | null;
  reviewer: string;
  confidence: number;
}

export interface ScientificEvent {
  event_id: string;
  event_type: string;
  iteration: number;
  source_agent: string;
  summary: string;
  data?: Record<string, unknown> | null;
  timestamp?: string | null;
}

export interface ResearchState {
  objective?: {
    goal?: string;
    target?: Record<string, unknown>;
    desired_behavior?: Record<string, unknown>;
    constraints?: Record<string, unknown>;
  };
  candidates: Candidate[];
  hypotheses: Hypothesis[];
  experiments: ExperimentSpec[];
  results: ExperimentResult[];
  findings: Finding[];
  reviews: Review[];
  knowledge_gaps: string[];
  uncertainties: (string | Record<string, unknown>)[];
  iteration: number;
  scientific_history: ScientificEvent[];
  tested_candidate_ids: string[];
  settled_candidate_ids: string[];
}

export type AgentRole =
  | "evidence"
  | "candidate"
  | "planner"
  | "simulation"
  | "analysis"
  | "critic"
  | "knowledge";

export interface RunDigest {
  candidates: number;
  hypotheses: number;
  experiments: number;
  results: number;
  findings: number;
  reviews: number;
  scientific_history: number;
  tested_candidate_ids: number;
  settled_candidate_ids: number;
  knowledge_gaps: number;
  uncertainties: number;
  iteration: number;
}

export interface RunSummary {
  run_id: string;
  engine_run_id: string | null;
  /** Where the HTTP layer thinks the run is: running, finished, error. */
  status: "running" | "finished" | "error";
  /** How the loop itself classified its ending: completed, max_iterations, stopped, failed. */
  engine_status: string | null;
  request: Record<string, unknown>;
  digest: RunDigest;
  n_events: number;
  error: string | null;
  summary: Record<string, number | string[]>;
  errors: string[];
}

export interface ExecutionTraceItem {
  trace_id: string;
  iteration: number;
  agent: AgentRole;
  input_ids: string[];
  output_ids: string[];
  routing_reason: string;
  status: "success" | "failure" | "skipped";
  error: string | null;
}

export interface RunDetail extends RunSummary {
  state: ResearchState | Record<string, never>;
  execution_trace: ExecutionTraceItem[];
}

export type RunEvent =
  | { seq: number; ts: number; type: "run_started"; request: Record<string, unknown> }
  | { seq: number; ts: number; type: "agent_started"; agent: AgentRole; iteration: number }
  | {
      seq: number;
      ts: number;
      type: "agent_finished";
      agent: AgentRole;
      iteration: number;
      duration_ms: number;
      output_ids: string[];
      events: ScientificEvent[];
      digest?: RunDigest;
    }
  | {
      seq: number;
      ts: number;
      type: "agent_failed";
      agent: AgentRole;
      iteration: number;
      duration_ms: number;
      error: string;
    }
  | {
      seq: number;
      ts: number;
      type: "run_finished";
      engine_run_id: string;
      engine_status: string;
      iterations_completed: number;
      errors: string[];
      summary: Record<string, number | string[]>;
      digest: RunDigest;
    }
  | { seq: number; ts: number; type: "run_failed"; error: string };

export interface AgentDescriptor {
  role: AgentRole;
  label: string;
  agent_name: string;
  model_version?: string;
  transport: "mcp-tool" | "sub-agent";
  deterministic: boolean;
  produces: string;
  claim: string;
}

export interface Health {
  status: string;
  schema_version: string;
  simulator_version: string;
  max_iterations_limit: number;
  active_runs: number;
}

export interface SelftestCheck {
  check: string;
  passed: boolean;
  status: "pass" | "fail" | "known_failure" | "unexpectedly_fixed";
  detail: string;
  known_failure_reason?: string;
}

export interface Selftest {
  passed: boolean;
  n_checks: number;
  n_failed: number;
  n_known_failures: number;
  checks: SelftestCheck[];
  note?: string;
}

/* ---- literature ---- */

/** A normalised quantity: the agent keeps what the paper said next to what it converted it to. */
export interface NormalizedQuantity {
  value?: number | null;
  unit?: string | null;
  original_value?: string | number | null;
  original_unit?: string | null;
  normalized_value?: number | null;
  normalized_unit?: string | null;
  normalization_note?: string | null;
}

export interface EvidenceRecord {
  evidence_id: string;
  claim?: string | null;
  evidence_type?: string | null;
  confidence?: number | null;
  source?: {
    source_id?: string | null;
    title?: string | null;
    doi_or_url?: string | null;
    year?: number | null;
    authors?: string[] | null;
    journal?: string | null;
    source_type?: string | null;
  } | null;
  bacteriocin?: { name?: string | null; aliases?: string[] | null; sequence?: string | null } | null;
  target?: { organism?: string | null; strain?: string | null } | null;
  conditions?: Record<string, NormalizedQuantity | string | number | null> | null;
  measurement?: {
    type?: string | null;
    value?: number | null;
    unit?: string | null;
    original_text?: string | null;
    /** "measured" or an author's interpretation — the distinction is preserved. */
    data_role?: string | null;
  } | null;
  /** Everything the paper did not report. Usually long, and shown rather than hidden. */
  missing_variables?: string[] | null;
  provenance?: {
    locator?: string | null;
    excerpt?: string | null;
    extraction_method?: string | null;
  } | null;
  [key: string]: unknown;
}

export interface LiteratureResponse {
  query_id: string;
  agent: string;
  decision: Record<string, unknown>;
  evidence: EvidenceRecord[];
  knowledge_gaps: string[];
  contradictions: Record<string, unknown>[];
  recommended_searches: string[];
  confidence: number;
  uncertainties: (Uncertainty | string)[];
  artifacts: Record<string, unknown>;
  warnings: string[];
}

/* ---- the candidate agent's curated knowledge ---- */

export interface KnowledgeRecord {
  name: string;
  sequence?: string | null;
  bacteriocin_class?: string | null;
  producing_organism?: string | null;
  known_targets?: string[] | null;
  known_non_targets?: string[] | null;
  structural_features?: string[] | null;
  known_stability?: {
    ph_stable_range?: [number, number] | number[] | null;
    thermostable?: boolean | null;
    optimal_ph_activity?: number | null;
    notes?: string | null;
  } | null;
  environmental_sensitivity?: string[] | null;
  mechanism?: string | null;
  notes?: string | null;
  [key: string]: unknown;
}

/* ---- candidate agent envelope ---- */

export interface CandidateProposal {
  candidate_id: string;
  name: string;
  sequence?: string | null;
  origin?: string | null;
  rank?: number | null;
  /** Component scores plus `total` and a `rationale` list, from the agent. */
  score?: Record<string, number | string[]> | null;
  score_total?: number | null;
  confidence?: number | null;
  features?: Record<string, unknown> | null;
  hypothesis?: string | null;
  hypotheses?: Record<string, unknown>[] | null;
  expected_strengths?: string[] | null;
  expected_failure_modes?: string[] | null;
  /** Always "unvalidated" — the agent proposes, it does not validate. */
  validation_status?: string | null;
  /** False unless the sequence was checked against a primary database. */
  sequence_verified?: boolean | null;
  [key: string]: unknown;
}

/**
 * A declared limitation. Agents emit these as structured records rather than
 * prose so the severity and the affected ids survive into the interface.
 */
export interface Uncertainty {
  kind: "aleatoric" | "epistemic" | "data-gap" | "model-limitation" | "contract-gap" | string;
  description: string;
  affects?: string[] | null;
  severity?: "low" | "medium" | "high" | string | null;
}

export interface CandidateEnvelope {
  agent: string;
  decision: {
    candidates?: CandidateProposal[];
    hypotheses?: Record<string, unknown>[];
    [key: string]: unknown;
  };
  confidence: number;
  uncertainties: (Uncertainty | string)[];
  artifacts: Record<string, unknown>;
  warnings: string[];
  model_version?: string;
}

/* --- target-driven design -------------------------------------------------
 *
 * The designer escalates through three tiers and each tier carries a different
 * kind of claim, so they are typed separately rather than flattened into one
 * candidate shape. A known bacteriocin's sequence is literature-derived, a
 * natural variant's is observed in a sequence database, and a designed one was
 * generated — it is a proposal and nothing more. Every predicted number on all
 * three, however, comes from the simulator.
 */

export type DesignTier = "known" | "natural_variant" | "computational_design";

/** Predictions the simulator attaches to a candidate. Never observations. */
export interface DesignSimulationMetrics {
  predicted_inhibition?: number | null;
  predicted_log10_reduction?: number | null;
  predicted_mic_um?: number | null;
  confidence?: number | null;
}

export interface DesignScoreComponents {
  predicted_activity?: number;
  target_match?: number;
  environmental_robustness?: number;
  evidence_quality?: number;
  natural_support?: number;
  novelty_value?: number;
  uncertainty_penalty?: number;
  unsupported_design_penalty?: number;
  [key: string]: number | undefined;
}

export interface KnownDesignCandidate extends CalibrationFields {
  candidate_id: string;
  name: string;
  sequence: string;
  bacteriocin_class?: string | null;
  tier: "known";
  score: number;
  components: DesignScoreComponents;
  provenance: string;
  experimentally_validated: boolean;
  evidence_count?: number | null;
  known_targets?: string[];
  simulation_metrics?: DesignSimulationMetrics;
}

export interface NaturalVariantCandidate extends CalibrationFields {
  candidate_id: string;
  parent_candidate_id: string;
  name: string;
  sequence: string;
  source?: string;
  mutation?: string;
  protein_position?: number;
  reference_aa?: string;
  alternate_aa?: string;
  /** Accessions in which this residue is actually observed. */
  observed_accessions?: string[];
  tier: "natural_variant";
  score: number;
  components: DesignScoreComponents;
  provenance: string;
  experimentally_validated: boolean;
  simulation_metrics?: DesignSimulationMetrics;
}

export interface DesignMutation {
  position: number;
  reference: string;
  alternate: string;
  origin: "natural_homolog" | "conservative_substitution" | "model_ranked_substitution" | string;
  supporting_accessions?: string[];
  rationale?: string | null;
}

export interface DesignedCandidate extends CalibrationFields {
  candidate_id: string;
  parent_candidate_id: string;
  sequence: string;
  mutations: DesignMutation[];
  design_class?: string;
  rationale?: {
    status?: string;
    evidence_ids?: string[];
    natural_variant_support?: string[];
    expected_properties?: string[];
  };
  /** The schema pins these two; a design can never claim to be measured. */
  provenance: "model-predicted";
  experimentally_validated: false;
  uncertainty?: { confidence?: number | null; components?: string[] };
  score: number;
  components: DesignScoreComponents;
  generation?: number;
  critic_verdict?: string;
  critic_notes?: string[];
  simulation_metrics?: DesignSimulationMetrics;
}

export interface DesignRecommendation {
  tier: DesignTier;
  name: string;
  score: number;
  predicted_inhibition: number;
  confidence: string;
  evidence_count?: number | null;
  experimentally_validated: boolean;
  candidate_id?: string | null;
  mutations: string[];
}

export interface TargetDesignResult {
  target: { organism: string; strain?: string | null; gram?: string | null };
  known_candidates: KnownDesignCandidate[];
  natural_variant_candidates: NaturalVariantCandidate[];
  designed_candidates: DesignedCandidate[];
  best_current_candidate?: (KnownDesignCandidate | NaturalVariantCandidate) | null;
  evidence_summary: {
    literature_candidates_screened?: number;
    natural_variants_identified?: number;
    computational_designs_generated?: number;
    [key: string]: unknown;
  };
  uncertainties: string[];
  recommended_next_experiment: {
    experiment_type?: string;
    candidate_id?: string;
    purpose?: string;
    suggested_concentrations_um?: number[];
    recommended_assay?: string;
    [key: string]: unknown;
  };
  limitations: string[];
  provenance: Record<string, unknown>;
  recommendations: DesignRecommendation[];
  calibration_summary?: CalibrationSummary;
  recommended_validation_experiment?: ValidationExperiment;
  iteration?: number;
  /** Explicitly non-operational: no wet-lab or engineering instructions. */
  future_production_concept: {
    status?: string;
    candidate_peptide?: string;
    producer_compatibility?: string;
    notes?: string[];
  };
}

/* --- calibration, PTM and scenarios (added with the active-learning pass) ---
 *
 * These qualify the predictions above rather than adding new ones. A raw score
 * and a calibrated score are different claims, and a prediction made where the
 * model has no observations is a third thing again — so the interval and the
 * extrapolation flag travel with the number they qualify.
 */

export interface CalibratedPrediction {
  raw_score?: number | null;
  raw_mic_um?: number | null;
  calibrated_score?: number | null;
  calibrated_mic_um?: number | null;
  confidence?: number | null;
  /** [low, high] on the calibrated score. */
  uncertainty_interval?: [number, number] | null;
  /** "uncalibrated_prior" means the number is a prior, not a fitted estimate. */
  calibration_mode?: string;
  is_extrapolative?: boolean;
  extrapolation_reasons?: string[];
}

export interface PtmModificationSite {
  position: number;
  residue: string;
  modification_type: string;
  description?: string;
}

export interface PtmProfile {
  is_ptm_dependent?: boolean;
  ptm_class?: string;
  structural_uncertainty_score?: number;
  /** The peptide needs host enzymes to mature — a sequence alone is not the molecule. */
  requires_enzymatic_machinery?: boolean;
  mature_topology_confirmed?: boolean;
  modification_sites?: PtmModificationSite[];
}

export interface ScenarioProfile {
  scenario_id: string;
  scenario_name: string;
  description?: string;
  predicted_activity_retention?: number;
  limiting_factors?: string[];
  matrix_effects?: Record<string, unknown>;
}

export interface CalibrationSummary {
  calibrated?: boolean;
  calibration_observations_count?: number;
  is_extrapolative?: boolean;
  extrapolation_reasons?: string[];
}

export interface ValidationExperiment {
  experiment_id?: string;
  candidate_id?: string;
  candidate_name?: string;
  tier?: DesignTier | string;
  sequence?: string;
  target?: Record<string, unknown>;
  recommended_assay?: string;
  dilution_series_um?: number[];
  anchor_mic_um?: number | null;
  information_gain_rationale?: string;
}

/** Carried by every tier, so it is mixed into each rather than repeated. */
export interface CalibrationFields {
  calibrated_prediction?: CalibratedPrediction | null;
  ptm_profile?: PtmProfile | null;
  scenario_profiles?: ScenarioProfile[];
  acquisition_score?: number | null;
  epistemic_uncertainty?: number | null;
  calibrated_score?: number | null;
  calibrated_mic_um?: number | null;
  uncertainty_interval?: [number, number] | null;
}

/* --- knowledge (research state) ------------------------------------------
 *
 * Read-only. Writing to the research state belongs to the loop, and the API
 * exposes only these three queries.
 */

export type KnowledgeOperation = "summary" | "open-questions" | "integrity";

export interface KnowledgeEnvelope {
  agent: string;
  decision: {
    operation: string;
    status: "ok" | "error" | string;
    error?: string;
    result?: Record<string, unknown>;
  };
  evidence: unknown[];
  confidence: number;
  uncertainties: (Uncertainty | string)[];
  artifacts: Record<string, unknown>;
  warnings: string[];
  recommended_next_action?: unknown;
  model_version?: string;
}

/** What `summary` returns under `decision.result`. */
export interface KnowledgeSummary {
  iteration?: number;
  event_count?: number;
  last_event_hash?: string | null;
  objective?: Record<string, unknown>;
  counts?: {
    candidates?: Record<string, number>;
    hypotheses?: Record<string, number>;
    experiments?: number;
    results?: number;
    findings?: number;
    evidence?: number;
  };
  provenance?: string;
  hypotheses?: Record<string, unknown>[];
  rejected_hypotheses?: Record<string, unknown>[];
  rejected_candidates?: Record<string, unknown>[];
  latest_ranking?: unknown;
  known_relationships?: Record<string, unknown>[];
  open_questions?: Record<string, unknown>[];
  n_open_questions?: number;
  active_uncertainties?: (Uncertainty | string)[];
  model_versions?: string[];
  model_version_warning?: string | null;
}
