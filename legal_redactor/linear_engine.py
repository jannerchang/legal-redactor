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
    "居民委员会",
    "村民委员会",
    "居委会",
    "村委会",
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
    "幼儿园",
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
    "饮料",
    "建筑工程",
    "建设工程",
    "电力建设",
    "电力工程",
    "园林绿化工程",
    "装饰工程",
    "设计",
    "新能源",
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
    r"(?:^|(?<=[\s，,。；;：:、（(与和及由向对给找]))"
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|"
    r"律师事务所|会计师事务所|保险公司|商业银行|幼儿园|公司|集团|银行)"
)
BARE_COMPANY_ALIAS_RE = re.compile(
    r"(?:^|[，。；、\n：:]|找到的|从未找|未找|直接找|找|与|和|由|对|"
    r"证据[一二三四五六七八九十\d]+中|"
    r"原告|被告[一二三四五六七八九十\d]?|第三人)"
    r"(?P<alias>(?!(?:原告|被告|第三人|从未找|未找|直接找|找|聊天记录首先|证据[一二三四五六七八九十\d]+中))"
    r"[\u4e00-\u9fa5A-Za-z0-9·]{2,8}(?:公司|集团))"
)


def _location_core(value: str) -> str:
    if value.endswith("小镇"):
        return value
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
    if value.endswith("幼儿园"):
        return "幼儿园"
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


def _strip_parenthetical_admin(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner in PROVINCE_NAMES or inner.endswith(("省", "市", "区", "县", "镇", "乡")):
            return ""
        return match.group(0)

    return re.sub(r"[（(]([\u4e00-\u9fa5]{2,8})[）)]", replace, value)


def _has_explicit_bare_brand_alias(text: str, brand: str) -> bool:
    if not brand:
        return False
    escaped = re.escape(brand)
    return bool(re.search(rf"(?:以下简称|简称|下称)[“\"'「『（(]?\s*{escaped}(?!公司|集团)\s*[”\"'」』）)]?", text))


def _strip_known_place_prefix(value: str) -> str:
    body = value
    for province in PROVINCE_NAMES:
        for prefix in (province, f"{province}省"):
            if body.startswith(prefix) and len(body) > len(prefix) + 1:
                body = body[len(prefix):]
                return body
    return body


def _derived_organization_alias_cores(organization: str) -> set[str]:
    """Derive conservative short company aliases from an accepted full name."""
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if organization.endswith(suffix)), "")
    if not legal_suffix:
        return set()
    body = _strip_parenthetical_admin(organization[: -len(legal_suffix)]).strip("（）() ")
    body = _strip_known_place_prefix(body)
    aliases: set[str] = set()
    if len(body) >= 2:
        aliases.add(body)
    industry = next(
        (term for term in sorted(INDUSTRY_TERMS, key=len, reverse=True) if body.endswith(term)),
        "",
    )
    brand = body[: -len(industry)] if industry else body
    brand = brand.strip("（）() ")
    if len(brand) >= 2:
        aliases.add(brand)
    if len(brand) >= 4:
        aliases.add(brand[:2])
        aliases.add(brand[2:])
    if "电力建设" in body:
        aliases.add("电建")
    if re.search(r"第[一二三四五六七八九十]+工程", body):
        number = re.search(r"第([一二三四五六七八九十]+)工程", body)
        if number:
            aliases.add(f"{number.group(1)}建")
    return {alias for alias in aliases if len(alias) >= 2}


def _looks_like_complete_bare_company_body(body: str) -> bool:
    return (
        len(body) >= 5
        and not _is_false_org(f"{body}公司")
        and any(term in body for term in ("电力", "建设", "工程", "建筑", "新能源", "能源"))
    )


def _explicit_organization_aliases(text: str, organization: str) -> list[str]:
    """Extract aliases that the document explicitly ties to one organization."""
    aliases: list[str] = []
    escaped = re.escape(organization)
    org_pattern = ORG_FULL_RE.pattern
    alias_pattern = r"[\u4e00-\u9fa5A-Za-z0-9·]{2,20}(?:公司|集团)"
    for match in re.finditer(escaped, text):
        window = text[match.end() : min(len(text), match.end() + 180)]
        for pattern in (
            rf"[（(][^）)]{{0,30}}(?:原名称|原名|曾用名|原公司名称|原为|原系)\s*[：:为]?\s*(?P<alias>{org_pattern})[^）)]*[）)]",
            rf"(?:原名称|原名|曾用名|原公司名称|原为|原系)\s*[：:为]?\s*(?P<alias>{org_pattern})",
            rf"(?:以下简称|简称为|简称|下称)\s*[“\"'「『（(]?\s*(?P<alias>{alias_pattern})\s*[”\"'」』）)]?",
        ):
            for alias_match in re.finditer(pattern, window):
                alias = _clean_organization_text(alias_match.group("alias"))
                if alias and alias != organization and alias not in aliases:
                    aliases.append(alias)
    return aliases


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
    use_semantic_rules: bool = True

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
            if (
                candidate.text in self.sample_blacklist
                and not self._llm_exact_overrides_sample_blacklist(candidate.type, candidate.text, candidate)
            ):
                continue
            if candidate.type in {"location", "grassroots_org"}:
                self.accept_location(candidate)
            elif candidate.type == "person":
                self.accept_person(candidate)
            elif candidate.type == "organization":
                self.accept_organization(candidate)
            elif candidate.type == "project":
                self.accept_project(candidate)
        return self.mappings

    def collect_candidates(
        self,
        text: str,
        admin_candidates: Iterable[Candidate],
        analysis: dict,
    ) -> list[Candidate]:
        candidates = list(admin_candidates)
        has_local_org_ner = any(
            candidate.type == "organization" and candidate.source.startswith("hanlp_ner")
            for candidate in candidates
        )
        party_candidates, _ = detect_party_candidates(text)
        candidates.extend(party_candidates)
        candidates.extend(detect_title_candidates(text))

        if self.use_semantic_rules:
            # Fallback person patterns have explicit legal-language context.
            candidates.extend(detect_fallback_person_candidates(text))

            # Generic organization discovery is restricted to complete legal names.
            if not has_local_org_ner:
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
                for match in BARE_COMPANY_ALIAS_RE.finditer(text):
                    value = _clean_organization_text(match.group("alias"))
                    if value and not _is_false_org(value):
                        start = match.start("alias")
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
            variants = item.get("variants", [])
            if isinstance(variants, list):
                for value in variants:
                    self._append_exact_candidate(candidates, text, value, "organization", item, window_by_id)
        for item in analysis.get("projects", []):
            for value in self._entity_values(item, "name", "full", "text"):
                self._append_exact_candidate(candidates, text, value, "project", item, window_by_id)
        return candidates

    @staticmethod
    def _entity_values(item: dict, *keys: str) -> list[str]:
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
        item: dict | None = None,
        window_by_id: dict[str, dict] | None = None,
    ) -> None:
        if not isinstance(value, str) or len(value) < 2:
            return
        start = -1
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
                        start = text.find(value, span_start, span_end)
        if start < 0:
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
        raw_value = candidate.text.strip(" ：:，,。；;\n\t")
        value = _clean_organization_text(raw_value)
        if not value and candidate.source.startswith("linear_llm"):
            value = raw_value
        if not value or value in self.known_organizations:
            return

        if any(suffix in value for suffix in INSTITUTION_SUFFIXES):
            masked = value
            for location in sorted(self.known_locations, key=len, reverse=True):
                masked = masked.replace(location, self.known_locations[location])
            if masked != value:
                self.known_organizations.add(value)
                self._add("organization", value, masked, candidate)
            return

        legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
        if not legal_suffix:
            if candidate.source.startswith("linear_llm") and len(value) >= 2 and not _is_false_org(f"{value}公司"):
                suffix = "局" if value.endswith("局") else "机构"
                self._add("organization", value, f"{self.counters.next('group_prefix')}{suffix}", candidate)
            return
        body = value[: -len(legal_suffix)]
        if candidate.source.startswith("hanlp_ner") and body.endswith(ADMIN_SUFFIXES):
            return
        location_mask, body = _strip_leading_locations(body, self.known_locations)
        body = _strip_parenthetical_admin(body).strip("（）() ")
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

        if (
            legal_suffix in {"公司", "集团"}
            and candidate.source in {"linear_full_org", "hanlp_ner", "heuristic_ner"}
            and not _looks_like_complete_bare_company_body(body)
            and not self._known_organization_allows_short_alias(body)
        ):
            return

        industry = next(
            (term for term in sorted(INDUSTRY_TERMS, key=len, reverse=True) if body.endswith(term)),
            "",
        )
        brand = body[: -len(industry)] if industry else body
        brand = brand.strip("（）() ")
        if len(brand) < 2 or (
            legal_suffix in {"公司", "集团"} and _is_false_org(f"{brand}公司")
        ):
            return

        brand_mask = self.counters.next("group_prefix")
        full_mask = f"{location_mask}{brand_mask}{industry}{_simple_legal_suffix(legal_suffix)}"
        self.known_organizations.add(value)
        self._add("organization", value, full_mask, candidate)
        for alias in _explicit_organization_aliases(self.source_text, value):
            alias_mask = f"{brand_mask}公司" if alias.endswith("公司") and not any(alias.endswith(s) for s in LEGAL_SUFFIXES[:-1]) else full_mask
            self._add("organization", alias, alias_mask, candidate)
        if _has_explicit_bare_brand_alias(self.source_text, brand):
            self._add("organization", brand, brand_mask, candidate)

        company_alias = f"{brand}公司"
        if company_alias in self.source_text:
            self._add("organization", company_alias, f"{brand_mask}公司", candidate)

    def _known_organization_allows_short_alias(self, alias_core: str) -> bool:
        if not alias_core or len(alias_core) < 2:
            return False
        if _has_explicit_bare_brand_alias(self.source_text, alias_core):
            return True
        for organization in self.known_organizations:
            if alias_core in _derived_organization_alias_cores(organization):
                return True
        return False

    def accept_project(self, candidate: Candidate) -> None:
        if not getattr(self.profile, "redact_projects", True):
            return
        value = candidate.text.strip(" ：:，,。；;\n\t")
        if (
            not value
            or value in self.seen_originals
            or value in self.sample_blacklist
            or value in {"项目", "工程", "小区", "楼盘"}
            or len(value) < 3
        ):
            return
        suffix = "地"
        for ending in ("小区", "项目", "工程", "花园", "华府", "澜庭", "蓝庭", "公寓", "广场", "大厦", "产业园"):
            if value.endswith(ending):
                suffix = ending
                break
        masked = f"{self.counters.next('project')}{suffix}"
        self._add("project", value, masked, candidate)

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
            or (
                original in self.sample_blacklist
                and not self._llm_exact_overrides_sample_blacklist(entity_type, original, candidate)
            )
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

    @staticmethod
    def _llm_exact_overrides_sample_blacklist(
        entity_type: str,
        original: str,
        candidate: Candidate,
    ) -> bool:
        if candidate.source != "linear_llm_exact":
            return False
        if entity_type == "person":
            return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", original))
        if entity_type == "organization":
            return any(original.endswith(suffix) for suffix in LEGAL_SUFFIXES + INSTITUTION_SUFFIXES)
        return False
