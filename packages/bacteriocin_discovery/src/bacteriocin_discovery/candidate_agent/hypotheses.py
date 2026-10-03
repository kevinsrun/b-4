"""Testable hypothesis generation.

A hypothesis is only useful to the loop if a simulation result can contradict
it. Every hypothesis produced here therefore carries:

* a quantitative ``predicted_inhibition_fraction``,
* the ``key_conditions`` the prediction is conditional on, and
* an explicit ``falsified_if`` clause.

The predicted fraction is a *prior*, not a simulation output. It is derived from
the same heuristics that drive the promise score and is tagged
``inferred-hypothesis`` so no downstream agent can mistake it for a measurement.
"""

from __future__ import annotations

from typing import Any

from ..ids import hypothesis_id
from .schema import CandidateProposal, CandidateTarget, DesiredBehavior, TestableHypothesis

#: Inhibition band treated as "substantial" when phrasing a falsification clause.
_SUBSTANTIAL_INHIBITION = 0.5

#: How far a result must fall from the prediction before the hypothesis is refuted.
_FALSIFICATION_MARGIN = 0.25


def _condition_summary(desired: DesiredBehavior) -> dict[str, Any]:
    """The conditions a hypothesis is conditional on, omitting unset fields."""
    conditions: dict[str, Any] = {"assay_domain": desired.assay_domain}
    if desired.ph_range is not None:
        conditions["ph_range"] = list(desired.ph_range)
    if desired.temperature_c is not None:
        conditions["temperature_c"] = desired.temperature_c
    if desired.target_cell_density is not None:
        conditions["target_cell_density"] = desired.target_cell_density
        conditions["target_cell_density_unit"] = desired.target_cell_density_unit
    if desired.medium is not None:
        conditions["medium"] = desired.medium
    if desired.incubation_time_h is not None:
        conditions["incubation_time_h"] = desired.incubation_time_h
    return conditions


def _describe_conditions(conditions: dict[str, Any]) -> str:
    """Render conditions into a readable clause for the hypothesis statement."""
    parts: list[str] = []
    if "ph_range" in conditions:
        low, high = conditions["ph_range"]
        parts.append(f"pH {low}-{high}")
    if "temperature_c" in conditions:
        parts.append(f"{conditions['temperature_c']} C")
    if "target_cell_density" in conditions:
        parts.append(
            f"{conditions['target_cell_density']:.0e} "
            f"{conditions.get('target_cell_density_unit') or 'CFU/mL'}"
        )
    if "medium" in conditions:
        parts.append(str(conditions["medium"]))
    return ", ".join(parts) if parts else "the specified conditions"


def build_hypothesis(
    candidate: CandidateProposal,
    target: CandidateTarget,
    desired: DesiredBehavior,
) -> TestableHypothesis:
    """Build the primary testable hypothesis for one candidate against one target.

    The predicted inhibition fraction is anchored on the candidate's promise
    score, which already folds in reported spectrum, physicochemical
    plausibility, resistance overlap and Gram-type accessibility.
    """
    promise = candidate.score.promise if candidate.score else 0.45
    conditions = _condition_summary(desired)
    condition_text = _describe_conditions(conditions)

    # Shrink towards 0.5 so a heuristic prior never masquerades as a confident
    # point prediction. The simulation agent is what sharpens this.
    predicted = round(0.5 + 0.7 * (promise - 0.5), 3)
    predicted = max(0.0, min(1.0, predicted))

    identity = candidate.name or candidate.candidate_id
    strain_text = f" {target.strain}" if target.strain else ""

    if predicted >= _SUBSTANTIAL_INHIBITION:
        direction = "inhibition"
        statement = (
            f"{identity} will produce substantial inhibition of {target.organism}{strain_text} "
            f"at {condition_text}, with an inhibition fraction near {predicted:.2f}."
        )
        falsified_if = (
            f"The simulated inhibition fraction falls below "
            f"{max(0.0, predicted - _FALSIFICATION_MARGIN):.2f} across the planned "
            "concentration range."
        )
    else:
        direction = "conditional"
        statement = (
            f"{identity} will show only limited inhibition of {target.organism}{strain_text} "
            f"at {condition_text}, with an inhibition fraction near {predicted:.2f}; "
            "activity is expected to be strongly dose- and density-dependent."
        )
        falsified_if = (
            f"The simulated inhibition fraction exceeds "
            f"{min(1.0, predicted + _FALSIFICATION_MARGIN):.2f} at or below the "
            "highest planned concentration."
        )

    hid = hypothesis_id(
        candidate=candidate.candidate_id,
        target_species=target.organism,
        prediction=statement,
    )

    # Confidence in the hypothesis is reduced by what is unknown about the
    # candidate, so a confident-sounding statement about an uncharacterised
    # peptide does not carry a confident number.
    uncertainty = candidate.score.uncertainty if candidate.score else 0.5
    confidence = round(max(0.05, min(0.9, (0.4 + 0.5 * promise) * (1.0 - 0.5 * uncertainty))), 3)

    return TestableHypothesis(
        hypothesis_id=hid,
        statement=statement,
        candidate_id=candidate.candidate_id,
        target_species=target.organism,
        predicted_direction=direction,
        predicted_inhibition_fraction=predicted,
        falsified_if=falsified_if,
        key_conditions=conditions,
        evidence_ids=list(candidate.evidence_ids),
        confidence=confidence,
    )


def build_mechanism_hypothesis(
    candidate: CandidateProposal,
    target: CandidateTarget,
    desired: DesiredBehavior,
) -> TestableHypothesis | None:
    """A secondary hypothesis about *why* the candidate acts, when a receptor is known.

    Mechanism hypotheses are what make a result transferable: knowing that
    activity tracks Man-PTS expression predicts behaviour for every other
    Man-PTS-dependent candidate, whereas a bare potency number does not.
    """
    receptor = candidate.features.receptor
    if not receptor:
        return None

    identity = candidate.name or candidate.candidate_id
    statement = (
        f"The activity of {identity} against {target.organism} is dependent on "
        f"{receptor}; inhibition will scale with the availability of that target molecule "
        "rather than with bulk peptide concentration alone."
    )
    falsified_if = (
        f"Inhibition is unchanged when {receptor} availability is varied in simulation, "
        "or inhibition tracks concentration with no saturation consistent with a "
        "receptor-limited mechanism."
    )

    hid = hypothesis_id(
        candidate=candidate.candidate_id,
        target_species=target.organism,
        prediction=statement,
    )
    return TestableHypothesis(
        hypothesis_id=hid,
        statement=statement,
        candidate_id=candidate.candidate_id,
        target_species=target.organism,
        predicted_direction="conditional",
        predicted_inhibition_fraction=None,
        falsified_if=falsified_if,
        key_conditions={**_condition_summary(desired), "mechanism_probe": receptor},
        evidence_ids=list(candidate.evidence_ids),
        confidence=0.4,
    )


def expected_strengths(
    candidate: CandidateProposal,
    target: CandidateTarget,
) -> list[str]:
    """Concrete reasons this candidate could succeed."""
    strengths: list[str] = []
    features = candidate.features
    computed = features.computed

    if any(t.strip().lower() == target.organism.strip().lower() for t in features.known_targets):
        strengths.append(f"Reported activity against {target.organism} in the source record.")
    if features.receptor:
        strengths.append(f"Known molecular target ({features.receptor}) gives a testable mechanism.")
    if features.known_stability.get("thermostable") is True:
        strengths.append("Reported thermostable, so assay temperature is unlikely to limit it.")

    stable_range = features.known_stability.get("ph_stable_range")
    if isinstance(stable_range, (list, tuple)) and len(stable_range) == 2:
        strengths.append(f"Documented pH stability over {stable_range[0]}-{stable_range[1]}.")

    if computed is not None:
        if computed.net_charge >= 2:
            strengths.append(
                f"Net charge {computed.net_charge:+.1f} at pH {computed.charge_ph} favours "
                "electrostatic association with the anionic bacterial envelope."
            )
        if 0.35 <= computed.hydrophobic_fraction <= 0.6:
            strengths.append(
                f"Hydrophobic fraction {computed.hydrophobic_fraction:.0%} is in the range "
                "typical of membrane-active peptides."
            )
        if computed.max_disulfide_bonds >= 1:
            strengths.append(
                f"{computed.cysteine_count} cysteines allow up to "
                f"{computed.max_disulfide_bonds} disulfide bond(s), which tend to rigidify "
                "and stabilise the fold."
            )
    return strengths


def expected_failure_modes(
    candidate: CandidateProposal,
    target: CandidateTarget,
    desired: DesiredBehavior,
) -> list[str]:
    """Concrete ways this candidate could fail.

    Stated up front so a negative result is interpretable rather than merely
    disappointing, and so the experiment planner knows which conditions to vary.
    """
    modes: list[str] = []
    features = candidate.features
    computed = features.computed

    if any(
        t.strip().lower() == target.organism.strip().lower() for t in features.known_non_targets
    ):
        modes.append(f"Source record reports no activity against {target.organism}.")
    if not features.known_targets:
        modes.append("No reported activity spectrum, so target range is unconstrained by evidence.")

    for concern in features.resistance_concerns:
        modes.append(f"Resistance route: {concern}.")
    for sensitivity in features.environmental_sensitivity:
        modes.append(f"Environmental limitation: {sensitivity}.")

    if target.gram == "negative" and not features.receptor:
        modes.append(
            "Gram-negative target: the outer membrane may block access entirely, and no "
            "uptake route is recorded."
        )

    if desired.ph_range is not None:
        stable_range = features.known_stability.get("ph_stable_range")
        if isinstance(stable_range, (list, tuple)) and len(stable_range) == 2:
            if float(stable_range[1]) < desired.ph_range[1]:
                modes.append(
                    f"Requested pH reaches {desired.ph_range[1]} but documented stability "
                    f"stops at {stable_range[1]}; loss of activity at the top of the range "
                    "is plausible."
                )

    if desired.target_cell_density is not None and desired.target_cell_density >= 1e8:
        modes.append(
            f"At {desired.target_cell_density:.0e} "
            f"{desired.target_cell_density_unit} the peptide-to-cell ratio may be too low "
            "for inhibition even where the peptide is intrinsically active."
        )

    if computed is not None and computed.caveats:
        modes.extend(computed.caveats)

    if candidate.origin in ("generated", "modified"):
        modes.append(
            "Computationally proposed sequence: folding, expression and post-translational "
            "modification are all unverified, and an unmodified variant of a modified "
            "bacteriocin class may simply be inactive."
        )
    if not candidate.sequence_verified and candidate.sequence:
        modes.append(
            "Sequence has not been verified against a primary database; a transcription "
            "error would invalidate every computed feature."
        )
    return modes


__all__ = [
    "build_hypothesis",
    "build_mechanism_hypothesis",
    "expected_failure_modes",
    "expected_strengths",
]
