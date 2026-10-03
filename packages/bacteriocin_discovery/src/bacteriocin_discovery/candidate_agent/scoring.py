"""Multi-objective scoring and diversity-aware ranking.

The brief is explicit that this agent must not optimise only for predicted
antimicrobial strength. A greedy "rank by predicted potency" agent produces a
degenerate loop: it proposes the same family of well-characterised peptides
every iteration, each experiment confirms what was already believed, and the
research state stops moving.

So the score has six components, each in ``[0, 1]``:

``promise``
    Predicted biological usefulness against this target. Heuristic, and
    explicitly not a potency prediction -- that is the simulation agent's job.
``novelty``
    Dissimilarity to candidates already tested, from ``previous_results``.
``uncertainty``
    How little is known about this candidate against this target. Carried as its
    own component so a caller can decide whether to seek or avoid it.
``information_gain``
    Expected reduction in uncertainty if this candidate were tested. Peaks where
    the outcome is genuinely in doubt, not where activity is most likely.
``hypothesis_discrimination``
    How well testing this candidate separates competing open hypotheses.
``condition_fit``
    Agreement between known stability and the requested assay conditions.

Ranking then runs a greedy diversity-aware selection rather than a plain sort,
because the value of a *set* of experiments is not the sum of its members'
values -- ten near-identical class IIa peptides answer close to one question.

All functions here are pure and deterministic.
"""

from __future__ import annotations

import math
from typing import Any

from .features import sequence_similarity
from .schema import (
    CandidateConstraints,
    CandidateProposal,
    CandidateTarget,
    CompetingHypothesis,
    DesiredBehavior,
    ScoreBreakdown,
)

# Heuristic reference values. These are coarse priors drawn from the general
# behaviour of cationic membrane-active peptides, NOT fitted parameters. They
# exist to order candidates sensibly before any simulation has been run, and
# should be replaced by a learned model once the loop has accumulated results.
_IDEAL_NET_CHARGE = 4.0
_CHARGE_TOLERANCE = 5.0
_IDEAL_GRAVY = 0.0
_GRAVY_TOLERANCE = 2.5
_TYPICAL_LENGTH_RANGE = (20, 60)

#: Outer-membrane transporters that Gram-negative-active bacteriocins hijack for
#: uptake. Their presence in a candidate's receptor record implies the candidate
#: depends on machinery only Gram-negative cells have.
_GRAM_NEGATIVE_UPTAKE_MARKERS = ("fhua", "tonb", "btub", "cir", "fiu", "sbma", "ompf")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _gaussian_fit(value: float, ideal: float, tolerance: float) -> float:
    """Smooth 0-1 preference peaking at ``ideal``, falling off over ``tolerance``."""
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    return math.exp(-(((value - ideal) / tolerance) ** 2))


def _species_match(a: str, b: str) -> bool:
    """Loose species comparison: exact, or genus-level when one side is a genus.

    Deliberately conservative. ``"Listeria monocytogenes"`` matches
    ``"Listeria monocytogenes"`` and ``"Listeria spp."``, but two different
    species in the same genus do not match, because bacteriocin spectra are
    frequently species- and even strain-specific.
    """
    a_clean, b_clean = a.strip().lower(), b.strip().lower()
    if not a_clean or not b_clean:
        return False
    if a_clean == b_clean:
        return True

    a_parts, b_parts = a_clean.split(), b_clean.split()
    a_genus, b_genus = a_parts[0], b_parts[0]
    if a_genus != b_genus:
        return False
    # Same genus: match only if either side is a genus-level wildcard.
    wildcards = {"spp.", "spp", "sp.", "sp", "species"}
    a_wild = len(a_parts) == 1 or a_parts[-1] in wildcards
    b_wild = len(b_parts) == 1 or b_parts[-1] in wildcards
    return a_wild or b_wild


# ---------------------------------------------------------------------------
# Component scores
# ---------------------------------------------------------------------------


def score_promise(
    candidate: CandidateProposal,
    target: CandidateTarget,
    desired: DesiredBehavior,
) -> tuple[float, list[str]]:
    """Predicted usefulness against this target. Returns (score, rationale).

    Evidence of reported activity against the target dominates; physicochemical
    heuristics only break ties among candidates with no reported spectrum.
    """
    rationale: list[str] = []
    features = candidate.features

    # Reported spectrum is the strongest signal available pre-simulation.
    reported_hit = any(_species_match(t, target.organism) for t in features.known_targets)
    reported_miss = any(_species_match(t, target.organism) for t in features.known_non_targets)

    if reported_hit and not reported_miss:
        base = 0.85
        rationale.append(f"Reported active against {target.organism} in the source record.")
    elif reported_miss and not reported_hit:
        base = 0.12
        rationale.append(
            f"Reported INACTIVE against {target.organism}; retained only for contrast value."
        )
    elif reported_hit and reported_miss:
        base = 0.5
        rationale.append(
            f"Source record reports conflicting activity against {target.organism}; "
            "strain-dependent effects are likely."
        )
    else:
        base = 0.45
        rationale.append(f"No reported activity data against {target.organism}.")

    # Physicochemical plausibility, applied as a modest adjustment.
    computed = features.computed
    if computed is not None:
        charge_fit = _gaussian_fit(computed.net_charge, _IDEAL_NET_CHARGE, _CHARGE_TOLERANCE)
        gravy_fit = _gaussian_fit(computed.gravy, _IDEAL_GRAVY, _GRAVY_TOLERANCE)
        lo, hi = _TYPICAL_LENGTH_RANGE
        length_fit = 1.0 if lo <= computed.sequence_length <= hi else 0.6

        physchem = (charge_fit + gravy_fit + length_fit) / 3.0
        base = _clamp(0.75 * base + 0.25 * physchem)
        rationale.append(
            f"Physicochemical plausibility {physchem:.2f} "
            f"(net charge {computed.net_charge:+.1f} at pH {computed.charge_ph}, "
            f"GRAVY {computed.gravy:+.2f}, {computed.sequence_length} residues)."
        )

    # Known resistance in the target is a direct, mechanistic penalty.
    blocked = _resistance_overlap(candidate, target, desired)
    if blocked:
        base *= 0.55
        rationale.append(
            "Penalised: target carries resistance factor(s) relevant to this candidate "
            f"({', '.join(sorted(blocked))})."
        )

    # Envelope accessibility cuts both ways, so both directions are penalised.
    receptor = (features.receptor or "").lower()
    needs_outer_membrane = any(marker in receptor for marker in _GRAM_NEGATIVE_UPTAKE_MARKERS)

    if target.gram == "negative" and not needs_outer_membrane:
        # Most class II bacteriocins cannot cross the outer membrane without a
        # dedicated uptake route.
        base *= 0.6
        rationale.append(
            "Penalised: Gram-negative target and no known outer-membrane uptake route "
            "recorded for this candidate."
        )
    elif target.gram == "positive" and needs_outer_membrane:
        # The reverse mismatch, and a harsher one: a Gram-positive cell has no
        # outer membrane, so an uptake route that depends on an outer-membrane
        # transporter does not merely work less well -- the machinery is absent.
        base *= 0.4
        rationale.append(
            f"Penalised: this candidate's recorded uptake route ({features.receptor}) is an "
            "outer-membrane transporter, which a Gram-positive target does not possess."
        )

    return _clamp(base), rationale


def _resistance_overlap(
    candidate: CandidateProposal,
    target: CandidateTarget,
    desired: DesiredBehavior,
) -> set[str]:
    """Resistance factors in the target (or to be avoided) that hit this candidate."""
    concerns = {c.strip().lower() for c in candidate.features.resistance_concerns if c.strip()}
    receptor = (candidate.features.receptor or "").strip().lower()

    declared = {f.strip().lower() for f in target.known_resistance_factors if f.strip()}
    declared |= {f.strip().lower() for f in desired.avoid_resistance_mechanisms if f.strip()}

    hits: set[str] = set()
    for factor in declared:
        if not factor:
            continue
        if any(factor in concern or concern in factor for concern in concerns):
            hits.add(factor)
        elif receptor and (factor in receptor or receptor in factor):
            hits.add(factor)
    return hits


def score_novelty(
    candidate: CandidateProposal,
    tested_sequences: list[str],
    tested_ids: set[str],
) -> tuple[float, list[str]]:
    """Dissimilarity to what has already been tested.

    ``1 - max_similarity`` over tested sequences. A candidate already tested
    scores 0: re-running it yields no new information unless conditions change,
    which is the experiment planner's lever, not this agent's.
    """
    if candidate.candidate_id in tested_ids:
        return 0.0, ["Already tested in a previous iteration; no novelty as a candidate."]

    if not candidate.sequence or not tested_sequences:
        if not tested_sequences:
            return 1.0, ["Nothing tested yet; candidate is fully novel to this campaign."]
        return 0.6, ["No sequence available, so novelty could not be measured; assumed moderate."]

    nearest = max(sequence_similarity(candidate.sequence, s) for s in tested_sequences)
    rationale = [f"Closest tested candidate has {nearest:.0%} 3-mer similarity."]
    if nearest > 0.6:
        rationale.append("Highly similar to an already-tested peptide; limited new information.")
    return _clamp(1.0 - nearest), rationale


def score_uncertainty(candidate: CandidateProposal) -> tuple[float, list[str]]:
    """Epistemic uncertainty about this candidate's behaviour.

    Driven by how much the record actually pins down. An unverified sequence, a
    missing class, no reported spectrum and no stability data all raise it.
    """
    rationale: list[str] = []
    features = candidate.features
    gaps = 0.0

    checks = (
        (not candidate.sequence, 0.25, "no sequence available"),
        (not candidate.sequence_verified, 0.10, "sequence not verified against a primary database"),
        (features.bacteriocin_class in (None, "", "unknown"), 0.15, "bacteriocin class unknown"),
        (not features.known_targets, 0.20, "no reported activity spectrum"),
        (not features.known_stability, 0.15, "no stability data"),
        (features.receptor is None, 0.15, "receptor/mechanism unknown"),
    )
    for is_gap, weight, label in checks:
        if is_gap:
            gaps += weight
            rationale.append(f"Unknown: {label}.")

    if candidate.origin in ("generated", "modified"):
        gaps += 0.25
        rationale.append(
            f"Origin '{candidate.origin}': computationally proposed, never characterised."
        )

    if not rationale:
        rationale.append("Candidate is comparatively well characterised.")
    return _clamp(gaps), rationale


def score_information_gain(
    promise: float,
    uncertainty: float,
    novelty: float,
) -> tuple[float, list[str]]:
    """Expected information from testing this candidate.

    Treats ``promise`` as a rough probability of a positive outcome and uses the
    normalised binary-entropy term ``4p(1-p)``, which peaks at ``p = 0.5``. This
    is the part that stops the agent degenerating into confirmation: a candidate
    that is near-certainly active teaches almost nothing, and neither does one
    that is near-certainly inactive. The most informative experiment is the one
    whose result is genuinely in doubt.

    Entropy is then modulated by how novel the candidate is and how much is
    unknown about it -- an uncertain outcome on ground already covered is worth
    less than the same uncertainty on new ground.
    """
    outcome_entropy = 4.0 * promise * (1.0 - promise)
    gain = outcome_entropy * (0.45 + 0.35 * novelty + 0.20 * uncertainty)

    rationale = [
        f"Outcome entropy {outcome_entropy:.2f} "
        f"(predicted-success proxy {promise:.2f}; maximal near 0.5)."
    ]
    if outcome_entropy < 0.3:
        rationale.append(
            "Outcome is fairly predictable either way, so the experiment is largely confirmatory."
        )
    return _clamp(gain), rationale


def score_hypothesis_discrimination(
    candidate: CandidateProposal,
    hypotheses: list[CompetingHypothesis],
) -> tuple[float, list[str]]:
    """How well this candidate separates competing open hypotheses.

    For each open hypothesis naming a ``discriminating_feature`` and a
    ``favourable_range``, check whether this candidate's feature value sits
    inside it. A candidate that satisfies some hypotheses and violates others
    is maximally discriminating: whichever way the experiment goes, some
    hypotheses lose. A candidate that all hypotheses agree on cannot separate
    them, no matter how promising it looks.
    """
    open_hypotheses = [h for h in hypotheses if h.status == "open"]
    if not open_hypotheses:
        return 0.0, ["No open competing hypotheses to discriminate between."]

    testable = 0
    inside = 0
    details: list[str] = []

    for hypothesis in open_hypotheses:
        value = _feature_value(candidate, hypothesis.discriminating_feature)
        if value is None or hypothesis.favourable_range is None:
            continue
        testable += 1
        low, high = hypothesis.favourable_range
        if low <= value <= high:
            inside += 1
            details.append(
                f"Satisfies {hypothesis.hypothesis_id} "
                f"({hypothesis.discriminating_feature}={value:.2f} in [{low}, {high}])."
            )
        else:
            details.append(
                f"Violates {hypothesis.hypothesis_id} "
                f"({hypothesis.discriminating_feature}={value:.2f} outside [{low}, {high}])."
            )

    if testable == 0:
        return (
            0.0,
            [
                f"{len(open_hypotheses)} open hypothesis/es, but none specify a "
                "discriminating_feature this candidate exposes."
            ],
        )

    # Peaks at a 50/50 split across hypotheses -- the maximally decisive case.
    fraction = inside / testable
    score = 4.0 * fraction * (1.0 - fraction) if testable > 1 else float(inside) / testable
    details.append(
        f"Splits {inside}/{testable} testable open hypotheses "
        f"(discrimination is highest on an even split)."
    )
    return _clamp(score), details


def _feature_value(candidate: CandidateProposal, feature: str | None) -> float | None:
    """Look up a named numeric feature on a candidate, or None if unavailable."""
    if not feature:
        return None
    computed = candidate.features.computed
    if computed is not None:
        value = getattr(computed, feature, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    # Allow hypotheses to key on curated numeric stability fields too.
    stability_value = candidate.features.known_stability.get(feature)
    if isinstance(stability_value, (int, float)) and not isinstance(stability_value, bool):
        return float(stability_value)
    return None


def score_condition_fit(
    candidate: CandidateProposal,
    desired: DesiredBehavior,
) -> tuple[float, list[str]]:
    """Agreement between known stability and the requested assay conditions.

    Starts optimistic and penalises concrete, documented mismatches. Absent
    data is treated as unknown rather than bad -- that absence is already
    priced into ``uncertainty``.
    """
    rationale: list[str] = []
    score = 0.75
    stability = candidate.features.known_stability

    stable_range = stability.get("ph_stable_range")
    if desired.ph_range and isinstance(stable_range, (list, tuple)) and len(stable_range) == 2:
        want_lo, want_hi = desired.ph_range
        have_lo, have_hi = float(stable_range[0]), float(stable_range[1])
        overlap = max(0.0, min(want_hi, have_hi) - max(want_lo, have_lo))
        want_span = max(want_hi - want_lo, 1e-9)
        coverage = _clamp(overlap / want_span)
        score = 0.35 + 0.65 * coverage
        if coverage >= 0.99:
            rationale.append(
                f"Stable across the full requested pH range {want_lo}-{want_hi}."
            )
        elif coverage > 0:
            rationale.append(
                f"Stability range {have_lo}-{have_hi} covers only {coverage:.0%} of the "
                f"requested pH range {want_lo}-{want_hi}."
            )
        else:
            rationale.append(
                f"Documented stability range {have_lo}-{have_hi} does not overlap the "
                f"requested pH range {want_lo}-{want_hi}."
            )
    elif desired.ph_range:
        rationale.append("No pH stability data; condition fit is a prior, not a measurement.")

    if desired.temperature_c is not None:
        thermostable = stability.get("thermostable")
        if desired.temperature_c > 45 and thermostable is False:
            score *= 0.6
            rationale.append(
                f"Penalised: requested {desired.temperature_c} C and the record reports "
                "the peptide is not thermostable."
            )
        elif desired.temperature_c > 45 and thermostable is True:
            rationale.append(f"Reported thermostable; {desired.temperature_c} C is tolerable.")

    # Dense cultures need more peptide per cell; sequestering peptides suffer most.
    if desired.target_cell_density is not None and desired.target_cell_density >= 1e8:
        sensitivities = " ".join(candidate.features.environmental_sensitivity).lower()
        if any(word in sensitivities for word in ("adsorb", "sequester", "binds")):
            score *= 0.8
            rationale.append(
                f"Penalised: high target density ({desired.target_cell_density:.0e} "
                f"{desired.target_cell_density_unit}) raises the effective dose requirement, and "
                "this candidate is recorded as adsorbing or being sequestered."
            )
        else:
            rationale.append(
                f"High target density ({desired.target_cell_density:.0e} "
                f"{desired.target_cell_density_unit}) requires a correspondingly higher dose; "
                "the experiment planner should sweep concentration rather than assume one value."
            )

    return _clamp(score), rationale


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------


def score_candidate(
    candidate: CandidateProposal,
    *,
    target: CandidateTarget,
    desired: DesiredBehavior,
    constraints: CandidateConstraints,
    tested_sequences: list[str],
    tested_ids: set[str],
    competing_hypotheses: list[CompetingHypothesis],
) -> ScoreBreakdown:
    """Compute the full score breakdown for one candidate."""
    promise, promise_why = score_promise(candidate, target, desired)
    novelty, novelty_why = score_novelty(candidate, tested_sequences, tested_ids)
    uncertainty, uncertainty_why = score_uncertainty(candidate)
    info_gain, info_why = score_information_gain(promise, uncertainty, novelty)
    discrimination, disc_why = score_hypothesis_discrimination(candidate, competing_hypotheses)
    condition_fit, fit_why = score_condition_fit(candidate, desired)

    weights = constraints.scoring_weights.normalised()
    components = {
        "promise": promise,
        "novelty": novelty,
        "uncertainty": uncertainty,
        "information_gain": info_gain,
        "hypothesis_discrimination": discrimination,
        "condition_fit": condition_fit,
    }
    total = sum(components[name] * weights[name] for name in components)

    return ScoreBreakdown(
        promise=round(promise, 4),
        novelty=round(novelty, 4),
        uncertainty=round(uncertainty, 4),
        information_gain=round(info_gain, 4),
        hypothesis_discrimination=round(discrimination, 4),
        condition_fit=round(condition_fit, 4),
        total=round(_clamp(total), 4),
        rationale=[
            *promise_why,
            *novelty_why,
            *uncertainty_why,
            *info_why,
            *disc_why,
            *fit_why,
        ],
    )


def select_diverse(
    candidates: list[CandidateProposal],
    *,
    k: int,
    diversity_weight: float,
) -> list[CandidateProposal]:
    """Greedy diversity-aware selection of ``k`` candidates.

    Each step picks the candidate maximising::

        (1 - w) * total_score - w * max_redundancy_with_already_selected

    where redundancy comes from :func:`experimental_redundancy`, which accounts
    for shared family and mechanism rather than sequence identity alone.

    This is maximal marginal relevance. The objective is submodular, so greedy
    selection is within a constant factor of optimal and is cheap, stable, and
    explainable -- which matters more here than exactness, because the scores
    being traded off are themselves heuristic.

    ``diversity_weight = 0`` reduces to ranking by score. Ties break on
    ``candidate_id`` so the output is reproducible.
    """
    if k <= 0 or not candidates:
        return []
    if not 0.0 <= diversity_weight <= 1.0:
        raise ValueError(f"diversity_weight must be within 0-1, got {diversity_weight}")

    pool = sorted(
        candidates,
        key=lambda c: (-(c.score.total if c.score else 0.0), c.candidate_id),
    )
    if diversity_weight == 0.0:
        return pool[:k]

    selected: list[CandidateProposal] = [pool[0]]
    remaining = pool[1:]

    while remaining and len(selected) < k:
        best_index = 0
        best_value = -math.inf
        for index, candidate in enumerate(remaining):
            similarity = _max_similarity(candidate, selected)
            score = candidate.score.total if candidate.score else 0.0
            value = (1.0 - diversity_weight) * score - diversity_weight * similarity
            # Strict > keeps the earlier (higher-scoring, id-sorted) candidate on ties.
            if value > best_value:
                best_value, best_index = value, index
        selected.append(remaining.pop(best_index))

    return selected


#: Redundancy attributed to two candidates sharing a bacteriocin class or a
#: receptor. Calibrated against the observation below: raw k-mer similarity
#: badly understates experimental redundancy between same-family peptides.
_SAME_CLASS_REDUNDANCY = 0.6
_SAME_RECEPTOR_REDUNDANCY = 0.55


def experimental_redundancy(a: CandidateProposal, b: CandidateProposal) -> float:
    """How much testing ``b`` duplicates testing ``a``, in ``[0, 1]``.

    Sequence identity alone is the wrong measure here. Two class IIa
    bacteriocins that both dock onto Man-PTS share only ~9% of their 3-mers --
    barely more than an unrelated lasso peptide at 0% -- yet testing both
    answers very nearly the same scientific question. Conversely two peptides
    could be sequence-similar and still probe different mechanisms.

    Redundancy is therefore the strongest of three signals:

    * k-mer sequence similarity,
    * sharing a bacteriocin class (same family, same general mode of action),
    * sharing a receptor (the same mechanistic hypothesis is under test).

    Taking the max rather than a mean keeps any one strong redundancy signal
    from being diluted by the others being unavailable, which matters because
    curated records are frequently missing a class or a receptor.
    """
    signals = [0.0]

    if a.sequence and b.sequence:
        signals.append(sequence_similarity(a.sequence, b.sequence))

    a_class, b_class = a.features.bacteriocin_class, b.features.bacteriocin_class
    if a_class and b_class and a_class == b_class:
        signals.append(_SAME_CLASS_REDUNDANCY)

    a_receptor, b_receptor = a.features.receptor, b.features.receptor
    if a_receptor and b_receptor and a_receptor.strip().lower() == b_receptor.strip().lower():
        signals.append(_SAME_RECEPTOR_REDUNDANCY)

    return max(signals)


def _max_similarity(candidate: CandidateProposal, others: list[CandidateProposal]) -> float:
    """Highest redundancy between ``candidate`` and any already-selected candidate."""
    return max((experimental_redundancy(candidate, other) for other in others), default=0.0)


def tested_history(previous_results: list[dict[str, Any]]) -> tuple[set[str], list[str]]:
    """Extract tested candidate IDs from ``previous_results``.

    Returns ``(tested_ids, [])``; sequences are resolved by the caller, which
    holds the candidate pool. Malformed entries are skipped rather than raising,
    because a single bad result record should not stop the loop.
    """
    tested_ids: set[str] = set()
    for entry in previous_results:
        if not isinstance(entry, dict):
            continue
        candidate = entry.get("candidate_id")
        if isinstance(candidate, str) and candidate:
            tested_ids.add(candidate)
    return tested_ids, []


__all__ = [
    "experimental_redundancy",
    "score_candidate",
    "score_condition_fit",
    "score_hypothesis_discrimination",
    "score_information_gain",
    "score_novelty",
    "score_promise",
    "score_uncertainty",
    "select_diverse",
    "tested_history",
]
