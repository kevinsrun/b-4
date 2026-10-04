"""The Candidate Generation & Design Agent.

One responsibility: given an objective, evidence, hypotheses, constraints and
previous results, propose a ranked, diverse set of bacteriocin candidates worth
testing next, each with a falsifiable hypothesis and explicit provenance.

It does not simulate, does not score potency, and does not decide what runs. It
recommends ``experiment_planner`` as the next step and leaves the decision to
Omnigent.
"""

from __future__ import annotations

import logging
from typing import Any

from bacteriocin_lab.shared.contract import (
    AgentResponseEnvelope,
    Evidence,
    RecommendedNextAction,
    Uncertainty,
)
from bacteriocin_lab.shared.ids import candidate_id as make_candidate_id
from bacteriocin_lab.shared.ids import evidence_id as make_evidence_id
from bacteriocin_lab.shared.ids import run_id as make_run_id

from .design import propose_variants
from .features import SequenceValidationError, compute_features
from .hypotheses import (
    build_hypothesis,
    build_mechanism_hypothesis,
    expected_failure_modes,
    expected_strengths,
)
from .knowledge import KnowledgeRecord, KnowledgeSource, default_knowledge_source
from .schema import (
    CandidateFeatures,
    CandidateGenerationResult,
    CandidateProposal,
    CandidateRequest,
    ScoreBreakdown,
)
from .scoring import score_candidate, select_diverse, tested_history

logger = logging.getLogger(__name__)

AGENT_NAME = "candidate_generation_agent"

#: Bump on any change that can alter output for identical input. Downstream
#: agents and stored evidence reference this to know which logic produced a
#: candidate (contract rule 7).
MODEL_VERSION = "candidate-generation/0.1.0"


class CandidateAgentError(RuntimeError):
    """Raised when the agent cannot produce a result at all."""


class CandidateGenerationAgent:
    """Tool-callable candidate generation agent.

    The knowledge source is injected rather than hardcoded so that every run is
    reconstructible from its inputs plus the named source (contract rule 6). The
    agent holds no mutable state between calls: ``run`` is a pure function of
    its request and the injected source.
    """

    def __init__(
        self,
        knowledge_source: KnowledgeSource | None = None,
        ncbi_client: Any | None = None,
    ):
        self._knowledge = knowledge_source if knowledge_source is not None else default_knowledge_source()
        self._ncbi_client = ncbi_client

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def check_candidate_similarity(
        self,
        candidate_id: str,
        sequence: str,
        database: str = "nr",
        client: Any | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check sequence similarity and novelty of a candidate using NCBI BLAST."""
        from bacteriocin_lab.agents.evidence.ncbi import blastp

        c = client or self._ncbi_client
        return blastp(
            sequence=sequence,
            candidate_id=candidate_id,
            database=database,
            client=c,
            **kwargs,
        )

    def verify_candidate_sequences(
        self,
        records: list[Any] | None = None,
        fetch_reference: Any | None = None,
        blast: Any | None = None,
        annotate_novelty: bool = False,
    ) -> dict[str, Any]:
        """Check stored sequences against their primary database records.

        Deliberately **not** called from :meth:`run`. ``run`` is a pure function
        of its request and the named knowledge source, and the research state is
        replayed from an append-only log; a live database lookup inside it would
        break both. The result of this pass is provenance, recorded alongside a
        candidate, and it never enters ``score_components``.

        With ``annotate_novelty`` the pass also BLASTs each sequence and attaches
        the heuristic novelty summary. That answers "is this already a known
        protein", which is useful for a generated variant with no accession, and
        is not a substitute for the exact comparison above.
        """
        from .verification import verify_candidates

        if records is None:
            records = list(self._knowledge.records())

        blast_fn = blast
        if blast_fn is None and annotate_novelty:
            from bacteriocin_lab.agents.evidence.ncbi import summarize_blast_similarity

            def blast_fn(sequence: str) -> dict[str, Any]:  # type: ignore[misc]
                return summarize_blast_similarity(
                    self.check_candidate_similarity(candidate_id=None, sequence=sequence)
                )

        result = verify_candidates(records, fetch_reference=fetch_reference, blast=blast_fn)
        result["knowledge_source"] = self._knowledge.source_name
        result["model_version"] = MODEL_VERSION
        return result

    def run(self, request: CandidateRequest) -> CandidateGenerationResult:
        """Produce ranked candidates for one request."""
        warnings: list[str] = []
        rejected: list[dict[str, Any]] = []

        pool = self._build_pool(request, warnings, rejected)
        if not pool:
            return self._empty_result(request, warnings, rejected)

        tested_ids, _ = tested_history(request.previous_results)
        tested_sequences = [c.sequence for c in pool if c.sequence and c.candidate_id in tested_ids]

        if request.constraints.allow_sequence_modification:
            pool.extend(self._design_variants(request, pool, warnings))

        for candidate in pool:
            candidate.score = score_candidate(
                candidate,
                target=request.target,
                desired=request.desired_behavior,
                constraints=request.constraints,
                tested_sequences=tested_sequences,
                tested_ids=tested_ids,
                competing_hypotheses=request.competing_hypotheses,
            )

        considered = len(pool)
        eligible = self._apply_score_floor(pool, request, rejected)
        selected = select_diverse(
            eligible,
            k=request.constraints.max_candidates,
            diversity_weight=request.constraints.diversity_weight,
        )

        for rank, candidate in enumerate(selected, start=1):
            self._finalise(candidate, request, rank)

        warnings.extend(self._collect_warnings(selected))

        return CandidateGenerationResult(
            candidates=selected,
            selection_logic=self._selection_logic(request, considered, len(selected)),
            uncertainties=self._collect_uncertainties(request, selected),
            recommended_next_action=self._next_action(request, selected),
            considered_count=considered,
            rejected=rejected,
            evidence=self._provenance_evidence(selected),
            warnings=sorted(set(warnings)),
            model_version=MODEL_VERSION,
        )

    def run_envelope(self, payload: dict[str, Any]) -> AgentResponseEnvelope:
        """JSON-in / JSON-out entry point for Omnigent.

        Validation errors are returned as a well-formed envelope with
        ``confidence=0`` rather than raised, so an orchestrator never has to
        catch exceptions across a tool boundary to keep the loop alive.
        """
        try:
            request = CandidateRequest.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - boundary: any validation failure
            logger.warning("Invalid request to %s: %s", AGENT_NAME, exc)
            return AgentResponseEnvelope(
                agent=AGENT_NAME,
                decision={"candidates": [], "selection_logic": "Request validation failed."},
                confidence=0.0,
                uncertainties=[
                    Uncertainty(
                        kind="data-gap",
                        description=f"Request did not validate against CandidateRequest: {exc}",
                        severity="high",
                    )
                ],
                warnings=[f"Invalid request: {exc}"],
                model_version=MODEL_VERSION,
            )

        result = self.run(request)
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision=result.model_dump(mode="json", exclude={"evidence", "warnings"}),
            evidence=result.evidence,
            confidence=self._overall_confidence(result),
            uncertainties=list(result.uncertainties),
            artifacts={
                "run_id": make_run_id(payload),
                "knowledge_source": self._knowledge.source_name,
                "considered_count": result.considered_count,
                "scoring_weights": request.constraints.scoring_weights.normalised(),
            },
            warnings=result.warnings,
            recommended_next_action=result.recommended_next_action,
            model_version=MODEL_VERSION,
        )

    # ------------------------------------------------------------------
    # Pool construction
    # ------------------------------------------------------------------

    def _build_pool(
        self,
        request: CandidateRequest,
        warnings: list[str],
        rejected: list[dict[str, Any]],
    ) -> list[CandidateProposal]:
        """Merge knowledge records, caller-supplied records and evidence into a pool."""
        records: list[KnowledgeRecord] = []

        try:
            records.extend(self._knowledge.records())
        except Exception as exc:  # noqa: BLE001 - a bad source must not kill the loop
            logger.warning("Knowledge source %s failed: %s", self._knowledge.source_name, exc)
            warnings.append(
                f"Knowledge source '{self._knowledge.source_name}' could not be read ({exc}); "
                "proceeding with caller-supplied candidates only."
            )

        for entry in request.candidate_pool:
            try:
                records.append(KnowledgeRecord.model_validate(entry))
            except Exception as exc:  # noqa: BLE001 - per-record, keep the rest
                rejected.append({"record": entry, "reason": f"Invalid candidate_pool entry: {exc}"})

        records.extend(self._records_from_evidence(request))

        ph = self._charge_ph(request)
        excluded = set(request.constraints.exclude_candidate_ids)
        pool: dict[str, CandidateProposal] = {}

        for record in records:
            proposal = self._to_proposal(record, ph, rejected)
            if proposal is None:
                continue
            if proposal.candidate_id in excluded:
                rejected.append(
                    {
                        "candidate_id": proposal.candidate_id,
                        "name": proposal.name,
                        "reason": "Explicitly excluded by constraints.exclude_candidate_ids.",
                    }
                )
                continue
            if not self._passes_filters(proposal, request, rejected):
                continue
            # Deterministic de-duplication: first record wins, and content-addressed
            # IDs mean the same peptide from two sources collapses to one candidate.
            pool.setdefault(proposal.candidate_id, proposal)

        return list(pool.values())

    def _records_from_evidence(self, request: CandidateRequest) -> list[KnowledgeRecord]:
        """Pull candidate records carried on incoming evidence.

        An evidence item may carry a ``candidate`` payload as an extra field --
        this is how an upstream literature-mining agent hands over a peptide it
        found. The evidence_id is preserved so provenance survives the hop.
        """
        records: list[KnowledgeRecord] = []
        for item in request.evidence:
            payload = getattr(item, "candidate", None)
            if not isinstance(payload, dict):
                continue
            try:
                record = KnowledgeRecord.model_validate(payload)
            except Exception as exc:  # noqa: BLE001 - skip the item, keep the rest
                logger.debug("Evidence %s carried an invalid candidate: %s", item.evidence_id, exc)
                continue
            record.source = record.source or item.source
            if item.evidence_type in ("literature-derived", "database-derived"):
                record.origin = item.evidence_type.removesuffix("-derived")
            setattr(record, "_evidence_id", item.evidence_id)
            records.append(record)
        return records

    def _to_proposal(
        self,
        record: KnowledgeRecord,
        ph: float,
        rejected: list[dict[str, Any]],
    ) -> CandidateProposal | None:
        """Convert a knowledge record into a scored-but-unranked proposal."""
        computed = None
        if record.sequence:
            try:
                computed = compute_features(
                    record.sequence, ph=ph, bacteriocin_class=record.bacteriocin_class
                )
            except SequenceValidationError as exc:
                rejected.append(
                    {"name": record.name, "reason": f"Unusable sequence: {exc}"}
                )
                return None

        origin = record.origin if record.origin in ("literature", "database") else "database"

        try:
            cid = make_candidate_id(sequence=record.sequence, name=record.name, origin=origin)
        except ValueError as exc:
            rejected.append({"name": record.name, "reason": str(exc)})
            return None

        evidence_ids: list[str] = []
        carried = getattr(record, "_evidence_id", None)
        if isinstance(carried, str):
            evidence_ids.append(carried)
        elif record.source or record.accession:
            evidence_ids.append(
                make_evidence_id(
                    claim=f"{record.name} properties and reported spectrum",
                    source=record.accession or record.source,
                    evidence_type=f"{origin}-derived",
                )
            )

        try:
            return CandidateProposal(
                candidate_id=cid,
                origin=origin,
                name=record.name,
                sequence=record.sequence,
                features=CandidateFeatures(
                    computed=computed,
                    bacteriocin_class=record.bacteriocin_class,
                    producing_organism=record.producing_organism,
                    known_targets=record.known_targets,
                    known_non_targets=record.known_non_targets,
                    structural_features=record.structural_features,
                    known_stability=record.known_stability,
                    environmental_sensitivity=record.environmental_sensitivity,
                    resistance_concerns=record.resistance_concerns,
                    receptor=record.receptor,
                ),
                evidence_ids=evidence_ids,
                validation_status="unvalidated",
                sequence_verified=record.sequence_verified,
            )
        except Exception as exc:  # noqa: BLE001 - per-record validation
            rejected.append({"name": record.name, "reason": f"Invalid candidate: {exc}"})
            return None

    def _design_variants(
        self,
        request: CandidateRequest,
        pool: list[CandidateProposal],
        warnings: list[str],
    ) -> list[CandidateProposal]:
        """Stretch goal: conservative variants of the best-characterised parents.

        Parents are chosen by how much is known about them, not by predicted
        potency: a variant is only interpretable against a well-characterised
        baseline.
        """
        budget = request.constraints.max_modified_candidates
        if budget <= 0:
            return []

        parents = sorted(
            (c for c in pool if c.sequence and c.features.known_targets),
            key=lambda c: (-len(c.features.known_targets), c.candidate_id),
        )[:2]
        if not parents:
            return []

        ph = self._charge_ph(request)
        variants: list[CandidateProposal] = []
        existing = {c.sequence for c in pool if c.sequence}

        for parent in parents:
            if len(variants) >= budget:
                break
            assert parent.sequence is not None  # guarded by the filter above
            for variant in propose_variants(
                parent.sequence, max_variants=budget - len(variants), max_substitutions=2
            ):
                if variant.sequence in existing:
                    continue
                existing.add(variant.sequence)

                name = f"{parent.name or parent.candidate_id} variant [{'/'.join(variant.modifications)}]"
                try:
                    computed = compute_features(
                        variant.sequence, ph=ph, bacteriocin_class=parent.features.bacteriocin_class
                    )
                except SequenceValidationError as exc:  # pragma: no cover - defensive
                    logger.debug("Generated variant rejected: %s", exc)
                    continue

                variants.append(
                    CandidateProposal(
                        candidate_id=make_candidate_id(
                            sequence=variant.sequence, name=name, origin="modified"
                        ),
                        origin="modified",
                        name=name,
                        sequence=variant.sequence,
                        features=parent.features.model_copy(update={"computed": computed}),
                        evidence_ids=list(parent.evidence_ids),
                        derived_from_candidate_id=parent.candidate_id,
                        modifications=[*variant.modifications, variant.design_intent],
                        validation_status="unvalidated",
                        sequence_verified=False,
                    )
                )

        if variants:
            warnings.append(
                f"{len(variants)} candidate(s) are computationally modified sequences with no "
                "experimental or structural validation. Expression, folding and any required "
                "post-translational modification are all unverified."
            )
        return variants

    # ------------------------------------------------------------------
    # Filtering, finalisation, reporting
    # ------------------------------------------------------------------

    def _passes_filters(
        self,
        candidate: CandidateProposal,
        request: CandidateRequest,
        rejected: list[dict[str, Any]],
    ) -> bool:
        constraints = request.constraints

        def reject(reason: str) -> bool:
            rejected.append(
                {"candidate_id": candidate.candidate_id, "name": candidate.name, "reason": reason}
            )
            return False

        if constraints.require_known_sequence and not candidate.sequence:
            return reject("constraints.require_known_sequence is set and no sequence is available.")
        if constraints.allowed_origins and candidate.origin not in constraints.allowed_origins:
            return reject(f"Origin '{candidate.origin}' is not in constraints.allowed_origins.")

        if candidate.sequence:
            length = len(candidate.sequence)
            if constraints.min_sequence_length and length < constraints.min_sequence_length:
                return reject(f"Length {length} is below min_sequence_length.")
            if constraints.max_sequence_length and length > constraints.max_sequence_length:
                return reject(f"Length {length} exceeds max_sequence_length.")
        return True

    def _apply_score_floor(
        self,
        pool: list[CandidateProposal],
        request: CandidateRequest,
        rejected: list[dict[str, Any]],
    ) -> list[CandidateProposal]:
        floor = request.constraints.min_total_score
        if floor <= 0:
            return pool

        kept: list[CandidateProposal] = []
        for candidate in pool:
            total = candidate.score.total if candidate.score else 0.0
            if total >= floor:
                kept.append(candidate)
            else:
                rejected.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "name": candidate.name,
                        "reason": f"Total score {total:.3f} is below min_total_score {floor}.",
                    }
                )
        return kept

    def _finalise(self, candidate: CandidateProposal, request: CandidateRequest, rank: int) -> None:
        """Attach rank, hypotheses, strengths, failure modes and confidence."""
        candidate.rank = rank

        primary = build_hypothesis(candidate, request.target, request.desired_behavior)
        candidate.hypotheses = [primary]
        candidate.hypothesis = primary.statement

        mechanism = build_mechanism_hypothesis(candidate, request.target, request.desired_behavior)
        if mechanism is not None:
            candidate.hypotheses.append(mechanism)

        candidate.expected_strengths = expected_strengths(candidate, request.target)
        candidate.expected_failure_modes = expected_failure_modes(
            candidate, request.target, request.desired_behavior
        )

        # Confidence that this is worth testing -- explicitly not a claim about
        # activity. A candidate can be well worth testing precisely because its
        # outcome is uncertain, so information_gain contributes positively.
        score = candidate.score
        if score is not None:
            worth_testing = 0.55 * score.total + 0.45 * score.information_gain
            candidate.confidence = round(max(0.0, min(1.0, worth_testing)), 4)

    def _collect_warnings(self, selected: list[CandidateProposal]) -> list[str]:
        warnings: list[str] = []
        if any(not c.sequence_verified and c.sequence for c in selected):
            warnings.append(
                "One or more selected candidates carry an unverified sequence. Verify against "
                "UniProt/BACTIBASE (scripts/verify_seed_sequences.py) before relying on computed "
                "features; a single wrong residue changes mass, charge and every derived score."
            )
        if any(
            c.features.computed is not None and c.features.computed.caveats for c in selected
        ):
            warnings.append(
                "Post-translationally modified candidates are present. Their computed mass and "
                "charge describe the unmodified primary sequence, not the mature peptide."
            )
        warnings.append(
            "All candidates and hypotheses here are computational proposals "
            "(evidence_type 'inferred-hypothesis' / 'model-predicted'). None is experimentally "
            "validated, and no predicted_inhibition_fraction in this output is a measurement."
        )
        return warnings

    def _collect_uncertainties(
        self, request: CandidateRequest, selected: list[CandidateProposal]
    ) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = [
            Uncertainty(
                kind="model-limitation",
                description=(
                    "Promise scores come from hand-set physicochemical heuristics and reported "
                    "spectra, not a model fitted to this campaign's data. They order candidates; "
                    "they do not predict potency. Replace with a learned model once the loop has "
                    "accumulated simulation results."
                ),
                affects=[c.candidate_id for c in selected],
                severity="high",
            )
        ]

        if not request.previous_results:
            uncertainties.append(
                Uncertainty(
                    kind="data-gap",
                    description=(
                        "No previous_results supplied, so novelty is unconstrained and the "
                        "ranking cannot yet account for what has already been learned."
                    ),
                    severity="medium",
                )
            )
        if not request.competing_hypotheses:
            uncertainties.append(
                Uncertainty(
                    kind="data-gap",
                    description=(
                        "No competing_hypotheses supplied, so hypothesis_discrimination scored 0 "
                        "for every candidate and contributed nothing to the ranking."
                    ),
                    severity="medium",
                )
            )

        unknown_spectrum = [c.candidate_id for c in selected if not c.features.known_targets]
        if unknown_spectrum:
            uncertainties.append(
                Uncertainty(
                    kind="data-gap",
                    description=(
                        f"{len(unknown_spectrum)} selected candidate(s) have no reported activity "
                        "spectrum; their promise scores rest on physicochemistry alone."
                    ),
                    affects=unknown_spectrum,
                    severity="medium",
                )
            )

        if request.desired_behavior.target_cell_density is None:
            uncertainties.append(
                Uncertainty(
                    kind="data-gap",
                    description=(
                        "desired_behavior.target_cell_density was not specified. Bacteriocin "
                        "activity is dose-per-cell dependent, so inhibition cannot be "
                        "meaningfully predicted without it. The experiment planner should treat "
                        "cell density as a swept variable."
                    ),
                    severity="high",
                )
            )
        return uncertainties

    def _provenance_evidence(self, selected: list[CandidateProposal]) -> list[Evidence]:
        """Emit one evidence record per proposal, marking it as inferred.

        This is what keeps rule 9 enforceable downstream: the candidate set
        arrives with its own provenance attached, so a later agent cannot read
        these proposals as findings.
        """
        evidence: list[Evidence] = []
        for candidate in selected:
            claim = (
                f"{candidate.name or candidate.candidate_id} was proposed for testing "
                f"(rank {candidate.rank}, total score "
                f"{candidate.score.total if candidate.score else 0.0:.3f})."
            )
            evidence.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        claim=claim,
                        source=f"{AGENT_NAME}@{MODEL_VERSION}",
                        evidence_type="inferred-hypothesis",
                    ),
                    evidence_type="inferred-hypothesis",
                    claim=claim,
                    source=f"{AGENT_NAME}@{MODEL_VERSION}",
                    confidence=candidate.confidence,
                    subject_ids=[
                        candidate.candidate_id,
                        *(h.hypothesis_id for h in candidate.hypotheses),
                    ],
                    notes="Proposal only. Not evidence of antimicrobial activity.",
                )
            )
        return evidence

    def _selection_logic(
        self, request: CandidateRequest, considered: int, returned: int
    ) -> str:
        weights = request.constraints.scoring_weights.normalised()
        weight_text = ", ".join(f"{name} {value:.0%}" for name, value in weights.items())
        return (
            f"Evaluated {considered} candidate(s) from knowledge source "
            f"'{self._knowledge.source_name}' plus caller-supplied records, and returned "
            f"{returned} ranked against {request.target.organism}. Each candidate was scored on "
            f"six objectives ({weight_text}), so the ranking is not a potency ordering: "
            "information_gain peaks where the outcome is most in doubt (4p(1-p)), and "
            "hypothesis_discrimination rewards candidates that split the open hypotheses rather "
            "than candidates all of them agree on. The returned set was then chosen by greedy "
            f"maximal-marginal-relevance selection at diversity_weight="
            f"{request.constraints.diversity_weight}, which trades some score for coverage so "
            "the set does not collapse onto one bacteriocin family. Every candidate is "
            "unvalidated and carries an explicit falsification clause."
        )

    def _next_action(
        self, request: CandidateRequest, selected: list[CandidateProposal]
    ) -> RecommendedNextAction:
        if not selected:
            return RecommendedNextAction(
                agent="evidence_gathering_agent",
                reason=(
                    "No candidate survived filtering, so the pool itself is the bottleneck. "
                    "Gather more bacteriocin records before planning an experiment."
                ),
            )

        density = request.desired_behavior.target_cell_density
        density_note = (
            f"Sweep bacteriocin_concentration against target_cell_density around {density:.0e} "
            f"{request.desired_behavior.target_cell_density_unit}"
            if density is not None
            else "Sweep bacteriocin_concentration and target_cell_density jointly, since "
            "target_cell_density was not specified"
        )
        return RecommendedNextAction(
            agent="experiment_planner",
            reason=(
                f"{len(selected)} ranked candidate(s) with falsifiable hypotheses are ready for "
                f"experiment design. {density_note}: inhibition depends on dose per cell, so a "
                "single concentration cannot test these hypotheses. Prioritise the top-ranked "
                "candidates, and note that the highest information_gain candidates are not the "
                "highest promise ones."
            ),
            payload_hint={
                "candidate_ids": [c.candidate_id for c in selected],
                "hypothesis_ids": [h.hypothesis_id for c in selected for h in c.hypotheses],
                "target": request.target.model_dump(mode="json"),
                "suggested_sweeps": ["bacteriocin_concentration", "target_cell_density", "ph"],
                "assay_domain": request.desired_behavior.assay_domain,
            },
        )

    def _empty_result(
        self,
        request: CandidateRequest,
        warnings: list[str],
        rejected: list[dict[str, Any]],
    ) -> CandidateGenerationResult:
        warnings.append(
            "No candidates available. Supply candidate_pool entries, evidence carrying candidate "
            "records, or configure a knowledge source."
        )
        return CandidateGenerationResult(
            candidates=[],
            selection_logic=(
                f"No candidate records were available from knowledge source "
                f"'{self._knowledge.source_name}', candidate_pool, or evidence."
            ),
            uncertainties=[
                Uncertainty(
                    kind="data-gap",
                    description="Empty candidate pool; nothing could be ranked.",
                    severity="high",
                )
            ],
            recommended_next_action=self._next_action(request, []),
            considered_count=0,
            rejected=rejected,
            warnings=sorted(set(warnings)),
            model_version=MODEL_VERSION,
        )

    def _charge_ph(self, request: CandidateRequest) -> float:
        """pH at which to evaluate net charge: the midpoint of the requested range."""
        ph_range = request.desired_behavior.ph_range
        return round((ph_range[0] + ph_range[1]) / 2.0, 2) if ph_range else 7.0

    def _overall_confidence(self, result: CandidateGenerationResult) -> float:
        """Confidence in the candidate *set*, not in any candidate's activity."""
        if not result.candidates:
            return 0.0
        mean = sum(c.confidence for c in result.candidates) / len(result.candidates)
        # A thin pool means the ranking had little to choose between, so cap
        # confidence by how much selection pressure there actually was.
        breadth = min(1.0, result.considered_count / 10.0)
        return round(max(0.0, min(1.0, mean * (0.6 + 0.4 * breadth))), 4)


# ---------------------------------------------------------------------------
# Module-level tool interface
# ---------------------------------------------------------------------------


def generate_candidates(
    payload: dict[str, Any],
    *,
    knowledge_source: KnowledgeSource | None = None,
) -> dict[str, Any]:
    """Tool-callable entry point: JSON in, JSON out.

    This is the function Omnigent registers as a tool.

    Args:
        payload: A ``CandidateRequest``-shaped dict.
        knowledge_source: Optional override for the curated record source.

    Returns:
        An ``AgentResponseEnvelope``-shaped dict. Always well-formed, including
        on invalid input.
    """
    agent = CandidateGenerationAgent(knowledge_source=knowledge_source)
    return agent.run_envelope(payload).model_dump(mode="json")


__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "CandidateAgentError",
    "CandidateGenerationAgent",
    "generate_candidates",
]
