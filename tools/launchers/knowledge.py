#!/usr/bin/env python3
"""MCP server exposing the Knowledge / Research-State Agent to Omnigent.

The research state is the memory of the whole loop: what it believed, why, which experiments
produced which results, which hypotheses survived and which candidates were rejected, and what is
still uncertain. This adapter makes it callable between steps, so a *stateless* sequence of MCP
calls accumulates real, reconstructable history on disk.

Same design rules as the other launchers, which came out of live runs:

* **Flat, annotated parameters** rather than one nested ``request`` dict.
* **Compact replies, provenance and warnings first**, so truncation cannot eat the caveats.
* Large inputs (a candidate envelope, an analysis envelope) can be passed **by path**: the
  candidate launcher already writes its full envelope to a file and returns the path.

Where the state lives: ``state_dir`` if given, else ``BACTERIOCIN_STATE_DIR``, else
``<repo>/artifacts/research_state``. The directory holds an append-only, hash-chained
``events.jsonl`` (authoritative) and a derived ``state.json``.

Run standalone for a smoke test::

    PYTHONPATH=. \\
        python3 tools/launchers/knowledge.py --selftest
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

REPO = Path(__file__).resolve().parent.parent.parent
# The launcher may be started from anywhere, so locate the package relative to this file.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pydantic import Field  # noqa: E402

from bacteriocin_lab.agents.knowledge import AGENT_NAME, MODEL_VERSION, KnowledgeAgent  # noqa: E402

# stdio is the MCP channel, so logs must never go to stdout.
logging.basicConfig(
    level=os.environ.get("BACTERIOCIN_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bacteriocin.knowledge.mcp")

DEFAULT_STATE_DIR = Path(
    os.environ.get("BACTERIOCIN_STATE_DIR") or REPO / "artifacts" / "research_state"
)
MAX_INPUT_BYTES = 20_000_000

PROVENANCE = (
    "RECORD KEEPING, NOT NEW FINDINGS. This state records what other agents concluded; most of it is "
    "simulation-derived or model-predicted and nothing in it is experimentally validated unless a "
    "result is explicitly wet-lab-derived. Hypotheses are inferred, not facts. History is append-only: "
    "a changed belief is a recorded transition, never an overwrite."
)

TOOL_NOTES = """\
Records and queries the persistent scientific state of the discovery programme. Deterministic: \
identical arguments against identical history give identical output. It never does science, never \
invents evidence, and never overwrites history: a hypothesis moving from supported to weakened keeps \
both states, in order, with the experiment and finding that triggered it.

Status vocabulary: hypotheses are open / supported / weakened / rejected. An INCONCLUSIVE analysis \
never changes a hypothesis (it is recorded as an observation and the hypothesis is untouched). \
A result is never 'validated'.
"""


#: Module level on purpose: the SDK resolves annotation strings (this module uses
#: ``from __future__ import annotations``) against module globals, not enclosing scopes.
StateDir = Annotated[
    str | None,
    Field(
        description="Directory holding this research state. Omit to use the configured default (BACTERIOCIN_STATE_DIR)."
    ),
]


def _load_json_file(path: str, label: str) -> Any:
    p = Path(path).expanduser()
    if p.suffix.lower() != ".json" or not p.is_file():
        raise ValueError(f"{label} must be the path of an existing .json file; got {path!r}")
    if p.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{label} is larger than {MAX_INPUT_BYTES // 1_000_000} MB")
    return json.loads(p.read_text(encoding="utf-8"))


def _agent(state_dir: str | None) -> KnowledgeAgent:
    return KnowledgeAgent(state_dir=state_dir or DEFAULT_STATE_DIR)


def _text_or_obj(value: Any, label: str) -> Any:
    """Models sometimes pass a JSON object as a string; accept both."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError as exc:
            raise ValueError(f"{label} must be a JSON object, not free text") from exc
    return value


def _shape(envelope: dict[str, Any], *, max_items: int = 50) -> dict[str, Any]:
    """A few-KB reply: provenance and warnings lead, so truncation cannot remove them."""
    d = envelope.get("decision") or {}
    out: dict[str, Any] = {
        "PROVENANCE": PROVENANCE,
        "warnings": envelope.get("warnings") or [],
        "agent": envelope.get("agent"),
        "model_version": envelope.get("model_version"),
        "operation": d.get("operation"),
        "status": d.get("status"),
    }
    if d.get("status") != "ok":
        out["error"] = d.get("error")
        if (
            "result" in d
        ):  # e.g. the list of integrity problems: a failure report must carry its evidence
            out["result"] = d["result"]
        return out
    unc = [u for u in envelope.get("uncertainties") or [] if isinstance(u, dict)]
    out["high_severity_uncertainties"] = [
        u["description"] for u in unc if u.get("severity") == "high"
    ]
    if "new_events" in d:  # a mutating operation
        s = d["state_summary"]
        out.update(
            persisted=d["persisted"],
            state_dir=(envelope.get("artifacts") or {}).get("state_dir"),
            iteration=d["iteration"],
            event_count=d["event_count"],
            last_event_hash=d["last_event_hash"],
            new_event_count=d["new_event_count"],
            new_event_types=dict(Counter(e["event"] for e in d["new_events"])),
            hypothesis_transitions=d["hypothesis_transitions"],
            candidate_transitions=d["candidate_transitions"],
            relationship_changes=d["relationship_changes"],
            hypotheses=[
                {
                    k: h[k]
                    for k in (
                        "hypothesis_id",
                        "status",
                        "contested",
                        "n_supporting",
                        "n_weakening",
                        "n_inconclusive",
                    )
                }
                for h in s["hypotheses"]
            ],
            rejected_hypotheses=s["rejected_hypotheses"],
            rejected_candidates=s["rejected_candidates"],
            n_open_questions=s["n_open_questions"],
            open_questions=[q["text"] for q in s["open_questions"][:5]],
        )
        if not d["persisted"]:
            out["updated_state_is_in_full_envelope"] = True
    else:
        result = d.get("result")
        if isinstance(result, list):
            out["count"], out["result"] = len(result), result[:max_items]
            if len(result) > max_items:
                out["truncated"] = (
                    f"showing {max_items} of {len(result)}; narrow with candidate_id/hypothesis_id"
                )
        elif (
            isinstance(result, dict)
            and isinstance(result.get("timeline"), list)
            and len(result["timeline"]) > max_items
        ):
            out["result"] = {**result, "timeline": result["timeline"][-max_items:]}
            out["truncated"] = (
                f"timeline shows the latest {max_items} of {len(result['timeline'])} entries"
            )
        else:
            out["result"] = result
    nxt = envelope.get("recommended_next_action")
    if nxt:
        out["recommended_next_action"] = {
            "agent": nxt.get("agent"),
            "reason": nxt.get("reason"),
            "payload_hint": nxt.get("payload_hint"),
        }
    return out


def _call(
    payload: dict[str, Any], *, state_dir: str | None, include_full_envelope: bool = False
) -> str:
    try:
        envelope = _agent(state_dir).run_envelope(payload).model_dump(mode="json")
    except Exception as exc:
        logger.exception("knowledge operation failed")
        envelope = {
            "agent": AGENT_NAME,
            "decision": {
                "operation": payload.get("operation"),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            },
            "warnings": [str(exc)],
            "model_version": MODEL_VERSION,
        }
    reply = _shape(envelope)
    if include_full_envelope:
        reply["envelope"] = envelope
    return json.dumps(reply, indent=2, default=str)


def build_server():
    """Construct a server compatible with MCP SDK 1.x (FastMCP) and 2.x (MCPServer)."""
    try:
        from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2
    except ModuleNotFoundError:
        from mcp.server.fastmcp import FastMCP as _ServerClass  # mcp 1.x

    server = _ServerClass(
        name="bacteriocin-knowledge",
        instructions=(
            "The persistent research state of an autonomous bacteriocin-discovery programme. Record-keeping only: "
            "append-only history, nothing validated, hypotheses are inferred."
        ),
    )

    @server.tool(
        name="initialize_research_state",
        description=TOOL_NOTES
        + "\nSet (or revise, preserving the old one) the research objective.",
    )
    def initialize_research_state(  # type: ignore[misc]
        objective: Annotated[
            dict[str, Any] | str,
            Field(
                description='The research objective as a JSON object, e.g. {"goal": "...", "target": "Listeria monocytogenes"}.'
            ),
        ],
        state_dir: StateDir = None,
    ) -> str:
        return _call(
            {"operation": "initialize_state", "objective": _text_or_obj(objective, "objective")},
            state_dir=state_dir,
        )

    @server.tool(
        name="register_candidates",
        description=TOOL_NOTES
        + "\nRecord the candidate agent's proposals: new candidates, their hypotheses, and this ranking. Accepts the full envelope or the compact reply.",
    )
    def register_candidates(  # type: ignore[misc]
        candidate_output: Annotated[
            dict[str, Any] | None,
            Field(description="The generate_candidates reply (full envelope or compact form)."),
        ] = None,
        candidate_output_path: Annotated[
            str | None,
            Field(
                description="Path to the full envelope .json (the candidates tool returns it as full_envelope_path). Use instead of candidate_output."
            ),
        ] = None,
        state_dir: StateDir = None,
    ) -> str:
        try:
            data = (
                _load_json_file(candidate_output_path, "candidate_output_path")
                if candidate_output_path
                else candidate_output
            )
        except (ValueError, OSError) as exc:
            return json.dumps({"PROVENANCE": PROVENANCE, "status": "error", "error": str(exc)})
        return _call(
            {
                "operation": "register_candidates",
                "candidate_output": _text_or_obj(data, "candidate_output"),
            },
            state_dir=state_dir,
        )

    @server.tool(
        name="record_experiment_plan",
        description=TOOL_NOTES
        + "\nRecord planned ExperimentSpec(s). Re-recording an identical spec is a no-op; a different spec for an existing experiment_id is refused rather than overwritten.",
    )
    def record_experiment_plan(  # type: ignore[misc]
        plan: Annotated[
            dict[str, Any] | list[dict[str, Any]],
            Field(
                description="One ExperimentSpec, a list of them, or an object with a 'specs' list."
            ),
        ],
        state_dir: StateDir = None,
    ) -> str:
        return _call({"operation": "record_experiment_plan", "plan": plan}, state_dir=state_dir)

    @server.tool(
        name="register_evidence",
        description=TOOL_NOTES
        + "\nRecord Evidence items (contract shape) with their provenance. Evidence types are preserved verbatim.",
    )
    def register_evidence(  # type: ignore[misc]
        evidence: Annotated[
            list[dict[str, Any]],
            Field(description="Evidence objects: evidence_id, evidence_type, claim, source, ..."),
        ],
        state_dir: StateDir = None,
    ) -> str:
        return _call({"operation": "register_evidence", "evidence": evidence}, state_dir=state_dir)

    @server.tool(
        name="update_research_state",
        description=TOOL_NOTES
        + "\nFold ONE Result Analysis output into the state: records the result and finding, applies the hypothesis transition (with previous and new status, and the experiment/finding that triggered it), updates known variable relationships, uncertainties, open questions and model versions, and closes the loop turn. Re-submitting an analysis already recorded changes nothing.",
    )
    def update_research_state(  # type: ignore[misc]
        analysis_result: Annotated[
            dict[str, Any] | None,
            Field(
                description="The Result Analysis envelope (or its decision): needs experiment_id, result_id, candidate_id, hypothesis_status (supported|weakened|inconclusive)."
            ),
        ] = None,
        analysis_result_path: Annotated[
            str | None,
            Field(description="Path to an analysis envelope .json, instead of analysis_result."),
        ] = None,
        result: Annotated[
            dict[str, Any] | None,
            Field(
                description="The ExperimentResult that was analysed. Strongly recommended: without it only the analysis's summary is recorded."
            ),
        ] = None,
        spec: Annotated[
            dict[str, Any] | None,
            Field(
                description="The ExperimentSpec, if the experiment was not recorded with record_experiment_plan."
            ),
        ] = None,
        hypothesis: Annotated[
            dict[str, Any] | None,
            Field(description="The hypothesis, if it was not registered earlier."),
        ] = None,
        candidate: Annotated[
            dict[str, Any] | None,
            Field(description="The candidate, if it was not registered earlier."),
        ] = None,
        evidence: Annotated[
            list[dict[str, Any]] | None,
            Field(description="Extra Evidence to record with this result."),
        ] = None,
        advance_iteration: Annotated[
            bool,
            Field(
                description="Close the current loop turn after this update. Pass false for all but the last result of a batch that shares a turn."
            ),
        ] = True,
        expected_event_count: Annotated[
            int | None,
            Field(
                description="Optimistic concurrency guard: refuse if the log has moved since you read event_count."
            ),
        ] = None,
        include_full_envelope: Annotated[
            bool, Field(description="Include the complete envelope (large: every new event).")
        ] = False,
        state_dir: StateDir = None,
    ) -> str:
        try:
            data = (
                _load_json_file(analysis_result_path, "analysis_result_path")
                if analysis_result_path
                else analysis_result
            )
        except (ValueError, OSError) as exc:
            return json.dumps({"PROVENANCE": PROVENANCE, "status": "error", "error": str(exc)})
        payload = {
            "operation": "update_state",
            "analysis_result": _text_or_obj(data, "analysis_result"),
            "result": result,
            "spec": spec,
            "hypothesis": hypothesis,
            "candidate": candidate,
            "evidence": evidence,
            "advance_iteration": advance_iteration,
            "expected_event_count": expected_event_count,
        }
        return _call(payload, state_dir=state_dir, include_full_envelope=include_full_envelope)

    @server.tool(
        name="reject_candidate",
        description=TOOL_NOTES
        + "\nManually reject a candidate, with a reason, as a recorded transition.",
    )
    def reject_candidate(  # type: ignore[misc]
        candidate_id: Annotated[str, Field(description="Candidate to reject.")],
        reason: Annotated[
            str, Field(min_length=3, description="Why. Recorded with the transition.")
        ],
        state_dir: StateDir = None,
    ) -> str:
        return _call(
            {"operation": "reject_candidate", "candidate_id": candidate_id, "reason": reason},
            state_dir=state_dir,
        )

    @server.tool(
        name="close_open_question",
        description=TOOL_NOTES
        + "\nClose a stored open question with a reason (derived questions close themselves when the state no longer implies them).",
    )
    def close_open_question(  # type: ignore[misc]
        question_id: Annotated[str, Field(description="question_id from get_open_questions.")],
        reason: Annotated[str, Field(min_length=3, description="Why it is closed.")],
        state_dir: StateDir = None,
    ) -> str:
        return _call(
            {"operation": "close_question", "question_id": question_id, "reason": reason},
            state_dir=state_dir,
        )

    @server.tool(
        name="get_candidate_history",
        description=TOOL_NOTES
        + "\nEverything recorded about one candidate: status changes, rankings, hypotheses, experiments, results, relationships, as one chronological timeline.",
    )
    def get_candidate_history(  # type: ignore[misc]
        candidate_id: Annotated[str, Field(description="Candidate ID.")],
        max_items: Annotated[
            int, Field(ge=1, le=500, description="Latest timeline entries to return.")
        ] = 50,
        state_dir: StateDir = None,
    ) -> str:
        return _shaped_query(
            {"operation": "get_candidate_history", "candidate_id": candidate_id},
            state_dir,
            max_items,
        )

    @server.tool(
        name="get_hypothesis_history",
        description=TOOL_NOTES
        + "\nA hypothesis's full timeline: every status it has had and why, and every analysis of it, including inconclusive ones that changed nothing.",
    )
    def get_hypothesis_history(  # type: ignore[misc]
        hypothesis_id: Annotated[str, Field(description="Hypothesis ID.")],
        max_items: Annotated[
            int, Field(ge=1, le=500, description="Latest timeline entries to return.")
        ] = 50,
        state_dir: StateDir = None,
    ) -> str:
        return _shaped_query(
            {"operation": "get_hypothesis_history", "hypothesis_id": hypothesis_id},
            state_dir,
            max_items,
        )

    @server.tool(
        name="get_experiment_history",
        description=TOOL_NOTES
        + "\nEvery experiment with its spec, results and findings, oldest first; optionally for one candidate or hypothesis.",
    )
    def get_experiment_history(  # type: ignore[misc]
        candidate_id: Annotated[
            str | None, Field(description="Only this candidate's experiments.")
        ] = None,
        hypothesis_id: Annotated[
            str | None, Field(description="Only this hypothesis's experiments.")
        ] = None,
        max_items: Annotated[
            int, Field(ge=1, le=500, description="Maximum experiments to return.")
        ] = 50,
        state_dir: StateDir = None,
    ) -> str:
        return _shaped_query(
            {
                "operation": "get_experiment_history",
                "candidate_id": candidate_id,
                "hypothesis_id": hypothesis_id,
            },
            state_dir,
            max_items,
        )

    @server.tool(
        name="get_open_questions",
        description=TOOL_NOTES
        + "\nWhat is still unanswered: questions raised by analyses plus those the current state implies (untested or contested hypotheses, unresolved variables).",
    )
    def get_open_questions(  # type: ignore[misc]
        max_items: Annotated[
            int, Field(ge=1, le=500, description="Maximum questions to return.")
        ] = 50,
        state_dir: StateDir = None,
    ) -> str:
        return _shaped_query({"operation": "get_open_questions"}, state_dir, max_items)

    @server.tool(
        name="summarize_research_state",
        description=TOOL_NOTES
        + "\nWhere the programme stands: objective, iteration, hypotheses by status, rejected hypotheses and candidates, latest ranking, known variable relationships, open questions, active uncertainties, model versions.",
    )
    def summarize_research_state(state_dir: StateDir = None) -> str:  # type: ignore[misc]
        return _shaped_query({"operation": "summarize_current_state"}, state_dir, 50)

    @server.tool(
        name="get_state_at_iteration",
        description=TOOL_NOTES
        + "\nReconstruct the state as it was when a past loop turn closed, from the event log alone.",
    )
    def get_state_at_iteration(  # type: ignore[misc]
        iteration: Annotated[int, Field(ge=0, description="Loop turn that had just closed.")],
        state_dir: StateDir = None,
    ) -> str:
        return _shaped_query(
            {"operation": "state_at_iteration", "iteration": iteration}, state_dir, 50
        )

    @server.tool(
        name="verify_state_integrity",
        description=TOOL_NOTES
        + "\nCheck the hash chain of the event log and that the derived snapshot matches a replay. Reports any sign that history was edited, removed or reordered.",
    )
    def verify_state_integrity(state_dir: StateDir = None) -> str:  # type: ignore[misc]
        return _shaped_query({"operation": "verify_integrity"}, state_dir, 50)

    return server


def _shaped_query(payload: dict[str, Any], state_dir: str | None, max_items: int) -> str:
    try:
        envelope = _agent(state_dir).run_envelope(payload).model_dump(mode="json")
    except Exception as exc:
        logger.exception("knowledge query failed")
        envelope = {
            "agent": AGENT_NAME,
            "decision": {
                "operation": payload["operation"],
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            },
            "warnings": [str(exc)],
        }
    return json.dumps(_shape(envelope, max_items=max_items), indent=2, default=str)


def _selftest() -> int:
    """Run a small campaign through the tool path against a throwaway state directory."""
    import asyncio

    server = build_server()
    tools = asyncio.run(server.list_tools())
    print("=== advertised tools (what the model sees) ===")
    for t in tools:
        print(f"  {t.name}: {len((t.inputSchema or {}).get('properties', {}))} parameters")

    state_dir = tempfile.mkdtemp(prefix="bacteriocin-state-")

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        out = asyncio.run(server.call_tool(name, {**args, "state_dir": state_dir}))
        text = out[0][0].text if isinstance(out, tuple) else out[0].text
        return json.loads(text)

    cand = {
        "decision": {
            "candidates": [
                {
                    "candidate_id": "cand_a",
                    "name": "A",
                    "rank": 1,
                    "score": {"total": 0.9},
                    "hypotheses": [
                        {
                            "hypothesis_id": "hyp_a",
                            "statement": "A inhibits",
                            "candidate_id": "cand_a",
                        }
                    ],
                }
            ]
        },
        "model_version": "candidate-generation/0.1.0",
    }

    def analysis(n: int, status: str) -> dict[str, Any]:
        return {
            "decision": {
                "finding_id": f"find_{n}",
                "experiment_id": f"exp_{n}",
                "result_id": f"res_{n}",
                "candidate_id": "cand_a",
                "hypothesis_id": "hyp_a",
                "hypothesis_status": status,
                "evidence_strength": "moderate",
            }
        }

    call("initialize_research_state", {"objective": {"goal": "selftest"}})
    call("register_candidates", {"candidate_output": cand})
    call("update_research_state", {"analysis_result": analysis(1, "supported")})
    out = call("update_research_state", {"analysis_result": analysis(2, "weakened")})
    (t,) = out["hypothesis_transitions"]
    print(
        f"\ntransition: {t['previous_status']} -> {t['new_status']} triggered_by {t['triggered_by']}"
    )
    hist = call("get_hypothesis_history", {"hypothesis_id": "hyp_a"})
    chain = [
        (c["from"], c["to"]) for c in hist["result"]["timeline"] if c["type"] == "status_change"
    ]
    intact = call("verify_state_integrity", {})["result"]["intact"]
    past = call("get_state_at_iteration", {"iteration": 1})
    print(
        f"status chain: {chain}\nintact: {intact}; state after turn 1 had hypothesis status: "
        f"{[h['status'] for h in past['result']['hypotheses']]}"
    )
    ok = (
        next(iter(out)) == "PROVENANCE"
        and chain == [(None, "open"), ("open", "supported"), ("supported", "weakened")]
        and intact
        and [h["status"] for h in past["result"]["hypotheses"]] == ["supported"]
        and len(json.dumps(out)) < 12000
    )
    print(f"\nprovenance first, history preserved, reconstructable, compact: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    build_server().run()
