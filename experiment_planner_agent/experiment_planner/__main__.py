"""CLI: python -m experiment_planner [request.json]  (stdin if no file)."""
import json
import sys

from .planner import run_agent

src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
print(json.dumps(run_agent(json.load(src)), indent=2, sort_keys=True))
