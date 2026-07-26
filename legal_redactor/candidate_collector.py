"""Collect full-document registry and deterministic database candidates."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol

from .entity_registry import RegistryMaterialization
from .models import Candidate


class CandidateDetector(Protocol):
    def detect(self, text: str) -> list[Candidate]: ...




@dataclass(frozen=True)
class CandidateCollectionContext:
    text: str
    seed_candidates: list[Candidate] = field(default_factory=list)
    detectors: tuple[CandidateDetector, ...] = ()
    registry_materialization: RegistryMaterialization | None = None


@dataclass(frozen=True)
class CandidateCollectionResult:
    candidates: list[Candidate]
    review_candidates: list[Candidate] = field(default_factory=list)



class CandidateCollector:
    """Combine the only supported discovery sources behind one interface."""

    def collect(self, context: CandidateCollectionContext) -> CandidateCollectionResult:
        candidates = list(context.seed_candidates)
        for detector in context.detectors:
            candidates.extend(detector.detect(context.text))
        review_candidates: list[Candidate] = []
        if context.registry_materialization is not None:
            candidates.extend(context.registry_materialization.candidates)
            review_candidates.extend(context.registry_materialization.review_candidates)
        return CandidateCollectionResult(
            candidates=self._deduplicate_candidates(candidates),
            review_candidates=review_candidates,
        )
    @staticmethod
    def _deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
        best: dict[tuple[str, str, int], Candidate] = {}
        for candidate in candidates:
            key = (candidate.type, candidate.text, candidate.start)
            previous = best.get(key)
            if previous is None:
                best[key] = candidate
                continue
            metadata = dict(previous.metadata)
            metadata.update(candidate.metadata)
            sources: list[str] = []
            for source in (
                previous.metadata.get("provenance_sources", [previous.source]),
                candidate.metadata.get("provenance_sources", [candidate.source]),
            ):
                values = source if isinstance(source, list) else [source]
                for value in values:
                    if isinstance(value, str) and value not in sources:
                        sources.append(value)
            metadata["provenance_sources"] = sources
            preferred = candidate if candidate.confidence > previous.confidence else previous
            best[key] = replace(
                preferred,
                metadata=metadata,
                needs_review=previous.needs_review or candidate.needs_review,
            )
        return list(best.values())
