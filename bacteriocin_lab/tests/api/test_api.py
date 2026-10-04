"""The HTTP layer forwards; it does not decide.

These tests check the two properties the API is supposed to have: a request
reaches the right specialist, and the specialist's own output comes back
without the transport editing it. Anything that asserts a scientific value
belongs in that agent's own tests, not here.

Network-backed literature retrieval is not exercised: it reaches Europe PMC,
so it is covered by the evidence agent's tests with a stub transport.
"""

from __future__ import annotations

import time

import pytest

from bacteriocin_lab.agents.simulator.selftest import run_selftest

fastapi = pytest.importorskip("fastapi", reason="the web extra is not installed")
from fastapi.testclient import TestClient  # noqa: E402

from bacteriocin_lab.api import create_app  # noqa: E402

OBJECTIVE = {
    "goal": "Find a candidate effective against high-density Listeria monocytogenes.",
    "species": "Listeria monocytogenes",
    "gram": "positive",
    "target_cell_density": 1e8,
    "max_iterations": 3,
    "seed": 42,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _await_run(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] != "running":
            return payload
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


class TestMeta:
    def test_health(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["schema_version"]

    def test_agent_roster_covers_every_loop_role(self, client: TestClient) -> None:
        body = client.get("/api/agents").json()
        roles = {a["role"] for a in body["agents"]}
        assert roles == set(body["loop"])

    def test_roster_states_a_claim_for_every_agent(self, client: TestClient) -> None:
        # The provenance labelling in the UI is driven by these, so an agent
        # without one would be shown as making no claim at all.
        for agent in client.get("/api/agents").json()["agents"]:
            assert agent["produces"] and agent["claim"]


class TestSimulator:
    def test_selftest_is_passed_through_unchanged(self, client: TestClient) -> None:
        served = client.get("/api/simulator/selftest").json()
        direct = run_selftest()
        assert served["n_checks"] == direct["n_checks"]
        assert served["passed"] == direct["passed"]
        # Known failures are reported, not filtered out.
        assert served["n_known_failures"] == direct["n_known_failures"]

    def test_experiment_returns_a_simulation_derived_result(self, client: TestClient) -> None:
        spec = {
            "experiment_id": "api-test-1",
            "candidate_id": "nisin",
            "target": {"species": "Listeria monocytogenes"},
            "conditions": {
                "bacteriocin_concentration": {"value": 2.0, "unit": "uM"},
                "target_cell_density": {"value": 1e6, "unit": "cfu_per_ml"},
                "ph": 6.5,
                "assay_domain": "simulated_in_vitro",
            },
        }
        registry = {
            "nisin": {
                "candidate_id": "nisin",
                "name": "nisin A",
                "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            }
        }
        body = client.post(
            "/api/simulator/experiment", json={"spec": spec, "candidate_registry": registry}
        ).json()
        assert body["evidence_type"] == "simulation-derived"
        assert body["validated_experimentally"] is False

    def test_invalid_spec_is_a_422_not_a_500(self, client: TestClient) -> None:
        response = client.post("/api/simulator/experiment", json={"spec": {"conditions": 7}})
        assert response.status_code == 422

    def test_batch_isolates_a_bad_spec(self, client: TestClient) -> None:
        good = {
            "experiment_id": "ok",
            "target": {"species": "Listeria monocytogenes"},
            "conditions": {"bacteriocin_concentration": 1.0, "assay_domain": "simulated_in_vitro"},
        }
        results = client.post(
            "/api/simulator/experiments", json={"specs": [good, {"conditions": 7}]}
        ).json()["results"]
        assert len(results) == 2
        assert results[1]["status"] == "failed"

    def test_reference_bacteriocins_come_from_the_knowledge_source(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/reference-bacteriocins").json()
        assert body["source_name"]
        assert any(r.get("sequence") for r in body["records"])


class TestCandidates:
    def test_proposals_are_never_marked_validated(self, client: TestClient) -> None:
        body = client.post(
            "/api/candidates",
            json={"species": "Listeria monocytogenes", "gram": "positive", "max_candidates": 3},
        ).json()
        candidates = body["decision"]["candidates"]
        assert candidates
        assert all(c["validation_status"] == "unvalidated" for c in candidates)

    def test_gram_is_required(self, client: TestClient) -> None:
        # Omitting it would skip envelope-accessibility reasoning silently, so
        # the API refuses rather than defaulting.
        response = client.post("/api/candidates", json={"species": "Listeria monocytogenes"})
        assert response.status_code == 422


class TestRuns:
    def test_a_run_completes_and_exposes_the_loop_verdict(self, client: TestClient) -> None:
        started = client.post("/api/runs", json=OBJECTIVE).json()
        finished = _await_run(client, started["run_id"])

        assert finished["status"] == "finished"
        assert finished["engine_status"] in {"completed", "stopped", "max_iterations", "failed"}
        assert finished["state"]["results"]
        assert finished["execution_trace"]

    def test_events_are_indexed_and_never_skip(self, client: TestClient) -> None:
        started = client.post("/api/runs", json=OBJECTIVE).json()
        run_id = started["run_id"]
        _await_run(client, run_id)

        everything = client.get(f"/api/runs/{run_id}/events").json()["events"]
        assert everything[0]["type"] == "run_started"
        assert everything[-1]["type"] == "run_finished"
        assert [e["seq"] for e in everything] == list(range(1, len(everything) + 1))

        # A reader that has seen n events gets exactly the rest.
        tail = client.get(f"/api/runs/{run_id}/events?since=3").json()["events"]
        assert tail == everything[3:]

    def test_reported_events_carry_the_engines_own_summaries(self, client: TestClient) -> None:
        started = client.post("/api/runs", json=OBJECTIVE).json()
        run_id = started["run_id"]
        finished = _await_run(client, run_id)

        streamed = [
            event
            for item in client.get(f"/api/runs/{run_id}/events").json()["events"]
            for event in item.get("events", [])
        ]
        recorded = finished["state"]["scientific_history"]
        # Every log entry the stream reported is one the run actually recorded.
        assert {e["event_id"] for e in streamed} <= {e["event_id"] for e in recorded}
        assert streamed

    def test_same_objective_and_seed_gives_the_same_run(self, client: TestClient) -> None:
        first = _await_run(client, client.post("/api/runs", json=OBJECTIVE).json()["run_id"])
        second = _await_run(client, client.post("/api/runs", json=OBJECTIVE).json()["run_id"])
        assert first["engine_run_id"] == second["engine_run_id"]
        assert first["summary"] == second["summary"]

    def test_iteration_ceiling_is_enforced(self, client: TestClient) -> None:
        response = client.post("/api/runs", json={**OBJECTIVE, "max_iterations": 500})
        assert response.status_code == 422

    def test_unknown_run_is_404(self, client: TestClient) -> None:
        assert client.get("/api/runs/nope").status_code == 404


class TestKnowledge:
    def test_only_read_operations_are_exposed(self, client: TestClient) -> None:
        # Writing to the recorded history belongs to the loop, not to a browser.
        assert client.get("/api/knowledge/update_state").status_code == 404

    def test_integrity_without_a_store_reports_rather_than_raises(self, client: TestClient) -> None:
        body = client.get("/api/knowledge/integrity").json()
        assert "decision" in body or "status" in body


class TestTargetDesignAPI:
    def test_design_target_endpoint(self, client: TestClient) -> None:
        response = client.post(
            "/api/design/target",
            json={"target_organism": "Listeria monocytogenes", "seed": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert "target" in data
        assert data["target"]["organism"] == "Listeria monocytogenes"
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0
        assert "best_current_candidate" in data
        assert "future_production_concept" in data
        assert data["future_production_concept"]["status"] == "requires_specialist_review"
