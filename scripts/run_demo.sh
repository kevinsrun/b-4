#!/usr/bin/env bash
# Launch the local-only, screen-recording BACTERION demo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="http://127.0.0.1:8000/api/health"
WEB_URL="http://127.0.0.1:3000/research"
DEMO_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bacterion-demo.XXXXXX")"
API_PID=""
WEB_PID=""

cleanup() {
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if curl --silent --fail "$API_URL" >/dev/null || curl --silent --fail "$WEB_URL" >/dev/null; then
  echo "A BACTERION demo service is already using port 8000 or 3000." >&2
  echo "Stop that demo first, then re-run this command for a clean recording session." >&2
  exit 1
fi

cd "$REPO_DIR"
uv sync --extra web >/dev/null
if [[ ! -d web/node_modules ]]; then
  (cd web && npm ci >/dev/null)
fi

uv run bacterion-api --port 8000 >"$DEMO_LOG_DIR/api.log" 2>&1 &
API_PID=$!
(cd web && npm run dev -- --hostname 127.0.0.1 --port 3000 >"$DEMO_LOG_DIR/web.log" 2>&1) &
WEB_PID=$!

for _ in $(seq 1 50); do
  if curl --silent --fail "$API_URL" >/dev/null && curl --silent --fail "$WEB_URL" >/dev/null; then
    echo
    echo "BACTERION demo ready: $WEB_URL"
    echo "Local-only deterministic mode: remote BLAST is not used."
    echo "Press Ctrl-C after recording to stop both local services."
    wait
    exit 0
  fi
  sleep 0.2
done

echo "Demo services did not become ready. Logs: $DEMO_LOG_DIR" >&2
exit 1
