"""Linear, human-style rule discovery for legal document redaction.

The engine reads discoveries in source order. Once an entity is confirmed, it
expands that entity into deterministic full-text replacement rules. The source
text is kept unchanged during discovery so generated masks cannot interfere
with later recognition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .counters import TypeCounters
from .detectors import (
    _clean_organization_text,
    _is_false_person,
    _is_false_org,
    _looks_like_false_location,
    detect_fallback_person_candidates,
    detect_party_candidates,
    detect_title_candidates,
)
from .models import Candidate, MappingEntry


ADMIN_SUFFIXES = (
    "特别行政区",
    "自治区",
    "自治州",
    "街道",
    "社区",
    "省",
    "市",
    "区",
    "县",
    "旗",
    "镇",
    "乡",
    "村",
)

LEGAL_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "公司",
    "集团",
)

INSTITUTION_SUFFIXES = (
    "保险股份有限公司",
    "保险有限公司",
    "保险公司",
    "商业银行股份有限公司",
    "股份制商业银行",
    "农村商业银行",
    "商业银行",
    "银行",
    "人民法院",
    "人民检察院",
    "公安局",
    "税务局",
)

INDUSTRY_TERMS = (
    "房地产开发",
    "建筑工程",
    "建设工程",
    "园林绿化工程",
    "装饰工程",
    "设计",
    "运输",
    "物流",
    "科技",
    "教育科技",
    "文化传媒",
    "物业管理",
    "人力资源服务",
    "燃气",
    "水务",
    "医药",
    "药业",
    "钢铁",
    "电子商务",
    "贸易",
    "商贸",
    "咨询",
    "服务",
)

PROVINCE_NAMES = (
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
)

ORG_FULL_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,50}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|"
    r"律师事务所|会计师事务所|保险公司|商业银行|银行)"
)


def _location_core(value: str) -> str:
    for suffix in ADMIN_SUFFIXES:
        if value.endswith(suffix) and len(value) - len(suffix) >= 2:
            return value[: -len(suffix)]
    return value


def _location_suffix(value: str) -> str:
    for suffix in ADMIN_SUFFIXES:
        if value.endswith(suffix):
            return suffix
    return "地"


def _simple_legal_suffix(value: str) -> str:
    if value.endswith("集团"):
        return "集团"
    return "公司"


def _strip_leading_locations(value: str, known_locations: dict[str, str]) -> tuple[str, str]:
    prefix = ""
    remaining = value
    for location in sorted(known_locations, key=len, reverse=True):
        if remaining.startswith(location) and len(remaining) > len(location):
            prefix += known_locations[location]
            remaining = remaining[len(location) :]
            break
    return prefix, remaining


def _has_explicit_bare_brand_alias(text: str, brand: str) -> bool:
    if not brand:
        return False
    escaped = re.escape(brand)
    return bool(re.search(rf"(?:以下简称|简称|下称)[“\"'「『（(]?\s*{escaped}\s*[”\"'」』）)]?", text))


@dataclass
class LinearRuleEngine:
    counters: TypeCounters
    profile: object
    sample_blacklist: set[str]
    get_location_prefix: Callable[[str], str]
    mappings: list[MappingEntry] = field(default_factory=list)
    known_locations: dict[str, str] = field(default_factory=dict)
    known_people: set[str] = field(default_factory=set)
    known_organizations: set[str] = field(default_factory=set)
    seen_originals: set[str] = field(default_factory=set)
    source_text: str = ""

    def discover(
        self,
        text: str,
        admin_candidates: Iterable[Candidate] = (),
        llm_analysis: dict | None = None,
    ) -> list[MappingEntry]:
        self.source_text = text
        candidates = self.collect_candidates(text, admin_candidates, llm_analysis or {})
        candidates = self._apply_llm_verdicts(candidates, text, llm_analysis or {})
        for candidate in sorted(candidates, key=lambda item: (item.start, -item.length, -item.confidence)):
            if candidate.text in self.sample_blacklist:
                continue
            if candidate.type in {"location", "grassroots_org"}:
                self.accept_location(candidate)
            elif candidate.type == "person":
                self.accept_person(candidate)
            elif candidate.type == "organization":
                self.accept_organization(candidate)
        return self.mappings

    def collect_candidates(
        self,
        text: str,
        admin_candidates: Iterable[Candidate],
        analysis: dict,
    ) -> list[Candidate]:
        candidates = list(admin_candidates)
        party_candidates, _ = detect_party_candidates(text)
        candidates.extend(party_candidates)
        candidates.extend(detect_title_candidates(text))

        # Fallback person patterns have explicit legal-language context.
        candidates.extend(detect_fallback_person_candidates(text))

        # Generic organization discovery is restricted to complete legal names.
        for match in ORG_FULL_RE.finditer(text):
            value = _clean_organization_text(match.group(0))
            if "与" in value:
                value = value.rsplit("与", 1)[-1]
            if value:
                start = match.start() + match.group(0).find(value)
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

        candidates.extend(self._llm_candidates(text, analysis))
        return self._deduplicate_candidates(candidates)

    @staticmethod
    def _apply_llm_verdicts(
        candidates: list[Candidate],
        text: str,
        analysis: dict,
    ) -> list[Candidate]:
        rejected = {
            value for value in analysis.get("reject", [])
            if isinstance(value, str)
        }
        calibrations = analysis.get("calibrate", {})
        if not isinstance(calibrations, dict):
            calibrations = {}

        reviewed: list[Candidate] = []
        for candidate in candidates:
            if candidate.text in rejected:
                continue
            calibrated = calibrations.get(candidate.text)
            if not isinstance(calibrated, str):
                reviewed.append(candidate)
                continue
            calibrated = calibrated.strip()
            if len(calibrated) < 2:
                continue
            nearby_start = max(0, candidate.start - 80)
            nearby_end = min(len(text), candidate.end + 80)
            start = text.find(calibrated, nearby_start, nearby_end)
            if start < 0:
                reviewed.append(candidate)
                continue
            reviewed.append(
                Candidate(
                    type=candidate.type,
                    text=calibrated,
                    start=start,
                    end=start + len(calibrated),
                    source="linear_llm_calibrated",
                    confidence=0.95,
                    risk_level=candidate.risk_level,
                    auto_redact=True,
                    role=candidate.role,
                    metadata=candidate.metadata,
                )
            )
        return reviewed

    def _llm_candidates(self, text: str, analysis: dict) -> list[Candidate]:
        candidates: list[Candidate] = []
        for item in analysis.get("locations", []):
            self._append_exact_candidate(candidates, text, item.get("full"), "location")
        for item in analysis.get("persons", []):
            self._append_exact_candidate(candidates, text, item.get("name"), "person")
        for item in analysis.get("companies", []):
            for value in item.get("variants", []):
                self._append_exact_candidate(candidates, text, value, "organization")
        return candidates

    @staticmethod
    def _append_exact_candidate(
        candidates: list[Candidate],
        text: str,
        value: object,
        entity_type: str,
    ) -> None:
        if not isinstance(value, str) or len(value) < 2:
            return
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

    def accept_location(self, candidate: Candidate) -> None:
        if not getattr(self.profile, "redact_locations", True):
            return
        value = candidate.text.strip()
        if _looks_like_false_location(self.source_text, candidate.start, candidate.end, value):
            return
        core = _location_core(value)
        if len(core) < 2:
            return
        suffix = _location_suffix(value)
        prefix = self.get_location_prefix(core)
        masked = f"{prefix}{suffix}"
        self.known_locations[value] = masked
        self.known_locations[core] = masked
        self._add("location", value, masked, candidate)
        if core != value:
            self._add("location", core, masked, candidate)

    def accept_person(self, candidate: Candidate) -> None:
        if not getattr(self.profile, "redact_persons", True):
            return
        value = candidate.text.strip()
        if (
            value in self.known_people
            or not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", value)
            or _is_false_person(value)
            or any(word in value for word in ("当事", "应予", "应当", "予以"))
        ):
            return
        self.known_people.add(value)
        masked = f"{value[0]}某{self.counters.next(f'person_{value[0]}')}"
        self._add("person", value, masked, candidate)

    def accept_organization(self, candidate: Candidate) -> None:
        if not getattr(self.profile, "redact_organizations", True):
            return
        value = _clean_organization_text(candidate.text)
        if not value or value in self.known_organizations:
            return
        self.known_organizations.add(value)

        if any(suffix in value for suffix in INSTITUTION_SUFFIXES):
            masked = value
            for location in sorted(self.known_locations, key=len, reverse=True):
                masked = masked.replace(location, self.known_locations[location])
            if masked != value:
                self._add("organization", value, masked, candidate)
            return

        legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
        if not legal_suffix:
            return
        body = value[: -len(legal_suffix)]
        location_mask, body = _strip_leading_locations(body, self.known_locations)
        if not location_mask:
            province = next(
                (name for name in PROVINCE_NAMES if body.startswith(name) and len(body) > len(name) + 1),
                "",
            )
            if province:
                location_prefix = self.get_location_prefix(province)
                location_mask = f"{location_prefix}省"
                self.known_locations[province] = location_mask
                self._add("location", province, location_mask, candidate)
                body = body[len(province) :]

        industry = next(
            (term for term in sorted(INDUSTRY_TERMS, key=len, reverse=True) if body.endswith(term)),
            "",
        )
        brand = body[: -len(industry)] if industry else body
        brand = brand.strip("（）() ")
        if len(brand) < 2 or _is_false_org(f"{brand}公司"):
            return

        brand_mask = self.counters.next("group_prefix")
        full_mask = f"{location_mask}{brand_mask}{industry}{_simple_legal_suffix(legal_suffix)}"
        self._add("organization", value, full_mask, candidate)
        if _has_explicit_bare_brand_alias(self.source_text, brand):
            self._add("organization", brand, brand_mask, candidate)

        company_alias = f"{brand}公司"
        if company_alias in self.source_text:
            self._add("organization", company_alias, f"{brand_mask}公司", candidate)

    def _add(
        self,
        entity_type: str,
        original: str,
        masked: str,
        candidate: Candidate,
    ) -> None:
        if (
            not original
            or original in self.seen_originals
            or original in self.sample_blacklist
            or original == masked
        ):
            return
        self.seen_originals.add(original)
        self.mappings.append(
            MappingEntry(
                type=entity_type,
                original=original,
                masked=masked,
                role=candidate.role,
                source=f"linear:{candidate.source}",
                confidence=candidate.confidence,
                restore_by_default=True,
            )
        )
