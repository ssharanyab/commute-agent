"""
FastAPI application for the Commute Agent HTTP API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.schemas import PlanRequest, ReplanRequest

logger = logging.getLogger(__name__)

# Heavy plan/replan imports are deferred inside handlers so Cloud Run cold
# start can serve /health and /places/* without loading Journey Builder / DE.


_CLIENT_ERRORS = {
    "COORDINATES_UNRESOLVED",
    "INVALID_REQUEST",
    "INVALID_ENDPOINT",
    "INVALID_ENDPOINT_KIND",
    "INVALID_NETWORK_NODE",
    "INVALID_PLACE_ENDPOINT",
    "UNKNOWN_NETWORK_NODE",
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

        capped = min(max(limit, 1), 10)
        logger.info("GET /places/autocomplete q=%r limit=%s", q, capped)
        suggestions, err = places_autocomplete(q, limit=capped)
        payload = {
            "ok": err is None,
            "query": q,
            "suggestions": [s.to_dict() for s in suggestions],
            "error": err,
            "configured": err != "missing_api_key",
        }
        logger.info(
            "GET /places/autocomplete done q=%r ok=%s error=%s count=%s configured=%s",
            q,
            payload["ok"],
            err,
            len(suggestions),
            payload["configured"],
        )
        return payload

    @app.get("/places/details")
    def places_details_endpoint(place_id: str = "") -> Dict[str, Any]:
        """Resolve a Places place_id to lat/lon (+ optional network-node match)."""
        from src.mobility.geocoding import place_details

        details, err = place_details(place_id)
        if details is None:
            return {
                "ok": False,
                "error": err or "not_found",
                "place": None,
                "network_node": None,
                "configured": err != "missing_api_key",
            }
        place = details.to_dict()
        network_node = None
        # Network snap is optional — keep Places details usable even if repo import is slow.
        try:
            from src.network.endpoint_resolve import match_place_to_network_node
            from src.api.service import default_mobility_repository

            repo = default_mobility_repository()
        except Exception as exc:  # pragma: no cover - defensive for slim cold path
            logger.warning("places_details network match unavailable: %s", type(exc).__name__)
            repo = None
            match_place_to_network_node = None  # type: ignore[assignment]

        if repo is not None and match_place_to_network_node is not None:
            # Conservative: proximity-only snap when Places types unavailable.
            # Require very tight distance; Flutter may still send kind=place.
            types = list(getattr(details, "types", None) or [])
            match = match_place_to_network_node(
                repo,
                lat=details.latitude,
                lon=details.longitude,
                place_types=types,
                display_name=details.name,
                place_id=details.place_id,
                require_transit_type_hint=True,
            ) if types else None
            # Without types, only snap inside 15m (pin essentially on published node).
            if match is None and not types:
                match = match_place_to_network_node(
                    repo,
                    lat=details.latitude,
                    lon=details.longitude,
                    place_types=None,
                    display_name=details.name,
                    place_id=details.place_id,
                    max_distance_m=15.0,
                    require_transit_type_hint=False,
                )
            if match is not None:
                ep = match.to_endpoint(
                    lat=details.latitude,
                    lon=details.longitude,
                    place_id=details.place_id,
                    display_name=details.name,
                )
                network_node = ep.to_dict()
        return {
            "ok": True,
            "error": None,
            "place": place,
            "network_node": network_node,
            "configured": True,
        }

    @app.post("/plan")
    def plan(body: PlanRequest) -> JSONResponse:
        from src.api.service import execute_plan
        from src.planner.models import InvalidCommuteRequest

        try:
            payload = execute_plan(body)
        except InvalidCommuteRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(content=payload, status_code=_status_for_payload(payload))

    @app.post("/replan")
    def replan(body: ReplanRequest) -> JSONResponse:
        from src.api.service import execute_replan
        from src.planner.models import InvalidCommuteRequest, InvalidReplanInput

        try:
            payload = execute_replan(body)
        except InvalidCommuteRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InvalidReplanInput as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(content=payload, status_code=_status_for_payload(payload))

    # Flutter web UI (same origin as API). Must be registered last.
    from src.api.static_web import mount_gowise_web

    mount_gowise_web(app)

    return app


app = create_app()
