"""
Bengaluru regulated auto fare + Karnataka Shakti eligibility as FareRules,
plus an auditable apply_fare_rules evaluator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest import auto_fare_provenance, shakti_provenance, utc_now
from src.network.models import (
    FareEligibilityCondition,
    FareRule,
    MobilityMode,
    SourceType,
)
from src.network.sync import (
    Fetcher,
    LocalDictDataSource,
    Normalizer,
    PassthroughParser,
    SyncPipeline,
)

ROOT = Path(__file__).resolve().parents[3] / "data" / "mobility_network"
AUTO_SEED = ROOT / "auto_fares" / "seed" / "bengaluru_auto_fare.json"
SHAKTI_SEED = ROOT / "shakti" / "seed" / "shakti_fare_policy.json"


def build_auto_fare_rule(
    *, retrieved_at: Optional[datetime] = None
) -> FareRule:
    prov = auto_fare_provenance(retrieved_at=retrieved_at)
    return FareRule(
        id="bengaluru_auto_regulated_v1",
        provider="Bengaluru_RTA",
        network="bengaluru_auto",
        mode=MobilityMode.AUTO_RICKSHAW,
        provenance=prov,
        base_fare=36.0,
        currency="INR",
        rule_structure={
            "fare_kind": "government_regulated_auto",
            "not_live_aggregator": True,
            "minimum": {"fare_inr": 36.0, "distance_km": 2.0},
            "per_km_after_minimum_inr": 18.0,
            "night": {
                "multiplier": 1.5,
                "start_local": "22:00",
                "end_local": "05:00",
            },
            "waiting": {
                "first_free_minutes": 5,
                "subsequent": "as_per_applicable_regulated_rule",
            },
        },
        eligibility=(
            FareEligibilityCondition(
                attribute="vehicle_type",
                operator="eq",
                value="auto_rickshaw",
                description="Applies to regulated auto-rickshaw services",
            ),
        ),
        service_exclusions=("app_aggregator_dynamic_pricing",),
        effective_from=datetime(2023, 1, 1),
        version=prov.version,
    )


def build_shakti_fare_rule(
    *, retrieved_at: Optional[datetime] = None
) -> FareRule:
    prov = shakti_provenance(retrieved_at=retrieved_at)
    return FareRule(
        id="karnataka_shakti_zero_fare_v1",
        provider="Government_of_Karnataka",
        network="karnataka_govt_bus",
        mode=MobilityMode.BUS,
        provenance=prov,
        base_fare=0.0,
        currency="INR",
        rule_structure={
            "fare_kind": "concession_zero_fare",
            "scheme": "Shakti",
            "geography": "Karnataka",
            "eligible_operators": ["BMTC", "KSRTC", "NWKRTC", "NEKRTC"],
            "zero_fare_when_eligible": True,
        },
        eligibility=(
            FareEligibilityCondition(
                attribute="domicile",
                operator="eq",
                value="Karnataka",
                description="Passenger must be Karnataka-domiciled",
            ),
            FareEligibilityCondition(
                attribute="passenger_category",
                operator="in",
                value=["woman", "girl", "transgender"],
                description="Eligible passenger categories under Shakti",
            ),
            FareEligibilityCondition(
                attribute="operator",
                operator="in",
                value=["BMTC", "KSRTC", "NWKRTC", "NEKRTC"],
                description="Government-run bus corporations",
            ),
            FareEligibilityCondition(
                attribute="service_class",
                operator="not_in",
                value=["luxury", "ac", "air_conditioned", "volvo_ac"],
                description="Luxury/AC and similar services excluded",
            ),
        ),
        service_exclusions=("luxury", "ac", "air_conditioned", "volvo_ac"),
        effective_from=datetime(2023, 6, 11),
        version=prov.version,
    )


class JsonSeedFetcher(Fetcher):
    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        return json.loads(self.path.read_text(encoding="utf-8"))


class FareSeedNormalizer(Normalizer):
    """Normalizer for fare-only snapshot seeds."""

    def __init__(self, *, default_rules: Optional[List[FareRule]] = None):
        self.default_rules = default_rules or []

    def normalize(self, parsed: Any) -> Dict[str, Any]:
        if isinstance(parsed, dict) and parsed.get("fare_rules"):
            return {
                "stops": [],
                "stations": [],
                "routes": [],
                "fare_rules": list(parsed["fare_rules"]),
                "dataset_meta": dict(parsed.get("dataset_meta") or {}),
            }
        return {
            "stops": [],
            "stations": [],
            "routes": [],
            "fare_rules": [r.to_dict() for r in self.default_rules],
            "dataset_meta": {},
        }


def build_auto_fare_sync_pipeline(
    repository: FileStaticMobilityRepository,
    seed_path: Path | str = AUTO_SEED,
) -> SyncPipeline:
    return SyncPipeline(
        source=LocalDictDataSource(
            name="auto_fares",
            provider_name="Bengaluru_RTA",
            source_label="bengaluru_rta_auto_fare_regulated",
        ),
        fetcher=JsonSeedFetcher(Path(seed_path)),
        parser=PassthroughParser(),
        normalizer=FareSeedNormalizer(default_rules=[build_auto_fare_rule()]),
        repository=repository,
        source_type=SourceType.GOVERNMENT_REGULATED,
        source_url="https://transport.karnataka.gov.in/",
    )


def build_shakti_sync_pipeline(
    repository: FileStaticMobilityRepository,
    seed_path: Path | str = SHAKTI_SEED,
) -> SyncPipeline:
    return SyncPipeline(
        source=LocalDictDataSource(
            name="shakti",
            provider_name="Government_of_Karnataka",
            source_label="karnataka_shakti_scheme",
        ),
        fetcher=JsonSeedFetcher(Path(seed_path)),
        parser=PassthroughParser(),
        normalizer=FareSeedNormalizer(default_rules=[build_shakti_fare_rule()]),
        repository=repository,
        source_type=SourceType.OFFICIAL_OPEN_DATA,
        source_url="https://bengaluruurban.nic.in/en/scheme-category/transport-department/",
    )


# ---------------------------------------------------------------------------
# Auditable fare evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FareDecision:
    fare_inr: Optional[float]
    currency: str
    status: str  # applied | ineligible | insufficient_profile | no_matching_rule
    rule_id: Optional[str]
    explanation: List[str]
    provenance: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fare_inr": self.fare_inr,
            "currency": self.currency,
            "status": self.status,
            "rule_id": self.rule_id,
            "explanation": list(self.explanation),
            "provenance": self.provenance,
        }


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")[:2]
    return time(int(hh), int(mm))


def _is_night(local_hhmm: str, start: str, end: str) -> bool:
    """Night window that may wrap midnight (e.g. 22:00–05:00)."""
    t = _parse_hhmm(local_hhmm)
    s = _parse_hhmm(start)
    e = _parse_hhmm(end)
    if s <= e:
        return s <= t < e
    return t >= s or t < e


def _condition_holds(cond: FareEligibilityCondition, profile: Dict[str, Any]) -> Optional[bool]:
    """
    Return True/False if evaluable; None if profile lacks required attribute
    (insufficient information — do NOT assume eligibility).
    """
    if cond.attribute not in profile or profile.get(cond.attribute) is None:
        return None
    actual = profile[cond.attribute]
    op = cond.operator
    expected = cond.value
    if op == "eq":
        return actual == expected
    if op == "in":
        return actual in (expected or [])
    if op == "not_in":
        return actual not in (expected or [])
    raise ValueError(f"Unsupported operator: {op}")


def _rule_eligibility(
    rule: FareRule, profile: Dict[str, Any]
) -> tuple:
    """Returns (eligible: bool|None, notes). None => insufficient profile."""
    notes: List[str] = []
    for raw in rule.eligibility:
        cond = (
            raw
            if isinstance(raw, FareEligibilityCondition)
            else FareEligibilityCondition.from_dict(raw)
        )
        result = _condition_holds(cond, profile)
        if result is None:
            notes.append(
                f"insufficient_profile for attribute '{cond.attribute}'"
            )
            return None, notes
        if result is False:
            notes.append(
                f"failed condition {cond.attribute} {cond.operator} {cond.value}"
            )
            return False, notes
        notes.append(
            f"passed condition {cond.attribute} {cond.operator} {cond.value}"
        )
    return True, notes


def compute_auto_fare_inr(
    rule: FareRule,
    *,
    distance_km: float,
    local_time_hhmm: Optional[str] = None,
) -> float:
    structure = rule.rule_structure or {}
    minimum = structure.get("minimum") or {}
    min_fare = float(minimum.get("fare_inr", rule.base_fare or 0.0))
    min_km = float(minimum.get("distance_km", 2.0))
    per_km = float(structure.get("per_km_after_minimum_inr", 18.0))
    fare = min_fare
    if distance_km > min_km:
        fare += (distance_km - min_km) * per_km
    night = structure.get("night") or {}
    if local_time_hhmm and night.get("multiplier"):
        if _is_night(
            local_time_hhmm,
            str(night.get("start_local", "22:00")),
            str(night.get("end_local", "05:00")),
        ):
            fare *= float(night["multiplier"])
    return round(fare, 2)


def apply_fare_rules(
    *,
    mode: str,
    operator: str,
    service_class: Optional[str] = None,
    passenger_profile: Optional[Dict[str, Any]] = None,
    distance_km: Optional[float] = None,
    local_time_hhmm: Optional[str] = None,
    rules: Sequence[FareRule] = (),
) -> FareDecision:
    """
    Evaluate fare rules with explicit eligibility. Never assumes Shakti/zero fare
    from incomplete profiles.
    """
    profile = dict(passenger_profile or {})
    profile.setdefault("operator", operator)
    if service_class is not None:
        profile.setdefault("service_class", service_class)

    mode_norm = (mode or "").strip().lower()
    explanations: List[str] = []

    # Prefer concession rules first when mode matches, then regulated base fares.
    ordered = sorted(
        rules,
        key=lambda r: 0 if (r.rule_structure or {}).get("fare_kind") == "concession_zero_fare" else 1,
    )

    for rule in ordered:
        if rule.mode.value != mode_norm and rule.mode.value != mode:
            continue
        if service_class and service_class in (rule.service_exclusions or ()):
            explanations.append(
                f"rule {rule.id} skipped: service_class '{service_class}' excluded"
            )
            continue

        eligible, notes = _rule_eligibility(rule, profile)
        explanations.extend([f"{rule.id}: {n}" for n in notes])
        if eligible is None:
            return FareDecision(
                fare_inr=None,
                currency=rule.currency,
                status="insufficient_profile",
                rule_id=rule.id,
                explanation=explanations
                + ["Do not assume eligibility when profile is incomplete."],
                provenance=rule.provenance.to_dict(),
            )
        if eligible is False:
            continue

        kind = (rule.rule_structure or {}).get("fare_kind")
        if kind == "concession_zero_fare":
            return FareDecision(
                fare_inr=0.0,
                currency=rule.currency,
                status="applied",
                rule_id=rule.id,
                explanation=explanations + ["Shakti/concession zero fare applied."],
                provenance=rule.provenance.to_dict(),
            )
        if kind == "government_regulated_auto":
            if distance_km is None:
                return FareDecision(
                    fare_inr=None,
                    currency=rule.currency,
                    status="insufficient_profile",
                    rule_id=rule.id,
                    explanation=explanations
                    + ["distance_km required for regulated auto fare"],
                    provenance=rule.provenance.to_dict(),
                )
            fare = compute_auto_fare_inr(
                rule, distance_km=float(distance_km), local_time_hhmm=local_time_hhmm
            )
            return FareDecision(
                fare_inr=fare,
                currency=rule.currency,
                status="applied",
                rule_id=rule.id,
                explanation=explanations
                + [
                    f"Regulated auto estimate for {distance_km} km"
                    + (f" at {local_time_hhmm}" if local_time_hhmm else "")
                ],
                provenance=rule.provenance.to_dict(),
            )
        if rule.base_fare is not None:
            return FareDecision(
                fare_inr=float(rule.base_fare),
                currency=rule.currency,
                status="applied",
                rule_id=rule.id,
                explanation=explanations + ["Base fare applied."],
                provenance=rule.provenance.to_dict(),
            )

    return FareDecision(
        fare_inr=None,
        currency="INR",
        status="no_matching_rule",
        rule_id=None,
        explanation=explanations or ["No matching fare rule."],
        provenance=None,
    )
