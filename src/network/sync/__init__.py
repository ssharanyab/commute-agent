"""
Daily / static-data sync framework (Phase 5A).

Pipeline:
  DataSource → Fetcher → Parser → Normalizer → Validator → Snapshot → Publish

On validation failure the previous active snapshot is retained and the
failed candidate is archived under failed/.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.network.file_repository import FileStaticMobilityRepository
from src.network.models import (
    DataProvenance,
    MobilityNetworkSnapshot,
    SourceType,
    ValidationStatus,
)
from src.network.sync.validation import validate_network_payload


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def checksum_payload(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(blob).hexdigest()


@dataclass
class SyncResult:
    success: bool
    published: bool
    dataset_name: str
    version: Optional[str]
    errors: List[str] = field(default_factory=list)
    previous_active_version: Optional[str] = None
    active_version: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "published": self.published,
            "dataset_name": self.dataset_name,
            "version": self.version,
            "errors": list(self.errors),
            "previous_active_version": self.previous_active_version,
            "active_version": self.active_version,
            "notes": list(self.notes),
        }


class DataSource(ABC):
    """Logical external dataset identity."""

    @property
    @abstractmethod
    def dataset_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def source(self) -> str:
        raise NotImplementedError


class Fetcher(ABC):
    @abstractmethod
    def fetch(self) -> Any:
        """Return raw bytes/text/dict from the source. Must not invent data."""
        raise NotImplementedError


class Parser(ABC):
    @abstractmethod
    def parse(self, raw: Any) -> Any:
        raise NotImplementedError


class Normalizer(ABC):
    @abstractmethod
    def normalize(self, parsed: Any) -> Dict[str, Any]:
        """
        Produce a normalized payload dict with keys such as:
        stops, stations, routes, fare_rules (lists of serializable dicts).
        """
        raise NotImplementedError


class Validator(ABC):
    @abstractmethod
    def validate(self, payload: Dict[str, Any]) -> List[str]:
        """Return error strings; empty means valid."""
        raise NotImplementedError


class DefaultNetworkValidator(Validator):
    def validate(self, payload: Dict[str, Any]) -> List[str]:
        return validate_network_payload(payload)


@dataclass
class SyncPipeline:
    """Orchestrates fetch→parse→normalize→validate→publish/rollback."""

    source: DataSource
    fetcher: Fetcher
    parser: Parser
    normalizer: Normalizer
    repository: FileStaticMobilityRepository
    validator: Validator = field(default_factory=DefaultNetworkValidator)
    source_type: SourceType = SourceType.UNKNOWN
    source_url: Optional[str] = None

    def run(self, *, version: Optional[str] = None) -> SyncResult:
        dataset = self.source.dataset_name
        previous = self.repository.get_active_snapshot(dataset)
        previous_version = previous.version if previous else None

        try:
            raw = self.fetcher.fetch()
            parsed = self.parser.parse(raw)
            payload = self.normalizer.normalize(parsed)
        except Exception as exc:
            return SyncResult(
                success=False,
                published=False,
                dataset_name=dataset,
                version=version,
                errors=[f"INGEST_FAILED ({type(exc).__name__}: {exc})"],
                previous_active_version=previous_version,
                active_version=previous_version,
                notes=["Previous active snapshot retained (ingest failure)."],
            )

        errors = self.validator.validate(payload)
        ver = version or _utc_now().strftime("%Y%m%dT%H%M%SZ")
        record_count = sum(
            len(payload.get(k) or [])
            for k in ("stops", "stations", "routes", "fare_rules")
        )
        provenance = DataProvenance(
            source=self.source.source,
            source_type=self.source_type,
            retrieved_at=_utc_now(),
            version=ver,
            source_url=self.source_url,
            notes="Produced by SyncPipeline",
        )
        snapshot = MobilityNetworkSnapshot(
            dataset_name=dataset,
            provider=self.source.provider,
            version=ver,
            fetched_at=_utc_now(),
            record_count=record_count,
            source=self.source.source,
            validation_status=(
                ValidationStatus.VALID if not errors else ValidationStatus.FAILED
            ),
            provenance=provenance,
            checksum=checksum_payload(payload),
            validation_errors=list(errors),
            payload=payload,
        )

        if errors:
            self.repository.save_failed_snapshot(snapshot)
            return SyncResult(
                success=False,
                published=False,
                dataset_name=dataset,
                version=ver,
                errors=list(errors),
                previous_active_version=previous_version,
                active_version=previous_version,
                notes=[
                    "Validation failed; previous active snapshot retained.",
                    f"Failed candidate archived under failed/{ver}.json",
                ],
            )

        self.repository.publish_snapshot(snapshot)
        active = self.repository.get_active_snapshot(dataset)
        return SyncResult(
            success=True,
            published=True,
            dataset_name=dataset,
            version=ver,
            errors=[],
            previous_active_version=previous_version,
            active_version=active.version if active else ver,
            notes=["Snapshot validated and published."],
        )


# --- Local / in-memory adapters for tests & next-phase wiring --------------


@dataclass
class LocalDictDataSource(DataSource):
    name: str
    provider_name: str
    source_label: str

    @property
    def dataset_name(self) -> str:
        return self.name

    @property
    def provider(self) -> str:
        return self.provider_name

    @property
    def source(self) -> str:
        return self.source_label


@dataclass
class StaticDictFetcher(Fetcher):
    """Fetcher that returns a provided payload — for tests only, not live feeds."""

    raw: Any

    def fetch(self) -> Any:
        return self.raw


@dataclass
class PassthroughParser(Parser):
    def parse(self, raw: Any) -> Any:
        return raw


@dataclass
class IdentityNormalizer(Normalizer):
    def normalize(self, parsed: Any) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            raise TypeError("IdentityNormalizer expects a dict payload")
        return dict(parsed)
