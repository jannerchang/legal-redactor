from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .entity_registry import FullDocumentEntityRegistry, RegistryMaterialization
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
    constraints: FullDocumentEntityRegistry | None = None,
) -> RecognitionAuditResult:
    """Classify detector/registry relationships without accepting or rejecting candidates."""
    detectors = _dedupe_candidates(detector_candidates)
    registry = _dedupe_candidates(registry_materialization.candidates)
    constraints = constraints or registry_materialization.constraints
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
                category = _identity_category(detector, match, constraints)
                items.append(RecognitionAuditItem(category, detector, match))
                consumed_detectors.add(id(detector))
                consumed_registry.add(id(match))
                continue
            match = registry_group[0]
            items.append(RecognitionAuditItem("type_conflict", detector, match, "same_span_different_type"))
            consumed_detectors.add(id(detector))
            consumed_registry.add(id(match))

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
    constraints: FullDocumentEntityRegistry,
) -> str:
    detector_id = _entity_id(detector)
    registry_id = _entity_id(registry)
    if detector_id and registry_id and detector_id != registry_id:
        if tuple(sorted((detector_id, registry_id))) in constraints.blocked_pairs():
            return "merge_conflict"
        return "grouping_conflict"
    detector_possible = detector.metadata.get("registry_possible_entity_ids", ())
    if isinstance(detector_possible, list) and registry_id and detector_possible and registry_id not in detector_possible:
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
