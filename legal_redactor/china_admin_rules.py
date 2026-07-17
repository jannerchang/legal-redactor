"""Nationwide province/city/county administrative division rules and path detection."""

from __future__ import annotations

import re

from .models import Candidate

MUNICIPALITIES = frozenset({"北京市", "天津市", "上海市", "重庆市"})

PROVINCE_ENTRIES: tuple[tuple[str, str], ...] = (
    ("北京", "北京市"),
    ("天津", "天津市"),
    ("河北", "河北省"),
    ("山西", "山西省"),
    ("内蒙古", "内蒙古自治区"),
    ("辽宁", "辽宁省"),
    ("吉林", "吉林省"),
    ("黑龙江", "黑龙江省"),
    ("上海", "上海市"),
    ("江苏", "江苏省"),
    ("浙江", "浙江省"),
    ("安徽", "安徽省"),
    ("福建", "福建省"),
    ("江西", "江西省"),
    ("山东", "山东省"),
    ("河南", "河南省"),
    ("湖北", "湖北省"),
    ("湖南", "湖南省"),
    ("广东", "广东省"),
    ("广西", "广西壮族自治区"),
    ("海南", "海南省"),
    ("重庆", "重庆市"),
    ("四川", "四川省"),
    ("贵州", "贵州省"),
    ("云南", "云南省"),
    ("西藏", "西藏自治区"),
    ("陕西", "陕西省"),
    ("甘肃", "甘肃省"),
    ("青海", "青海省"),
    ("宁夏", "宁夏回族自治区"),
    ("新疆", "新疆维吾尔自治区"),
    ("香港", "香港特别行政区"),
    ("澳门", "澳门特别行政区"),
    ("台湾", "台湾省"),
)

PROVINCE_SHORT_NAMES = frozenset(short for short, _ in PROVINCE_ENTRIES)
PROVINCE_FULL_NAMES = frozenset(full for _, full in PROVINCE_ENTRIES)
SHORT_TO_FULL_PROVINCE = dict(PROVINCE_ENTRIES)

ADMIN_PATH_RE = re.compile(
    r"^(?:(?P<prov>[\u4e00-\u9fa5]{2,12}(?:省|自治区|特别行政区)))?"
    r"(?:(?P<city>[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)))?"
    r"(?:(?P<county>[\u4e00-\u9fa5]{2,12}(?:(?<!社)区|县|旗|市)))?"
    r"(?:(?P<town>[\u4e00-\u9fa5]{2,12}(?:街道|镇|乡)))?"
    r"(?:(?P<village>[\u4e00-\u9fa5]{2,20}(?:居民委员会|居委会|村民委员会|村委会|社区|村)))?$"
)

ADMIN_PATH_SEARCH_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,12}(?:省|自治区|特别行政区)"
    r"[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)"
    r"[\u4e00-\u9fa5]{2,12}(?:(?<!社)区|县|旗)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:市|特别行政区)"
    r"[\u4e00-\u9fa5]{2,12}(?:(?<!社)区|县|旗)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:省|自治区|特别行政区)"
    r"[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)"
    r"[\u4e00-\u9fa5]{2,12}(?:(?<!社)区|县|旗)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:省|自治区|特别行政区)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)"
    r"|"
    r"[\u4e00-\u9fa5]{2,12}(?:(?<!社)区|县|旗)"
)

# Pre-compiled patterns for detect_china_admin_rule_candidates
_PROVINCE_FULL_PATTERNS = tuple(
    (short, full, re.compile(re.escape(full)))
    for short, full in PROVINCE_ENTRIES
)
_PROVINCE_SHORT_PATTERNS = tuple(
    (short, full, re.compile(rf"(?<![\u4e00-\u9fa5]){re.escape(short)}(?![\u4e00-\u9fa5])"))
    for short, full in PROVINCE_ENTRIES
)

FALSE_LOCATION_TERMS = frozenset(
    {
        "本院",
        "原告",
        "被告",
        "第三人",
        "合同",
        "项目",
        "工程",
        "公司",
        "集团",
    }
)

ADDRESS_PREFIX_MARKERS = (
    "住所地",
    "户籍地",
    "经常居住地",
    "所在地",
    "住所",
    "户籍",
    "住",
)


_LEADING_ADMIN_CONNECTORS = frozenset("由从向在至到及与和后前")
_ADDRESS_CITY_PREFIX_RE = re.compile(r"^(?:住|住所|户籍)(?P<city>[\u4e00-\u9fa5]{2,12}市)$")
_LEADING_ADMIN_NARRATIVE_RE = re.compile(r"^(?:(?:原告|被告)[\u4e00-\u9fa5·]{0,4})?(?:后)?(?:搬至|迁至|住)")
_PROVINCE_OR_MUNICIPALITY_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(
        sorted(
            (re.escape(name) for name in (*PROVINCE_FULL_NAMES, *PROVINCE_SHORT_NAMES)),
            key=len,
            reverse=True,
        )
    ) + r")"
)


def normalize_province_name(value: str) -> str | None:
    text = value.strip()
    if text in PROVINCE_FULL_NAMES:
        return text
    if text in PROVINCE_SHORT_NAMES:
        return SHORT_TO_FULL_PROVINCE[text]
    for short, full in PROVINCE_ENTRIES:
        if text == full or text == short:
            return full
        if text.endswith("省") and text[:-1] == short:
            return full
    return None


def decompose_admin_path(text: str) -> dict[str, str]:
    value = text.strip()
    if any(value.startswith(municipality) for municipality in MUNICIPALITIES):
        compact_parts = _decompose_compact_admin_path(value)
        if compact_parts:
            return compact_parts
    match = ADMIN_PATH_RE.match(value)
    if match:
        parts = {key: part for key, part in match.groupdict().items() if part}
        if _admin_path_match_is_valid(parts):
            return parts
    return _decompose_compact_admin_path(value)


def _admin_path_match_is_valid(parts: dict[str, str]) -> bool:
    if parts.get("prov"):
        return True
    city = parts.get("city", "")
    if not city:
        return bool(parts)
    if any(city.startswith(short) and len(city) > len(short) for short, _ in PROVINCE_ENTRIES):
        return False
    if len(city) > 8 and not parts.get("county"):
        return False
    return True


def _decompose_compact_admin_path(text: str) -> dict[str, str]:
    """Parse compact paths such as 河北唐山迁安市 when the province omits 省."""
    rest = text
    parts: dict[str, str] = {}

    for short, full in PROVINCE_ENTRIES:
        if rest.startswith(full):
            parts["prov"] = full
            rest = rest[len(full) :]
            break
    else:
        for short, full in sorted(PROVINCE_ENTRIES, key=lambda item: len(item[0]), reverse=True):
            if not rest.startswith(short) or len(rest) <= len(short):
                continue
            parts["prov"] = full
            rest = rest[len(short) :]
            break

    if not rest:
        return parts

    rest, county = _split_county_suffix(rest)
    if county:
        parts["county"] = county

    if not rest:
        return parts

    city_match = re.match(r"[\u4e00-\u9fa5]{2,12}(?:市|自治州|地区|盟)", rest)
    if city_match:
        parts["city"] = city_match.group(0)
    elif parts.get("prov"):
        parts["city"] = rest
    return parts


def detect_china_admin_rule_candidates(text: str) -> list[Candidate]:
    """Detect nationwide 省/市/区县 paths and validated province names."""
    candidates: list[Candidate] = []
    seen_spans: set[tuple[int, int, str]] = set()

    for match in ADMIN_PATH_SEARCH_RE.finditer(text):
        fragment = match.group(0)
        if not fragment or fragment in FALSE_LOCATION_TERMS:
            continue
        normalized = _normalize_rule_fragment(text, match.start(), match.end())
        if normalized is None:
            continue
        fragment, start, end = normalized
        parts = decompose_admin_path(_strip_admin_connectors(fragment))
        if not parts and not normalize_province_name(fragment):
            continue
        if parts.get("prov") and not normalize_province_name(parts["prov"]):
            continue
        _append_rule_candidates(
            candidates,
            seen_spans,
            text=text,
            fragment=fragment,
            start=start,
            end=end,
            parts=parts,
            confidence=0.88,
            reason="全国三级行政区划路径规则",
        )

    for short, full, full_pattern in _PROVINCE_FULL_PATTERNS:
        for match in full_pattern.finditer(text):
            index = match.start()
            end = match.end()
            if _looks_like_org_context(text, index, end):
                continue
            _append_rule_candidates(
                candidates,
                seen_spans,
                text=text,
                fragment=full,
                start=index,
                end=end,
                parts={"prov": full},
                confidence=0.9,
                reason=f"全国省级行政区划：{full}",
            )
    for short, full, short_pattern in _PROVINCE_SHORT_PATTERNS:
        for match in short_pattern.finditer(text):
            index = match.start()
            end = match.end()
            if _looks_like_org_context(text, index, end):
                continue
            _append_rule_candidates(
                candidates,
                seen_spans,
                text=text,
                fragment=short,
                start=index,
                end=end,
                parts={"prov": full},
                confidence=0.86,
                reason=f"全国省级行政区划：{full}",
            )
    return candidates


def _append_rule_candidates(
    candidates: list[Candidate],
    seen_spans: set[tuple[int, int, str]],
    *,
    text: str,
    fragment: str,
    start: int,
    end: int,
    parts: dict[str, str],
    confidence: float,
    reason: str,
) -> None:
    payloads: list[tuple[str, int, int, dict[str, str]]] = []
    cursor = start
    for key in ("prov", "city", "county"):
        value = parts.get(key)
        if not value:
            continue
        local_start = fragment.find(value, cursor - start)
        if local_start < 0:
            local_start = fragment.find(value)
        if local_start < 0:
            continue
        absolute_start = start + local_start
        absolute_end = absolute_start + len(value)
        cursor = absolute_end
        part_parts = {key: value}
        if key == "prov":
            part_parts["prov"] = value
        payloads.append((value, absolute_start, absolute_end, part_parts))

    for value, value_start, value_end, metadata_parts in payloads:
        key = (value_start, value_end, value)
        if key in seen_spans:
            continue
        seen_spans.add(key)
        candidates.append(
            Candidate(
                type="location",
                text=value,
                start=value_start,
                end=value_end,
                source="china_admin_rules",
                confidence=confidence,
                risk_level="medium",
                auto_redact=True,
                reason=reason,
                metadata={
                    "parts": metadata_parts,
                    "context": text[max(0, value_start - 30) : min(len(text), value_end + 30)],
                },
            )
        )


def _looks_like_org_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 4) : min(len(text), end + 8)]
    return any(marker in window for marker in ("有限公司", "股份有限公司", "银行", "法院", "检察院"))


def _split_county_suffix(rest: str) -> tuple[str, str | None]:
    for length in range(3, min(len(rest), 10) + 1):
        candidate = rest[-length:]
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,8}(?:(?<!社)区|县|旗|市)", candidate):
            return rest[:-length], candidate
    return rest, None


def _strip_admin_connectors(fragment: str) -> str:
    return re.sub(
        r"(省|自治区|特别行政区|市|自治州|地区|盟|区|县|旗)[与和及至到向在由从]+",
        r"\1",
        fragment,
    )


def _normalize_rule_fragment(text: str, start: int, end: int) -> tuple[str, int, int] | None:
    fragment = text[start:end]
    address_city_match = _ADDRESS_CITY_PREFIX_RE.match(fragment)
    if address_city_match:
        city = address_city_match.group("city")
        return city, start + address_city_match.start("city"), end
    narrative_match = _LEADING_ADMIN_NARRATIVE_RE.match(fragment)
    if narrative_match:
        fragment = fragment[narrative_match.end() :]
        start += narrative_match.end()
        if len(fragment) < 2:
            return None
    for marker in ADDRESS_PREFIX_MARKERS:
        if not fragment.startswith(marker):
            continue
        trimmed = fragment[len(marker) :]
        if len(trimmed) < 2:
            return None
        return trimmed, start + len(marker), end
    connector_match = re.match(r"^(?:与|和|及|至|到|向|在|由|从|迁至|搬至)", fragment)
    if connector_match:
        fragment = fragment[connector_match.end() :]
        start += connector_match.end()
        if len(fragment) < 2:
            return None
    known_start = _known_admin_start(fragment)
    is_hierarchical_path = any(
        suffix in fragment for suffix in ("区", "县", "旗", "街道", "镇", "乡")
    )
    if (
        fragment.endswith(("省", "自治区", "特别行政区", "市"))
        and not is_hierarchical_path
        and not _PROVINCE_OR_MUNICIPALITY_PREFIX_RE.match(fragment)
    ):
        return None
    if known_start > 0:
        prefix = fragment[:known_start]
        if any(char not in _LEADING_ADMIN_CONNECTORS for char in prefix):
            return None
        fragment = fragment[known_start:]
        start += known_start
    elif is_hierarchical_path and not _PROVINCE_OR_MUNICIPALITY_PREFIX_RE.match(fragment):
        address_match = re.search(r"住(?P<path>[\u4e00-\u9fa5]+(?:省|市).+)$", fragment)
        if not address_match:
            return None
        fragment = address_match.group("path")
        start += address_match.start("path")
    if any(fragment.startswith(marker) for marker in FALSE_LOCATION_TERMS):
        return None
    return fragment, start, end

def _known_admin_start(fragment: str) -> int:
    matches = [
        index
        for name in (*PROVINCE_FULL_NAMES, *PROVINCE_SHORT_NAMES)
        if (index := fragment.find(name)) >= 0
    ]
    return min(matches) if matches else -1
