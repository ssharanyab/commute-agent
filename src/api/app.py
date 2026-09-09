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


_CLIENT_ERRORS = {
    "COORDINATES_UNRESOLVED",
    "INVALID_REQUEST",
}
_NOT_FOUND_ERRORS = {
    "NO_ROUTES",
    "NO_VALID_ROUTES",
    "NO_FEASIBLE_JOURNEY",
    "NO_CANDIDATES",
}
_UPSTREAM_ERRORS = {
    "MAPS_API_UNAVAILABLE",
}


def _status_for_payload(payload: Dict[str, Any]) -> int:
    err = payload.get("error")
    if not err:
        return 200
    if err in _UPSTREAM_ERRORS:
        return 502
    if err in _NOT_FOUND_ERRORS:
        return 404
    if err in _CLIENT_ERRORS:
        return 400
    return 500


def create_app() -> FastAPI:
    app = FastAPI(
        title="Patchamomma Commute Agent API",
        version="0.1.0",
        description=(
            "HTTP API over ADK Mobility Orchestrator (Journey Builder + "
            "Decision Engine) + adaptive replan. Gemini explains only; "
            "never ranks."
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

    @app.get("/places/autocomplete")
    def places_autocomplete_endpoint(q: str = "", limit: int = 6) -> Dict[str, Any]:
        """Bengaluru-biased Places Autocomplete proxy (API key stays server-side)."""
        from src.mobility.geocoding import places_autocomplete

        suggestions, err = places_autocomplete(q, limit=min(max(limit, 1), 10))
        return {
            "ok": err is None,
            "query": q,
            "suggestions": [s.to_dict() for s in suggestions],
            "error": err,
            "configured": err != "missing_api_key",
        }

    @app.get("/places/details")
    def places_details_endpoint(place_id: str = "") -> Dict[str, Any]:
        """Resolve a Places place_id to lat/lon for Flutter plan requests."""
        from src.mobility.geocoding import place_details

        details, err = place_details(place_id)
        if details is None:
            return {
                "ok": False,
                "error": err or "not_found",
                "place": None,
                "configured": err != "missing_api_key",
            }
        return {
            "ok": True,
            "error": None,
            "place": details.to_dict(),
            "configured": True,
        }

    @app.post("/plan")
    def plan(body: PlanRequest) -> JSONResponse:
        try:
            payload = execute_plan(body)
        except InvalidCommuteRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(content=payload, status_code=_status_for_payload(payload))

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

        return JSONResponse(content=payload, status_code=_status_for_payload(payload))

    return app


app = create_app()
