from __future__ import annotations

import json
from pathlib import Path

from bacteriocin_lab.agents.evidence.models import LiteratureQuery, LiteratureResponse

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "bacteriocin_lab" / "agents" / "evidence" / "schemas"


def main() -> None:
    SCHEMA_DIR.mkdir(exist_ok=True)
    for filename, model in (
        ("literature-query.schema.json", LiteratureQuery),
        ("literature-response.schema.json", LiteratureResponse),
    ):
        path = SCHEMA_DIR / filename
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
