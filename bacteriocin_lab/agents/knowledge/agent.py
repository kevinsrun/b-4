"""The Knowledge / Research-State Agent: the Omnigent-callable interface.

A structured scientific state manager, not a memory chatbot: every operation is deterministic,
every belief change is a recorded transition, and the whole state can be rebuilt from its event
log. It does no science itself -- it records what the other agents concluded, says what changed,
and reports what is still open.

JSON in, ``AgentResponseEnvelope`` out; it never raises across the tool boundary. Two modes:

* **persisted** -- ``state_dir`` (or ``BACTERIOCIN_STATE_DIR``) names the store; the state is read
  from and committed to its event log, so a stateless MCP call sequence accumulates real history;
* **pure** -- ``previous_state`` is supplied and the updated state is returned in
  ``artifacts.updated_state``; nothing is written.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ValidationError

from bacteriocin_lab.shared import ResearchState, UpdatedResearchState
from bacteriocin_lab.shared.contract import (
    AgentResponseEnvelope,
    RecommendedNextAction,
    Uncertainty,
)

from . import manager as pure
from . import queries
from .errors import KnowledgeError, NotFound, StateConflict, StateInputError, StateIntegrityError
from .manager import ResearchStateManager
from .policy import StatePolicy
from .session import Clock
from .store import InMemoryStateStore, JsonFileStateStore

logger = logging.getLogger(__name__)

AGENT_NAME = "knowledge_agent"

#: Bump on any change that can alter output for identical input.
MODEL_VERSION = "knowledge-state/0.1.0"

STATE_DIR_ENV = "BACTERIOCIN_STATE_DIR"

MUTATING = {
    "initialize_state",
    "register_candidates",
    "record_experiment_plan",
    "register_evidence",
    "update_state",
    "reject_candidate",
    "close_question",
}
QUERIES = {
    "get_candidate_history",
    "get_hypothesis_history",
    "get_experiment_history",
    "get_open_questions",
    "summarize_current_state",
    "verify_integrity",
    "state_at_iteration",
}
OPERATIONS = sorted(MUTATING | QUERIES)

_UNCERTAINTY_KINDS = {"aleatoric", "epistemic", "data-gap", "model-limitation", "contract-gap"}


class KnowledgeAgent:
    def __init__(
        self,
        *,
        state_dir: str | os.PathLike[str] | None = None,
        clock: Clock | None = None,
        policy: StatePolicy | None = None,
    ) -> None:
        self.default_state_dir = state_dir or os.environ.get(STATE_DIR_ENV)
        self.clock, self.policy = clock, policy

    # ------------------------------------------------------------------
    def run_envelope(self, payload: dict[str, Any]) -> AgentResponseEnvelope:
        op = payload.get("operation") if isinstance(payload, dict) else None
        try:
            if op not in OPERATIONS:
                raise StateInputError(f"operation must be one of {OPERATIONS}; got {op!r}")
            return self._dispatch(op, payload)
        except StateConflict as exc:
            return self._failure(op, "conflict", str(exc))
        except NotFound as exc:
            return self._failure(op, "not_found", str(exc))
        except (StateInputError, ValidationError, KeyError, TypeError, ValueError) as exc:
            return self._failure(op, "error", f"{type(exc).__name__}: {exc}")
        except (StateIntegrityError, KnowledgeError) as exc:
            logger.error("integrity failure: %s", exc)
            return self._failure(op, "integrity_error", str(exc))
        except Exception as exc:
            logger.exception("knowledge agent failed")
            return self._failure(op, "error", f"Internal error: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    def _source(
        self, payload: dict[str, Any]
    ) -> tuple[ResearchStateManager | None, ResearchState | None]:
        """(manager, None) in persisted mode; (None, state) in pure mode."""
        directory = payload.get("state_dir") or self.default_state_dir
        if directory and payload.get("previous_state") is None:
            return ResearchStateManager(
                JsonFileStateStore(directory), clock=self.clock, policy=self.policy
            ), None
        if payload.get("previous_state") is not None:
            return None, ResearchState.model_validate(payload["previous_state"])
        return None, None

    def _dispatch(self, op: str, p: dict[str, Any]) -> AgentResponseEnvelope:
        mgr, pure_state = self._source(p)
        if op == "verify_integrity":
            # Must not load the state first: on a damaged log loading fails, and diagnosing that is the point.
            if mgr is None:
                raise StateInputError("verify_integrity needs the event log: pass state_dir")
            return self._verify(mgr)
        if op in QUERIES:
            if mgr is None and pure_state is None:
                raise StateInputError(
                    f"{op} needs a state: pass state_dir (or set {STATE_DIR_ENV}) or previous_state"
                )
            return self._query(op, p, mgr, pure_state if pure_state is not None else mgr.state())  # type: ignore[union-attr]

        def need(*names: str) -> list[Any]:
            missing = [n for n in names if p.get(n) in (None, "")]
            if missing:
                raise StateInputError(f"{op} requires: {', '.join(missing)}")
            return [p[n] for n in names]

        if mgr is None:  # pure mode (or no state yet): same operations on an in-memory log
            mgr = ResearchStateManager(InMemoryStateStore(), clock=self.clock, policy=self.policy)
            if pure_state is not None:
                # Replaying is impossible without the log; operate purely on the supplied state instead.
                return self._mutate_pure(op, p, pure_state, need)
        updated = self._apply(mgr, op, p, need)
        persisted = isinstance(mgr.store, JsonFileStateStore)
        updated.persisted = persisted
        return self._mutation_envelope(op, updated, store=mgr.store if persisted else None)

    @staticmethod
    def _apply(mgr: ResearchStateManager, op: str, p: dict[str, Any], need) -> UpdatedResearchState:
        if op == "initialize_state":
            return mgr.initialize(need("objective")[0])
        if op == "register_candidates":
            return mgr.register_candidates(need("candidate_output")[0])
        if op == "record_experiment_plan":
            return mgr.record_experiment_plan(need("plan")[0])
        if op == "register_evidence":
            return mgr.register_evidence(need("evidence")[0])
        if op == "reject_candidate":
            c, r = need("candidate_id", "reason")
            return mgr.reject_candidate(c, r, triggered_by=p.get("triggered_by"))
        if op == "close_question":
            q, r = need("question_id", "reason")
            return mgr.close_question(q, r, triggered_by=p.get("triggered_by"))
        (analysis,) = need("analysis_result")
        context = {k: p.get(k) for k in ("result", "spec", "hypothesis", "candidate", "evidence")}
        return mgr.update_state(
            analysis,
            expected_event_count=p.get("expected_event_count"),
            advance_iteration=p.get("advance_iteration", True),
            **context,
        )

    def _mutate_pure(
        self, op: str, p: dict[str, Any], state: ResearchState, need
    ) -> AgentResponseEnvelope:
        kw = {"clock": self.clock, "policy": self.policy}
        if op == "initialize_state":
            updated = pure.initialize_state(need("objective")[0], state, **kw)
        elif op == "register_candidates":
            updated = pure.register_candidates(state, need("candidate_output")[0], **kw)
        elif op == "record_experiment_plan":
            updated = pure.record_experiment_plan(state, need("plan")[0], **kw)
        elif op == "register_evidence":
            updated = pure.register_evidence(state, need("evidence")[0], **kw)
        elif op == "reject_candidate":
            c, r = need("candidate_id", "reason")
            updated = pure.reject_candidate(state, c, r, triggered_by=p.get("triggered_by"), **kw)
        elif op == "close_question":
            q, r = need("question_id", "reason")
            updated = pure.close_question(state, q, r, triggered_by=p.get("triggered_by"), **kw)
        else:
            (analysis,) = need("analysis_result")
            updated = pure.update_state(
                state,
                analysis,
                advance_iteration=p.get("advance_iteration", True),
                expected_event_count=p.get("expected_event_count"),
                **{k: p.get(k) for k in ("result", "spec", "hypothesis", "candidate", "evidence")},
                **kw,
            )
        return self._mutation_envelope(op, updated, store=None)

    # ------------------------------------------------------------------
    def _query(
        self, op: str, p: dict[str, Any], mgr: ResearchStateManager | None, state: ResearchState
    ) -> AgentResponseEnvelope:
        artifacts: dict[str, Any] = {}
        if op == "get_candidate_history":
            result: Any = queries.get_candidate_history(state, p["candidate_id"])
        elif op == "get_hypothesis_history":
            result = queries.get_hypothesis_history(state, p["hypothesis_id"])
        elif op == "get_experiment_history":
            result = queries.get_experiment_history(
                state, candidate_id=p.get("candidate_id"), hypothesis_id=p.get("hypothesis_id")
            )
        elif op == "get_open_questions":
            result = queries.get_open_questions(state)
        elif op == "summarize_current_state":
            result = queries.summarize_current_state(state)
        elif op == "state_at_iteration":
            if mgr is None:
                raise StateInputError(
                    "state_at_iteration needs the event log: pass state_dir, not previous_state"
                )
            past = mgr.state_at_iteration(int(p["iteration"]))
            result = queries.summarize_current_state(past)
            artifacts["state"] = past.model_dump(mode="json")
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision={"operation": op, "status": "ok", "result": result},
            confidence=1.0,
            uncertainties=self._uncertainties(state),
            artifacts={"event_count": state.event_count, **artifacts},
            warnings=[],
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _verify(mgr: ResearchStateManager) -> AgentResponseEnvelope:
        problems = mgr.verify_integrity()
        try:
            events = mgr.store.events()
        except KnowledgeError:
            events = []
        result = {
            "intact": not problems,
            "problems": problems,
            "event_count": len(events),
            "last_event_hash": events[-1].event_hash if events else None,
        }
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision={
                "operation": "verify_integrity",
                "status": "ok" if not problems else "integrity_error",
                "result": result,
            },
            confidence=1.0 if not problems else 0.0,
            warnings=list(problems),
            artifacts={"event_count": len(events)},
            uncertainties=[]
            if not problems
            else [
                Uncertainty(
                    kind="data-gap",
                    description="The event log failed verification; the recorded history cannot be trusted until it is restored.",
                    severity="high",
                )
            ],
            model_version=MODEL_VERSION,
        )

    def _mutation_envelope(
        self, op: str, updated: UpdatedResearchState, *, store: JsonFileStateStore | None
    ) -> AgentResponseEnvelope:
        state = updated.state
        summary = queries.summarize_current_state(state)
        compact_events = [
            {
                k: v
                for k, v in e.model_dump(mode="json").items()
                if k not in ("prev_hash", "event_hash")
            }
            for e in updated.new_events
        ]
        decision = {
            "operation": op,
            "status": "ok",
            "persisted": updated.persisted,
            "iteration": state.iteration,
            "event_count": state.event_count,
            "last_event_hash": state.last_event_hash,
            "new_event_count": len(updated.new_events),
            "new_events": compact_events,
            "hypothesis_transitions": [self._brief(t) for t in updated.hypothesis_transitions],
            "candidate_transitions": [self._brief(t) for t in updated.candidate_transitions],
            "relationship_changes": [self._brief(t) for t in updated.relationship_changes],
            "state_summary": summary,
        }
        warnings = list(updated.warnings)
        artifacts: dict[str, Any] = {
            "event_count": state.event_count,
            "last_event_hash": state.last_event_hash,
        }
        if store is not None:
            artifacts.update(
                state_dir=str(store.directory),
                events_path=str(store.events_path),
                state_path=str(store.state_path),
            )
        else:
            artifacts["updated_state"] = state.model_dump(mode="json")
            warnings.append(
                "Not persisted: no state_dir was given, so the updated state is returned in artifacts.updated_state and nothing was written."
            )
        hint = {
            "open_questions": [q["text"] for q in summary["open_questions"][:5]],
            "hypothesis_statuses": {h["hypothesis_id"]: h["status"] for h in summary["hypotheses"]},
            "rejected_hypothesis_ids": [h["hypothesis_id"] for h in summary["rejected_hypotheses"]],
            "contested_hypothesis_ids": [
                h["hypothesis_id"] for h in summary["hypotheses"] if h["contested"]
            ],
        }
        nxt = (
            RecommendedNextAction(
                agent="experiment_planner",
                reason="State updated; plan the next experiment from the open questions and the hypotheses that are still undecided or contested.",
                payload_hint=hint,
            )
            if op == "update_state"
            else None
        )
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision=decision,
            confidence=1.0,
            uncertainties=self._uncertainties(state),
            artifacts=artifacts,
            warnings=warnings,
            recommended_next_action=nxt,
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _brief(event: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v
            for k, v in event.items()
            if k not in ("prev_hash", "event_hash", "timestamp", "seq")
        }

    @staticmethod
    def _uncertainties(state: ResearchState, limit: int = 8) -> list[Uncertainty]:
        out = []
        for u in queries.active_uncertainties(state, min_severity="medium")[:limit]:
            kind = u["kind"] if u["kind"] in _UNCERTAINTY_KINDS else "epistemic"
            out.append(
                Uncertainty(
                    kind=kind,
                    description=u["description"],
                    affects=u["affects"],
                    severity=u["severity"]
                    if u["severity"] in ("low", "medium", "high")
                    else "medium",
                )
            )
        return out

    @staticmethod
    def _failure(op: str | None, status: str, message: str) -> AgentResponseEnvelope:
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision={"operation": op, "status": status, "error": message},
            confidence=0.0,
            uncertainties=[Uncertainty(kind="data-gap", description=message, severity="high")],
            warnings=[message],
            model_version=MODEL_VERSION,
        )


_DEFAULT: KnowledgeAgent | None = None


def knowledge_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Omnigent-callable entry point: JSON in, contract-shaped JSON out. Never raises.

    ``payload["operation"]`` is one of :data:`OPERATIONS`; the other keys are that operation's
    arguments plus an optional ``state_dir`` / ``previous_state``.
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = KnowledgeAgent()
    return _DEFAULT.run_envelope(payload).model_dump(mode="json")


__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "OPERATIONS",
    "STATE_DIR_ENV",
    "KnowledgeAgent",
    "knowledge_call",
]
