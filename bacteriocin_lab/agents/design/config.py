"""Configuration for the target-to-bacteriocin computational design pipeline."""

from __future__ import annotations

import os

MAX_DESIGN_GENERATIONS: int = int(os.getenv("MAX_DESIGN_GENERATIONS", "3"))
MAX_DESIGNS_PER_GENERATION: int = int(os.getenv("MAX_DESIGNS_PER_GENERATION", "10"))
MAX_TOTAL_DESIGNS_PER_RUN: int = int(os.getenv("MAX_TOTAL_DESIGNS_PER_RUN", "25"))
MAX_MUTATIONS_PER_DESIGN: int = int(os.getenv("MAX_MUTATIONS_PER_DESIGN", "3"))
DESIGN_RANDOM_SEED: int | None = (
    int(os.getenv("DESIGN_RANDOM_SEED")) if os.getenv("DESIGN_RANDOM_SEED") else None
)

DEFAULT_KNOWN_THRESHOLD: float = float(os.getenv("DESIGN_KNOWN_THRESHOLD", "0.80"))
DEFAULT_NATURAL_THRESHOLD: float = float(os.getenv("DESIGN_NATURAL_THRESHOLD", "0.85"))
