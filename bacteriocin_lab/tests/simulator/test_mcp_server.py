"""Tests for the MCP transport.

The server must not be a place where behaviour hides. These tests assert that
it is a faithful pass-through: same numbers as the direct API, errors returned
as structured payloads rather than raised, and nothing exposed that was not
deliberately registered.

Skipped entirely when the optional ``mcp`` extra is absent, so the core model
keeps testing without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="requires the optional 'mcp' extra")

from bacteriocin_lab.agents.simulator import mcp_server as srv  # noqa: E402
from bacteriocin_lab.agents.simulator import run_agent as direct_run_agent  # noqa: E402
from bacteriocin_lab.agents.simulator import run_experiment as direct_run_experiment  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "evaluation" / "examples" / "simulator"
SPEC = json.loads((EXAMPLES / "spec_nisin_listeria.json").read_text())
ENVELOPE = json.loads((EXAMPLES / "agent_envelope.json").read_text())

#: Every tool the agent config allow-lists. Kept here as a literal so that
#: adding a tool to the server without deciding to expose it fails a test.
EXPECTED_TOOLS = {
    "capabilities",
    "describe",
    "get_schema",
    "run_agent",
    "run_experiment",
    "run_experiments",
    "selftest",
}


@pytest.mark.anyio
async def test_registered_tools_are_exactly_the_declared_surface() -> None:
    tools = await srv.server.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.mark.anyio
async def test_every_tool_carries_a_description() -> None:
    for tool in await srv.server.list_tools():
        assert tool.description, f"{tool.name} has no description"


def test_run_experiment_matches_the_direct_api_exactly() -> None:
    """The transport must not perturb a single digit."""
    through_mcp = srv.run_experiment(SPEC)
    direct = direct_run_experiment(SPEC).to_json_dict()
    for payload in (through_mcp, direct):
        payload.pop("created_at", None)
    assert through_mcp == direct


def test_run_agent_matches_the_direct_api() -> None:
    through_mcp = srv.run_agent(ENVELOPE)
    direct = direct_run_agent(ENVELOPE).to_json_dict()
    assert through_mcp["decision"] == direct["decision"]
    assert through_mcp["recommended_next_action"] == direct["recommended_next_action"]
    assert [e["evidence_id"] for e in through_mcp["evidence"]] == [
        e["evidence_id"] for e in direct["evidence"]
    ]


def test_results_are_json_serialisable() -> None:
    json.dumps(srv.run_experiment(SPEC))
    json.dumps(srv.run_agent(ENVELOPE))
    json.dumps(srv.capabilities())
    json.dumps(srv.describe())


def test_a_malformed_spec_returns_a_structured_error_not_an_exception() -> None:
    out = srv.run_experiment({"not": "a spec"})
    assert out["error_code"] == "spec_validation_error"
    assert "message" in out


def test_an_unavailable_backend_is_reported_structurally() -> None:
    spec = json.loads(json.dumps(SPEC))
    spec["conditions"]["assay_domain"] = "wet_lab_in_vitro"
    out = srv.run_experiment(spec)
    assert out["error_code"] == "backend_unavailable"


def test_one_bad_spec_does_not_sink_a_batch() -> None:
    out = srv.run_experiments([SPEC, {"bogus": True}])
    assert isinstance(out, list) and len(out) == 2
    assert out[0]["status"] == "ok"
    assert out[1]["status"] == "failed"
    assert out[1]["error"]["error_code"] == "spec_validation_error"


def test_batch_preserves_input_order() -> None:
    second = json.loads(json.dumps(SPEC))
    second["experiment_id"] = "exp-second"
    out = srv.run_experiments([SPEC, second])
    assert [r["experiment_id"] for r in out] == [SPEC["experiment_id"], "exp-second"]


@pytest.mark.parametrize(
    "name", ["experiment_spec", "experiment_result", "agent_input", "agent_output"]
)
def test_each_schema_is_retrievable(name: str) -> None:
    schema = srv.get_schema(name)
    assert "properties" in schema


def test_schema_all_returns_every_model() -> None:
    assert set(srv.get_schema("all")) == {
        "experiment_spec",
        "experiment_result",
        "agent_input",
        "agent_output",
    }


def test_unknown_schema_is_reported_not_raised() -> None:
    out = srv.get_schema("nonsense")
    assert out["error_code"] == "unknown_schema"
    assert "experiment_spec" in out["details"]["available"]


def test_capabilities_declares_both_backends() -> None:
    caps = srv.capabilities()
    assert set(caps["backends"]) == {"simulation", "wet_lab"}
    assert caps["backends"]["wet_lab"]["available"] is False


def test_selftest_invariants_pass_through_the_server() -> None:
    report = srv.selftest()
    assert report["passed"] is True
    assert report["n_failed"] == 0


def test_the_server_cannot_launder_a_result_into_wet_lab_evidence() -> None:
    """Agent rule 9 must survive the transport."""
    assert srv.run_experiment(SPEC)["evidence_type"] == "simulation-derived"
    assert srv.run_experiment(SPEC)["validated_experimentally"] is False
