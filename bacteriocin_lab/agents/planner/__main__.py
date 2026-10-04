"""CLI: python -m bacteriocin_lab.agents.planner [request.json]  (stdin if no file)."""

import json
import sys

from .planner import run_agent


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        with open(argv[0]) as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)
    print(json.dumps(run_agent(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # importing the module must never read stdin
    raise SystemExit(main())
