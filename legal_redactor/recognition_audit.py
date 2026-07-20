from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .entity_registry import RegistryMaterialization
from .models import Candidate

_RECOGNITION_CATEGORIES = (
    "agreed",
    "llm_only",
    "detector_only",
    "type_conflict",
    "grouping_conflict",
    "merge_conflict",
    "split_conflict",
    "uncertain",
)


@dataclass(frozen=True)
class RecognitionAuditItem:
    category: str
    detector_candidate: Candidate | None = None
    registry_candidate: Candidate | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RecognitionAuditResult:
    items: tuple[RecognitionAuditItem, ...] = ()
    category_counts: dict[str, int] = field(default_factory=dict)
    review_candidates: tuple[Candidate, ...] = ()

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "category_counts": dict(self.category_counts),
            "review_candidate_count": len(self.review_candidates),
        }


def audit_recognition(
    detector_candidates: Iterable[Candidate],
    registry_materialization: RegistryMaterialization,
) -> RecognitionAuditResult:
    """Classify detector/registry relationships without accepting or rejecting candidates."""
    detectors = _dedupe_candidates(detector_candidates)
    registry = _dedupe_candidates(registry_materialization.candidates)
    detector_by_span = _by_span(detectors)
    registry_by_span = _by_span(registry)
    items: list[RecognitionAuditItem] = []
    consumed_detectors: set[int] = set()
    consumed_registry: set[int] = set()

    for span in sorted(set(detector_by_span) & set(registry_by_span)):
        detector_group = detector_by_span[span]
        registry_group = registry_by_span[span]
        for detector in detector_group:
            match = next((candidate for candidate in registry_group if candidate.type == detector.type), None)
            if match is not None:
                category = _identity_category(detector, match)
                items.append(RecognitionAuditItem(category, detector, match))
                consumed_detectors.add(id(detector))
                consumed_registry.add(id(match))
                continue
            match = registry_group[0]
            items.append(RecognitionAuditItem("type_conflict", detector, match, "same_span_different_type"))
            consumed_detectors.add(id(detector))
            consumed_registry.add(id(match))

    detectors = [
        detector
        for detector in detectors
        if id(detector) in consumed_detectors
        or not any(_full_document_person_correction(registry_candidate, detector) for registry_candidate in registry)
    ]


    for detector in detectors:
        if id(detector) in consumed_detectors:
            continue
        overlap = next((candidate for candidate in registry if _overlaps(detector, candidate)), None)
        if overlap is not None:
            category = "split_conflict" if detector.length < overlap.length else "merge_conflict"
            items.append(RecognitionAuditItem(category, detector, overlap, "overlapping_boundaries"))
            consumed_detectors.add(id(detector))
            consumed_registry.add(id(overlap))
        else:
            items.append(RecognitionAuditItem("detector_only", detector, None))
            consumed_detectors.add(id(detector))

    for candidate in registry:
        if id(candidate) not in consumed_registry:
            items.append(RecognitionAuditItem("llm_only", None, candidate))

    for candidate in registry_materialization.review_candidates:
        items.append(RecognitionAuditItem("uncertain", None, candidate, candidate.reason))

    category_counts = {category: 0 for category in _RECOGNITION_CATEGORIES}
    review_candidates: list[Candidate] = []
    for item in items:
        category_counts[item.category] += 1
        if item.category in {
            "type_conflict",
            "grouping_conflict",
            "merge_conflict",
            "split_conflict",
            "uncertain",
        }:
            review_candidates.extend(
                candidate
                for candidate in (item.detector_candidate, item.registry_candidate)
                if candidate is not None
            )
    return RecognitionAuditResult(
        items=tuple(items),
        category_counts=category_counts,
        review_candidates=tuple(_dedupe_candidates(review_candidates)),
    )


def _identity_category(
    detector: Candidate,
    registry: Candidate,
) -> str:
    detector_id = _entity_id(detector)
    registry_id = _entity_id(registry)
    if detector_id and registry_id and detector_id != registry_id:
        return "grouping_conflict"
    return "agreed"


def _entity_id(candidate: Candidate) -> str | None:
    value = candidate.metadata.get("registry_entity_id")
    return value if isinstance(value, str) and value else None


def _by_span(candidates: list[Candidate]) -> dict[tuple[int, int, str], list[Candidate]]:
    result: dict[tuple[int, int, str], list[Candidate]] = {}
    for candidate in candidates:
        result.setdefault((candidate.start, candidate.end, candidate.text), []).append(candidate)
    return result


def _full_document_person_correction(inner: Candidate, outer: Candidate) -> bool:
    return (
        inner.type == "person"
        and outer.type == "person"
        and inner.source.startswith("full_document_llm")
        and inner.start >= outer.start
        and inner.end <= outer.end
        and (inner.start, inner.end) != (outer.start, outer.end)
    )


def _overlaps(left: Candidate, right: Candidate) -> bool:
    return left.start < right.end and right.start < left.end


def _dedupe_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    result: list[Candidate] = []
    seen: set[tuple[str, str, int, int, str | None]] = set()
    for candidate in candidates:
        key = (candidate.type, candidate.text, candidate.start, candidate.end, _entity_id(candidate))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
