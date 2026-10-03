#!/usr/bin/env python3
"""MCP boundary for the bounded Literature & Evidence Agent.

The scientific extraction lives in ``b4_literature``. This file only exposes
an explicit, model-readable tool schema and keeps the stdio transport clean.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Any

_SRC = Path(__file__).resolve().parents[2] / "packages" / "b4_literature" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from b4_literature.agent import LiteratureEvidenceAgent  # noqa: E402
from b4_literature.models import SourceDocument  # noqa: E402
from pydantic import Field, ValidationError  # noqa: E402

logging.basicConfig(
    level=os.environ.get("BACTERIOCIN_LOG_LEVEL", "WARNING"),
    stream=sys.stderr,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bacteriocin.literature.mcp")

TOOL_DESCRIPTION = """\
Retrieve and structure bacteriocin literature evidence with source identity,
experimental conditions, measured-vs-interpreted status, original units,
missing variables, contradictions, and confidence.

LITERATURE-DERIVED DOES NOT MEAN INDEPENDENTLY PROVEN. This tool never chooses
a final candidate and never runs an experiment. Retrieval is read-only,
abstract-first, explicitly bounded, and disabled unless requested.
"""


def _request(
    *,
    question: str,
    query_id: str | None,
    bacteriocin: str | None,
    target_organism: str | None,
    target_strain: str | None,
    retrieval_enabled: bool,
    max_results: int,
    timeout_seconds: float,
    source_documents: list[SourceDocument] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question,
        "retrieval": {
            "enabled": retrieval_enabled,
            "sources": ["europe_pmc"],
            "max_results": max_results,
            "timeout_seconds": timeout_seconds,
        },
        "source_documents": [
            document.model_dump(mode="json") for document in (source_documents or [])
        ],
    }
    for key, value in (
        ("query_id", query_id),
        ("bacteriocin", bacteriocin),
        ("target_organism", target_organism),
        ("target_strain", target_strain),
    ):
        if value is not None:
            payload[key] = value
    return payload


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "agent": "literature-evidence-agent",
        "decision": {
            "status": "failed",
            "candidate_decision": "not-performed",
            "documents_considered": 0,
            "records_extracted": 0,
        },
        "evidence": [],
        "knowledge_gaps": ["The request could not be validated or processed."],
        "contradictions": [],
        "recommended_searches": [],
        "confidence": 0.0,
        "uncertainties": [],
        "artifacts": {},
        "warnings": [f"{type(exc).__name__}: {exc}"],
        "recommended_next_action": {
            "action": "correct-request",
            "requires_codex_or_human_adjudication": True,
        },
    }


def build_server():
    """Construct a server compatible with MCP SDK 1.x and 2.x."""
    try:
        from mcp.server.mcpserver import MCPServer as _ServerClass
    except ModuleNotFoundError:
        from mcp.server.fastmcp import FastMCP as _ServerClass

    server = _ServerClass(
        name="bacteriocin-literature-evidence",
        instructions=(
            "Return provenance-preserving literature evidence. Never promote "
            "author interpretation to measured data or make a candidate decision."
        ),
    )

    @server.tool(name="literature_evidence", description=TOOL_DESCRIPTION)
    def literature_evidence(  # type: ignore[misc]
        question: Annotated[
            str,
            Field(
                min_length=3,
                description="Scientific question or bounded literature search query.",
            ),
        ],
        bacteriocin: Annotated[
            str | None,
            Field(description="Bacteriocin identity to bind extracted claims to."),
        ] = None,
        target_organism: Annotated[
            str | None,
            Field(description="Target organism to bind extracted claims to."),
        ] = None,
        target_strain: Annotated[
            str | None,
            Field(description="Target strain when known; never inferred when omitted."),
        ] = None,
        retrieval_enabled: Annotated[
            bool,
            Field(description="Opt in to read-only Europe PMC retrieval."),
        ] = False,
        max_results: Annotated[
            int,
            Field(ge=1, le=50, description="Maximum Europe PMC records to request."),
        ] = 10,
        timeout_seconds: Annotated[
            float,
            Field(ge=1, le=60, description="Per-source retrieval timeout in seconds."),
        ] = 15.0,
        source_documents: Annotated[
            list[SourceDocument] | None,
            Field(
                description=(
                    "Optional bounded source documents with source metadata, text, and "
                    "locator. Useful for full text supplied by another trusted retriever."
                )
            ),
        ] = None,
        query_id: Annotated[
            str | None,
            Field(description="Caller-supplied query identity; generated if omitted."),
        ] = None,
    ) -> str:
        try:
            result = LiteratureEvidenceAgent().run(
                _request(
                    question=question,
                    query_id=query_id,
                    bacteriocin=bacteriocin,
                    target_organism=target_organism,
                    target_strain=target_strain,
                    retrieval_enabled=retrieval_enabled,
                    max_results=max_results,
                    timeout_seconds=timeout_seconds,
                    source_documents=source_documents,
                )
            )
            payload = result.model_dump(mode="json")
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning("literature request rejected: %s", exc)
            payload = _error_payload(exc)
        except Exception as exc:
            logger.exception("literature evidence processing failed")
            payload = _error_payload(exc)
        return json.dumps(payload, indent=2, ensure_ascii=False)

    return server


if __name__ == "__main__":
    build_server().run()
