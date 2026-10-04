"""Thin adapters from orchestration state to the real scientific agents.

These adapters translate contracts only. Scientific interpretation, review policy, and knowledge
state transitions remain owned by ``bacteriocin_lab.agents.analysis|critic|knowledge``.
"""

from __future__ import annotations

import json
from typing import Any

from bacteriocin_lab.agents.analysis import ResultAnalysisAgent as ScientificAnalysisAgent
from bacteriocin_lab.agents.critic import ScientificCriticAgent as ScientificReviewAgent
from bacteriocin_lab.agents.knowledge import KnowledgeAgent as ScientificKnowledgeAgent
from bacteriocin_lab.shared import ResearchState as KnowledgeResearchState
from bacteriocin_lab.shared.contract import AgentResponseEnvelope, Uncertainty

from ..state import ResearchStateManager
from ..types import Evidence, Finding, ResearchState, Review

_MAX_STORED_PAYLOAD_BYTES = 256_000
_VERDICT_MAP = {
    "approve": "approved",
    "approve_with_caveats": "needs_more_evidence",
    "needs_more_evidence": "needs_more_evidence",
    "reject": "rejected",
}


def _model_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {}


def _envelope_dict(response: AgentResponseEnvelope | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, AgentResponseEnvelope):
        payload = response.model_dump(mode="json")
    elif isinstance(response, dict):
        payload = response
    else:
        raise TypeError(f"Real agent returned {type(response).__name__}, expected an envelope")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    if len(encoded) > _MAX_STORED_PAYLOAD_BYTES:
        raise ValueError(
            f"Real agent payload is {len(encoded)} bytes; bounded metadata limit is "
            f"{_MAX_STORED_PAYLOAD_BYTES} bytes"
        )
    return payload


def _merge_uncertainties(state: ResearchState, raw: list[Any]) -> None:
    existing = {
        json.dumps(
            item.model_dump(mode="json") if isinstance(item, Uncertainty) else item,
            sort_keys=True,
            default=str,
        )
        for item in state.uncertainties
    }
    for item in raw:
        parsed: str | Uncertainty = (
            item if isinstance(item, str) else Uncertainty.model_validate(item)
        )
        key = json.dumps(
            parsed.model_dump(mode="json") if isinstance(parsed, Uncertainty) else parsed,
            sort_keys=True,
            default=str,
        )
        if key not in existing:
            state.uncertainties.append(parsed)
            existing.add(key)


def _matching_context(state: ResearchState) -> tuple[Any, Any, Any, Any]:
    result = state.results[-1]
    spec = next(
        (item for item in reversed(state.experiments) if item.experiment_id == result.experiment_id),
        None,
    )
    hypothesis_id = getattr(result, "hypothesis_id", None) or (
        getattr(spec, "hypothesis_id", None) if spec else None
    )
    hypothesis = state.get_hypothesis(hypothesis_id) if hypothesis_id else None
    if hypothesis is None:
        hypothesis = next(
            (item for item in state.hypotheses if item.candidate_id == result.candidate_id),
            None,
        )
    candidate = state.get_candidate(result.candidate_id) if result.candidate_id else None
    return result, spec, hypothesis, candidate


class RealAnalysisAdapter:
    """Invoke the repository's actual Result Analysis Agent."""

    name = "analysis"

    def __init__(self, agent: ScientificAnalysisAgent | None = None) -> None:
        self.agent = agent or ScientificAnalysisAgent()

    def run(self, state: ResearchState) -> dict[str, Any]:
        if not state.results:
            return {
                "agent": self.name,
                "status": "skipped",
                "reason": "No experiment results to analyze",
                "output_ids": [],
            }

        result, spec, hypothesis, candidate = _matching_context(state)
        payload = {
            "result": result.model_dump(mode="json"),
            "spec": spec.model_dump(mode="json") if spec else None,
            "hypothesis": hypothesis.model_dump(mode="json") if hypothesis else None,
            "candidate": candidate.model_dump(mode="json") if candidate else None,
            "previous_results": [item.model_dump(mode="json") for item in state.results[:-1]],
            "evidence": [item.model_dump(mode="json") for item in state.evidence],
            "research_objective": state.objective.model_dump(mode="json"),
            # Results are passed exactly once via previous_results. The remaining state still gives
            # the agent the objective and accumulated scientific context it needs.
            "research_state": {
                "objective": state.objective.model_dump(mode="json"),
                "candidates": [item.model_dump(mode="json") for item in state.candidates],
                "hypotheses": [item.model_dump(mode="json") for item in state.hypotheses],
                "evidence": [item.model_dump(mode="json") for item in state.evidence],
                "findings": [item.model_dump(mode="json") for item in state.findings],
                "iteration": state.iteration,
            },
        }
        envelope = _envelope_dict(self.agent.run_envelope(payload))
        decision = envelope.get("decision") or {}
        status = decision.get("hypothesis_status")
        if status not in {"supported", "weakened", "inconclusive"}:
            raise ValueError(f"Real analysis returned unsupported hypothesis status {status!r}")
        finding_id = decision.get("finding_id")
        if not finding_id:
            raise ValueError("Real analysis returned no finding_id")

        state_mgr = ResearchStateManager(state)
        emitted_evidence_ids: list[str] = []
        for raw_evidence in envelope.get("evidence") or []:
            evidence = Evidence.model_validate(raw_evidence)
            state_mgr.add_evidence(evidence, source_agent="result_analysis_agent")
            emitted_evidence_ids.append(evidence.evidence_id)

        variable_effects = {
            str(item["variable"]): float(item["effect_size"])
            for item in decision.get("findings") or []
            if item.get("variable") and item.get("effect_size") is not None
        }
        result_ids = [str(decision.get("result_id") or result.result_id)]
        result_ids.extend(
            str(item)
            for item in (envelope.get("artifacts") or {}).get("prior_results_used") or []
        )
        result_ids = list(dict.fromkeys(result_ids))
        statement = str(decision.get("status_basis") or "")
        if not statement and decision.get("findings"):
            statement = str(decision["findings"][0].get("interpretation") or "")

        finding = Finding(
            finding_id=str(finding_id),
            statement=statement,
            status=status,
            confidence=float(decision.get("confidence", envelope.get("confidence", 0.0))),
            candidate_ids=[str(decision.get("candidate_id") or result.candidate_id)],
            hypothesis_ids=[str(decision["hypothesis_id"])]
            if decision.get("hypothesis_id")
            else [],
            evidence_ids=list(dict.fromkeys([result.result_id, *emitted_evidence_ids])),
            result_ids=result_ids,
            factor_sensitivities=variable_effects,
            recommendations=[str(item) for item in decision.get("recommended_followup_questions") or []],
            uncertainties=list(envelope.get("uncertainties") or []),
            provenance_note=decision.get("provenance_note"),
            analysis_payload=envelope,
        )
        state_mgr.add_finding(finding, source_agent="result_analysis_agent")
        _merge_uncertainties(state, list(envelope.get("uncertainties") or []))
        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [finding.finding_id, *emitted_evidence_ids],
            "finding": finding.model_dump(mode="json"),
            "real_agent": envelope.get("agent"),
        }


class RealCriticAdapter:
    """Submit explicit, cited claims to the repository's actual Scientific Critic."""

    name = "critic"

    def __init__(self, agent: ScientificReviewAgent | None = None) -> None:
        self.agent = agent or ScientificReviewAgent()

    def run(self, state: ResearchState) -> dict[str, Any]:
        latest_finding = state.findings[-1] if state.findings else None
        if latest_finding is None:
            raise ValueError("No analysis finding is available for real critic review")

        known_result_ids = {item.result_id for item in state.results}
        result_ids = [item for item in latest_finding.result_ids if item in known_result_ids]
        if not result_ids:
            result_ids = [
                item
                for item in latest_finding.evidence_ids
                if item in known_result_ids
            ]
        known_evidence_ids = {item.evidence_id for item in state.evidence}
        evidence_ids = [
            item for item in latest_finding.evidence_ids if item in known_evidence_ids
        ]
        result = next(
            (item for item in reversed(state.results) if item.result_id in result_ids),
            state.results[-1] if state.results else None,
        )
        candidate_id = latest_finding.candidate_ids[0] if latest_finding.candidate_ids else None
        hypothesis_id = (
            latest_finding.hypothesis_ids[0] if latest_finding.hypothesis_ids else None
        )
        payload = {
            "claims": [
                {
                    "claim_id": latest_finding.finding_id,
                    "statement": latest_finding.statement,
                    "evidence_ids": evidence_ids,
                    "result_ids": result_ids,
                    "hypothesis_id": hypothesis_id,
                    "candidate_id": candidate_id,
                    "asserted_confidence": latest_finding.confidence,
                    "conditions_claimed": _model_dict(result.conditions) if result else {},
                }
            ],
            "previous_results": [item.model_dump(mode="json") for item in state.results],
            "evidence": [item.model_dump(mode="json") for item in state.evidence],
            "competing_hypotheses": [
                {
                    "hypothesis_id": item.hypothesis_id,
                    "statement": item.statement,
                    "discriminating_variable": item.discriminating_feature,
                }
                for item in state.hypotheses
                if item.hypothesis_id != hypothesis_id
            ],
            "research_objective": state.objective.model_dump(mode="json"),
            "research_state": {
                "iteration": state.iteration,
                "finding_id": latest_finding.finding_id,
            },
        }
        # Deliberately omit minimum_results_per_claim: the real agent's safety floor remains active.
        envelope = _envelope_dict(self.agent.run_envelope(payload))
        decision = envelope.get("decision") or {}
        real_status = decision.get("status")
        if real_status not in _VERDICT_MAP:
            raise ValueError(f"Real critic returned unsupported verdict {real_status!r}")
        review_data = (envelope.get("artifacts") or {}).get("review") or {}
        issues = list(review_data.get("issues") or [])
        followups = list(review_data.get("required_followups") or [])
        critique = "; ".join(str(item.get("description", "")) for item in issues if item)
        if not critique:
            critique = f"Real scientific critic verdict: {real_status}."
        next_action = envelope.get("recommended_next_action")
        recommendation = dict(next_action or {})
        provenance = {
            "agent": envelope.get("agent"),
            "model_version": envelope.get("model_version"),
            "claim_id": latest_finding.finding_id,
            "result_ids": result_ids,
            "evidence_ids": evidence_ids,
            "source_evidence_types": sorted(
                {str(item.evidence_type) for item in state.results if item.result_id in result_ids}
            ),
        }
        review = Review(
            review_id=str(review_data.get("review_id") or decision.get("review_id")),
            status=_VERDICT_MAP[real_status],
            critique=critique,
            recommendation=recommendation,
            reviewer="scientific_critic_agent",
            confidence=float(review_data.get("confidence", envelope.get("confidence", 0.0))),
            issues=issues,
            required_followups=followups,
            uncertainties=list(envelope.get("uncertainties") or []),
            provenance=provenance,
            critic_payload=envelope,
        )
        ResearchStateManager(state).add_review(review, source_agent="scientific_critic_agent")
        _merge_uncertainties(state, list(envelope.get("uncertainties") or []))
        return {
            "agent": self.name,
            "status": review.status,
            "real_status": real_status,
            "review": review.model_dump(mode="json"),
            "output_ids": [review.review_id],
        }


class RealKnowledgeAdapter:
    """Use the actual Knowledge Agent in pure mode and retain its returned state bridge."""

    name = "knowledge"

    def __init__(self, agent: ScientificKnowledgeAgent | None = None) -> None:
        self.agent = agent or ScientificKnowledgeAgent()

    def _call(
        self, knowledge_state: dict[str, Any], operation: str, **payload: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        envelope = _envelope_dict(
            self.agent.run_envelope(
                {"operation": operation, "previous_state": knowledge_state, **payload}
            )
        )
        decision = envelope.get("decision") or {}
        if decision.get("status") != "ok":
            raise ValueError(
                f"Real knowledge operation {operation!r} failed: {decision.get('error') or decision}"
            )
        updated = (envelope.get("artifacts") or {}).get("updated_state")
        if not isinstance(updated, dict):
            raise ValueError(f"Real knowledge operation {operation!r} returned no updated_state")
        return updated, envelope

    def run(self, state: ResearchState) -> dict[str, Any]:
        latest_finding = state.findings[-1] if state.findings else None
        if latest_finding is None or not latest_finding.analysis_payload:
            raise ValueError("No real analysis payload is available for Knowledge Agent update")

        knowledge_state = state.knowledge_state or KnowledgeResearchState().model_dump(mode="json")
        objective = state.objective.model_dump(mode="json")
        if knowledge_state.get("objective") != objective:
            knowledge_state, _ = self._call(
                knowledge_state, "initialize_state", objective=objective
            )

        known_candidates = set((knowledge_state.get("candidates") or {}).keys())
        known_hypotheses = set((knowledge_state.get("hypotheses") or {}).keys())
        candidate_payload: list[dict[str, Any]] = []
        for candidate in state.candidates:
            hypotheses = [
                item.model_dump(mode="json")
                for item in state.hypotheses
                if item.candidate_id == candidate.candidate_id
                and item.hypothesis_id not in known_hypotheses
            ]
            if candidate.candidate_id not in known_candidates or hypotheses:
                candidate_payload.append(
                    {
                        **candidate.model_dump(mode="json"),
                        "origin": candidate.source or "orchestration",
                        "score": {"total": candidate.score_total},
                        "hypotheses": hypotheses,
                    }
                )
        if candidate_payload:
            knowledge_state, _ = self._call(
                knowledge_state,
                "register_candidates",
                candidate_output={"decision": {"candidates": candidate_payload}},
            )

        known_evidence = set((knowledge_state.get("evidence") or {}).keys())
        missing_evidence = [
            item.model_dump(mode="json")
            for item in state.evidence
            if item.evidence_id not in known_evidence
        ]
        if missing_evidence:
            knowledge_state, _ = self._call(
                knowledge_state, "register_evidence", evidence=missing_evidence
            )

        analysis = latest_finding.analysis_payload
        decision = analysis.get("decision") or {}
        experiment_id = decision.get("experiment_id")
        result_id = decision.get("result_id")
        spec = next(
            (item for item in state.experiments if item.experiment_id == experiment_id), None
        )
        if spec and experiment_id not in (knowledge_state.get("experiments") or {}):
            knowledge_state, _ = self._call(
                knowledge_state,
                "record_experiment_plan",
                plan=spec.model_dump(mode="json"),
            )
        result = next((item for item in state.results if item.result_id == result_id), None)
        hypothesis = state.get_hypothesis(decision.get("hypothesis_id"))
        candidate = state.get_candidate(decision.get("candidate_id"))
        knowledge_state, envelope = self._call(
            knowledge_state,
            "update_state",
            analysis_result=analysis,
            result=result.model_dump(mode="json") if result else None,
            spec=spec.model_dump(mode="json") if spec else None,
            hypothesis=hypothesis.model_dump(mode="json") if hypothesis else None,
            candidate=candidate.model_dump(mode="json") if candidate else None,
            expected_event_count=knowledge_state.get("event_count"),
        )
        state.knowledge_state = knowledge_state

        state_mgr = ResearchStateManager(state)
        updated_hypotheses: list[str] = []
        for hypothesis_id, record in (knowledge_state.get("hypotheses") or {}).items():
            hypothesis = state.get_hypothesis(hypothesis_id)
            new_status = record.get("status")
            if hypothesis is not None and new_status != hypothesis.status:
                state_mgr.update_hypothesis_status(
                    hypothesis_id,
                    new_status=new_status,
                    source_agent="knowledge_agent",
                    reason="Synchronized from the real Knowledge Agent state transition.",
                )
                updated_hypotheses.append(hypothesis_id)

        settled_candidates: list[str] = []
        for candidate_id, record in (knowledge_state.get("candidates") or {}).items():
            if record.get("status") == "rejected" and candidate_id not in state.settled_candidate_ids:
                state.settled_candidate_ids.append(candidate_id)
                settled_candidates.append(candidate_id)

        state.iteration += 1
        _merge_uncertainties(state, list(envelope.get("uncertainties") or []))
        knowledge_event_id = state_mgr.record_event(
            event_type="knowledge_updated",
            source_agent="knowledge_agent",
            summary=(
                f"Real Knowledge Agent committed iteration {state.iteration - 1}; "
                f"event_count={knowledge_state.get('event_count', 0)}"
            ),
            data={
                "decision": envelope.get("decision"),
                "updated_hypotheses": updated_hypotheses,
                "settled_candidates": settled_candidates,
            },
        )
        real_event_ids = [
            str(item["event_id"])
            for item in (envelope.get("decision") or {}).get("new_events") or []
            if item.get("event_id")
        ]
        return {
            "agent": self.name,
            "status": "success",
            "iteration": state.iteration,
            "knowledge_event_count": knowledge_state.get("event_count", 0),
            "updated_hypotheses": updated_hypotheses,
            "settled_candidates": settled_candidates,
            "output_ids": [knowledge_event_id, *real_event_ids],
            "real_agent": envelope.get("agent"),
        }


__all__ = ["RealAnalysisAdapter", "RealCriticAdapter", "RealKnowledgeAdapter"]
