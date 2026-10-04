"""When does the state change its mind? Explicit, configurable, and recorded with every transition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatePolicy:
    """Rules for hypothesis and candidate status transitions.

    * An **inconclusive** analysis never changes a hypothesis (it is recorded as an
      observation; the hypothesis is reported as untouched).
    * A **supported** analysis sets ``supported`` (and reopens a rejected hypothesis).
    * A **weakened** analysis sets ``weakened``, or ``rejected`` when the evidence was
      ``strong`` or the last ``reject_after_consecutive_weakened`` decisive results all
      weakened it.
    * A candidate is ``rejected`` when every one of its hypotheses is rejected.
    """

    reject_on_strong_weakening: bool = True
    reject_after_consecutive_weakened: int = 2
    reject_candidate_when_all_hypotheses_rejected: bool = True


DEFAULT_POLICY = StatePolicy()

__all__ = ["DEFAULT_POLICY", "StatePolicy"]
