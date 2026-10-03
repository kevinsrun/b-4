from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .agent import LiteratureEvidenceAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieve and structure bacteriocin literature evidence")
    parser.add_argument("--input", "-i", type=Path, help="JSON query file; stdin is used when omitted")
    parser.add_argument("--output", "-o", type=Path, help="Write JSON response to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        payload = json.loads(raw)
        response = LiteratureEvidenceAgent().run(payload).model_dump(mode="json")
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    rendered = json.dumps(response, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
