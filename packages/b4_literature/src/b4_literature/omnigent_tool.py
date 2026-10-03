from __future__ import annotations

from typing import Any

from .agent import LiteratureEvidenceAgent


def collect_literature_evidence(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a B⁴ literature request and return JSON-compatible evidence output."""
    return LiteratureEvidenceAgent().run(request).model_dump(mode="json")
