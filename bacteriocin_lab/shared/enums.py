"""Status vocabularies of the research state."""

from __future__ import annotations

from typing import Literal

#: ``open``: never decided. ``supported`` / ``weakened``: the latest decisive result.
#: ``rejected``: weakened strongly or repeatedly (see the manager's policy).
#: An *inconclusive* analysis never changes a hypothesis status -- it is recorded as an
#: observation and the hypothesis is reported as untouched.
HypothesisStatus = Literal["open", "supported", "weakened", "rejected"]
CandidateStatus = Literal["proposed", "under_test", "rejected"]
ExperimentStatus = Literal["planned", "completed", "failed"]
QuestionStatus = Literal["open", "closed"]
UncertaintyStatus = Literal["active", "resolved"]
AnalysisStatus = Literal["supported", "weakened", "inconclusive"]
