"""Result Analysis Agent.

Interprets ``ExperimentResult`` objects: does the result support, weaken, or fail
to distinguish its hypothesis; how does it compare with earlier experiments;
which variables drove it; what was unexpected; how confident is the reading.
Interprets only -- never runs experiments and never calls simulation-derived
evidence experimentally validated.

Typical use from Omnigent::

    from bacteriocin_discovery.result_analysis_agent import analyze_result

    response = analyze_result({
        "result": {...},                 # the ExperimentResult just produced
        "previous_results": [...],       # ALL earlier ExperimentResult objects
        "hypothesis": {"hypothesis_id": "hyp_...",
                       "expected_relationship": {"variable": "target_cell_density",
                                                 "direction": "negative"}},
    })
"""

from .agent import (
    AGENT_NAME,
    MODEL_VERSION,
    AnalysisIntegrityError,
    ResultAnalysisAgent,
    analyze_result,
)
from .schema import (
    Driver,
    ExpectedRelationship,
    HypothesisUnderTest,
    ResultAnalysis,
    ResultAnalysisRequest,
    UnexpectedResult,
    VariableFinding,
)

__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "AnalysisIntegrityError",
    "Driver",
    "ExpectedRelationship",
    "HypothesisUnderTest",
    "ResultAnalysis",
    "ResultAnalysisAgent",
    "ResultAnalysisRequest",
    "UnexpectedResult",
    "VariableFinding",
    "analyze_result",
]
