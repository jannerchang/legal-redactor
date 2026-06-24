from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any


CN_TZ = timezone(timedelta(hours=8))


_MAPPING_TYPE_ORDER = {
    "organization": 0,
    "individual_business": 0,
    "project": 0,
    "location": 1,
    "grassroots_org": 1,
    "person": 2,
}


def sort_mapping_entries(mappings: list["MappingEntry"]) -> list["MappingEntry"]:
    """Sort mappings for display/export without changing replacement semantics."""
    return sorted(
        mappings,
        key=lambda entry: (
            _MAPPING_TYPE_ORDER.get(entry.type, 9),
            entry.masked or "",
            -len(entry.original or ""),
            entry.original or "",
        ),
    )


@dataclass
class Candidate:
    type: str
    text: str
    start: int
    end: int
    source: str
    confidence: float
    risk_level: str
    auto_redact: bool
    role: str | None = None
    reason: str | None = None
    suggested_mask_type: str | None = None
    needs_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MappingEntry:
    type: str
    original: str
    masked: str
    role: str | None
    source: str
    confidence: float
    restore_by_default: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MappingEntry":
        return cls(**data)


@dataclass
class RedactionMap:
    version: str
    created_at: str
    mode: str
    source_file: str | None
    mappings: list[MappingEntry]

    @classmethod
    def create(
        cls,
        mappings: list[MappingEntry],
        mode: str = "normal",
        source_file: str | None = None,
    ) -> "RedactionMap":
        return cls(
            version="1.0",
            created_at=datetime.now(CN_TZ).isoformat(timespec="seconds"),
            mode=mode,
            source_file=source_file,
            mappings=sort_mapping_entries(mappings),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "mode": self.mode,
            "source_file": self.source_file,
            "mappings": [m.to_dict() for m in self.mappings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RedactionMap":
        return cls(
            version=str(data.get("version", "1.0")),
            created_at=str(data.get("created_at", "")),
            mode=str(data.get("mode", "normal")),
            source_file=data.get("source_file"),
            mappings=[MappingEntry(**item) for item in data.get("mappings", [])],
        )


@dataclass
class Leak:
    type: str
    text: str
    start: int
    end: int
    source: str
    risk_level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RestorePreview:
    restored_text: str
    restored_entries: list[MappingEntry]
    skipped_entries: list[MappingEntry]
    diff: str


@dataclass
class RedactionResult:
    original_text: str
    redacted_text: str
    redaction_map: RedactionMap
    candidates: list[Candidate]
    review_candidates: list[Candidate]
    leaks: list[Leak]
    mode: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class RedactedDocument:
    source_file: str
    original_text: str
    redacted_text: str
    leaks: list[Leak] = field(default_factory=list)


@dataclass
class BatchRedactionResult:
    documents: list[RedactedDocument]
    redaction_map: RedactionMap
    candidates: list[Candidate]
    review_candidates: list[Candidate]
    leaks: list[Leak]
    mode: str
    warnings: list[str] = field(default_factory=list)
