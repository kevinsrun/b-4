"""Shared experiment schemas for the Omnigent bacteriocin-discovery lab.

This module implements the ExperimentSpec / ExperimentResult contract exactly
as specified in the shared system contract, plus a small number of *additive*
optional extensions that the simulation backend needs in order to compute
anything at all (notably: the peptide sequence behind ``candidate_id``).

Contract-stability rules honoured here:

* Every field named in the shared contract exists, with the contract's name,
  nesting and default (``None`` where the contract shows ``null``).
* Extensions are **optional** with safe defaults, so a producer that only
  knows the contract shape still validates.
* Unknown keys are preserved rather than dropped (``model_config.extra``),
  so a newer planner can send fields an older backend has not learned yet
  without losing information on round-trip.
* Proposed contract changes are documented in ``CONTRACT.md``, never applied
  unilaterally.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_NAME = "simulation_experiment_backend"

# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------


class EvidenceType(str, Enum):
    """Provenance classes required by the shared contract (agent rule 8)."""

    LITERATURE = "literature-derived"
    DATABASE = "database-derived"
    MODEL_PREDICTED = "model-predicted"
    SIMULATION = "simulation-derived"
    INFERRED = "inferred-hypothesis"
    WET_LAB = "wet-lab-derived"


class AssayDomain(str, Enum):
    """Where an experiment is executed. Routes the spec to a backend adapter."""

    SIMULATED_IN_VITRO = "simulated_in_vitro"
    SIMULATED_IN_VIVO_LIKE = "simulated_in_vivo_like"
    WET_LAB_IN_VITRO = "wet_lab_in_vitro"
    WET_LAB_IN_VIVO = "wet_lab_in_vivo"


class AssayType(str, Enum):
    """Assay readout being emulated. Determines the *primary* metric."""

    MIC_BROTH_MICRODILUTION = "mic_broth_microdilution"
    MICROTITER_GROWTH_INHIBITION = "microtiter_growth_inhibition"
    TIME_KILL = "time_kill"
    AGAR_WELL_DIFFUSION = "agar_well_diffusion"
    SPOT_ON_LAWN = "spot_on_lawn"


class GrowthPhase(str, Enum):
    LAG = "lag"
    EARLY_EXPONENTIAL = "early_exponential"
    EXPONENTIAL = "exponential"
    LATE_EXPONENTIAL = "late_exponential"
    STATIONARY = "stationary"
    BIOFILM = "biofilm"


class BacteriocinClass(str, Enum):
    """Coarse structural class; drives the receptor-dependence term."""

    CLASS_I_LANTIBIOTIC = "class_I_lantibiotic"
    CLASS_IIA_PEDIOCIN_LIKE = "class_IIa_pediocin_like"
    CLASS_IIB_TWO_PEPTIDE = "class_IIb_two_peptide"
    CLASS_IIC_CIRCULAR = "class_IIc_circular"
    CLASS_IID_UNMODIFIED = "class_IId_unmodified"
    CLASS_III_BACTERIOLYSIN = "class_III_bacteriolysin"
    COLICIN_LIKE = "colicin_like"
    UNKNOWN = "unknown"


class DensityUnit(str, Enum):
    CFU_PER_ML = "cfu_per_ml"
    CELLS_PER_ML = "cells_per_ml"
    OD600 = "od600"
    LOG10_CFU_PER_ML = "log10_cfu_per_ml"


class ConcentrationUnit(str, Enum):
    MICROMOLAR = "uM"
    NANOMOLAR = "nM"
    UG_PER_ML = "ug_per_ml"
    IU_PER_ML = "iu_per_ml"


class ParameterSource(str, Enum):
    """Where a value used by the forward model came from."""

    PROVIDED = "provided"
    IMPUTED_DEFAULT = "imputed_default"
    CURATED_PRIOR = "curated_prior"
    SEQUENCE_DERIVED = "sequence_derived"
    HEURISTIC_INFERENCE = "heuristic_inference"
    FALLBACK_GENERIC = "fallback_generic"


# --------------------------------------------------------------------------
# small value objects
# --------------------------------------------------------------------------

_BASE_MODEL_CONFIG = ConfigDict(
    extra="allow",            # forward-compatibility: never silently drop planner fields
    use_enum_values=False,
    validate_assignment=True,
    populate_by_name=True,
)


class _Model(BaseModel):
    model_config = _BASE_MODEL_CONFIG

    def to_json_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-safe dict (enums -> values, None preserved)."""
        return json.loads(self.model_dump_json(exclude_none=False))


class Quantity(_Model):
    """A number with an explicit unit.

    Cell densities and concentrations are accepted either as a bare number
    (unit assumed, warning emitted) or as this object. Treating density as a
    unit-carrying quantity is deliberate: OD600 and CFU/mL differ by ~9 orders
    of magnitude and the inoculum effect is a first-class model term.
    """

    value: float
    unit: str

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("value must be finite")
        return v


class IonicConditions(_Model):
    """Ionic composition. All concentrations in mM.

    Monovalent salt screens electrostatic peptide/membrane attraction;
    divalent cations compete directly for anionic membrane sites; chelators
    (EDTA) permeabilise the Gram-negative outer membrane.
    """

    nacl_mm: float | None = None
    kcl_mm: float | None = None
    mgcl2_mm: float | None = None
    cacl2_mm: float | None = None
    edta_mm: float | None = None

    @field_validator("nacl_mm", "kcl_mm", "mgcl2_mm", "cacl2_mm", "edta_mm")
    @classmethod
    def _non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("ionic concentrations must be >= 0 mM")
        return v


class ResistanceFactor(_Model):
    """A known resistance/susceptibility determinant of the target.

    ``effect`` is the direction on *susceptibility*: ``"resistance"`` raises the
    effective MIC, ``"sensitisation"`` lowers it. ``magnitude`` is in log10 MIC
    units when known; otherwise the backend substitutes a class default and
    records the imputation.
    """

    name: str
    effect: Literal["resistance", "sensitisation"] = "resistance"
    magnitude_log10_mic: float | None = None
    evidence_type: EvidenceType = EvidenceType.LITERATURE
    evidence_id: str | None = None
    notes: str | None = None


# --------------------------------------------------------------------------
# ExperimentSpec
# --------------------------------------------------------------------------


class Target(_Model):
    """Target organism. ``species``/``strain`` are the contract fields."""

    species: str | None = None
    strain: str | None = None

    # --- additive extensions (optional) ---
    taxon_id: int | None = None
    resistance_factors: list[ResistanceFactor] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("species", "strain")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class Conditions(_Model):
    """Experimental conditions. Field names follow the shared contract."""

    bacteriocin_concentration: float | Quantity | None = None
    target_cell_density: float | Quantity | None = None
    producer_cell_density: float | Quantity | None = None
    ph: float | None = None
    temperature_c: float | None = None
    medium: str | None = None
    ionic_conditions: IonicConditions | dict[str, Any] = Field(default_factory=IonicConditions)
    incubation_time: float | None = None
    growth_phase: GrowthPhase | str | None = None
    assay_domain: AssayDomain = AssayDomain.SIMULATED_IN_VITRO

    # --- additive extensions (optional) ---
    incubation_time_unit: Literal["h", "min", "s"] = "h"
    assay_type: AssayType | str | None = None
    aeration: Literal["aerobic", "anaerobic", "microaerophilic"] | None = None
    permeabilizer: str | None = None

    @field_validator("ph")
    @classmethod
    def _ph_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not (0.0 <= v <= 14.0):
            raise ValueError("ph must be within 0-14")
        return v

    @field_validator("temperature_c")
    @classmethod
    def _temp_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not (-30.0 <= v <= 150.0):
            raise ValueError("temperature_c must be within -30..150 C")
        return v

    @field_validator("incubation_time")
    @classmethod
    def _time_positive(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("incubation_time must be >= 0")
        return v

    @field_validator("bacteriocin_concentration", "target_cell_density", "producer_cell_density")
    @classmethod
    def _quantity_non_negative(cls, v: Any) -> Any:
        if isinstance(v, Quantity):
            if v.unit != DensityUnit.LOG10_CFU_PER_ML.value and v.value < 0:
                raise ValueError("quantity value must be >= 0 in this unit")
        elif isinstance(v, (int, float)) and v < 0:
            raise ValueError("concentration/density must be >= 0")
        return v

    @model_validator(mode="after")
    def _coerce_ionic(self) -> "Conditions":
        if isinstance(self.ionic_conditions, dict):
            object.__setattr__(
                self, "ionic_conditions", IonicConditions.model_validate(self.ionic_conditions)
            )
        return self


_AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
_AA_AMBIGUOUS = set("BJOUXZ")


class CandidateProperties(_Model):
    """Pre-computed physicochemical descriptors supplied by another agent.

    Any field left ``None`` is recomputed from the sequence. Values supplied
    here win, and are recorded with ``ParameterSource.PROVIDED`` so that the
    analysis agent can tell which descriptors are ours.
    """

    net_charge: float | None = None
    net_charge_ph: float | None = None
    hydrophobic_moment: float | None = None
    gravy: float | None = None
    molecular_weight_da: float | None = None
    isoelectric_point: float | None = None


class CandidateSpec(_Model):
    """PROPOSED ADDITIVE EXTENSION -- see CONTRACT.md section "candidate block".

    The shared ExperimentSpec carries only ``candidate_id``. A forward model
    cannot predict activity from an opaque ID, so the backend accepts the
    candidate's scientific content either inline here or through a
    ``candidate_registry`` passed to the adapter. If neither is available the
    simulation still runs, using a generic-peptide prior, and flags the result
    with greatly inflated uncertainty plus a warning.
    """

    candidate_id: str | None = None
    name: str | None = None
    sequence: str | None = None
    bacteriocin_class: BacteriocinClass | str | None = None
    properties: CandidateProperties = Field(default_factory=CandidateProperties)
    molecular_weight_da: float | None = None
    source_organism: str | None = None
    evidence_type: EvidenceType | None = None

    @field_validator("sequence")
    @classmethod
    def _validate_sequence(cls, v: str | None) -> str | None:
        if v is None:
            return None
        seq = re.sub(r"[\s\-\*]", "", v).upper()
        if not seq:
            return None
        bad = set(seq) - _AA_ALPHABET - _AA_AMBIGUOUS
        if bad:
            raise ValueError(
                f"sequence contains non-amino-acid characters: {''.join(sorted(bad))}"
            )
        if len(seq) > 1000:
            raise ValueError("sequence longer than 1000 residues is not a bacteriocin peptide")
        return seq


class ExperimentSpec(_Model):
    """A single experiment to execute. Contract shape preserved."""

    experiment_id: str
    hypothesis_id: str | None = None
    candidate_id: str | None = None
    target: Target = Field(default_factory=Target)
    conditions: Conditions = Field(default_factory=Conditions)

    # --- additive extensions (optional) ---
    candidate: CandidateSpec | None = None
    replicates: int = Field(default=1, ge=1, le=100)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("experiment_id")
    @classmethod
    def _id_present(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("experiment_id must be a non-empty persistent ID")
        return v

    @model_validator(mode="after")
    def _reconcile_candidate_id(self) -> "ExperimentSpec":
        """Keep ``candidate_id`` and ``candidate.candidate_id`` consistent."""
        if self.candidate is not None:
            if self.candidate.candidate_id and self.candidate_id:
                if self.candidate.candidate_id != self.candidate_id:
                    raise ValueError(
                        "candidate.candidate_id does not match spec.candidate_id "
                        f"({self.candidate.candidate_id!r} vs {self.candidate_id!r})"
                    )
            elif self.candidate.candidate_id and not self.candidate_id:
                object.__setattr__(self, "candidate_id", self.candidate.candidate_id)
            elif self.candidate_id and not self.candidate.candidate_id:
                self.candidate.candidate_id = self.candidate_id
        return self

    def spec_hash(self) -> str:
        """Stable hash of the scientific content of the spec.

        ``experiment_id`` and free-text notes are excluded so that two
        differently-labelled but scientifically identical experiments hash
        identically -- this is what lets the analysis agent detect repeats.
        """
        payload = self.to_json_dict()
        for key in ("experiment_id", "notes", "metadata"):
            payload.pop(key, None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------
# ExperimentResult
# --------------------------------------------------------------------------


class Measurement(_Model):
    """Predicted observables.

    The four contract fields are always populated for a successful simulation.
    Assay-specific native readouts are additive and may be ``None``.
    All values are continuous; no active/inactive labelling is performed here.
    """

    # --- contract fields ---
    predicted_inhibition_fraction: float | None = None
    predicted_survival_fraction: float | None = None
    predicted_activity: float | None = None
    uncertainty: float | None = None

    # --- additive extensions ---
    primary_metric: str | None = None
    ci95_inhibition_fraction: list[float] | None = None
    # ``uncertainty`` is the standard deviation of the inhibition *fraction*,
    # which necessarily collapses near 0 or 1. These two report the same spread
    # on scales that stay interpretable when the fraction saturates.
    sigma_logit_inhibition: float | None = None
    uncertainty_log10_reduction: float | None = None
    predicted_log10_reduction_vs_control: float | None = None
    predicted_log10_change_from_inoculum: float | None = None
    predicted_mic_um: float | None = None
    predicted_zone_diameter_mm: float | None = None
    free_peptide_concentration_um: float | None = None
    kill_rate_per_h: float | None = None
    dose_over_mic: float | None = None

    @field_validator(
        "predicted_inhibition_fraction",
        "predicted_survival_fraction",
        "predicted_activity",
    )
    @classmethod
    def _unit_interval(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not (-1e-9 <= v <= 1.0 + 1e-9):
            raise ValueError("fraction must be within [0, 1]")
        return min(1.0, max(0.0, v))


class ImportantFactor(_Model):
    """One entry of the local sensitivity ranking.

    ``sensitivity`` is the local derivative of ``logit(inhibition)`` with
    respect to this factor, in the units named by ``unit`` (per decade for
    ratio-scale factors, per a stated absolute step for pH and temperature).
    One logit unit is ~0.43 log10 of survival.
    ``source`` tells the planner whether the factor was actually specified or
    silently imputed -- an imputed high-sensitivity factor is the single most
    useful thing this backend can report back to the loop.
    """

    factor: str
    sensitivity: float
    direction: Literal["increases_activity", "decreases_activity", "negligible"]
    value: Any = None
    unit: str | None = None
    source: ParameterSource = ParameterSource.PROVIDED
    rationale: str | None = None


class ParameterProvenance(_Model):
    """How one model input was obtained."""

    parameter: str
    value: Any = None
    source: ParameterSource
    evidence_type: EvidenceType
    reference: str | None = None


class UncertaintyComponent(_Model):
    """One additive variance contribution, in logit-of-inhibition units."""

    source: str
    sigma_logit: float
    rationale: str | None = None


class Reproducibility(_Model):
    """Everything needed to reproduce this result bit-for-bit."""

    deterministic: bool = True
    spec_hash: str | None = None
    parameter_set_hash: str | None = None
    code_version: str | None = None
    random_seed: int | None = None


class ExperimentResult(_Model):
    """Result of one experiment. Contract shape preserved."""

    # --- contract fields ---
    result_id: str
    experiment_id: str
    candidate_id: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    measurement: Measurement = Field(default_factory=Measurement)
    important_factors: list[ImportantFactor] = Field(default_factory=list)
    evidence_type: EvidenceType = EvidenceType.SIMULATION
    model_version: str = ""
    warnings: list[str] = Field(default_factory=list)

    # --- additive extensions ---
    status: Literal["ok", "failed"] = "ok"
    hypothesis_id: str | None = None
    backend: str = "simulation"
    assay_domain: AssayDomain = AssayDomain.SIMULATED_IN_VITRO
    assay_type: str | None = None
    confidence: float | None = None
    validated_experimentally: bool = False
    uncertainty_components: list[UncertaintyComponent] = Field(default_factory=list)
    parameter_provenance: list[ParameterProvenance] = Field(default_factory=list)
    mechanism_trace: dict[str, Any] = Field(default_factory=dict)
    reproducibility: Reproducibility = Field(default_factory=Reproducibility)
    error: dict[str, Any] | None = None
    created_at: str | None = None

    @field_validator("evidence_type")
    @classmethod
    def _never_claim_wet_lab(cls, v: EvidenceType) -> EvidenceType:
        """Agent rule 9: this backend must never emit wet-lab provenance."""
        if v == EvidenceType.WET_LAB:
            raise ValueError(
                "the simulation backend must not label results as wet-lab-derived"
            )
        return v

    @model_validator(mode="after")
    def _never_claim_validation(self) -> "ExperimentResult":
        if self.validated_experimentally:
            raise ValueError(
                "simulation results can never be marked validated_experimentally"
            )
        return self


# --------------------------------------------------------------------------
# agent envelopes (common input/output shape)
# --------------------------------------------------------------------------


class EvidenceRecord(_Model):
    """Provenance-preserving evidence emitted into the shared research state."""

    evidence_id: str
    evidence_type: EvidenceType = EvidenceType.SIMULATION
    statement: str
    candidate_id: str | None = None
    hypothesis_id: str | None = None
    experiment_id: str | None = None
    result_id: str | None = None
    confidence: float = 0.0
    model_version: str | None = None
    validated_experimentally: bool = False
    supporting_values: dict[str, Any] = Field(default_factory=dict)
    derived_from: list[str] = Field(default_factory=list)


class AgentInput(_Model):
    """Common envelope, plus the backend's specialised fields."""

    research_objective: dict[str, Any] = Field(default_factory=dict)
    research_state: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    previous_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # --- specialised fields for this agent ---
    # Typed as a union with ``dict`` on purpose: a malformed spec must survive
    # envelope validation so that batch execution can turn it into a single
    # failed result. Typing this as ``list[ExperimentSpec]`` would make one bad
    # field reject the whole envelope and cost the loop an entire iteration.
    experiment_specs: list[ExperimentSpec | dict[str, Any]] = Field(default_factory=list)
    candidate_registry: dict[str, CandidateSpec] = Field(default_factory=dict)
    backend: str | None = None
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _accept_singular_spec(self) -> "AgentInput":
        """Tolerate a single ``experiment_spec`` key from a caller."""
        extra = self.model_extra or {}
        single = extra.get("experiment_spec")
        if single is not None and not self.experiment_specs:
            self.experiment_specs = [ExperimentSpec.model_validate(single)]
        return self


class AgentOutput(_Model):
    """Common output shape."""

    agent: str = AGENT_NAME
    decision: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainties: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    recommended_next_action: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AGENT_NAME",
    "AgentInput",
    "AgentOutput",
    "AssayDomain",
    "AssayType",
    "BacteriocinClass",
    "CandidateProperties",
    "CandidateSpec",
    "Conditions",
    "ConcentrationUnit",
    "DensityUnit",
    "EvidenceRecord",
    "EvidenceType",
    "ExperimentResult",
    "ExperimentSpec",
    "GrowthPhase",
    "ImportantFactor",
    "IonicConditions",
    "Measurement",
    "ParameterProvenance",
    "ParameterSource",
    "Quantity",
    "Reproducibility",
    "ResistanceFactor",
    "Target",
    "UncertaintyComponent",
]
