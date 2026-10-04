from __future__ import annotations

import json
from pathlib import Path

from bacteriocin_lab.agents.evidence.models import LiteratureQuery, LiteratureResponse
from bacteriocin_lab.agents.evidence.omnigent_tool import collect_literature_evidence

ROOT = Path(__file__).resolve().parents[2] / "agents" / "evidence"


def test_checked_in_schemas_match_models() -> None:
    expected = {
        "literature-query.schema.json": LiteratureQuery.model_json_schema(),
        "literature-response.schema.json": LiteratureResponse.model_json_schema(),
    }
    for filename, schema in expected.items():
        assert json.loads((ROOT / "schemas" / filename).read_text()) == schema


def test_omnigent_tool_returns_json_compatible_shared_envelope() -> None:
    result = collect_literature_evidence(
        {
            "query_id": "example-query",
            "question": "Does nisin inhibit Listeria?",
            "source_documents": [
                {
                    "source": {"source_id": "example", "title": "Example"},
                    "text": "Nisin inhibited Listeria in vitro.",
                }
            ],
        }
    )
    json.dumps(result)
    assert result["agent"] == "literature-evidence-agent"
    assert result["query_id"] == "example-query"
    assert result["decision"]["candidate_decision"] == "not-performed"
    assert result["recommended_next_action"]["requires_codex_or_human_adjudication"] is True
