from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .models import BatchRedactionResult, Candidate, Leak, MappingEntry, RedactionResult


def redaction_debug_trace(result: RedactionResult) -> dict[str, Any]:
    """Build a compact, downloadable trace for a single redaction run."""
    documents = [
        {
            "source_file": result.redaction_map.source_file,
            "original_text": result.original_text,
            "redacted_text": result.redacted_text,
        }
    ]
    return _build_trace(
        mode=result.mode,
        source_file=result.redaction_map.source_file,
        mappings=result.redaction_map.mappings,
        documents=documents,
        review_candidates=result.review_candidates,
        leaks=result.leaks,
        warnings=result.warnings,
    )


def batch_debug_trace(result: BatchRedactionResult) -> dict[str, Any]:
    """Build a compact, downloadable trace for a batch redaction run."""
    documents = [
        {
            "source_file": document.source_file,
            "original_text": document.original_text,
            "redacted_text": document.redacted_text,
        }
        for document in result.documents
    ]
    return _build_trace(
        mode=result.mode,
        source_file=result.redaction_map.source_file,
        mappings=result.redaction_map.mappings,
        documents=documents,
        review_candidates=result.review_candidates,
        leaks=result.leaks,
        warnings=result.warnings,
    )


def debug_trace_from_parts(
    *,
    mode: str,
    source_file: str | None,
    mappings: list[MappingEntry],
    documents: list[dict[str, str | None]],
    review_candidates: list[Candidate],
    leaks: list[Leak],
    warnings: list[str],
) -> dict[str, Any]:
    return _build_trace(
        mode=mode,
        source_file=source_file,
        mappings=mappings,
        documents=documents,
        review_candidates=review_candidates,
        leaks=leaks,
        warnings=warnings,
    )


def debug_trace_to_json(trace: dict[str, Any]) -> str:
    return json.dumps(trace, ensure_ascii=False, indent=2)


def _build_trace(
    *,
    mode: str,
    source_file: str | None,
    mappings: list[MappingEntry],
    documents: list[dict[str, str | None]],
    review_candidates: list[Candidate],
    leaks: list[Leak],
    warnings: list[str],
) -> dict[str, Any]:
    source_counts = Counter(mapping.source for mapping in mappings)
    type_counts = Counter(mapping.type for mapping in mappings)
    return {
        "version": "1.0",
        "mode": mode,
        "source_file": source_file,
        "summary": {
            "mapping_count": len(mappings),
            "review_candidate_count": len(review_candidates),
            "leak_count": len(leaks),
            "source_counts": dict(sorted(source_counts.items())),
            "type_counts": dict(sorted(type_counts.items())),
        },
        "documents": [
            {
                "source_file": document.get("source_file"),
                "original_chars": len(str(document.get("original_text") or "")),
                "redacted_chars": len(str(document.get("redacted_text") or "")),
            }
            for document in documents
        ],
        "mappings": [
            {
                **mapping.to_dict(),
                "occurrences": _mapping_occurrences(mapping, documents),
            }
            for mapping in mappings
        ],
        "review_candidates": [_safe_candidate_dict(candidate) for candidate in review_candidates],
        "leaks": [leak.to_dict() for leak in leaks],
        "warnings": list(warnings),
    }


def _mapping_occurrences(
    mapping: MappingEntry,
    documents: list[dict[str, str | None]],
) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    if not mapping.original:
        return occurrences
    for document in documents:
        text = str(document.get("original_text") or "")
        positions = _find_positions(text, mapping.original)
        if positions:
            occurrences.append(
                {
                    "source_file": document.get("source_file"),
                    "count": len(positions),
                    "positions": positions[:20],
                    "truncated": len(positions) > 20,
                }
            )
    return occurrences


def _find_positions(text: str, needle: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index == -1:
            return positions
        positions.append(index)
        start = index + max(1, len(needle))


def _safe_candidate_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "type": candidate.type,
        "text": candidate.text,
        "start": candidate.start,
        "end": candidate.end,
        "source": candidate.source,
        "confidence": candidate.confidence,
        "risk_level": candidate.risk_level,
        "auto_redact": candidate.auto_redact,
        "role": candidate.role,
        "reason": candidate.reason,
        "suggested_mask_type": candidate.suggested_mask_type,
        "needs_review": candidate.needs_review,
    }
