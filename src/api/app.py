"""
FastAPI application for the Commute Agent HTTP API.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.schemas import PlanRequest, ReplanRequest
from src.api.service import execute_plan, execute_replan
from src.planner.models import InvalidCommuteRequest, InvalidReplanInput


def create_app() -> FastAPI:
    app = FastAPI(
        title="Patchamomma Commute Agent API",
        version="0.1.0",
        description=(
            "Thin HTTP API over deterministic planner + adaptive replan + "
            "optional Gemini explanations. Ranking is never done by Gemini."
        ),
    )

    # Flutter web / local demos need CORS; ranking/planner behavior unchanged.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "service": "commute-agent"}

    @app.post("/plan")
    def plan(body: PlanRequest) -> JSONResponse:
        try:
            payload = execute_plan(body)
        except InvalidCommuteRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        status = 200
        if payload.get("error") == "MAPS_API_UNAVAILABLE":
            status = 502
        elif payload.get("error") in {"NO_ROUTES", "NO_VALID_ROUTES"}:
            status = 404
        elif payload.get("error"):
            status = 500
        return JSONResponse(content=payload, status_code=status)

    @app.post("/replan")
    def replan(body: ReplanRequest) -> JSONResponse:
        try:
            payload = execute_replan(body)
        except InvalidCommuteRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InvalidReplanInput as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        status = 200
        if payload.get("error") == "MAPS_API_UNAVAILABLE":
            status = 502
        elif payload.get("error") in {"NO_ROUTES", "NO_VALID_ROUTES"}:
            status = 404
        elif payload.get("error"):
            status = 500
        return JSONResponse(content=payload, status_code=status)

    return app


app = create_app()
