"""
Phase 7K-8 — prune redundant pure-road mode chains (retention only).

Does not change Decision Engine weights or Metro scoring.
"""

from __future__ import annotations

from src.journey_builder.diversity import (
    collapse_mode_tokens,
    is_redundant_road_only_chain,
    select_diverse_journeys,
    select_diverse_partials,
)
from src.journey_builder.models import Journey


class _Partial:
    def __init__(self, modes):
        self.modes = tuple(modes)
        self.edge_ids = modes


def _journey(modes: tuple, cid: str = "j") -> Journey:
    return Journey(
        candidate_id=cid,
        origin=(0.0, 0.0),
        destination=(1.0, 1.0),
        legs=[],
        transfer_count=0,
        walking_distance_meters=0.0,
        transit_leg_count=0,
        road_leg_count=len(modes),
        modes=list(modes),
        snapshot_versions={},
        provenance_sources=[],
        enrichment_requirements=[],
        temporal_feasibility="unknown",
        mode_signature=" → ".join(collapse_mode_tokens(modes)),
    )


class TestPhase7K8RedundantRoadChains:
    def test_auto_cab_is_redundant(self):
        assert is_redundant_road_only_chain(("auto", "cab"))
        assert is_redundant_road_only_chain(("auto_rickshaw", "cab"))

    def test_cab_auto_is_redundant(self):
        assert is_redundant_road_only_chain(("cab", "auto"))
        assert is_redundant_road_only_chain(("cab", "auto_rickshaw"))

    def test_auto_auto_and_cab_cab_are_redundant(self):
        assert is_redundant_road_only_chain(("auto", "auto"))
        assert is_redundant_road_only_chain(("cab", "cab"))

    def test_single_road_kept(self):
        assert not is_redundant_road_only_chain(("auto",))
        assert not is_redundant_road_only_chain(("cab",))

    def test_auto_bus_auto_kept(self):
        assert not is_redundant_road_only_chain(("auto", "bus", "auto"))
        assert not is_redundant_road_only_chain(("auto", "bmtc", "auto"))

    def test_walk_metro_walk_kept(self):
        assert not is_redundant_road_only_chain(("walk", "metro", "walk"))

    def test_auto_metro_walk_kept(self):
        assert not is_redundant_road_only_chain(("auto", "metro", "walk"))

    def test_select_diverse_partials_drops_auto_cab(self):
        partials = [
            _Partial(("auto", "cab")),
            _Partial(("cab", "auto")),
            _Partial(("auto", "bus", "auto")),
            _Partial(("walk", "metro", "walk")),
            _Partial(("auto", "metro", "walk")),
            _Partial(("auto",)),
        ]
        kept, meta = select_diverse_partials(partials, max_keep=10)
        sigs = {collapse_mode_tokens(p.modes) for p in kept}
        assert ("auto", "cab") not in sigs
        assert ("cab", "auto") not in sigs
        assert ("auto", "bmtc", "auto") in sigs
        assert ("walk", "metro", "walk") in sigs
        assert ("auto", "metro", "walk") in sigs
        assert ("auto",) in sigs
        assert meta["redundant_road_chains_pruned"] >= 2

    def test_select_diverse_journeys_drops_auto_cab(self):
        journeys = [
            _journey(("auto_rickshaw", "cab"), "ac"),
            _journey(("cab", "auto_rickshaw"), "ca"),
            _journey(("auto_rickshaw", "bus", "auto_rickshaw"), "aba"),
            _journey(("walk", "metro", "walk"), "wmw"),
            _journey(("auto_rickshaw", "metro", "walk"), "amw"),
        ]
        kept, meta = select_diverse_journeys(journeys, max_candidates=10)
        sigs = {collapse_mode_tokens(j.modes) for j in kept}
        assert ("auto", "cab") not in sigs
        assert ("cab", "auto") not in sigs
        assert ("auto", "bmtc", "auto") in sigs
        assert ("walk", "metro", "walk") in sigs
        assert ("auto", "metro", "walk") in sigs
        assert meta["redundant_road_chains_pruned"] == 2
