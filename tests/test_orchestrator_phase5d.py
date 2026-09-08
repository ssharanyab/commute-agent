"""
Phase 5D — ADK Mobility Orchestrator tests.

Canonical demo OD: Electronic City → Majestic (not a hardcoded production route).
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.agent.orchestrator as orch_mod
import src.agent.capabilities as cap_pkg
from src.agent.demo_od import (
    CANONICAL_DEMO_DEPARTURE,
    ELECTRONIC_CITY,
    MAJESTIC,
)
from src.agent.orchestrator import (
    MobilityOrchestrator,
    OrchestratorRequest,
    plan_commute_with_adk,
)
from src.agent.capabilities.network import query_mobility_network
from src.agent.capabilities.historical import get_historical_context
from src.agent.capabilities.weather import get_weather_context
from src.agent.capabilities.traffic import enrich_road_legs
from src.decision_engine.models import RouteCandidate, UserPreferences
from src.journey_builder import SearchLimits
from src.journey_builder.models import (
    EdgeKind,
    EnrichmentRequirement,
    Journey,
    JourneyLeg,
)
from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmtc_gtfs import build_bmtc_sync_pipeline
from src.network.ingest.bmrcl import build_bmrcl_sync_pipeline
from src.network.models import (
    DataProvenance,
    MobilityMode,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)
from src.network.sync.validation import assert_no_hardcoded_journeys
from src.planner.models import PlannerResult, CommuteRequest
from src.decision_engine.models import EvaluationResult


def _prov() -> dict:
    return DataProvenance(
        source="orch_test",
        source_type=SourceType.INTERNAL_DERIVED,
        retrieved_at=datetime.now(timezone.utc),
        version="t1",
    ).to_dict()


def _publish_corridor(repo: FileStaticMobilityRepository) -> None:
    """Synthetic corridor usable for Electronic City → Majestic-scale tests."""
    p = _prov()
    # Place stops near EC and Majestic-ish coords so access works in unit tests.
    payload = {
        "stops": [
            {
                "id": "EC_STOP",
                "name": "Electronic City Bus Stop",
                "latitude": ELECTRONIC_CITY.latitude,
                "longitude": ELECTRONIC_CITY.longitude,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "MID_STOP",
                "name": "Mid Corridor Stop",
                "latitude": 12.91,
                "longitude": 77.61,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "MAJ_STOP",
                "name": "Majestic Bus Stop",
                "latitude": MAJESTIC.latitude,
                "longitude": MAJESTIC.longitude,
                "provider": "BMTC",
                "network": "bmtc",
                "stop_type": "bus_stop",
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "stations": [
            {
                "id": "majestic_metro",
                "name": "Nadaprabhu Kempegowda Station, Majestic",
                "latitude": MAJESTIC.latitude,
                "longitude": MAJESTIC.longitude,
                "provider": "BMRCL",
                "lines": ["purple", "green"],
                "line_order": {"purple": 1, "green": 1},
                "interchange_station_ids": ["majestic_metro"],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "mid_metro",
                "name": "Mid Metro",
                "latitude": 12.91,
                "longitude": 77.615,
                "provider": "BMRCL",
                "lines": ["purple"],
                "line_order": {"purple": 2},
                "interchange_station_ids": [],
                "accessibility": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "routes": [
            {
                "id": "BUS_EC_MAJ",
                "name": "EC to Majestic Bus",
                "short_name": "ECM",
                "provider": "BMTC",
                "network": "bmtc",
                "mode": "bus",
                "stop_ids": ["EC_STOP", "MID_STOP", "MAJ_STOP"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
            {
                "id": "purple",
                "name": "Purple Line",
                "short_name": "P",
                "provider": "BMRCL",
                "network": "bmrcl",
                "mode": "metro",
                "stop_ids": ["mid_metro", "majestic_metro"],
                "geometry_ref": None,
                "service_metadata": {},
                "source_metadata": {},
                "provenance": p,
            },
        ],
        "fare_rules": [],
    }
    snap = MobilityNetworkSnapshot(
        dataset_name="demo_network",
        provider="test",
        version="ec-maj-v1",
        fetched_at=datetime.now(timezone.utc),
        record_count=8,
        source="orch_test",
        validation_status=ValidationStatus.VALID,
        provenance=DataProvenance.from_dict(p),
        checksum="x",
        payload=payload,
    )
    repo.publish_snapshot(snap)


@pytest.fixture
def demo_repo(tmp_path: Path):
    repo = FileStaticMobilityRepository(tmp_path)
    _publish_corridor(repo)
    return repo


def _ec_maj_request(**kwargs) -> OrchestratorRequest:
    base = dict(
        user_id="demo-user",
        origin=ELECTRONIC_CITY.address,
        destination=MAJESTIC.address,
        departure_time=CANONICAL_DEMO_DEPARTURE,
        origin_lat=ELECTRONIC_CITY.latitude,
        origin_lon=ELECTRONIC_CITY.longitude,
        destination_lat=MAJESTIC.latitude,
        destination_lon=MAJESTIC.longitude,
        invoke_gemini=False,
        invoke_weather=True,
        invoke_historical=True,
        invoke_live_traffic=False,
        allow_legacy_maps_fallback=False,
        search_limits=SearchLimits(
            max_walking_access_meters=500,
            max_walking_egress_meters=500,
            max_walk_transfer_meters=400,
            max_direct_walk_meters=100,
            allow_road_access=True,
            max_candidates=15,
            max_transfers=3,
            max_legs=10,
        ),
    )
    base.update(kwargs)
    return OrchestratorRequest(**base)


class TestArchitecturalRegression:
    def test_no_hardcoded_journey_templates(self):
        assert_no_hardcoded_journeys(vars(orch_mod))
        assert_no_hardcoded_journeys(vars(cap_pkg))
        for path in Path("src/agent").rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            assert not re.search(r"^\s*ALLOWED_JOURNEYS\s*=", src, re.M)
            assert not re.search(r"^\s*SUPPORTED_COMBINATIONS\s*=", src, re.M)
            assert "AUTO_METRO_WALK" not in src
            assert "BUS_METRO_WALK" not in src


class TestCapabilities:
    def test_network_reads_repository(self, demo_repo):
        ctx = query_mobility_network(
            demo_repo,
            latitude=ELECTRONIC_CITY.latitude,
            longitude=ELECTRONIC_CITY.longitude,
        )
        assert ctx.available
        assert ctx.network_snapshot_versions.get("demo_network") == "ec-maj-v1"
        assert any(s["id"] == "EC_STOP" for s in ctx.relevant_stops)

    def test_historical_missing_zones_no_fabrication(self):
        result = get_historical_context(
            origin_zone=None, destination_zone=None, hour=8
        )
        assert result.coverage is False
        assert result.expected_duration_minutes is None
        assert "INSUFFICIENT" in result.reason

    def test_weather_unavailable(self):
        ctx = get_weather_context("Electronic City, Bengaluru")
        assert ctx.available is False
        assert ctx.weather is None
        assert ctx.reason == "not_configured"


class TestOrchestrator:
    def test_invokes_required_capabilities(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(_ec_maj_request())
        names = {c.name: c.status for c in result.metadata.capabilities}
        assert names.get("personalization") == "invoked"
        assert names.get("mobility_network") == "invoked"
        assert names.get("journey_builder") == "invoked"
        assert names.get("decision_engine") == "invoked"
        assert result.metadata.decision_engine_invoked is True

    def test_journey_builder_not_hardcoded(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(_ec_maj_request())
        assert result.journey_build is not None
        assert result.metadata.journey_candidate_count == len(result.journeys)
        # Journeys carry real stop/station refs from the network
        if result.journeys:
            refs = set()
            for j in result.journeys:
                for leg in j.legs:
                    if leg.from_ref:
                        refs.add(leg.from_ref)
                    if leg.to_ref:
                        refs.add(leg.to_ref)
            assert refs & {"EC_STOP", "MAJ_STOP", "MID_STOP", "majestic_metro", "mid_metro"}

    def test_multiple_candidates_flow(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(
            _ec_maj_request(
                search_limits=SearchLimits(
                    max_walking_access_meters=600,
                    max_walking_egress_meters=600,
                    max_walk_transfer_meters=500,
                    max_direct_walk_meters=50,
                    allow_road_access=True,
                    max_candidates=20,
                )
            )
        )
        assert result.metadata.journey_candidate_count >= 1
        assert len(result.route_candidates) == len(result.journeys) or result.evaluation

    def test_traffic_enrichment_only_when_needed(self, demo_repo):
        calls = {"n": 0}

        def fake_routes(**kwargs):
            calls["n"] += 1
            return [
                RouteCandidate(
                    route_id="drive_1",
                    mode="cab",
                    travel_time_minutes=22.0,
                    cost=200.0,
                    walking_minutes=0.0,
                    transfers=0,
                    congestion_score=0.4,
                    reliability_score=0.7,
                    disruption_risk=0.1,
                    google_polyline="poly",
                )
            ]

        orch = MobilityOrchestrator(
            repository=demo_repo, traffic_get_routes=fake_routes
        )
        # With road access enabled, enrichment may be needed
        result = orch.run(
            _ec_maj_request(
                invoke_live_traffic=True,
                search_limits=SearchLimits(
                    max_walking_access_meters=200,
                    max_walking_egress_meters=200,
                    max_direct_walk_meters=50,
                    allow_road_access=True,
                    max_road_access_meters=5000,
                    max_candidates=10,
                ),
            )
        )
        statuses = [c for c in result.metadata.capabilities if c.name == "traffic_enrichment"]
        assert statuses
        if statuses[0].status == "invoked":
            assert calls["n"] >= 1
        else:
            assert calls["n"] == 0

        # Disabled → skipped
        orch2 = MobilityOrchestrator(
            repository=demo_repo, traffic_get_routes=fake_routes
        )
        result2 = orch2.run(_ec_maj_request(invoke_live_traffic=False))
        te = [c for c in result2.metadata.capabilities if c.name == "traffic_enrichment"][0]
        assert te.status == "skipped"

    def test_historical_invoked_when_zones_present(self, demo_repo):
        provider = MagicMock()
        provider.get_signal.return_value = MagicMock(
            signal={"has_historical_coverage": False},
            provenance=DataProvenance(
                source="test",
                source_type=SourceType.RESEARCH_DATASET,
                retrieved_at=datetime.now(timezone.utc),
            ),
        )
        # Patch get_historical_context path via provider that returns coverage false
        from src.network.historical import HistoricalMobilityResult

        def get_signal(**kwargs):
            return HistoricalMobilityResult(
                signal={"has_historical_coverage": False},
                provenance=DataProvenance(
                    source="uber_test",
                    source_type=SourceType.RESEARCH_DATASET,
                    retrieved_at=datetime.now(timezone.utc),
                ),
                model_name="uber_movement_xgboost",
            )

        provider.get_signal = get_signal
        orch = MobilityOrchestrator(
            repository=demo_repo, historical_provider=provider
        )
        result = orch.run(
            _ec_maj_request(origin_zone=12, destination_zone=84, invoke_historical=True)
        )
        hist = [c for c in result.metadata.capabilities if c.name == "historical_mobility"][0]
        assert hist.status in {"invoked", "unavailable"}
        assert result.historical is not None
        assert result.historical.coverage is False
        assert "HISTORICAL_COVERAGE_MISSING" in result.metadata.warnings

    def test_weather_graceful(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(_ec_maj_request(invoke_weather=True))
        assert result.weather is not None
        assert result.weather.available is False
        assert "WEATHER_UNAVAILABLE" in result.metadata.warnings
        # Still ranks if journeys exist
        assert result.evaluation is not None or result.recommendation.error

    def test_gemini_unavailable_does_not_break(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(_ec_maj_request(invoke_gemini=True))
        assert result.gemini_invoked is False
        assert result.mode == "deterministic_fallback"
        if result.journeys:
            assert result.decision is not None
            assert result.decision.authoritative is True

    def test_decision_engine_authoritative(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(_ec_maj_request())
        if not result.journeys:
            pytest.skip("no journeys in synthetic corridor")
        assert result.decision is not None
        assert result.decision.authoritative is True
        assert (
            result.recommendation.recommended_route.route_id
            == result.decision.recommended_route_id
        )

    def test_gemini_cannot_override_decision(self, demo_repo):
        def fake_explain(request, evaluation, decision):
            return (
                "I think a different journey is better: OVERRIDE_ID",
                True,
                "",
            )

        orch = MobilityOrchestrator(
            repository=demo_repo, explain_fn=fake_explain
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "src.agent.orchestrator.gemini_credentials_available",
                lambda: True,
            )
            mp.setattr("src.agent.orchestrator.adk_importable", lambda: True)
            result = orch.run(_ec_maj_request(invoke_gemini=True))
        if not result.decision:
            pytest.skip("no decision")
        # Explanation may mention OVERRIDE_ID as text, but recommended id unchanged
        assert (
            result.recommendation.recommended_route.route_id
            == result.decision.recommended_route_id
        )
        assert result.decision.recommended_route_id != "OVERRIDE_ID"

    def test_excluded_modes_hard(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        result = orch.run(
            _ec_maj_request(
                preferences=UserPreferences(excluded_modes=["cab"]),
                invoke_live_traffic=False,
            )
        )
        for j in result.journeys:
            assert "cab" not in j.modes
            # Cab exclusion does not imply auto exclusion (Decision Engine cab family).
    def test_electronic_city_to_majestic_integration(self, demo_repo):
        result = plan_commute_with_adk(
            _ec_maj_request(),
            repository=demo_repo,
        )
        assert result.metadata.journey_candidate_count >= 1
        assert any(
            c.name == "journey_builder" and c.status == "invoked"
            for c in result.metadata.capabilities
        )
        # Dynamic discovery — do not assert a fixed combination
        mode_sets = {tuple(j.modes) for j in result.journeys}
        assert mode_sets  # at least one discovered path
        assert result.metadata.to_dict()["network_snapshot_versions"].get(
            "demo_network"
        ) == "ec-maj-v1"

    def test_deterministic_reproducible(self, demo_repo):
        orch = MobilityOrchestrator(repository=demo_repo)
        req = _ec_maj_request()
        a = orch.run(req)
        b = orch.run(req)
        assert [j.candidate_id for j in a.journeys] == [
            j.candidate_id for j in b.journeys
        ]
        if a.decision and b.decision:
            assert a.decision.recommended_route_id == b.decision.recommended_route_id

    def test_orchestration_metadata(self, demo_repo):
        result = plan_commute_with_adk(_ec_maj_request(), repository=demo_repo)
        meta = result.metadata.to_dict()
        assert "capabilities" in meta
        assert meta["journey_candidate_count"] >= 0
        assert "gemini_available" in meta
        assert "explanation_mode" in meta

    def test_api_compatibility_plan_commute_still_importable(self):
        from src.planner.service import plan_commute
        from src.agent.tools import plan_commute as tool_plan

        assert callable(plan_commute)
        assert callable(tool_plan)

    def test_phase5b_seed_orchestration_smoke(self, tmp_path: Path):
        """Real Phase 5B artifacts: graph load + orchestrate (may fallback)."""
        repo = FileStaticMobilityRepository(tmp_path)
        fixture = Path(__file__).parent / "fixtures" / "bmtc_gtfs_sample"
        assert build_bmtc_sync_pipeline(fixture, repo).run(version="bmtc").success
        seed = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "mobility_network"
            / "bmrcl"
            / "seed"
            / "bmrcl_network_seed.json"
        )
        assert build_bmrcl_sync_pipeline(repo, seed).run(version="bmrcl").success

        # EC→Majestic coords; BMTC sample won't span that OD — expect no path
        # or empty with explicit metadata (no fabrication).
        result = plan_commute_with_adk(
            _ec_maj_request(allow_legacy_maps_fallback=False),
            repository=repo,
        )
        assert any(c.name == "journey_builder" for c in result.metadata.capabilities)
        assert result.metadata.network_snapshot_versions.get("bmtc") == "bmtc"
        # Either empty candidates with warning, or whatever topology allows — never fake
        if result.metadata.journey_candidate_count == 0:
            assert (
                "NO_FEASIBLE_JOURNEY" in result.metadata.warnings
                or result.recommendation.error == "NO_FEASIBLE_JOURNEY"
                or any("NO_PATH" in w for w in (result.journey_build.warnings if result.journey_build else []))
            )


class TestEnrichmentUnit:
    def test_enrich_road_legs_uses_maps_abstraction(self):
        journey = Journey(
            candidate_id="j1",
            origin=(12.84, 77.66),
            destination=(12.97, 77.57),
            legs=[
                JourneyLeg(
                    index=0,
                    mode=MobilityMode.CAB,
                    from_node_id="a",
                    to_node_id="b",
                    edge_id="e1",
                    edge_kind=EdgeKind.ROAD_ACCESS,
                    needs_enrichment=True,
                )
            ],
            transfer_count=0,
            walking_distance_meters=0,
            transit_leg_count=0,
            road_leg_count=1,
            modes=["cab"],
            snapshot_versions={},
            provenance_sources=[],
            enrichment_requirements=[
                EnrichmentRequirement(
                    requirement_type="road_geometry_time",
                    leg_index=0,
                    mode="cab",
                    from_lat=12.84,
                    from_lon=77.66,
                    to_lat=12.85,
                    to_lon=77.67,
                )
            ],
        )

        def fake_get_routes(**kwargs):
            return [
                RouteCandidate(
                    route_id="x",
                    mode="cab",
                    travel_time_minutes=10.0,
                    cost=1.0,
                    walking_minutes=0,
                    transfers=0,
                    congestion_score=0.2,
                    reliability_score=0.8,
                    disruption_risk=0.0,
                    distance_meters=1000,
                    google_polyline="abc",
                )
            ]

        results = enrich_road_legs(journey, get_routes=fake_get_routes)
        assert len(results) == 1
        assert results[0].available is True
        assert results[0].duration_minutes == 10.0
