"""The public discovery-response formatter.

This module is the only place that turns orchestration state into product
language.  It intentionally drops identifiers, traces, routes, timestamps,
and implementation metadata.  Those remain available through the existing
developer API for diagnosis; they are not part of a scientific answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_KNOWN_TARGETS = {
    "listeria monocytogenes": ("Listeria monocytogenes", "positive"),
    "staphylococcus aureus": ("Staphylococcus aureus", "positive"),
    "clostridium difficile": ("Clostridium difficile", "positive"),
    "escherichia coli": ("Escherichia coli", "negative"),
}


def infer_target(prompt: str, target_organism: str | None = None) -> tuple[str, str]:
    """Resolve a supported target without guessing its Gram classification.

    A caller may supply the organism separately, but the public prompt-only
    path recognises the organisms offered in the product UI.  Unknown organisms
    must be supplied with explicit context instead of receiving a fabricated
    Gram classification.
    """
    haystack = (target_organism or prompt).casefold()
    for needle, target in _KNOWN_TARGETS.items():
        if needle in haystack:
            return target
    raise ValueError(
        "Choose a supported target organism or include one of the examples: "
        "Listeria monocytogenes, Staphylococcus aureus, Clostridium difficile, or Escherichia coli."
    )


def _confidence(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "Low"
    if score >= 0.7:
        return "High"
    if score >= 0.4:
        return "Moderate"
    return "Low"


def _clean(text: Any) -> str:
    """Remove record identifiers and schema language from a visible sentence."""
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(
        r"\b(?:run|cand|hyp|exp|res|find|rev|ev)[_-][0-9a-f]{6,}\b", "", text, flags=re.I
    )
    replacements = {
        "simulation-derived": "computational simulation",
        "literature-derived": "published evidence",
        "database-derived": "database evidence",
        "cfu_per_ml": "CFU/mL",
        "target_cell_density": "target cell density",
        "assay_type": "assay type",
        "growth_phase": "growth phase",
        "ionic_strength_mm": "ionic strength",
        "producer_cell_density": "producer cell density",
        "sigma_logit": "uncertainty estimate",
    }
    for raw, visible in replacements.items():
        cleaned = re.sub(rf"\b{re.escape(raw)}\b", visible, cleaned, flags=re.I)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.\t")
    return cleaned


def _condition_view(conditions: Mapping[str, Any]) -> dict[str, Any]:
    density = conditions.get("target_cell_density")
    if isinstance(density, Mapping):
        density = density.get("value")
    return {
        "pH": conditions.get("ph"),
        "temperature_c": conditions.get("temperature_c"),
        "target_cell_density": density,
        "incubation_hours": conditions.get("incubation_time"),
    }


def _uncertainty_text(item: Any) -> str:
    if isinstance(item, Mapping):
        kind = item.get("kind")
        friendly = {
            "model-limitation": (
                "This is a computational prediction and requires experimental validation."
            ),
            "aleatoric": "The predicted effect has substantial uncertainty.",
            "data-gap": (
                "Some assay conditions were supplied by defaults, so this prediction is "
                "provisional."
            ),
            "epistemic": (
                "Target-specific activity estimates are based on incomplete prior evidence."
            ),
        }
        return friendly.get(kind, _clean(item.get("description")))
    return _clean(item)


def build_discovery_response(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build one bounded product response from a completed workflow result.

    This is a presentation function, not a scoring function.  Candidate
    ranking, experiment selection, simulation, review, and state updates have
    already happened when it is called.
    """
    state = result.get("final_state") or {}
    objective = state.get("objective") or result.get("objective") or {}
    target = objective.get("target") or {}
    candidates = state.get("candidates") or []
    experiments = state.get("experiments") or []
    results = state.get("results") or []
    reviews = state.get("reviews") or []
    findings = state.get("findings") or []

    candidate = candidates[0] if candidates else {}
    first_result = results[0] if results else {}
    first_measurement = first_result.get("measurement") or {}
    first_conditions = first_result.get("conditions") or {}
    first_experiment = experiments[0] if experiments else {}
    followup = experiments[1] if len(experiments) > 1 else None
    candidate_name = candidate.get("name") or "No sufficiently supported candidate"
    confidence = _confidence(candidate.get("confidence"))

    why = []
    known_targets = (candidate.get("features") or {}).get("known_targets") or []
    if known_targets:
        why.append(
            f"Its recorded target spectrum includes {', '.join(map(str, known_targets[:2]))}."
        )
    if candidate.get("sequence"):
        why.append(
            "Its sequence was carried into the computational experiment rather than treated as "
            "an opaque label."
        )
    if candidate.get("validation_status") == "unvalidated":
        why.append(
            "It is a ranked computational candidate, not an experimentally validated "
            "recommendation."
        )

    inhibition = first_measurement.get("predicted_inhibition_fraction")
    effect_description = "A computational experiment was completed under the selected conditions."
    if isinstance(inhibition, (int, float)):
        effect_description = (
            f"The initial computational simulation estimated {inhibition:.0%} inhibition at pH "
            f"{first_conditions.get('ph', 'the selected condition')}."
        )

    critic = reviews[0] if reviews else {}
    critic_status = str(critic.get("status") or "")
    critic_verdict = (
        "More evidence needed"
        if critic_status == "needs_more_evidence"
        else "Scientific review completed"
    )
    next_summary = "No additional computational experiment was selected."
    adaptivity = "The workflow completed its planned evaluation."
    if followup:
        before = (first_experiment.get("conditions") or {}).get("ph")
        after = (followup.get("conditions") or {}).get("ph")
        next_summary = f"Compare the candidate at pH {after} under otherwise matched conditions."
        adaptivity = (
            "The scientific review requested more discriminating evidence, so the next "
            f"experiment changed pH from {before} to {after}."
        )

    uncertainty = [_uncertainty_text(item) for item in state.get("uncertainties") or []]
    uncertainty = list(dict.fromkeys(item for item in uncertainty if item))[:4]
    if not uncertainty:
        uncertainty = ["This is a computational prediction and requires experimental validation."]

    evidence = []
    if known_targets:
        evidence.append(
            {
                "label": "Target compatibility",
                "summary": (
                    "Recorded candidate spectrum includes "
                    f"{', '.join(map(str, known_targets[:2]))}."
                ),
            }
        )
    if first_result:
        evidence.append(
            {
                "label": "Computational simulation",
                "summary": (
                    "The candidate sequence was evaluated in a mechanistic simulation under "
                    "the displayed conditions."
                ),
            }
        )
    if findings:
        evidence.append(
            {
                "label": "Scientific review",
                "summary": (
                    "The current simulation does not yet establish a sufficiently supported "
                    "condition-response relationship."
                ),
            }
        )

    return {
        "target": {
            "organism": target.get("species") or target.get("organism") or "Unspecified target"
        },
        "recommendation": {
            "name": candidate_name,
            "tier": "Known bacteriocin" if candidate else "No recommendation",
            "confidence": confidence,
            "summary": (
                f"{candidate_name} is the highest-ranked candidate from this computational "
                "screen for "
                f"{target.get('species') or 'the selected target'}."
                if candidate
                else "No sufficiently supported candidate was identified in this screen."
            ),
        },
        "predicted_effect": {
            "description": effect_description,
            "conditions": _condition_view(first_conditions),
            "evidence_label": "Computational simulation",
        },
        "why_this_candidate": why,
        "evidence": evidence,
        "uncertainty": uncertainty,
        "scientific_review": {
            "verdict": critic_verdict,
            "summary": (
                "The first computational result did not yet provide enough evidence for a "
                "reliable conclusion."
            )
            if critic_status == "needs_more_evidence"
            else adaptivity,
        },
        "adaptive_experiment": {
            "initial_condition": _condition_view(first_experiment.get("conditions") or {}),
            "next_condition": _condition_view(followup.get("conditions") or {})
            if followup
            else None,
            "explanation": adaptivity,
        },
        "next_experiment": {"summary": next_summary, "reason": adaptivity},
        "status": "computational_prediction",
    }
