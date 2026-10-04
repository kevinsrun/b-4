"""Target-to-Bacteriocin Computational Design System.

Exposes hierarchical candidate evaluation, calibration, scenario testing,
PTM-aware uncertainty, and active-learning validation.
"""

from __future__ import annotations

from .active_learning import (
    compute_acquisition_score,
    compute_epistemic_uncertainty,
    formulate_validation_experiment,
    recalibrate_and_rerank,
)
from .agent import ComputationalDesignAgent
from .calibration import (
    CURATED_REFERENCE_OBSERVATIONS,
    ActivityCalibrator,
    ActivityObservation,
    CalibratedPrediction,
)
from .config import (
    DEFAULT_KNOWN_THRESHOLD,
    DEFAULT_NATURAL_THRESHOLD,
    MAX_DESIGN_GENERATIONS,
    MAX_DESIGNS_PER_GENERATION,
    MAX_MUTATIONS_PER_DESIGN,
    MAX_TOTAL_DESIGNS_PER_RUN,
)
from .critic import CriticVerdict, DesignCritic
from .models import (
    DesignedCandidate,
    DesignMutation,
    DesignRationale,
    DesignScoreComponents,
    DesiredProperties,
    FutureProductionConcept,
    RecommendationItem,
    TargetContext,
    TargetDesignResult,
)
from .pipeline import design_for_target, format_sequence_novelty, normalize_target
from .ptm import (
    ModificationSite,
    PTMProfile,
    analyze_ptm_profile,
)
from .scenarios import (
    ScenarioProfile,
    compute_gravy,
    count_protease_cleavage_sites,
    evaluate_environmental_scenarios,
)
from .scoring import compute_candidate_score

__all__ = [
    "CURATED_REFERENCE_OBSERVATIONS",
    "DEFAULT_KNOWN_THRESHOLD",
    "DEFAULT_NATURAL_THRESHOLD",
    "MAX_DESIGNS_PER_GENERATION",
    "MAX_DESIGN_GENERATIONS",
    "MAX_MUTATIONS_PER_DESIGN",
    "MAX_TOTAL_DESIGNS_PER_RUN",
    "ActivityCalibrator",
    "ActivityObservation",
    "CalibratedPrediction",
    "ComputationalDesignAgent",
    "CriticVerdict",
    "DesignCritic",
    "DesignMutation",
    "DesignRationale",
    "DesignScoreComponents",
    "DesignedCandidate",
    "DesiredProperties",
    "FutureProductionConcept",
    "ModificationSite",
    "PTMProfile",
    "RecommendationItem",
    "ScenarioProfile",
    "TargetContext",
    "TargetDesignResult",
    "analyze_ptm_profile",
    "compute_acquisition_score",
    "compute_candidate_score",
    "compute_epistemic_uncertainty",
    "compute_gravy",
    "count_protease_cleavage_sites",
    "design_for_target",
    "evaluate_environmental_scenarios",
    "format_sequence_novelty",
    "formulate_validation_experiment",
    "normalize_target",
    "recalibrate_and_rerank",
]
