"""
Phase 7K-5 — Google Routes enrichment reaches Decision Engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock

import pytest

from src.agent.capabilities import TrafficEnrichmentResult
from src.agent.capabilities.adapt import journeys_to_route_candidates
from src.agent.capabilities.enrichment_apply import (
    apply_enrichments,
    apply_traffic_enrichment_to_journey,
)
from src.agent.capabilities.traffic import enrich_road_legs
from src.agent.orchestrator import MobilityOrchestrator, OrchestratorRequest
from src.decision_engine.evaluator import evaluate_routes
from src.decision_engine.models import preference_profile
from src.journey_builder.economics import aggregate_journey_economics, annotate_leg_economics, mode_signature
from src.journey_builder.models import (
    EdgeKind,
    EnrichmentRequirement,
    Journey,
    JourneyLeg,
    SegmentRole,
    ValueStatus,
)
from src.network.models import MobilityMode


def _leg(
    index: int,
    mode: MobilityMode,
    *,
    dist: float,
    role: SegmentRole,
    kind: EdgeKind,
    needs_enrichment: bool = False,
) -> JourneyLeg:
    leg = JourneyLeg(
        index=index,
        mode=mode,
        from_node_id=f"n{index}",
        to_node_id=f"n{index + 1}",
        edge_id=f"e{index}",
        edge_kind=kind,
        distance_meters=dist,
        needs_enrichment=needs_enrichment,
        segment_role=role,
    )
    return annotate_leg_economics(leg)


def _journey(legs: List[JourneyLeg], *, cid: str = "j1") -> Journey:
    econ = aggregate_journey_economics(legs)
    modes = [l.mode.value for l in legs]
    reqs = []
    for leg in legs:
        if leg.needs_enrichment:
            reqs.append(
                EnrichmentRequirement(
                    requirement_type="road_geometry_time",
                    leg_index=leg.index,
                    mode=leg.mode.value,
                    from_lat=12.97,
                    from_lon=77.57,
                    to_lat=12.975,
                    to_lon=77.60,
                )
            )
    return Journey(
        candidate_id=cid,
        origin=(12.97, 77.57),
        destination=(12.975, 77.60),
        legs=legs,
        transfer_count=0,
        walking_distance_meters=econ["walking_distance_meters"],
        transit_leg_count=sum(1 for l in legs if l.mode.value in {"bus", "metro"}),
        road_leg_count=sum(
            1 for l in legs if l.edge_kind in {EdgeKind.ROAD_ACCESS, EdgeKind.ROAD_DIRECT}
        ),
        modes=modes,
        snapshot_versions={},
        provenance_sources=["test"],
        enrichment_requirements=reqs,
        total_cost_inr=econ["total_cost_inr"],
        cost_status=econ["cost_status"],
        total_duration_seconds=econ["total_duration_seconds"],
        duration_status=econ["duration_status"],
        access_walking_meters=econ["access_walking_meters"],
        transfer_walking_meters=econ["transfer_walking_meters"],
        egress_walking_meters=econ["egress_walking_meters"],
        mode_signature=mode_signature(legs),
    )


class TestPhase7K5EnrichmentToDecisionEngine:
    def test_successful_enrichment_reaches_route_candidate(self):
        legs = [
            _leg(
                0,
                MobilityMode.AUTO_RICKSHAW,
                dist=3000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        assert j.legs[0].duration_seconds is None
        enr = {
            "j1": [
                TrafficEnrichmentResult(
                    journey_id="j1",
                    leg_index=0,
                    available=True,
                    duration_minutes=18.5,
                    distance_meters=4200.0,
                    provenance={
                        "source": "google_maps_routes",
                        "provider": "Google Routes",
                    },
                    reason="ok",
                )
            ]
        }
        applied = apply_enrichments([j], enr)
        assert applied[0].legs[0].duration_status == ValueStatus.KNOWN.value
        assert applied[0].legs[0].duration_seconds == pytest.approx(18.5 * 60)
        assert applied[0].legs[0].distance_meters == 4200.0
        assert applied[0].duration_status == ValueStatus.KNOWN.value
        assert "Google Routes" in (applied[0].legs[0].provenance.notes or "")

        cands = journeys_to_route_candidates(applied, enrichments=enr)
        assert cands[0].duration_status == "known"
        assert cands[0].travel_time_minutes == pytest.approx(18.5)
        assert cands[0].distance_meters == 4200

        ranked = evaluate_routes(cands, preference_profile("FASTEST"))
        assert ranked.recommended_route is not None
        assert ranked.recommended_route.travel_time_minutes == pytest.approx(18.5)

    def test_failed_maps_remains_unknown_not_zero_on_leg(self):
        legs = [
            _leg(
                0,
                MobilityMode.CAB,
                dist=5000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        enr = {
            "j1": [
                TrafficEnrichmentResult(
                    journey_id="j1",
                    leg_index=0,
                    available=False,
                    reason="NO_ROUTES",
                    provenance={"source": "google_maps_routes"},
                )
            ]
        }
        applied = apply_enrichments([j], enr)
        assert applied[0].legs[0].duration_seconds is None
        assert applied[0].legs[0].duration_status == ValueStatus.UNAVAILABLE.value
        assert applied[0].legs[0].duration_seconds != 0

        cands = journeys_to_route_candidates(applied, enrichments=enr)
        assert cands[0].duration_status in {"unknown", "unavailable"}
        # Must not look like a 0-minute trip.
        assert cands[0].travel_time_minutes != 0.0

    def test_multiple_road_legs_independently_enriched(self):
        legs = [
            _leg(
                0,
                MobilityMode.AUTO_RICKSHAW,
                dist=800,
                role=SegmentRole.ACCESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
            _leg(
                1,
                MobilityMode.METRO,
                dist=4000,
                role=SegmentRole.TRANSIT,
                kind=EdgeKind.METRO,
            ),
            _leg(
                2,
                MobilityMode.AUTO_RICKSHAW,
                dist=900,
                role=SegmentRole.EGRESS,
                kind=EdgeKind.ROAD_ACCESS,
                needs_enrichment=True,
            ),
        ]
        j = _journey(legs)
        assert len(j.enrichment_requirements) == 2

        class _Cand:
            travel_time_minutes = 0
            distance_meters = 0
            congestion_score = 0.3
            mode = "DRIVE"
            google_polyline = "poly"
            google_route_token = "tok"

        calls = []

        def fake_get_routes(**kwargs):
            calls.append(kwargs)
            c = _Cand()
            c.travel_time_minutes = 4.0 + len(calls)
            c.distance_meters = 1000.0 * len(calls)
            return [c]

        results = enrich_road_legs(j, get_routes=fake_get_routes)
        assert len(calls) == 2
        assert len(results) == 2
        assert all(r.available for r in results)
        assert results[0].leg_index == 0
        assert results[1].leg_index == 2
        assert results[0].duration_minutes != results[1].duration_minutes

        out = apply_traffic_enrichment_to_journey(j, results)
        assert out.legs[0].duration_seconds == pytest.approx(5.0 * 60)
        assert out.legs[2].duration_seconds == pytest.approx(6.0 * 60)
        assert out.legs[1].duration_status == ValueStatus.UNKNOWN.value
        # Totals stay unknown because metro is unknown — but road legs known.
        assert out.duration_status == ValueStatus.UNKNOWN.value
        assert out.legs[0].duration_status == ValueStatus.KNOWN.value
        assert out.legs[2].duration_status == ValueStatus.KNOWN.value

        cands = journeys_to_route_candidates(
            [out], enrichments={j.candidate_id: results}
        )
        # travel time includes Google road + structural metro
        assert cands[0].travel_time_minutes > 11.0  # 5+6 + metro
        assert results[0].provenance.get("provider") == "Google Routes"

    def test_google_distance_and_duration_on_candidate(self):
        legs = [
            _leg(
                0,
                MobilityMode.CAB,
                dist=1000,
                role=SegmentRole.FULL_JOURNEY_ROAD,
                kind=EdgeKind.ROAD_DIRECT,
                needs_enrichment=True,
            )
        ]
        j = _journey(legs)
        enr = {
            "j1": [
                TrafficEnrichmentResult(
                    journey_id="j1",
                    leg_index=0,
                    available=True,
                    duration_minutes=9.25,
                    distance_meters=3333.0,
                    provenance={"source": "google_maps_routes", "provider": "Google Routes"},
                    reason="ok",
                )
            ]
        }
        applied = apply_enrichments([j], enr)
        cands = journeys_to_route_candidates(applied, enrichments=enr)
        assert cands[0].distance_meters == 3333
        assert cands[0].travel_time_minutes == pytest.approx(9.25)
        assert cands[0].duration_status == "known"

    def test_orchestrator_invokes_enrichment_before_decision(self, tmp_path):
        """Runtime path: JB → enrich → apply → adapt → DE (mocked Maps)."""
        from src.network.file_repository import FileStaticMobilityRepository
        from src.network.models import (
            DataProvenance,
            MobilityNetworkSnapshot,
            SourceType,
            ValidationStatus,
        )

        repo = FileStaticMobilityRepository(tmp_path)
        p = DataProvenance(
            source="t",
            source_type=SourceType.INTERNAL_DERIVED,
            retrieved_at=datetime.now(timezone.utc),
        ).to_dict()
        # Minimal network so JB can emit a direct road OD.
        snap = MobilityNetworkSnapshot(
            dataset_name="bmrcl",
            provider="test",
            version="t",
            fetched_at=datetime.now(timezone.utc),
            record_count=0,
            source="t",
            validation_status=ValidationStatus.VALID,
            provenance=DataProvenance.from_dict(p),
            checksum="x",
            payload={"stations": [], "routes": [], "stops": [], "fare_rules": []},
        )
        repo.publish_snapshot(snap)

        class _Cand:
            travel_time_minutes = 14.0
            distance_meters = 5500.0
            congestion_score = 0.45
            mode = "DRIVE"
            google_polyline = "abc"
            google_route_token = "rt"

        fake = MagicMock(return_value=[_Cand()])
        orch = MobilityOrchestrator(repository=repo, traffic_get_routes=fake)
        req = OrchestratorRequest(
            user_id="t",
            origin="A",
            destination="B",
            departure_time=datetime(2024, 9, 6, 8, 0, tzinfo=timezone.utc),
            origin_lat=12.9700,
            origin_lon=77.5800,
            destination_lat=12.9750,
            destination_lon=77.6060,
            invoke_live_traffic=True,
            invoke_gemini=False,
            invoke_weather=False,
            invoke_historical=False,
        )
        result = orch.run(req)
        caps = {c.name: c for c in (result.metadata.capabilities or [])}
        assert "traffic_enrichment" in caps
        # Direct road candidates should trigger Maps.
        if any(j.enrichment_requirements for j in (result.journeys or [])):
            assert fake.called
            assert caps["traffic_enrichment"].status == "invoked"
            detail = caps["traffic_enrichment"].detail or {}
            assert detail.get("provider") == "Google Routes"
            # At least one road candidate should carry known Google duration.
            roadish = [
                c
                for c in result.route_candidates
                if c.mode in {"auto_rickshaw", "cab", "hybrid"}
                or "auto" in (c.mode_signature or "")
                or "cab" in (c.mode_signature or "")
            ]
            known_road = [c for c in roadish if c.duration_status == "known"]
            # Pure auto/cab OD after enrichment should be known.
            assert known_road or any(
                c.duration_status == "known" for c in result.route_candidates
            )
