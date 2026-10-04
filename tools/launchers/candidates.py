#!/usr/bin/env python3
"""MCP server exposing the Candidate Generation & Design Agent to Omnigent.

Omnigent declares MCP servers per agent bundle (``tools/mcp/<name>.yaml``,
stdio transport). This module is the adapter between that transport and
``generate_candidates``.

Two design decisions here came out of a live run against Claude and are worth
keeping in mind before changing them:

**Explicit typed parameters, not a nested ``request`` dict.** A single
``request: dict`` parameter advertises the JSON Schema
``{"type": "object", "additionalProperties": true}`` -- which tells the model
nothing. In the live run the model guessed ``n_candidates`` instead of
``constraints.max_candidates`` and silently got the whole pool back. Flat,
annotated parameters make the schema self-documenting, so there is nothing to
guess. ``request_override`` remains as the escape hatch for full contract access.

**Compact response by default, warnings first.** The full envelope is ~25 KB for
five candidates, and the orchestrator truncated a 56 KB reply at ~2 KB --
discarding exactly the provenance warnings this agent exists to surface. The
default response is a few KB with the disclaimer and warnings at the top, so
truncation cannot eat them. The full envelope is written to a file and offered
behind ``include_full_envelope``.

Run standalone for a smoke test::

    python3 tools/launchers/candidates.py --selftest
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

# The bundle may be launched from anywhere, so locate the package relative to
# this file rather than relying on the caller's cwd.
_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pydantic import Field  # noqa: E402

from bacteriocin_lab.agents.candidate import (  # noqa: E402
    AGENT_NAME,
    MODEL_VERSION,
    CandidateGenerationAgent,
    JsonFileKnowledgeSource,
)

# stdio is the MCP channel, so logs must never go to stdout.
logging.basicConfig(
    level=os.environ.get("BACTERIOCIN_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bacteriocin.mcp")

#: Optional override: point at a curated dataset instead of the shipped seed.
_KNOWLEDGE_PATH = os.environ.get("BACTERIOCIN_KNOWLEDGE_PATH")

#: Where full envelopes are written so nothing is lost to truncation.
_ARTIFACT_DIR = Path(
    os.environ.get("BACTERIOCIN_ARTIFACT_DIR") or Path(tempfile.gettempdir()) / "bacteriocin-runs"
)


def _build_agent() -> CandidateGenerationAgent:
    """Construct the agent once, honouring the knowledge-source override.

    Reused across calls because ``JsonFileKnowledgeSource`` caches its records
    on first read; a fresh agent per call would re-parse the dataset.
    """
    if _KNOWLEDGE_PATH:
        path = Path(_KNOWLEDGE_PATH)
        if not path.is_file():
            # Fail loudly: a campaign run against the wrong dataset is worse
            # than one that refuses to start.
            raise FileNotFoundError(
                f"BACTERIOCIN_KNOWLEDGE_PATH={path} does not exist. "
                "Unset it to use the shipped seed dataset."
            )
        logger.info("Using knowledge source %s", path)
        return CandidateGenerationAgent(
            knowledge_source=JsonFileKnowledgeSource(path, name=f"file:{path.name}")
        )
    logger.info("Using the shipped seed dataset (unverified sequences)")
    return CandidateGenerationAgent()


_AGENT = _build_agent()


TOOL_DESCRIPTION = """\
Propose a ranked, diverse set of bacteriocin candidates worth testing next \
against a target organism, each with a falsifiable hypothesis and a \
six-component score breakdown.

PROPOSALS ONLY. This tool does not simulate, does not measure, and never claims \
a candidate is active. Every candidate is validation_status="unvalidated"; every \
predicted_inhibition_fraction is a heuristic prior, NOT a measurement. Never \
restate its output as an experimental finding.

The ranking is NOT a potency ordering. It balances predicted usefulness against \
expected information gain, novelty, and power to discriminate between competing \
hypotheses, so a candidate can rank highly precisely because its outcome is \
uncertain. Read each candidate's score breakdown to see which objective drove \
its rank.

Deterministic: identical arguments always return identical output. To change the \
result, change the arguments.

Pass `gram` whenever you know it. Without it the envelope-accessibility check is \
skipped, and a candidate that cannot physically work on the target can rank high.
Pass `target_cell_density` whenever you know it: activity is dose-PER-CELL \
dependent, so the same concentration can clear a dilute culture and fail on a \
dense one.
"""


def _as_float(value: float | str | None, field: str) -> float | None:
    """Accept a number or a numeric string such as "1e8".

    A live run showed the model passing ``target_cell_density="1e8"``, which a
    strict ``float`` parameter rejected and cost a wasted round trip. Scientific
    notation is the natural way to write a cell density, so coerce it rather
    than making the caller learn the hard way. A genuinely unparseable value
    still raises, with the field named.
    """
    if value is None or isinstance(value, (int, float)):
        return None if value is None else float(value)
    text = str(value).strip().replace(",", "").replace("_", "")
    try:
        return float(text)
    except ValueError:
        raise ValueError(
            f"{field} must be a number (e.g. 100000000 or 1e8); got {value!r}"
        ) from None


def _build_request(
    *,
    organism: str,
    strain: str | None,
    gram: str,
    known_resistance_factors: list[str] | None,
    max_candidates: int,
    ph_low: float | None,
    ph_high: float | None,
    temperature_c: float | None,
    target_cell_density: float | None,
    medium: str | None,
    incubation_time_h: float | None,
    assay_domain: str,
    diversity_weight: float,
    min_total_score: float,
    require_known_sequence: bool,
    allow_sequence_modification: bool,
    exclude_candidate_ids: list[str] | None,
    scoring_weights: dict[str, float] | None,
    competing_hypotheses: list[dict[str, Any]] | None,
    previous_results: list[dict[str, Any]] | None,
    candidate_pool: list[dict[str, Any]] | None,
    research_objective: str | None,
    request_override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a CandidateRequest payload from flat parameters.

    ``request_override`` is merged last and wins, so a caller that needs a
    contract field this signature does not expose is never blocked.
    """
    target: dict[str, Any] = {"organism": organism, "gram": gram}
    if strain:
        target["strain"] = strain
    if known_resistance_factors:
        target["known_resistance_factors"] = known_resistance_factors

    desired: dict[str, Any] = {"high_inhibition": True, "assay_domain": assay_domain}
    # Only a complete pair is a range; a lone bound would be ambiguous.
    if ph_low is not None and ph_high is not None:
        desired["ph_range"] = [ph_low, ph_high]
    if temperature_c is not None:
        desired["temperature_c"] = temperature_c
    if target_cell_density is not None:
        desired["target_cell_density"] = target_cell_density
    if medium:
        desired["medium"] = medium
    if incubation_time_h is not None:
        desired["incubation_time_h"] = incubation_time_h

    constraints: dict[str, Any] = {
        "max_candidates": max_candidates,
        "diversity_weight": diversity_weight,
        "min_total_score": min_total_score,
        "require_known_sequence": require_known_sequence,
        "allow_sequence_modification": allow_sequence_modification,
    }
    if exclude_candidate_ids:
        constraints["exclude_candidate_ids"] = exclude_candidate_ids
    if scoring_weights:
        constraints["scoring_weights"] = scoring_weights

    request: dict[str, Any] = {
        "target": target,
        "desired_behavior": desired,
        "constraints": constraints,
    }
    if competing_hypotheses:
        request["competing_hypotheses"] = competing_hypotheses
    if previous_results:
        request["previous_results"] = previous_results
    if candidate_pool:
        request["candidate_pool"] = candidate_pool
    if research_objective:
        request["research_objective"] = {"goal": research_objective}

    if request_override:
        request.update(request_override)
    return request


def _error_envelope(exc: Exception) -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "decision": {"candidates": [], "selection_logic": "Tool invocation failed."},
        "evidence": [],
        "confidence": 0.0,
        "uncertainties": [],
        "artifacts": {},
        "warnings": [f"Internal error: {type(exc).__name__}: {exc}"],
        "recommended_next_action": None,
        "model_version": MODEL_VERSION,
    }


def _save_envelope(envelope: dict[str, Any]) -> str | None:
    """Write the full envelope so nothing is lost when the reply is truncated."""
    try:
        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        run = (envelope.get("artifacts") or {}).get("run_id") or "run_unknown"
        path = _ARTIFACT_DIR / f"{run}.json"
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return str(path)
    except OSError as exc:
        logger.warning("Could not write envelope artifact: %s", exc)
        return None


def _compact(envelope: dict[str, Any], artifact_path: str | None) -> dict[str, Any]:
    """A few-KB view of the result, with the disclaimer and warnings first.

    Field order matters: a truncated reply must still carry the provenance
    caveats, so they lead. Candidates are reduced to what a decision needs --
    identity, the score split that explains the rank, the hypothesis, and the
    falsification clause.
    """
    decision = envelope.get("decision") or {}
    candidates = decision.get("candidates") or []
    # Normalised weights the agent actually used, for the contribution maths.
    weights = (envelope.get("artifacts") or {}).get("scoring_weights") or {}

    compact_candidates = []
    for candidate in candidates:
        score = candidate.get("score") or {}
        computed = (candidate.get("features") or {}).get("computed") or {}
        features = candidate.get("features") or {}
        hypotheses = candidate.get("hypotheses") or []
        primary = hypotheses[0] if hypotheses else {}

        # Name the objective that actually drove the rank, so the model does not
        # have to infer it (and cannot mistake rank for predicted potency).
        #
        # This is the WEIGHTED contribution, not the largest raw component. On a
        # cold start novelty is 1.00 for every candidate, so the raw maximum
        # reports "novelty" for everything and explains nothing. Weighting by
        # the scoring weights gives the real share of the total: novelty 1.00 at
        # 15% contributes 0.15, while promise 0.88 at 35% contributes 0.31.
        components = {
            k: score.get(k, 0.0)
            for k in (
                "promise",
                "information_gain",
                "novelty",
                "hypothesis_discrimination",
                "condition_fit",
                "uncertainty",
            )
        }
        contributions = {
            k: round(value * weights.get(k, 0.0), 4) for k, value in components.items()
        }
        driver = max(contributions, key=lambda k: contributions[k]) if contributions else None

        compact_candidates.append(
            {
                "rank": candidate.get("rank"),
                "name": candidate.get("name"),
                "candidate_id": candidate.get("candidate_id"),
                "validation_status": candidate.get("validation_status"),
                "origin": candidate.get("origin"),
                "bacteriocin_class": features.get("bacteriocin_class"),
                "receptor": features.get("receptor"),
                "score_total": score.get("total"),
                "score_components": components,
                "score_contributions": contributions,
                "rank_driven_by": driver,
                "worth_testing_confidence": candidate.get("confidence"),
                "sequence_length": computed.get("sequence_length"),
                "net_charge": computed.get("net_charge"),
                "charge_ph": computed.get("charge_ph"),
                "gravy": computed.get("gravy"),
                "sequence_verified": candidate.get("sequence_verified"),
                "hypothesis": primary.get("statement"),
                "predicted_inhibition_fraction_PRIOR": primary.get(
                    "predicted_inhibition_fraction"
                ),
                "falsified_if": primary.get("falsified_if"),
                "hypothesis_ids": [h.get("hypothesis_id") for h in hypotheses],
                "expected_failure_modes": (candidate.get("expected_failure_modes") or [])[:3],
            }
        )

    high_severity = [
        u.get("description")
        for u in decision.get("uncertainties") or []
        if isinstance(u, dict) and u.get("severity") == "high"
    ]

    return {
        "PROVENANCE": (
            "PROPOSALS, NOT FINDINGS. Every candidate is unvalidated. Every "
            "predicted_inhibition_fraction_PRIOR is a heuristic prior, not a measurement. "
            "Do not restate any of this as an experimental result."
        ),
        "warnings": envelope.get("warnings") or [],
        "high_severity_uncertainties": high_severity,
        "agent": envelope.get("agent"),
        "model_version": envelope.get("model_version"),
        "returned_count": len(compact_candidates),
        "considered_count": decision.get("considered_count"),
        "set_confidence_means_worth_testing": envelope.get("confidence"),
        "candidates": compact_candidates,
        "recommended_next_action": envelope.get("recommended_next_action"),
        "selection_logic": decision.get("selection_logic"),
        "full_envelope_path": artifact_path,
        "note": (
            "Ranking is not a potency ordering; read rank_driven_by. "
            "Set include_full_envelope=true for the complete contract payload "
            "(large), or read full_envelope_path."
        ),
    }


def build_server():
    """Construct the MCP server with the tools registered.

    Both SDK majors are supported deliberately. Omnigent 0.16 bundles mcp
    1.30, where the server class is ``FastMCP``; a fresh install resolves 2.x,
    where it was renamed ``MCPServer``. The shared installer may pick either
    interpreter, so pinning one import would crash the server on the other.
    The two classes agree on ``tool()`` and ``run()``.
    """
    try:
        from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2
    except ModuleNotFoundError:
        from mcp.server.fastmcp import FastMCP as _ServerClass  # mcp 1.x

    server = _ServerClass(
        name="bacteriocin-candidate-generation",
        instructions=(
            "Exposes the Candidate Generation & Design Agent of an autonomous "
            "bacteriocin-discovery system. Proposals only -- never treat its output as "
            "experimental evidence."
        ),
    )

    @server.tool(name="generate_candidates", description=TOOL_DESCRIPTION)
    def generate_candidates_tool(  # type: ignore[misc]
        organism: Annotated[
            str, Field(description="Target species, e.g. 'Listeria monocytogenes'. Required.")
        ],
        gram: Annotated[
            Literal["positive", "negative", "unknown"],
            Field(
                description=(
                    "Gram stain of the target. PASS THIS WHENEVER KNOWN -- it gates the "
                    "mechanism-plausibility check."
                )
            ),
        ] = "unknown",
        strain: Annotated[str | None, Field(description="Strain, e.g. 'EGD-e'.")] = None,
        max_candidates: Annotated[
            int,
            Field(ge=1, le=500, description="How many candidates to return. THIS is the count."),
        ] = 5,
        ph_low: Annotated[
            float | None,
            Field(ge=0, le=14, description="Lower bound of the assay pH range. Pair with ph_high."),
        ] = None,
        ph_high: Annotated[
            float | None,
            Field(ge=0, le=14, description="Upper bound of the assay pH range. Pair with ph_low."),
        ] = None,
        temperature_c: Annotated[
            float | None, Field(description="Assay temperature in Celsius, e.g. 37.")
        ] = None,
        target_cell_density: Annotated[
            float | str | None,
            Field(
                description=(
                    "Target cell density in CFU/mL. Accepts a number or a numeric "
                    "string, so 100000000 and \"1e8\" both work. PASS THIS WHENEVER KNOWN -- "
                    "activity is dose-per-cell dependent; omitting it yields a "
                    "high-severity uncertainty."
                ),
            ),
        ] = None,
        medium: Annotated[str | None, Field(description="Growth medium, e.g. 'BHI'.")] = None,
        incubation_time_h: Annotated[
            float | None, Field(ge=0, description="Incubation time in hours.")
        ] = None,
        assay_domain: Annotated[
            Literal["simulated_in_vitro", "simulated_in_vivo_like", "in_vitro", "in_vivo"],
            Field(description="Experimental context. Default is the simulation backend."),
        ] = "simulated_in_vitro",
        diversity_weight: Annotated[
            float,
            Field(
                ge=0,
                le=1,
                description=(
                    "0 ranks by score alone; higher trades score for coverage across "
                    "bacteriocin families."
                ),
            ),
        ] = 0.3,
        min_total_score: Annotated[
            float, Field(ge=0, le=1, description="Drop candidates scoring below this.")
        ] = 0.0,
        require_known_sequence: Annotated[
            bool, Field(description="Drop candidates with no sequence.")
        ] = False,
        allow_sequence_modification: Annotated[
            bool,
            Field(
                description=(
                    "Enable conservative variant design (inverse-design stretch goal). "
                    "Variants are computational proposals with nothing verified."
                )
            ),
        ] = False,
        exclude_candidate_ids: Annotated[
            list[str] | None,
            Field(description="Candidate IDs to exclude, e.g. ones already settled."),
        ] = None,
        scoring_weights: Annotated[
            dict[str, float] | None,
            Field(
                description=(
                    "Relative objective weights, normalised internally. Keys: promise, "
                    "novelty, uncertainty, information_gain, hypothesis_discrimination, "
                    "condition_fit."
                )
            ),
        ] = None,
        competing_hypotheses: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "Open hypotheses the next experiment could settle. Each needs "
                    "hypothesis_id, statement, discriminating_feature (a numeric feature "
                    "such as 'net_charge' or 'gravy') and favourable_range [low, high]. "
                    "Without these, the discrimination objective scores 0 for everything."
                )
            ),
        ] = None,
        previous_results: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "ALL prior ExperimentResult objects, not just the latest. This is what "
                    "stops the loop re-proposing settled candidates."
                )
            ),
        ] = None,
        candidate_pool: Annotated[
            list[dict[str, Any]] | None,
            Field(description="Extra candidate records to merge with the knowledge source."),
        ] = None,
        research_objective: Annotated[
            str | None, Field(description="One-line statement of the campaign goal.")
        ] = None,
        include_full_envelope: Annotated[
            bool,
            Field(
                description=(
                    "Include the complete contract envelope. LARGE (~25 KB for 5 "
                    "candidates) and liable to be truncated; the compact response already "
                    "carries warnings, scores, hypotheses and falsification clauses."
                )
            ),
        ] = False,
        request_override: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Escape hatch: raw CandidateRequest fields, merged last and winning "
                    "over the arguments above. Only needed for contract fields this "
                    "signature does not expose."
                )
            ),
        ] = None,
    ) -> str:
        """Propose ranked bacteriocin candidates. See the tool description."""
        request = _build_request(
            organism=organism,
            strain=strain,
            gram=gram,
            known_resistance_factors=None,
            max_candidates=max_candidates,
            ph_low=ph_low,
            ph_high=ph_high,
            temperature_c=temperature_c,
            target_cell_density=_as_float(target_cell_density, "target_cell_density"),
            medium=medium,
            incubation_time_h=incubation_time_h,
            assay_domain=assay_domain,
            diversity_weight=diversity_weight,
            min_total_score=min_total_score,
            require_known_sequence=require_known_sequence,
            allow_sequence_modification=allow_sequence_modification,
            exclude_candidate_ids=exclude_candidate_ids,
            scoring_weights=scoring_weights,
            competing_hypotheses=competing_hypotheses,
            previous_results=previous_results,
            candidate_pool=candidate_pool,
            research_objective=research_objective,
            request_override=request_override,
        )

        try:
            envelope = _AGENT.run_envelope(request).model_dump(mode="json")
        except Exception as exc:
            logger.exception("generate_candidates failed")
            envelope = _error_envelope(exc)

        artifact_path = _save_envelope(envelope)
        payload = _compact(envelope, artifact_path)
        if include_full_envelope:
            payload["envelope"] = envelope
        return json.dumps(payload, indent=2)

    @server.tool(
        name="describe_agent",
        description=(
            "Return this agent's identity, model_version, knowledge source, scoring "
            "objectives, and the things it refuses to do. Call this to learn what the "
            "candidate generator will and will not do before using it."
        ),
    )
    def describe_agent() -> str:  # type: ignore[misc]
        return json.dumps(
            {
                "agent": AGENT_NAME,
                "model_version": MODEL_VERSION,
                "knowledge_source": _AGENT._knowledge.source_name,
                "responsibility": (
                    "Propose ranked bacteriocin candidates and falsifiable hypotheses "
                    "for the next experiment."
                ),
                "scoring_objectives": {
                    "promise": "Predicted biological usefulness against the target.",
                    "information_gain": "Expected uncertainty reduction; peaks at 4p(1-p).",
                    "novelty": "Dissimilarity to already-tested candidates.",
                    "condition_fit": "Known stability vs. requested assay conditions.",
                    "hypothesis_discrimination": "Power to split competing open hypotheses.",
                    "uncertainty": "How little is known about the candidate.",
                },
                "will_not": [
                    "Simulate experiments or predict potency.",
                    "Claim any candidate is experimentally validated.",
                    "Generate de novo sequences (only conservative variants, when enabled).",
                    "Invoke other agents; recommended_next_action is advisory.",
                ],
                "determinism": "Identical arguments always produce identical output.",
                "next_agent": "experiment_planner",
            },
            indent=2,
        )

    @server.tool(
        name="discover_candidate_variants",
        description=(
            "Discover naturally occurring sequence variants in homologs of a bacteriocin candidate "
            "using sequence similarity (BLAST), multiple sequence alignment, and CDS mapping. "
            "Returns ranked variants and candidate proposals with falsifiable hypotheses. "
            "Never claims variants are experimentally validated."
        ),
    )
    def discover_candidate_variants_tool(  # type: ignore[misc]
        candidate_id: Annotated[
            str, Field(description="Identifier of the reference candidate bacteriocin.")
        ],
        sequence: Annotated[
            str, Field(description="Query amino acid sequence of the bacteriocin candidate.")
        ],
        database: Annotated[
            str,
            Field(description="BLAST database to search for homologs, e.g. 'swissprot' or 'nr'."),
        ] = "swissprot",
        max_homologs: Annotated[
            int,
            Field(
                ge=1,
                le=50,
                description="Maximum number of homologs to retrieve and align (max 50).",
            ),
        ] = 20,
        max_variants: Annotated[
            int,
            Field(ge=1, le=10, description="Maximum number of ranked variants to return (max 10)."),
        ] = 5,
        ref_cds: Annotated[
            str | None,
            Field(
                description="Optional reference nucleotide coding sequence (CDS) for codon changes."
            ),
        ] = None,
    ) -> str:
        """Discover natural variants and generate candidate proposals."""
        from bacteriocin_lab.agents.variant import (
            DEFAULT_MAX_VARIANT_HOMOLOGS,
            DEFAULT_MAX_VARIANTS_PER_CANDIDATE,
            VariantBudgetExceededError,
            discover_variants,
            variant_to_proposal,
        )

        if max_homologs > DEFAULT_MAX_VARIANT_HOMOLOGS:
            raise VariantBudgetExceededError(
                f"max_homologs={max_homologs} exceeds limit {DEFAULT_MAX_VARIANT_HOMOLOGS}"
            )
        if max_variants > DEFAULT_MAX_VARIANTS_PER_CANDIDATE:
            raise VariantBudgetExceededError(
                f"max_variants={max_variants} exceeds limit {DEFAULT_MAX_VARIANTS_PER_CANDIDATE}"
            )

        try:
            result = discover_variants(
                candidate_id=candidate_id,
                sequence=sequence,
                database=database,
                max_homologs=max_homologs,
                max_variants=max_variants,
                ref_cds=ref_cds,
                strict_budget=True,
            )
            proposals = [
                variant_to_proposal(v, sequence).model_dump(mode="json")
                for v in result.variants
            ]
            payload = {
                "candidate_id": result.candidate_id,
                "reference_sequence": result.reference_sequence,
                "homolog_count": result.homolog_count,
                "aligned_homolog_count": result.aligned_homolog_count,
                "variants": [v.model_dump(mode="json") for v in result.variants],
                "proposals": proposals,
                "provenance": result.provenance,
                "sources": result.sources,
                "warnings": result.warnings,
            }
            return json.dumps(payload, indent=2)
        except Exception as exc:
            logger.exception("discover_candidate_variants failed")
            return json.dumps(
                {
                    "error": str(exc),
                    "candidate_id": candidate_id,
                    "variants": [],
                    "proposals": [],
                    "provenance": "database-derived",
                    "warnings": [f"Variant discovery failed: {exc}"],
                },
                indent=2,
            )

    return server


def _selftest() -> int:
    """Exercise the tool path without a transport and print what a client sees."""
    import asyncio

    server = build_server()
    tools = asyncio.run(server.list_tools())

    print("=== advertised schema (what the model actually sees) ===")
    for tool in tools:
        props = list((tool.inputSchema or {}).get("properties", {}))
        print(f"{tool.name}: {len(props)} parameters")
        if tool.name == "generate_candidates":
            print("  " + ", ".join(props))
            required = (tool.inputSchema or {}).get("required", [])
            print(f"  required: {required}")

    print("\n=== call with flat arguments ===")
    result = asyncio.run(
        server.call_tool(
            "generate_candidates",
            {
                "organism": "Listeria monocytogenes",
                "strain": "EGD-e",
                "gram": "positive",
                "max_candidates": 3,
                "ph_low": 6.0,
                "ph_high": 7.5,
                "temperature_c": 37,
                "target_cell_density": 1e8,
            },
        )
    )
    text = result[0][0].text if isinstance(result, tuple) else result[0].text
    payload = json.loads(text)
    print(f"response size: {len(text)} bytes")
    print(f"returned_count: {payload['returned_count']} (asked for 3)")
    print(f"warnings present: {len(payload['warnings'])}")
    print(f"full envelope at: {payload['full_envelope_path']}")
    for candidate in payload["candidates"]:
        print(
            f"  #{candidate['rank']} {candidate['name']}  "
            f"total={candidate['score_total']:.3f}  driver={candidate['rank_driven_by']}"
        )

    ok = payload["returned_count"] == 3 and len(text) < 12000
    print(f"\ncount honoured and response compact: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    build_server().run()
