"""Candidate discovery for the linear redaction path.

The collector owns source discovery, source ordering, local offset rewriting,
LLM exact materialization, and candidate dedupe. It intentionally does not
accept or mask entities; ``LinearRuleEngine`` keeps verdict application,
overlap resolution, and deterministic mapping expansion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from .china_admin_rules import detect_china_admin_rule_candidates
from .detectors import (
    detect_fallback_person_candidates,
    detect_inline_party_person_list_candidates,
    detect_party_candidates,
    detect_title_candidates,
)
from .filters import clean_organization_text as _clean_organization_text
from .filters import is_false_org as _is_false_org
from .lexicon import BARE_COMPANY_ALIAS_RE, INSTITUTION_SUFFIXES, LEGAL_SUFFIXES, ORG_FULL_RE
from .llm import is_noise_entity_text, _is_valid_company_variant
from .models import Candidate


SENTENCE_SPLIT_RE = re.compile(r"[^\n。！？；;，,、]+[。！？；;，,、]?")


@dataclass(frozen=True)
class CandidateCollectionContext:
    text: str
    seed_candidates: list[Candidate] = field(default_factory=list)
    llm_analysis: dict[str, Any] = field(default_factory=dict)
    llm_primary_discovery: bool = False
    use_semantic_rules: bool = True
    use_china_admin_rules: bool = True


@dataclass(frozen=True)
class CandidateCollectionResult:
    candidates: list[Candidate]

    def with_llm_analysis(
        self,
        collector: "CandidateCollector",
        text: str,
        analysis: dict[str, Any],
    ) -> "CandidateCollectionResult":
        return CandidateCollectionResult(
            candidates=collector._deduplicate_candidates(
                [*self.candidates, *collector._llm_candidates(text, analysis)]
            )
        )


class CandidateCollector:
    """Collect ordered candidates behind one small discovery interface."""

    def collect(self, context: CandidateCollectionContext) -> CandidateCollectionResult:
        candidates = list(context.seed_candidates)
        if context.llm_primary_discovery:
            candidates.extend(self._llm_candidates(context.text, context.llm_analysis))
            return CandidateCollectionResult(candidates=self._deduplicate_candidates(candidates))

        has_local_org_ner = any(
            candidate.type == "organization" and candidate.source.startswith("hanlp_ner")
            for candidate in candidates
        )
        candidates.extend(detect_title_candidates(context.text))
        candidates.extend(detect_inline_party_person_list_candidates(context.text))
        party_candidates: list[Candidate] = []
        fallback_people: list[Candidate] = []
        local_orgs: list[Candidate] = []
        for segment, offset in self._sentence_spans(context.text):
            segment_party, _ = detect_party_candidates(segment)
            party_candidates.extend(self._offset_candidates(segment_party, offset))
            if context.use_semantic_rules:
                fallback_people.extend(
                    self._offset_candidates(
                        detect_fallback_person_candidates(segment),
                        offset,
                    )
                )
                if not has_local_org_ner:
                    local_orgs.extend(self._organization_candidates(segment, offset))
        candidates.extend(party_candidates)

        if context.use_semantic_rules:
            candidates.extend(fallback_people)
            if context.use_china_admin_rules:
                candidates.extend(detect_china_admin_rule_candidates(context.text))
            candidates.extend(local_orgs)

        candidates.extend(self._llm_candidates(context.text, context.llm_analysis))
        return CandidateCollectionResult(candidates=self._deduplicate_candidates(candidates))

    @staticmethod
    def _sentence_spans(text: str) -> list[tuple[str, int]]:
        spans = [
            (match.group(0), match.start())
            for match in SENTENCE_SPLIT_RE.finditer(text)
            if match.group(0).strip()
        ]
        return spans or [(text, 0)]

    @staticmethod
    def _offset_candidates(candidates: Iterable[Candidate], offset: int) -> list[Candidate]:
        if offset == 0:
            return list(candidates)
        return [
            replace(
                candidate,
                start=candidate.start + offset,
                end=candidate.end + offset,
            )
            for candidate in candidates
        ]

    @staticmethod
    def _organization_candidates(text: str, offset: int = 0) -> list[Candidate]:
        candidates: list[Candidate] = []
        for match in ORG_FULL_RE.finditer(text):
            value = _clean_organization_text(match.group(0))
            if "与" in value:
                value = value.rsplit("与", 1)[-1]
            if value and _is_false_org(value):
                continue
            if value:
                start = offset + match.start() + match.group(0).find(value)
                candidates.append(
                    Candidate(
                        type="organization",
                        text=value,
                        start=start,
                        end=start + len(value),
                        source="linear_full_org",
                        confidence=0.9,
                        risk_level="medium",
                        auto_redact=True,
                    )
                )
        for match in BARE_COMPANY_ALIAS_RE.finditer(text):
            value = _clean_organization_text(match.group("alias"))
            if value and not _is_false_org(value):
                start = offset + match.start("alias")
                candidates.append(
                    Candidate(
                        type="organization",
                        text=value,
                        start=start,
                        end=start + len(value),
                        source="linear_bare_org_alias",
                        confidence=0.91,
                        risk_level="medium",
                        auto_redact=True,
                    )
                )
        return candidates

    def _llm_candidates(self, text: str, analysis: dict[str, Any]) -> list[Candidate]:
        candidates: list[Candidate] = []
        windows = analysis.get("_sentence_windows", [])
        window_by_id = {
            item.get("id"): item
            for item in windows
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(windows, list) else {}
        for item in analysis.get("locations", []):
            for value in self._entity_values(item, "full", "name", "text"):
                self._append_exact_candidate(candidates, text, value, "location", item, window_by_id)
        for item in analysis.get("persons", []):
            for value in self._entity_values(item, "name", "text"):
                self._append_exact_candidate(candidates, text, value, "person", item, window_by_id)
        for item in analysis.get("companies", []):
            for value in self._entity_values(item, "name", "full", "brand", "text"):
                self._append_exact_candidate(candidates, text, value, "organization", item, window_by_id)
            variants = item.get("variants", []) if isinstance(item, dict) else []
            if isinstance(variants, list):
                for value in variants:
                    self._append_exact_candidate(candidates, text, value, "organization", item, window_by_id)
        for item in analysis.get("projects", []):
            for value in self._entity_values(item, "name", "full", "text"):
                self._append_exact_candidate(candidates, text, value, "project", item, window_by_id)
        return candidates

    @staticmethod
    def _entity_values(item: dict[str, Any], *keys: str) -> list[str]:
        values: list[str] = []
        if not isinstance(item, dict):
            return values
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value not in values:
                values.append(value)
        return values

    @staticmethod
    def _append_exact_candidate(
        candidates: list[Candidate],
        text: str,
        value: object,
        entity_type: str,
        item: dict[str, Any] | None = None,
        window_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if not isinstance(value, str) or len(value) < 2:
            return
        if is_noise_entity_text(value):
            return
        if entity_type == "organization" and not _is_valid_company_variant(value):
            return
        start = -1
        had_window = False
        if item and window_by_id:
            window_id = item.get("window")
            if isinstance(window_id, str):
                window = window_by_id.get(window_id)
                if window:
                    try:
                        span_start = int(window.get("start", 0))
                        span_end = int(window.get("end", 0))
                    except (TypeError, ValueError):
                        span_start = 0
                        span_end = 0
                    if span_end > span_start:
                        had_window = True
                        start = text.find(value, span_start, span_end)
        if start < 0 and had_window:
            occurrences = [match.start() for match in re.finditer(re.escape(value), text)]
            is_complete_organization = (
                entity_type == "organization"
                and any(
                    value.endswith(suffix)
                    for suffix in LEGAL_SUFFIXES + INSTITUTION_SUFFIXES
                    if suffix not in {"公司", "集团"}
                )
            )
            if len(occurrences) == 1 and (
                entity_type in {"person", "location", "project"}
                or is_complete_organization
            ):
                start = occurrences[0]
        elif start < 0 and not had_window:
            start = text.find(value)
        if start < 0:
            return
        candidates.append(
            Candidate(
                type=entity_type,
                text=value,
                start=start,
                end=start + len(value),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    @staticmethod
    def _deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
        best: dict[tuple[str, str, int], Candidate] = {}
        for candidate in candidates:
            key = (candidate.type, candidate.text, candidate.start)
            previous = best.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                best[key] = candidate
        return list(best.values())


def candidate_needs_llm_review(candidate: Candidate) -> bool:
    source = candidate.source
    if source in {"fallback_person", "heuristic_ner", "linear_full_org", "linear_bare_org_alias"}:
        return True
    if suspicious_organization_candidate(candidate):
        return True
    if candidate.confidence < 0.85:
        return True
    if source.startswith("hanlp_ner"):
        if candidate.type == "person":
            return len(candidate.text) <= 2
        if candidate.type in {"location", "grassroots_org"}:
            return len(candidate.text) <= 4 or candidate.text.startswith(("（", "("))
        if candidate.type == "organization":
            return len(candidate.text) <= 6 or not any(
                candidate.text.endswith(suffix)
                for suffix in LEGAL_SUFFIXES
                if suffix not in {"公司", "集团"}
            )
    return False


def suspicious_organization_candidate(candidate: Candidate) -> bool:
    if candidate.type != "organization":
        return False
    text = candidate.text.strip()
    if not text:
        return False
    if _is_false_org(text):
        return False
    if len(text) >= 10:
        return True
    if any(
        marker in text
        for marker in (
            "否认",
            "关联公司",
            "合同",
            "银行流水",
            "人员混同",
            "搅浑",
            "欲证实",
            "无权再向",
        )
    ):
        return True
    return candidate.source == "party_section" and len(text) > 6
