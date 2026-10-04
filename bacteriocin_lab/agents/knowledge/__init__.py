"""Knowledge / research-state agent.

The persistent scientific state of the discovery programme: what it believed, why, which
experiments produced which results, which hypotheses survived and which candidates were
rejected, and what is still uncertain. A structured state manager, not a memory chatbot.

The state is an append-only, hash-chained event log; ``ResearchState`` is a pure projection of
it, so any past iteration can be reconstructed and no belief is ever silently overwritten.

From Omnigent::

    from bacteriocin_lab.agents.knowledge import knowledge_call

    knowledge_call({"operation": "update_state", "state_dir": "artifacts/research_state",
                    "analysis_result": analysis_envelope, "result": experiment_result})
"""

from .agent import AGENT_NAME, MODEL_VERSION, OPERATIONS, KnowledgeAgent, knowledge_call
from .errors import KnowledgeError, NotFound, StateConflict, StateInputError, StateIntegrityError
from .events import verify_chain
from .manager import (
    ResearchStateManager,
    close_question,
    initialize_state,
    record_experiment_plan,
    register_candidates,
    register_evidence,
    reject_candidate,
    update_state,
)
from .policy import DEFAULT_POLICY, StatePolicy
from .queries import (
    get_candidate_history,
    get_experiment_history,
    get_hypothesis_history,
    get_open_questions,
    summarize_current_state,
)
from .reducer import replay
from .store import InMemoryStateStore, JsonFileStateStore, StateStore

__all__ = [
    "AGENT_NAME",
    "DEFAULT_POLICY",
    "MODEL_VERSION",
    "OPERATIONS",
    "InMemoryStateStore",
    "JsonFileStateStore",
    "KnowledgeAgent",
    "KnowledgeError",
    "NotFound",
    "ResearchStateManager",
    "StateConflict",
    "StateInputError",
    "StateIntegrityError",
    "StatePolicy",
    "StateStore",
    "close_question",
    "get_candidate_history",
    "get_experiment_history",
    "get_hypothesis_history",
    "get_open_questions",
    "initialize_state",
    "knowledge_call",
    "record_experiment_plan",
    "register_candidates",
    "register_evidence",
    "reject_candidate",
    "replay",
    "summarize_current_state",
    "update_state",
    "verify_chain",
]
