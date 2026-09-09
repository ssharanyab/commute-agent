"""Phase 7A — Mobility strategy + constraints contract (no ranking changes)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent.mobility_strategy import (
    AccessoryMode,
    MobilityConstraints,
    MobilityStrategy,
    is_public_transport_mode,
    merge_excluded_modes,
    parse_strategy,
    public_transport_mode_values,
)
from src.api.schemas import PlanRequest
from src.api.service import orchestrator_request_from_plan
from src.network.models import MobilityMode


class TestMobilityStrategy:
    def test_enum_values(self):
        assert MobilityStrategy.AGENT_DECIDES.value == "AGENT_DECIDES"
        assert MobilityStrategy.PUBLIC_TRANSPORT_FIRST.value == "PUBLIC_TRANSPORT_FIRST"
        assert MobilityStrategy.ROAD_TRANSPORT_FIRST.value == "ROAD_TRANSPORT_FIRST"
        assert MobilityStrategy.PUBLIC_TRANSPORT_ONLY.value == "PUBLIC_TRANSPORT_ONLY"

    def test_parse_round_trip(self):
        for s in MobilityStrategy:
            assert MobilityStrategy.parse(s.value) is s
            assert MobilityStrategy.parse(s.value.lower()) is s

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="invalid mobility strategy"):
            MobilityStrategy.parse("METRO_ONLY")

    def test_parse_strategy_optional(self):
        assert parse_strategy(None) is None
        assert parse_strategy("") is None
        assert parse_strategy("  ") is None
        assert parse_strategy("agent_decides") is MobilityStrategy.AGENT_DECIDES


class TestAccessoryAndPublicTransport:
    def test_accessory_aliases(self):
        assert AccessoryMode.parse("WALK") is AccessoryMode.WALK
        assert AccessoryMode.parse("auto_rickshaw") is AccessoryMode.AUTO
        assert AccessoryMode.parse("taxi") is AccessoryMode.CAB

    def test_accessory_invalid(self):
        with pytest.raises(ValueError, match="invalid accessory mode"):
            AccessoryMode.parse("helicopter")

    def test_public_transport_classification(self):
        assert public_transport_mode_values() == frozenset(
            {MobilityMode.BUS.value, MobilityMode.METRO.value}
        )
        assert is_public_transport_mode(MobilityMode.BUS) is True
        assert is_public_transport_mode(MobilityMode.METRO) is True
        assert is_public_transport_mode("bmtc") is True
        assert is_public_transport_mode("bmrcl") is True
        assert is_public_transport_mode("bus") is True
        assert is_public_transport_mode("metro") is True
        assert is_public_transport_mode(MobilityMode.WALK) is False
        assert is_public_transport_mode(MobilityMode.CAB) is False
        assert is_public_transport_mode(MobilityMode.AUTO_RICKSHAW) is False
        assert is_public_transport_mode("auto") is False


class TestMobilityConstraints:
    def test_serialization_round_trip(self):
        c = MobilityConstraints(
            excluded_modes=["cab", "auto"],
            max_walking_distance_meters=1000,
            max_transfers=2,
            allowed_accessory_modes=[AccessoryMode.WALK, AccessoryMode.AUTO],
        )
        d = c.to_dict()
        assert d["excluded_modes"] == ["cab", "auto"]
        assert d["max_walking_distance_meters"] == 1000
        assert d["max_transfers"] == 2
        assert d["allowed_accessory_modes"] == ["walk", "auto"]
        again = MobilityConstraints.from_mapping(d)
        assert again == c

    def test_from_mapping_none(self):
        assert MobilityConstraints.from_mapping(None) is None

    def test_negative_walking_rejected(self):
        with pytest.raises(ValueError, match="max_walking_distance_meters"):
            MobilityConstraints(max_walking_distance_meters=-1)

    def test_negative_transfers_rejected(self):
        with pytest.raises(ValueError, match="max_transfers"):
            MobilityConstraints(max_transfers=-2)

    def test_merge_excluded_modes(self):
        c = MobilityConstraints(excluded_modes=["cab"])
        assert merge_excluded_modes(["auto"], c) == ["auto", "cab"]
        assert merge_excluded_modes(["auto"], None) == ["auto"]
        assert merge_excluded_modes(None, None) is None


class TestPlanRequestContract:
    def test_missing_strategy_and_constraints_ok(self):
        body = PlanRequest(origin="A", destination="B")
        assert body.strategy is None
        assert body.constraints is None

    def test_strategy_serialization(self):
        for value in (
            "AGENT_DECIDES",
            "PUBLIC_TRANSPORT_FIRST",
            "ROAD_TRANSPORT_FIRST",
            "PUBLIC_TRANSPORT_ONLY",
        ):
            body = PlanRequest(origin="A", destination="B", strategy=value.lower())
            assert body.strategy == value

    def test_invalid_strategy_422_shape(self):
        with pytest.raises(ValidationError):
            PlanRequest(origin="A", destination="B", strategy="NOT_A_STRATEGY")

    def test_constraints_validation(self):
        with pytest.raises(ValidationError):
            PlanRequest(
                origin="A",
                destination="B",
                constraints={"max_walking_distance_meters": -5},
            )
        with pytest.raises(ValidationError):
            PlanRequest(
                origin="A",
                destination="B",
                constraints={"max_transfers": -1},
            )
        with pytest.raises(ValidationError):
            PlanRequest(
                origin="A",
                destination="B",
                constraints={"allowed_accessory_modes": ["ferry"]},
            )

    def test_constraints_round_trip(self):
        body = PlanRequest(
            origin="Electronic City, Bengaluru",
            destination="Majestic, Bengaluru",
            strategy="PUBLIC_TRANSPORT_FIRST",
            preference_profile="BALANCED",
            constraints={
                "excluded_modes": ["cab"],
                "max_walking_distance_meters": 1000,
                "max_transfers": 2,
                "allowed_accessory_modes": ["walk", "auto"],
            },
        )
        dumped = body.model_dump()
        assert dumped["strategy"] == "PUBLIC_TRANSPORT_FIRST"
        assert dumped["constraints"]["excluded_modes"] == ["cab"]
        assert dumped["constraints"]["allowed_accessory_modes"] == ["walk", "auto"]

    def test_legacy_excluded_modes_still_on_preferences(self):
        body = PlanRequest(
            origin="A",
            destination="B",
            preferences={"excluded_modes": ["auto", "cab"]},
        )
        assert body.preferences.excluded_modes == ["auto", "cab"]
        assert body.constraints is None


class TestOrchestratorWiring:
    def test_strategy_reaches_orchestrator_request(self):
        body = PlanRequest(
            origin="Electronic City, Bengaluru",
            destination="Majestic, Bengaluru",
            strategy="PUBLIC_TRANSPORT_FIRST",
            preference_profile="BALANCED",
            constraints={
                "excluded_modes": ["cab"],
                "max_walking_distance_meters": 800,
                "max_transfers": 1,
                "allowed_accessory_modes": ["walk", "auto"],
            },
            invoke_gemini=False,
            invoke_live_traffic=False,
        )
        req = orchestrator_request_from_plan(body)
        assert req.strategy is MobilityStrategy.PUBLIC_TRANSPORT_FIRST
        assert req.constraints is not None
        assert req.constraints.max_walking_distance_meters == 800
        assert req.constraints.max_transfers == 1
        assert req.constraints.allowed_accessory_modes == [
            AccessoryMode.WALK,
            AccessoryMode.AUTO,
        ]
        # Exclusion merged into preferences for existing DE path; strategy not applied.
        assert req.preferences is not None
        assert "cab" in (req.preferences.excluded_modes or [])

    def test_missing_strategy_leaves_orchestrator_unset(self):
        body = PlanRequest(
            origin="Electronic City, Bengaluru",
            destination="Majestic, Bengaluru",
            preferences={"excluded_modes": ["auto"]},
            invoke_gemini=False,
            invoke_live_traffic=False,
        )
        req = orchestrator_request_from_plan(body)
        assert req.strategy is None
        assert req.constraints is None
        assert req.preferences.excluded_modes == ["auto"]

    def test_preferences_and_constraints_excluded_union(self):
        body = PlanRequest(
            origin="A",
            destination="B",
            preferences={"excluded_modes": ["auto"]},
            constraints={"excluded_modes": ["cab"]},
        )
        req = orchestrator_request_from_plan(body)
        assert req.preferences.excluded_modes == ["auto", "cab"]
