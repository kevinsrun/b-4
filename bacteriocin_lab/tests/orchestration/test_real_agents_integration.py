"""Integration tests exercising the repository's real specialist agents."""

from __future__ import annotations

import json
from typing import Any

from bacteriocin_lab.agents.candidate import CandidateGenerationAgent, EmptyKnowledgeSource
from bacteriocin_lab.agents.evidence.models import LiteratureResponse
from bacteriocin_lab.orchestration import ResearchObjective, ResearchState, run_discovery
from bacteriocin_lab.orchestration.agent_adapters.candidate_adapter import CandidateAgentAdapter
from bacteriocin_lab.orchestration.agent_adapters.literature_adapter import LiteratureAgentAdapter
from bacteriocin_lab.orchestration.registry import AgentRegistry


class StaticLiteratureAgent:
    def __init__(self, response: LiteratureResponse) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def run(self, request: dict[str, Any]) -> LiteratureResponse:
        self.requests.append(request)
        return self.response


def _literature_record(evidence_id: str, name: str, activity: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source": {
            "source_id": f"doi:10.1000/{name.lower().replace(' ', '-')}",
            "title": f"Activity study for {name}",
            "doi_or_url": f"https://doi.org/10.1000/{name.lower().replace(' ', '-')}",
            "year": 2025,
        },
        "bacteriocin": {"name": name},
        "target": {"organism": "Listeria monocytogenes", "strain": "ATCC 19115"},
        "conditions": {"assay_domain": "in_vitro", "assay_type": "broth_microdilution"},
        "measurement": {
            "type": "antimicrobial_activity",
            "value": activity,
            "original_text": f"{name} was {activity} against Listeria monocytogenes",
            "data_role": "author-interpretation",
        },
        "claim": f"{name} was {activity} against Listeria monocytogenes.",
        "evidence_type": "literature-derived",
        "confidence": 0.8,
        "missing_variables": [
            "bacteriocin_sequence",
            "target_cell_density",
            "producer_cell_density",
        ],
        "provenance": {
            "locator": "Results, paragraph 2",
            "excerpt": f"{name} was {activity} against Listeria monocytogenes.",
            "extraction_method": "deterministic-rule",
        },
    }


def _literature_response(
    records: list[dict[str, Any]], contradictions: list[dict[str, Any]] | None = None
) -> LiteratureResponse:
    return LiteratureResponse.model_validate(
        {
            "query_id": "query_fixture",
            "decision": {
                "status": "evidence-collected",
                "candidate_decision": "not-performed",
                "documents_considered": len(records),
                "records_extracted": len(records),
            },
            "evidence": records,
            "knowledge_gaps": ["No extracted record reports bacteriocin sequence."],
            "contradictions": contradictions or [],
            "recommended_searches": [],
            "confidence": 0.8,
            "uncertainties": ["Fixture uncertainty retained."],
            "artifacts": {"source_ids": [record["source"]["source_id"] for record in records]},
            "warnings": [],
            "recommended_next_action": {
                "action": "review-evidence-and-search-gaps",
                "requires_codex_or_human_adjudication": True,
            },
        }
    )


def _rank_from_fixture(active_name: str) -> tuple[ResearchState, StaticLiteratureAgent]:
    x_activity = "active" if active_name == "Candidate X" else "inactive"
    y_activity = "active" if active_name == "Candidate Y" else "inactive"
    response = _literature_response(
        [
            _literature_record("ev_aaaaaaaaaaaaaaaaaaaaaaaa", "Candidate X", x_activity),
            _literature_record("ev_bbbbbbbbbbbbbbbbbbbbbbbb", "Candidate Y", y_activity),
        ]
    )
    literature_agent = StaticLiteratureAgent(response)
    state = ResearchState(
        objective=ResearchObjective(
            goal="Rank literature-supported candidates.",
            target={"species": "Listeria monocytogenes", "gram": "positive"},
            constraints={"max_candidates": 2},
        )
    )
    LiteratureAgentAdapter(literature_agent).run(state)  # type: ignore[arg-type]
    CandidateAgentAdapter().run(state)
    return state, literature_agent


def test_real_agents_discovery_turn() -> None:
    """Run one discovery turn with the real literature, candidate, planner, and simulator."""
    registry = AgentRegistry.default()

    objective = ResearchObjective(
        goal="Discover a bacteriocin against Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e6},
        constraints={"max_candidates": 2},
    )

    # Execute 1 turn with real agents
    result = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry,
        seed=42,
    )

    # Verify execution
    assert result.status in ("completed", "max_iterations")
    assert result.iterations_completed >= 1

    final_state = result.final_state
    assert len(final_state["candidates"]) >= 1
    assert len(final_state["experiments"]) >= 1
    assert len(final_state["results"]) >= 1
    assert len(final_state["findings"]) >= 1
    assert len(final_state["reviews"]) >= 1

    # Verify simulation result properties
    res = final_state["results"][0]
    assert res["evidence_type"] == "simulation-derived"
    assert res["validated_experimentally"] is False
    assert res["measurement"]["predicted_inhibition_fraction"] is not None


def test_literature_evidence_changes_real_candidate_ranking_and_preserves_provenance() -> None:
    state_a, literature_a = _rank_from_fixture("Candidate X")
    state_b, _literature_b = _rank_from_fixture("Candidate Y")

    assert state_a.candidates[0].name == "Candidate X"
    assert state_b.candidates[0].name == "Candidate Y"
    assert state_a.candidates[0].evidence_ids == ["ev_aaaaaaaaaaaaaaaaaaaaaaaa"]
    assert state_b.candidates[0].evidence_ids == ["ev_bbbbbbbbbbbbbbbbbbbbbbbb"]

    top_hypotheses = [
        hypothesis
        for hypothesis in state_a.hypotheses
        if hypothesis.candidate_id == state_a.candidates[0].candidate_id
    ]
    assert top_hypotheses
    assert top_hypotheses[0].evidence_ids == ["ev_aaaaaaaaaaaaaaaaaaaaaaaa"]

    stored = state_a.evidence[0].model_dump(mode="json")
    record = stored["literature_record"]
    assert stored["evidence_type"] == "literature-derived"
    assert stored["source_uri"] == "https://doi.org/10.1000/candidate-x"
    assert record["measurement"]["data_role"] == "author-interpretation"
    assert record["measurement"]["original_text"].startswith("Candidate X was active")
    assert record["missing_variables"] == [
        "bacteriocin_sequence",
        "producer_cell_density",
        "target_cell_density",
    ]
    assert record["provenance"]["locator"] == "Results, paragraph 2"
    assert stored["citation"] == record["source"]
    assert stored["provenance"] == record["provenance"]
    assert "wet-lab-derived" not in json.dumps(state_a.to_dict())

    # Offline remains the implicit default unless the objective opts in.
    assert literature_a.requests[0]["retrieval"] == {"enabled": False}
    assert "mode" not in literature_a.requests[0]


def test_literature_adapter_omits_candidate_payload_for_contested_and_ambiguous_records() -> None:
    contested_active = _literature_record("ev_cccccccccccccccccccccccc", "Candidate Z", "active")
    contested_inactive = _literature_record(
        "ev_dddddddddddddddddddddddd", "Candidate Z", "inactive"
    )
    ambiguous = _literature_record("ev_eeeeeeeeeeeeeeeeeeeeeeee", "Candidate Q", "uncertain")
    response = _literature_response(
        [contested_active, contested_inactive, ambiguous],
        contradictions=[
            {
                "contradiction_id": "cx_ffffffffffffffffffffffff",
                "evidence_ids": [
                    "ev_cccccccccccccccccccccccc",
                    "ev_dddddddddddddddddddddddd",
                ],
                "topic": "activity of Candidate Z against Listeria monocytogenes",
                "description": "Sources report opposing activity classifications.",
                "unresolved": True,
            }
        ],
    )
    state = ResearchState(objective=ResearchObjective(target={"species": "Listeria monocytogenes"}))

    LiteratureAgentAdapter(StaticLiteratureAgent(response)).run(state)  # type: ignore[arg-type]

    stored = [item.model_dump(mode="json") for item in state.evidence]
    assert all("candidate" not in item for item in stored)
    assert stored[0]["contradictions"][0]["unresolved"] is True
    assert stored[1]["contradictions"][0]["evidence_ids"] == [
        "ev_cccccccccccccccccccccccc",
        "ev_dddddddddddddddddddddddd",
    ]
    assert stored[2]["contradictions"] == []


def test_literature_objective_passthrough_is_bounded_and_explicit() -> None:
    agent = StaticLiteratureAgent(_literature_response([]))
    documents = [{"document": index} for index in range(105)]
    state = ResearchState(
        objective=ResearchObjective(
            target={"species": "Listeria monocytogenes"},
            constraints={
                "literature": {
                    "mode": "hybrid",
                    "bacteriocin": "nisin",
                    "source_documents": documents,
                    "retrieval": {
                        "enabled": True,
                        "sources": ["ncbi", "not-a-source"],
                        "max_results": 500,
                        "timeout_seconds": 500,
                    },
                }
            },
        )
    )

    LiteratureAgentAdapter(agent).run(state)  # type: ignore[arg-type]

    request = agent.requests[0]
    assert request["mode"] == "hybrid"
    assert request["bacteriocin"] == "nisin"
    assert len(request["source_documents"]) == 100
    assert request["retrieval"] == {
        "enabled": True,
        "sources": ["ncbi"],
        "max_results": 50,
        "timeout_seconds": 60.0,
    }


def test_candidate_adapter_accepts_injected_real_agent_envelope() -> None:
    response = _literature_response(
        [_literature_record("ev_999999999999999999999999", "Candidate X", "active")]
    )
    state = ResearchState(
        objective=ResearchObjective(
            target={"species": "Listeria monocytogenes", "gram": "positive"}
        )
    )
    LiteratureAgentAdapter(StaticLiteratureAgent(response)).run(state)  # type: ignore[arg-type]

    adapter = CandidateAgentAdapter(CandidateGenerationAgent(EmptyKnowledgeSource()))
    result = adapter.run(state)

    assert result["candidates_count"] == 1
    assert state.candidates[0].name == "Candidate X"
    assert state.candidates[0].evidence_ids == ["ev_999999999999999999999999"]
