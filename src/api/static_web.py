"""Serve the GoWise Flutter web build from the same FastAPI process (Cloud Run)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Default: repo-root static/gowise (copied into the container by Dockerfile).
_DEFAULT_WEB_ROOT = Path(__file__).resolve().parents[2] / "static" / "gowise"


def resolve_web_root() -> Path | None:
    raw = (os.environ.get("GOWISE_WEB_ROOT") or "").strip()
    root = Path(raw) if raw else _DEFAULT_WEB_ROOT
    index = root / "index.html"
    if index.is_file():
        return root
    return None


def mount_gowise_web(app: FastAPI) -> bool:
    """
    Mount Flutter web assets last so /plan, /places/*, /health keep priority.

    Returns True when the web UI was mounted.
    """
    root = resolve_web_root()
    if root is None:
        logger.info(
            "GoWise web UI not mounted (no index.html under %s). "
            "Run scripts/prepare_gowise_web.sh before docker build.",
            os.environ.get("GOWISE_WEB_ROOT") or _DEFAULT_WEB_ROOT,
        )
        return False

    index = root / "index.html"

    @app.get("/")
    async def gowise_index() -> FileResponse:
        return FileResponse(index)

    # Flutter emits hashed assets + canvaskit + js at the web root.
    # Mount at "/" last: only unmatched paths fall through to StaticFiles.
    app.mount(
        "/",
        StaticFiles(directory=str(root), html=True),
        name="gowise_web",
    )
    logger.info("GoWise web UI mounted from %s", root)
    return True
