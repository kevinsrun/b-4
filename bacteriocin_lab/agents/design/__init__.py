"""Target-to-Bacteriocin Computational Design System.

Exposes hierarchical candidate evaluation and iterative sequence design.
"""

from __future__ import annotations

from .agent import ComputationalDesignAgent
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
from .scoring import compute_candidate_score

__all__ = [
    "DEFAULT_KNOWN_THRESHOLD",
    "DEFAULT_NATURAL_THRESHOLD",
    "MAX_DESIGNS_PER_GENERATION",
    "MAX_DESIGN_GENERATIONS",
    "MAX_MUTATIONS_PER_DESIGN",
    "MAX_TOTAL_DESIGNS_PER_RUN",
    "ComputationalDesignAgent",
    "CriticVerdict",
    "DesignCritic",
    "DesignMutation",
    "DesignRationale",
    "DesignScoreComponents",
    "DesignedCandidate",
    "DesiredProperties",
    "FutureProductionConcept",
    "RecommendationItem",
    "TargetContext",
    "TargetDesignResult",
    "compute_candidate_score",
    "design_for_target",
    "format_sequence_novelty",
    "normalize_target",
]
