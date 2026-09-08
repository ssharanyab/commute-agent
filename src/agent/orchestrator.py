"""
ADK Mobility Orchestrator (Phase 5D).

Coordinates domain capabilities. Does NOT rank journeys via Gemini.
Journey Builder discovers candidates; Decision Engine ranks them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.agent.capabilities import (
    ContextCapabilityResult,
    DecisionCapabilityResult,
    HistoricalCapabilityResult,
    MobilityContext,
    OrchestrationMetadata,
    PersonalizationResult,
)
from src.agent.capabilities.adapt import journeys_to_route_candidates
from src.agent.capabilities.historical import get_historical_context
from src.agent.capabilities.journey import build_candidate_journeys
from src.agent.capabilities.network import query_mobility_network
from src.agent.capabilities.personalization import (
    apply_transfer_limit,
    resolve_personalization,
    to_journey_constraints,
)
from src.agent.capabilities.traffic import enrich_road_legs
from src.agent.capabilities.weather import get_weather_context
from src.agent.config import (
    FALLBACK_NOTICE,
    adk_importable,
    gemini_credentials_available,
)
from src.agent.demo_od import BENGALURU_LANDMARKS
from src.agent.schemas import (
    AgentRecommendation,
    AgentRunResult,
    ground_recommendation,
    recommendation_from_planner,
)
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import EvaluationResult, RouteCandidate, UserPreferences
from src.journey_builder import SearchLimits
from src.journey_builder.models import Journey, JourneyBuildResult
from src.network.repository import StaticMobilityDataRepository
from src.planner.models import CommuteRequest, PlannerResult
from src.planner.service import plan_commute as _legacy_plan_commute


@dataclass
class OrchestratorRequest:
    user_id: str
    origin: str
    destination: str
    departure_time: datetime
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None
    preferences: Optional[UserPreferences] = None
    origin_zone: Optional[int] = None
    destination_zone: Optional[int] = None
    max_transfers: Optional[int] = None
    search_limits: Optional[SearchLimits] = None
    invoke_gemini: bool = False
    invoke_weather: bool = True
    invoke_historical: bool = True
    invoke_live_traffic: bool = True
    allow_legacy_maps_fallback: bool = True
    raw_text: Optional[str] = None


@dataclass
class OrchestrationResult:
    recommendation: AgentRecommendation
    journey_build: Optional[JourneyBuildResult]
    journeys: List[Journey]
    route_candidates: List[RouteCandidate]
    evaluation: Optional[EvaluationResult]
    decision: Optional[DecisionCapabilityResult]
    mobility_context: Optional[MobilityContext]
    personalization: Optional[PersonalizationResult]
    historical: Optional[HistoricalCapabilityResult]
    weather: Optional[ContextCapabilityResult]
    enrichment_results: Dict[str, List[Any]]
    metadata: OrchestrationMetadata
    legacy_planner_result: Optional[PlannerResult] = None
    gemini_available: bool = False
    gemini_invoked: bool = False
    adk_invoked: bool = False
    mode: str = "deterministic_fallback"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation": self.recommendation.to_dict(),
            "journey_build": self.journey_build.to_dict()
            if self.journey_build
            else None,
            "journeys": [j.to_dict() for j in self.journeys],
            "route_candidates": [c.to_dict() for c in self.route_candidates],
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "mobility_context": self.mobility_context.to_dict()
            if self.mobility_context
            else None,
            "personalization": self.personalization.to_dict()
            if self.personalization
            else None,
            "historical": self.historical.to_dict() if self.historical else None,
            "weather": self.weather.to_dict() if self.weather else None,
            "enrichment_results": {
                k: [e.to_dict() for e in v]
                for k, v in self.enrichment_results.items()
            },
            "metadata": self.metadata.to_dict(),
            "legacy_planner_result": self.legacy_planner_result.to_dict()
            if self.legacy_planner_result
            else None,
            "gemini_available": self.gemini_available,
            "gemini_invoked": self.gemini_invoked,
            "adk_invoked": self.adk_invoked,
            "mode": self.mode,
        }

    def to_agent_run_result(self, parsed_intent: Optional[Dict[str, Any]] = None) -> AgentRunResult:
        commute = CommuteRequest(
            user_id="orchestrator",
            origin="",
            destination="",
        )
        # Prefer legacy planner result shape when present for AgentRunResult compat.
        planner = self.legacy_planner_result
        if planner is None and self.evaluation is not None:
            planner = PlannerResult(
                request=CommuteRequest(
                    user_id=self.recommendation.recommended_route.route_id
                    if self.recommendation.recommended_route
                    else "orch",
                    origin="orchestrated",
                    destination="orchestrated",
                ),
                routes=list(self.route_candidates),
                evaluation=self.evaluation,
                data_sources=["journey_builder", "decision_engine"],
                historical_signal_used=bool(
                    self.historical and self.historical.coverage
                ),
                warnings=list(self.metadata.warnings),
            )
        return AgentRunResult(
            recommendation=self.recommendation,
            parsed_intent=dict(parsed_intent or {}),
            commute_request=planner.request if planner else commute,
            planner_result=planner,
            tools_selected=[c.name for c in self.metadata.capabilities],
            gemini_available=self.gemini_available,
            gemini_invoked=self.gemini_invoked,
            adk_invoked=self.adk_invoked,
            mode=self.mode,
        )


def resolve_coordinates(
    label: str,
    lat: Optional[float],
    lon: Optional[float],
) -> Tuple[Optional[float], Optional[float], str]:
    if lat is not None and lon is not None:
        return float(lat), float(lon), "explicit"
    key = (label or "").strip().lower()
    place = BENGALURU_LANDMARKS.get(key)
    if place:
        return place.latitude, place.longitude, "landmark_table"
    return None, None, "unresolved"


class MobilityOrchestrator:
    """
    Predictable orchestration sequence:

    personalization → network → journey builder → enrichment →
    historical/weather → decision engine → optional Gemini explanation.
    """

    def __init__(
        self,
        repository: Optional[StaticMobilityDataRepository] = None,
        *,
        traffic_get_routes: Optional[Callable] = None,
        weather_provider: Optional[Callable] = None,
        historical_provider: Optional[Any] = None,
        explain_fn: Optional[Callable] = None,
        legacy_plan_fn: Optional[Callable] = None,
    ):
        self.repository = repository
        self.traffic_get_routes = traffic_get_routes
        self.weather_provider = weather_provider
        self.historical_provider = historical_provider
        self.explain_fn = explain_fn
        self.legacy_plan_fn = legacy_plan_fn or _legacy_plan_commute

    def run(self, request: OrchestratorRequest) -> OrchestrationResult:
        meta = OrchestrationMetadata()
        gemini_available = gemini_credentials_available()
        meta.gemini_available = gemini_available

        # 1–2. Personalization / hard constraints
        personalization = resolve_personalization(
            preferences=request.preferences,
            max_transfers=request.max_transfers,
            user_id=request.user_id,
        )
        meta.record(
            "personalization",
            "invoked",
            "resolve request constraints",
            source=personalization.source,
        )
        journey_constraints = to_journey_constraints(personalization)
        limits = request.search_limits or SearchLimits()
        limits = apply_transfer_limit(limits, personalization)

        # Resolve coordinates
        o_lat, o_lon, o_how = resolve_coordinates(
            request.origin, request.origin_lat, request.origin_lon
        )
        d_lat, d_lon, d_how = resolve_coordinates(
            request.destination, request.destination_lat, request.destination_lon
        )
        if o_lat is None or d_lat is None:
            meta.record(
                "geocode",
                "failed",
                "coordinates unresolved",
                origin=o_how,
                destination=d_how,
            )
            meta.warnings.append("COORDINATES_UNRESOLVED")
            return self._empty_result(
                meta,
                personalization,
                error="COORDINATES_UNRESOLVED",
                explanation=FALLBACK_NOTICE,
            )
        meta.record(
            "geocode",
            "invoked",
            "resolve origin/destination coordinates",
            origin=o_how,
            destination=d_how,
        )

        # 3. Network context
        mobility_context: Optional[MobilityContext] = None
        if self.repository is None:
            meta.record(
                "mobility_network",
                "unavailable",
                "no StaticMobilityDataRepository configured",
            )
            meta.warnings.append("NETWORK_REPOSITORY_UNAVAILABLE")
        else:
            mobility_context = query_mobility_network(
                self.repository, latitude=o_lat, longitude=o_lon
            )
            meta.network_snapshot_versions = dict(
                mobility_context.network_snapshot_versions
            )
            meta.record(
                "mobility_network",
                "invoked" if mobility_context.available else "unavailable",
                "query Phase 5A/5B repository",
                stops=len(mobility_context.relevant_stops),
                stations=len(mobility_context.relevant_stations),
            )

        # 4. Journey Builder
        journey_build: Optional[JourneyBuildResult] = None
        journeys: List[Journey] = []
        if self.repository is None:
            meta.record(
                "journey_builder",
                "skipped",
                "repository required for DynamicJourneyBuilder",
            )
        else:
            journey_build = build_candidate_journeys(
                self.repository,
                origin_lat=o_lat,
                origin_lon=o_lon,
                destination_lat=d_lat,
                destination_lon=d_lon,
                departure_time=request.departure_time,
                constraints=journey_constraints,
                search_limits=limits,
            )
            journeys = list(journey_build.candidates)
            meta.journey_candidate_count = len(journeys)
            meta.network_snapshot_versions.update(
                journey_build.network_snapshot_versions
            )
            meta.record(
                "journey_builder",
                "invoked",
                "DynamicJourneyBuilder graph search",
                candidates=len(journeys),
                warnings=list(journey_build.warnings),
            )

        # 5–6. Live traffic enrichment only when needed
        enrichment_results: Dict[str, List[Any]] = {}
        if request.invoke_live_traffic and journeys:
            needed = [j for j in journeys if j.enrichment_requirements]
            if not needed:
                meta.record(
                    "traffic_enrichment",
                    "skipped",
                    "no road legs requiring enrichment",
                )
            else:
                dep = request.departure_time.isoformat()
                for journey in needed:
                    try:
                        results = enrich_road_legs(
                            journey,
                            get_routes=self.traffic_get_routes,
                            departure_time=dep,
                        )
                    except Exception as exc:
                        meta.warnings.append(
                            f"TRAFFIC_ENRICHMENT_FAILED ({type(exc).__name__})"
                        )
                        results = []
                    enrichment_results[journey.candidate_id] = results
                    meta.enrichment_count += sum(1 for r in results if r.available)
                meta.record(
                    "traffic_enrichment",
                    "invoked",
                    "enrich road access/egress legs via Maps",
                    journeys=len(needed),
                    enriched_legs=meta.enrichment_count,
                )
        else:
            meta.record(
                "traffic_enrichment",
                "skipped",
                "disabled or no candidates",
            )

        # 7. Historical
        historical: Optional[HistoricalCapabilityResult] = None
        if request.invoke_historical:
            hour = request.departure_time.hour
            historical = get_historical_context(
                origin_zone=request.origin_zone,
                destination_zone=request.destination_zone,
                hour=hour,
                provider=self.historical_provider,
            )
            meta.record(
                "historical_mobility",
                "invoked" if historical.available else "unavailable",
                historical.reason,
                coverage=historical.coverage,
            )
            if not historical.coverage:
                meta.warnings.append("HISTORICAL_COVERAGE_MISSING")
        else:
            meta.record("historical_mobility", "skipped", "disabled by request")

        # 8. Weather / context
        weather: Optional[ContextCapabilityResult] = None
        if request.invoke_weather:
            weather = get_weather_context(
                request.origin, weather_provider=self.weather_provider
            )
            meta.record(
                "weather_context",
                "invoked" if weather.available else "unavailable",
                weather.reason,
            )
            if not weather.available:
                meta.warnings.append("WEATHER_UNAVAILABLE")
        else:
            meta.record("weather_context", "skipped", "disabled by request")

        # 9. Decision Engine (authoritative ranking)
        evaluation: Optional[EvaluationResult] = None
        decision: Optional[DecisionCapabilityResult] = None
        route_candidates: List[RouteCandidate] = []
        legacy: Optional[PlannerResult] = None

        if journeys:
            route_candidates = journeys_to_route_candidates(
                journeys,
                enrichments=enrichment_results,
                historical=historical,
            )
            prefs = request.preferences or UserPreferences(
                excluded_modes=personalization.excluded_modes,
                max_walking_minutes=personalization.max_walking_minutes,
            )
            evaluation = evaluate_routes(route_candidates, prefs)
            meta.decision_engine_invoked = True
            decision = _decision_from_evaluation(evaluation)
            meta.record(
                "decision_engine",
                "invoked",
                "deterministic ranking of journey candidates",
                recommended=decision.recommended_route_id,
            )
        elif request.allow_legacy_maps_fallback:
            meta.fallbacks.append("legacy_plan_commute")
            meta.record(
                "journey_builder",
                "failed",
                "NO_FEASIBLE_JOURNEY — falling back to Maps planner",
            )
            try:
                legacy = self.legacy_plan_fn(
                    CommuteRequest(
                        user_id=request.user_id,
                        origin=request.origin,
                        destination=request.destination,
                        departure_time=request.departure_time.isoformat(),
                        preferences=request.preferences,
                        origin_zone=request.origin_zone,
                        destination_zone=request.destination_zone,
                    )
                )
                evaluation = legacy.evaluation
                route_candidates = list(legacy.routes)
                meta.decision_engine_invoked = evaluation is not None
                if evaluation:
                    decision = _decision_from_evaluation(evaluation)
                meta.record(
                    "legacy_plan_commute",
                    "invoked",
                    "existing deterministic Maps planner fallback",
                )
            except Exception as exc:
                meta.record(
                    "legacy_plan_commute",
                    "failed",
                    f"{type(exc).__name__}",
                )
                meta.warnings.append("LEGACY_PLANNER_FAILED")
        else:
            meta.record(
                "decision_engine",
                "skipped",
                "no journey candidates and legacy fallback disabled",
            )
            meta.warnings.append("NO_FEASIBLE_JOURNEY")

        # 10–11. Explanation (Gemini optional; never overrides ranking)
        explanation = _deterministic_explanation(decision, evaluation, meta)
        gemini_invoked = False
        adk_invoked = False
        mode = "deterministic_fallback"
        meta.explanation_mode = mode

        if request.invoke_gemini and gemini_available and adk_importable():
            if self.explain_fn is not None:
                try:
                    text, ok, err = self.explain_fn(request, evaluation, decision)
                    if ok and text:
                        explanation = text
                        gemini_invoked = True
                        adk_invoked = True
                        mode = "adk_gemini"
                        meta.explanation_mode = mode
                        meta.record(
                            "gemini_explanation",
                            "invoked",
                            "explain Decision Engine result only",
                        )
                    else:
                        meta.record(
                            "gemini_explanation",
                            "failed",
                            err or "empty explanation",
                        )
                        meta.fallbacks.append("deterministic_explanation")
                except Exception as exc:
                    meta.record(
                        "gemini_explanation",
                        "failed",
                        type(exc).__name__,
                    )
                    meta.fallbacks.append("deterministic_explanation")
            else:
                # Default: reuse planner explanation path when a PlannerResult exists
                meta.record(
                    "gemini_explanation",
                    "skipped",
                    "no explain_fn injected; use deterministic explanation",
                )
                meta.fallbacks.append("deterministic_explanation")
        else:
            meta.record(
                "gemini_explanation",
                "skipped",
                "gemini unavailable or not requested",
            )

        meta.gemini_invoked = gemini_invoked

        if legacy is not None:
            recommendation = ground_recommendation(legacy, explanation)
        elif evaluation is not None:
            # Build a minimal PlannerResult for grounding helpers
            pseudo = PlannerResult(
                request=CommuteRequest(
                    user_id=request.user_id,
                    origin=request.origin,
                    destination=request.destination,
                    departure_time=request.departure_time.isoformat(),
                    preferences=request.preferences,
                    origin_zone=request.origin_zone,
                    destination_zone=request.destination_zone,
                ),
                routes=route_candidates,
                evaluation=evaluation,
                data_sources=["journey_builder", "decision_engine"],
                historical_signal_used=bool(historical and historical.coverage),
                warnings=list(meta.warnings),
            )
            recommendation = recommendation_from_planner(pseudo, explanation)
            # Defense: discard any conflicting Gemini override attempts
            recommendation = ground_recommendation(
                pseudo,
                explanation,
                conflicting=None,
            )
        else:
            recommendation = AgentRecommendation(
                recommended_route=None,
                alternatives=[],
                estimated_time=None,
                estimated_cost=None,
                walking_time=None,
                transfers=None,
                reliability=None,
                traffic=None,
                explanation=explanation,
                reason_codes=[],
                data_sources=[],
                historical_signal_used=False,
                replanning_available=False,
                warnings=list(meta.warnings),
                error="NO_FEASIBLE_JOURNEY",
            )

        recommendation.warnings = list(
            dict.fromkeys(list(recommendation.warnings) + list(meta.warnings))
        )

        return OrchestrationResult(
            recommendation=recommendation,
            journey_build=journey_build,
            journeys=journeys,
            route_candidates=route_candidates,
            evaluation=evaluation,
            decision=decision,
            mobility_context=mobility_context,
            personalization=personalization,
            historical=historical,
            weather=weather,
            enrichment_results=enrichment_results,
            metadata=meta,
            legacy_planner_result=legacy,
            gemini_available=gemini_available,
            gemini_invoked=gemini_invoked,
            adk_invoked=adk_invoked,
            mode=mode,
        )

    def _empty_result(
        self,
        meta: OrchestrationMetadata,
        personalization: PersonalizationResult,
        *,
        error: str,
        explanation: str,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            recommendation=AgentRecommendation(
                recommended_route=None,
                alternatives=[],
                estimated_time=None,
                estimated_cost=None,
                walking_time=None,
                transfers=None,
                reliability=None,
                traffic=None,
                explanation=explanation,
                reason_codes=[],
                data_sources=[],
                historical_signal_used=False,
                replanning_available=False,
                warnings=list(meta.warnings),
                error=error,
            ),
            journey_build=None,
            journeys=[],
            route_candidates=[],
            evaluation=None,
            decision=None,
            mobility_context=None,
            personalization=personalization,
            historical=None,
            weather=None,
            enrichment_results={},
            metadata=meta,
        )


def _decision_from_evaluation(evaluation: EvaluationResult) -> DecisionCapabilityResult:
    ranked = [
        s.route.route_id
        for s in evaluation.ranked_routes
        if s.is_valid
    ]
    scores = {
        s.route.route_id: float(s.final_score)
        for s in evaluation.ranked_routes
        if s.is_valid
    }
    categories = {
        c.category: c.route.route_id for c in (evaluation.route_categories or [])
    }
    rec = evaluation.recommended_route
    return DecisionCapabilityResult(
        ranked_route_ids=ranked,
        recommended_route_id=rec.route_id if rec else None,
        category_assignments=categories,
        scores=scores,
        reason_codes=list(evaluation.reason_codes or []),
        evaluation=evaluation.to_dict(),
        authoritative=True,
    )


def _deterministic_explanation(
    decision: Optional[DecisionCapabilityResult],
    evaluation: Optional[EvaluationResult],
    meta: OrchestrationMetadata,
) -> str:
    if decision and decision.recommended_route_id:
        score = decision.scores.get(decision.recommended_route_id)
        score_txt = f" (score={score:.1f})" if score is not None else ""
        return (
            f"Deterministic Decision Engine selected journey "
            f"{decision.recommended_route_id}{score_txt} as BEST_OVERALL. "
            f"Candidates considered: {meta.journey_candidate_count}. "
            f"{FALLBACK_NOTICE}"
        )
    if meta.warnings:
        return f"No feasible recommendation. Warnings: {', '.join(meta.warnings)}"
    return FALLBACK_NOTICE


def plan_commute_with_adk(
    request: OrchestratorRequest,
    *,
    repository: Optional[StaticMobilityDataRepository] = None,
    **orchestrator_kwargs: Any,
) -> OrchestrationResult:
    """
    High-level Phase 5D entry point.

    Always produces deterministic ranking when candidates exist.
    Gemini explanation is optional and never overrides Decision Engine.
    """
    orch = MobilityOrchestrator(repository=repository, **orchestrator_kwargs)
    return orch.run(request)
