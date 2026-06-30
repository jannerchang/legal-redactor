"""Resolve overlapping entity candidates before linear acceptance."""

from __future__ import annotations

import re

from .models import Candidate

SOURCE_PRIORITY: dict[str, int] = {
    "party_section": 100,
    "hebei_admin_db": 95,
    "linear_llm_exact": 90,
    "linear_llm_calibrated": 88,
    "linear_full_org": 75,
    "linear_bare_org_alias": 72,
    "title_section": 65,
    "hanlp_ner": 60,
    "heuristic_ner": 50,
    "fallback_person": 40,
}

TYPE_PRIORITY: dict[str, int] = {
    "organization": 40,
    "project": 30,
    "location": 20,
    "grassroots_org": 20,
    "person": 10,
}

NOISY_ORG_PREFIXES = (
    "到的",
    "从未找",
    "未找",
    "直接找",
    "找",
    "一中",
    "二中",
    "三名",
    "该聊天",
    "首先",
    "原名",
)


def is_noisy_org_capture(text: str) -> bool:
    return (
        any(text.startswith(prefix) for prefix in NOISY_ORG_PREFIXES)
        or (bool(re.match(r"^[一二三四五六七八九十\d]", text)) and len(text) <= 7)
        or "的管理" in text
        or "聊天记录" in text
        or "主张过" in text
    )


def _source_rank(source: str) -> int:
    if source in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[source]
    for prefix, rank in SOURCE_PRIORITY.items():
        if source.startswith(prefix):
            return rank
    return 15


def _candidate_quality(candidate: Candidate) -> tuple[int, int, float, int]:
    source_rank = _source_rank(candidate.source)
    if candidate.type == "organization" and is_noisy_org_capture(candidate.text):
        source_rank -= 40
    return (
        source_rank,
        TYPE_PRIORITY.get(candidate.type, 0),
        candidate.confidence,
        candidate.length,
    )


def _overlaps(left: Candidate, right: Candidate) -> bool:
    return not (left.end <= right.start or left.start >= right.end)


def _should_prefer_nested(inner: Candidate, outer: Candidate) -> bool:
    if inner.type != "organization" or outer.type != "organization":
        return False
    if not (outer.start <= inner.start and outer.end >= inner.end):
        return False
    if inner.text == outer.text:
        return False
    if outer.text.endswith(inner.text) and is_noisy_org_capture(outer.text):
        return True
    return False


def resolve_candidate_overlaps(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the highest-quality candidate for each overlapping span."""
    if len(candidates) < 2:
        return list(candidates)

    ranked = sorted(candidates, key=_candidate_quality, reverse=True)
    accepted: list[Candidate] = []
    for candidate in ranked:
        skip_candidate = False
        for index, other in enumerate(list(accepted)):
            if not _overlaps(candidate, other):
                continue
            if _should_prefer_nested(candidate, other):
                accepted[index] = candidate
                skip_candidate = True
                break
            if _should_prefer_nested(other, candidate):
                skip_candidate = True
                break
        if skip_candidate:
            continue
        if any(_overlaps(candidate, other) for other in accepted):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda item: (item.start, -item.length, -item.confidence))