"""
Dataset registry for external mobility / intelligence sources (Phase 5A).

Descriptors document intent and configuration state. They do NOT claim a
source is "official" unless that is explicitly recorded as known.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DatasetDescriptor:
    dataset_id: str
    name: str
    provider: str
    authority_or_source: str
    static_or_live: str  # "static" | "live" | "historical_model"
    expected_refresh_cadence: str
    ingestion_adapter: str
    license_or_usage_notes: str
    currently_configured: bool
    authoritative_or_secondary: str  # "authoritative" | "secondary" | "unknown"
    notes: str = ""
    claimed_official: bool = False

    def to_dict(self) -> Dict:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "provider": self.provider,
            "authority_or_source": self.authority_or_source,
            "static_or_live": self.static_or_live,
            "expected_refresh_cadence": self.expected_refresh_cadence,
            "ingestion_adapter": self.ingestion_adapter,
            "license_or_usage_notes": self.license_or_usage_notes,
            "currently_configured": self.currently_configured,
            "authoritative_or_secondary": self.authoritative_or_secondary,
            "notes": self.notes,
            "claimed_official": self.claimed_official,
        }


# Phase 5B configures Bengaluru static ingest adapters with explicit provenance.
DATASET_REGISTRY: Dict[str, DatasetDescriptor] = {
    "bmtc_network": DatasetDescriptor(
        dataset_id="bmtc_network",
        name="BMTC schedule data — community GTFS",
        provider="BMTC",
        authority_or_source=(
            "COMMUNITY_UNOFFICIAL — MobilityDatabase mdb-2595 / "
            "Vonter unofficial BMTC GTFS (https://github.com/Vonter/bmtc-gtfs). "
            "Producer notes derivation from Namma BMTC app; NOT BMTC official GTFS."
        ),
        static_or_live="static",
        expected_refresh_cadence="daily",
        ingestion_adapter="src.network.ingest.bmtc_gtfs.build_bmtc_sync_pipeline",
        license_or_usage_notes=(
            "Community/unofficial feed; see producer repository terms. "
            "Do not commit large GTFS archives; fetch locally (data/mobility_network/bmtc/README.md)."
        ),
        currently_configured=True,
        authoritative_or_secondary="secondary",
        notes=(
            "UI/backend label: 'BMTC schedule data — community GTFS'. "
            "Timetable accuracy may be imperfect; missing times are never fabricated."
        ),
        claimed_official=False,
    ),
    "bmrcl_metro_network": DatasetDescriptor(
        dataset_id="bmrcl_metro_network",
        name="Bengaluru Metro / BMRCL network (official-derived seed)",
        provider="BMRCL",
        authority_or_source=(
            "OFFICIAL — normalized/derived from BMRCL website materials "
            "(https://english.bmrc.co.in/schematic-route-map/). "
            "Not a downloadable official GTFS feed."
        ),
        static_or_live="static",
        expected_refresh_cadence="on_network_change",
        ingestion_adapter="src.network.ingest.bmrcl.build_bmrcl_sync_pipeline",
        license_or_usage_notes=(
            "Derived from official BMRCL publications. Coordinates omitted unless "
            "machine-readable official data provides them. Seed: "
            "data/mobility_network/bmrcl/seed/bmrcl_network_seed.json"
        ),
        currently_configured=True,
        authoritative_or_secondary="authoritative",
        notes=(
            "Future official CSV/JSON/GTFS can replace the seed artifact without "
            "changing StaticMobilityDataRepository."
        ),
        claimed_official=True,
    ),
    "transit_fare_rules": DatasetDescriptor(
        dataset_id="transit_fare_rules",
        name="Bengaluru regulated auto fare (static estimate)",
        provider="Bengaluru_RTA",
        authority_or_source=(
            "GOVERNMENT_REGULATED — Bengaluru RTA / government-notified auto fare "
            "structure (₹36/2km + ₹18/km; 1.5× night). Institutional hub: "
            "https://transport.karnataka.gov.in/ — not live aggregator pricing."
        ),
        static_or_live="static",
        expected_refresh_cadence="on_policy_change",
        ingestion_adapter="src.network.ingest.fares.build_auto_fare_sync_pipeline",
        license_or_usage_notes=(
            "Regulated fare estimate only. Not Uber/Ola/Rapido/Namma Yatri live quotes. "
            "Seed: data/mobility_network/auto_fares/seed/bengaluru_auto_fare.json"
        ),
        currently_configured=True,
        authoritative_or_secondary="authoritative",
        notes=(
            "Existing Maps ₹25 transit heuristic remains separate and is NOT this dataset."
        ),
        claimed_official=False,
    ),
    "government_concession_rules": DatasetDescriptor(
        dataset_id="government_concession_rules",
        name="Karnataka Shakti fare eligibility policy",
        provider="Government_of_Karnataka",
        authority_or_source=(
            "OFFICIAL_GOVERNMENT — Shakti scheme documentation "
            "(https://bengaluruurban.nic.in/en/scheme-category/transport-department/). "
            "Supporting research PDF from FPI Bengaluru / Karnataka government."
        ),
        static_or_live="static",
        expected_refresh_cadence="on_policy_change",
        ingestion_adapter="src.network.ingest.fares.build_shakti_sync_pipeline",
        license_or_usage_notes=(
            "Official scheme policy modeled as FareRule eligibility conditions. "
            "Seed: data/mobility_network/shakti/seed/shakti_fare_policy.json"
        ),
        currently_configured=True,
        authoritative_or_secondary="authoritative",
        notes=(
            "Not a universal bus discount. Incomplete passenger profiles must not "
            "assume eligibility. Excludes luxury/AC and similar service classes."
        ),
        claimed_official=True,
    ),
    "uber_movement_historical": DatasetDescriptor(
        dataset_id="uber_movement_historical",
        name="Road historical mobility data (Uber Movement)",
        provider="Uber Movement",
        authority_or_source="Uber Movement research / aggregate travel-time CSV (existing pipeline)",
        static_or_live="historical_model",
        expected_refresh_cadence="offline_retrain",
        ingestion_adapter="UberMovementHistoricalProvider",
        license_or_usage_notes="Use per Uber Movement terms applicable to the local CSV",
        currently_configured=True,
        authoritative_or_secondary="secondary",
        notes=(
            "Existing XGBoost / FeaturePipeline artifacts under models/. "
            "Road OD travel-time signal only — not a transit network feed."
        ),
        claimed_official=False,
    ),
    "weather": DatasetDescriptor(
        dataset_id="weather",
        name="Weather conditions",
        provider="unconfigured",
        authority_or_source="Intended weather API (not configured)",
        static_or_live="live",
        expected_refresh_cadence="sub_hourly",
        ingestion_adapter="WeatherProvider",
        license_or_usage_notes="TBD",
        currently_configured=False,
        authoritative_or_secondary="unknown",
        notes="Agent tool get_weather returns not_configured today.",
        claimed_official=False,
    ),
    "google_live_routing": DatasetDescriptor(
        dataset_id="google_live_routing",
        name="Google live routing (Maps Routes API)",
        provider="Google",
        authority_or_source="Google Maps Platform Routes API v2",
        static_or_live="live",
        expected_refresh_cadence="on_request",
        ingestion_adapter="MapsClient",
        license_or_usage_notes="Google Maps Platform Terms of Service",
        currently_configured=True,
        authoritative_or_secondary="secondary",
        notes=(
            "Existing src/mobility Maps client. Live durations/geometry; "
            "fares/reliability remain heuristics unless replaced by fare rules."
        ),
        claimed_official=False,
    ),
    "local_file_network_snapshot": DatasetDescriptor(
        dataset_id="local_file_network_snapshot",
        name="Local file-backed normalized network snapshot store",
        provider="internal",
        authority_or_source="Internal Phase 5A file store (tests / future sync publish)",
        static_or_live="static",
        expected_refresh_cadence="on_sync",
        ingestion_adapter="FileStaticMobilityRepository",
        license_or_usage_notes="Internal",
        currently_configured=True,
        authoritative_or_secondary="secondary",
        notes="Replaceable storage backend for StaticMobilityDataRepository.",
        claimed_official=False,
    ),
}


def get_dataset(dataset_id: str) -> Optional[DatasetDescriptor]:
    return DATASET_REGISTRY.get(dataset_id)


def list_datasets(*, configured_only: bool = False) -> List[DatasetDescriptor]:
    values = list(DATASET_REGISTRY.values())
    if configured_only:
        return [d for d in values if d.currently_configured]
    return values


def configured_dataset_ids() -> List[str]:
    return [d.dataset_id for d in list_datasets(configured_only=True)]
