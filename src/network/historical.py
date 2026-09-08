"""
Historical mobility intelligence provider abstraction (Phase 5A).

Wraps the existing Uber Movement XGBoost pipeline without modifying it.
Does not mix static transit network data into the road model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.network.models import DataProvenance, SourceType
from src.predict import get_historical_mobility_signal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class HistoricalMobilityResult:
    """Provider response with explicit model/provenance metadata."""

    signal: Dict[str, Any]
    provenance: DataProvenance
    model_name: str
    model_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": dict(self.signal),
            "provenance": self.provenance.to_dict(),
            "model_name": self.model_name,
            "model_version": self.model_version,
        }


class HistoricalMobilityProvider(ABC):
    """Interface for multiple future historical / ML intelligence providers."""

    @abstractmethod
    def get_signal(
        self,
        *,
        origin_zone: int,
        destination_zone: int,
        hour: int,
    ) -> HistoricalMobilityResult:
        raise NotImplementedError


class UberMovementHistoricalProvider(HistoricalMobilityProvider):
    """
    Thin wrapper over existing `get_historical_mobility_signal`.

    Preserves the current XGBoost + FeaturePipeline behavior and artifacts.
    """

    MODEL_NAME = "uber_movement_xgboost"
    SIGNAL_SOURCE = "historical_uber_movement_ml"

    def __init__(self, models_dir: str = "models"):
        self.models_dir = models_dir

    def get_signal(
        self,
        *,
        origin_zone: int,
        destination_zone: int,
        hour: int,
    ) -> HistoricalMobilityResult:
        signal = get_historical_mobility_signal(
            origin_zone=int(origin_zone),
            destination_zone=int(destination_zone),
            hour=int(hour),
            models_dir=self.models_dir,
        )
        # Prefer source label already stamped by historical_signal helpers.
        source = str(signal.get("signal_source") or self.SIGNAL_SOURCE)
        provenance = DataProvenance(
            source=source,
            source_type=SourceType.RESEARCH_DATASET,
            retrieved_at=_utc_now(),
            version=str(signal.get("model_version") or "artifact"),
            confidence=(
                float(signal["confidence"])
                if signal.get("confidence") is not None
                else None
            ),
            notes=(
                "Road OD historical travel-time signal from existing "
                "Uber Movement XGBoost pipeline; not a transit network feed."
            ),
        )
        return HistoricalMobilityResult(
            signal=dict(signal),
            provenance=provenance,
            model_name=self.MODEL_NAME,
            model_version=str(signal.get("model_version") or "artifact"),
        )
