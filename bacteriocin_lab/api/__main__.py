"""Run the BACTERION API: ``python -m bacteriocin_lab.api`` or ``bacterion-api``."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    import os

    default_host = os.environ.get("HOST", "127.0.0.1")
    default_port = int(os.environ.get("PORT", "8000"))
    parser = argparse.ArgumentParser(prog="bacterion-api", description=__doc__)
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument(
        "--origin",
        action="append",
        dest="origins",
        help="Allowed CORS origin; repeatable. Defaults to localhost:3000.",
    )
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ModuleNotFoundError:
        parser.error("the web extra is not installed; run: uv sync --extra web")

    if args.reload:
        # The reloader needs an import string rather than a constructed app.
        uvicorn.run(
            "bacteriocin_lab.api.app:app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
        return 0

    from .app import create_app

    uvicorn.run(create_app(allow_origins=args.origins), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
