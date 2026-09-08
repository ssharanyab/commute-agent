"""
Static mobility network foundation (Phase 5A + 5B ingest adapters).

Provider-independent domain contracts, dataset registry, file-backed store,
daily-sync abstractions, historical mobility provider wrapper, and Bengaluru
static ingest (community BMTC GTFS, BMRCL seed, regulated auto fare, Shakti).

Does NOT implement Journey Builder or hardcoded multimodal combinations.
"""

from src.network.models import (
    DataProvenance,
    FareEligibilityCondition,
    FareRule,
    MobilityMode,
    MobilityNetworkSnapshot,
    MobilityRoute,
    MobilityStation,
    MobilityStop,
    MobilityStopTime,
    MobilityTrip,
    SourceType,
    StopType,
    ValidationStatus,
)
from src.network.registry import DATASET_REGISTRY, DatasetDescriptor, get_dataset
from src.network.repository import StaticMobilityDataRepository
from src.network.file_repository import FileStaticMobilityRepository
from src.network.historical import (
    HistoricalMobilityProvider,
    UberMovementHistoricalProvider,
)

__all__ = [
    "DataProvenance",
    "FareEligibilityCondition",
    "FareRule",
    "MobilityMode",
    "MobilityNetworkSnapshot",
    "MobilityRoute",
    "MobilityStation",
    "MobilityStop",
    "MobilityStopTime",
    "MobilityTrip",
    "SourceType",
    "StopType",
    "ValidationStatus",
    "DATASET_REGISTRY",
    "DatasetDescriptor",
    "get_dataset",
    "StaticMobilityDataRepository",
    "FileStaticMobilityRepository",
    "HistoricalMobilityProvider",
    "UberMovementHistoricalProvider",
]
