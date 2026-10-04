"""Production ASGI entrypoint for serverless deployment (Vercel, etc.)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root is on sys.path so bacteriocin_lab can be imported
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bacteriocin_lab.api.app import app_from_env

app = app_from_env()
