"""Organization parsing, alias derivation, and masking helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Mapping

from .filters import clean_organization_text as _clean_organization_text, is_false_org as _is_false_org
from .lexicon import (
    INDUSTRY_TERMS_BY_LEN,
    LEGAL_SUFFIXES,
    ORG_FULL_RE,
    PROVINCE_NAMES,
)
from .location_utils import strip_leading_locations


@dataclass(frozen=True)
class CompanyMaskPlan:
    value: str
    full_mask: str
    brand: str
    brand_mask: str
    legal_suffix: str
    location_updates: tuple[tuple[str, str], ...]
    aliases: tuple[str, ...]


def simple_legal_suffix(value: str) -> str:
    if value.endswith("集团"):
        return "集团"
    if value.endswith("幼儿园"):
        return "幼儿园"
    return "公司"


def strip_parenthetical_admin(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner in PROVINCE_NAMES or inner.endswith(("省", "市", "区", "县", "镇", "乡")):
            return ""
        return match.group(0)

    return re.sub(r"[（(]([\u4e00-\u9fa5]{2,8})[）)]", replace, value)


def has_explicit_short_company_alias(text: str, brand: str) -> bool:
    if not brand:
        return False
    escaped = re.escape(brand)
    return bool(
        re.search(
            rf"(?:以下简称|简称为|简称|下称)\s*[“\"'「『（(]?\s*(?:{escaped}|{escaped}公司|{escaped}集团)\s*[”\"'」』）)]?",
            text,
        )
    )


def has_explicit_bare_brand_alias(text: str, brand: str) -> bool:
    if not brand:
        return False
    escaped = re.escape(brand)
    return bool(
        re.search(
            rf"(?:以下简称|简称|下称)[“\"'「『（(]?\s*{escaped}(?!公司|集团)\s*[”\"'」』）)]?",
            text,
        )
    )


def strip_known_place_prefix(value: str) -> str:
    body = value
    for province in PROVINCE_NAMES:
        for prefix in (province, f"{province}省"):
            if body.startswith(prefix) and len(body) > len(prefix) + 1:
                return body[len(prefix) :]
    return body


def _industry_and_brand_from_body(body: str) -> tuple[str, str]:
    industry = next((term for term in INDUSTRY_TERMS_BY_LEN if body.endswith(term)), "")
    brand = body[: -len(industry)] if industry else body
    return industry, brand.strip("（）() ")


_INDUSTRY_LEADING_MARKERS = ("建设", "建筑", "装饰", "安装", "工程", "电力", "新能源")


def _place_mask(place: str, get_location_prefix: Callable[[str], str]) -> str:
    """Keep a leading place inside an organization out of its organization mask.

    Locations are independently recognized and masked. Repeating a place as an
    organization prefix both leaks the entity relation and lets a city surface
    drift into a province-shaped placeholder.
    """
    _ = place, get_location_prefix
    return ""


def _split_leading_place_prefix(body: str) -> tuple[str, str]:
    """Split a company body into a leading place prefix and the remaining brand body."""
    if body.startswith(("中国", "中华", "全国")):
        return "", body
    body = body.strip("（）() ")
    for province in PROVINCE_NAMES:
        if body.startswith(province) and len(body) > len(province) + 1:
            return province, body[len(province) :]

    city, remainder = _strip_leading_city_name(body)
    if city:
        return city, remainder

    for size in (2, 3, 4):
        if len(body) <= size + 2:
            continue
        prefix = body[:size]
        if prefix in PROVINCE_NAMES:
            continue
        remainder = body[size:]
        if remainder.startswith(_INDUSTRY_LEADING_MARKERS):
            continue
        _, remainder_brand = _industry_and_brand_from_body(remainder)
        if (
            remainder_brand
            and 2 <= len(remainder_brand) <= 8
            and not remainder_brand.endswith(_INDUSTRY_LEADING_MARKERS)
        ):
            return prefix, remainder
    return "", body


@lru_cache(maxsize=512)
def derived_organization_alias_cores(organization: str) -> frozenset[str]:
    """Derive conservative short company aliases from an accepted full name."""
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if organization.endswith(suffix)), "")
    if not legal_suffix:
        return frozenset()
    body = strip_parenthetical_admin(organization[: -len(legal_suffix)]).strip("（）() ")
    body = strip_known_place_prefix(body)
    aliases: set[str] = set()
    if len(body) >= 2:
        aliases.add(body)
    industry = next((term for term in INDUSTRY_TERMS_BY_LEN if body.endswith(term)), "")
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
    return frozenset(alias for alias in aliases if len(alias) >= 2)


def looks_like_complete_bare_company_body(body: str) -> bool:
    return (
        len(body) >= 5
        and not _is_false_org(f"{body}公司")
        and any(term in body for term in ("电力", "建设", "工程", "建筑", "新能源", "能源"))
    )


def _explicit_alias_search_window(text: str, start: int, end: int) -> str:
    """Limit alias extraction to the clause that belongs to one organization mention."""
    preceding = text[max(0, start - 24) : start]
    if re.search(r"(?:以下简称|简称为|简称|下称)\s*$", preceding):
        return ""

    rest = text[end:]
    parts: list[str] = []
    paren_match = re.match(r"^[（(][^）)]*[）)]", rest)
    if paren_match:
        parts.append(paren_match.group(0))
        rest = rest[paren_match.end() :]
    fragment_match = re.match(r"^[^。！？；]*[。！？；]?", rest)
    if fragment_match:
        fragment = fragment_match.group(0)[:120]
        if fragment and not re.match(r"^[与及和]", fragment):
            parts.append(fragment)
    return "".join(parts)


def explicit_organization_aliases(text: str, organization: str) -> list[str]:
    """Extract aliases that the document explicitly ties to one organization."""
    aliases: list[str] = []
    escaped = re.escape(organization)
    org_pattern = ORG_FULL_RE.pattern
    suffixed_alias_pattern = r"[\u4e00-\u9fa5A-Za-z0-9·]{2,20}(?:公司|集团)"
    bare_alias_pattern = r"[\u4e00-\u9fa5A-Za-z0-9·]{2,20}"
    for match in re.finditer(escaped, text):
        window = _explicit_alias_search_window(text, match.start(), match.end())
        if not window:
            continue
        for pattern in (
            rf"[（(][^）)]{{0,30}}(?:原名称|原名|曾用名|原公司名称|原为|原系)\s*[：:为]?\s*(?P<alias>{org_pattern})[^）)]*[）)]",
            rf"(?:原名称|原名|曾用名|原公司名称|原为|原系)\s*[：:为]?\s*(?P<alias>{org_pattern})",
            rf"(?:以下简称|简称为|简称|下称)\s*[“\"'「『（(]?\s*(?P<alias>{suffixed_alias_pattern})\s*[”\"'」』）)]?",
            rf"(?:以下简称|简称为|简称|下称)\s*[“\"'「『（(]?\s*(?P<alias>{bare_alias_pattern})\s*[”\"'」』）)]?",
        ):
            for alias_match in re.finditer(pattern, window):
                alias = _clean_organization_text(alias_match.group("alias"))
                if alias and alias != organization and alias not in aliases:
                    aliases.append(alias)
    return aliases


def mask_institution(value: str, known_locations: dict[str, str]) -> str | None:
    masked = value
    for location in sorted(known_locations, key=len, reverse=True):
        masked = masked.replace(location, known_locations[location])
    if masked != value:
        return masked
    for suffix in ("律师事务所", "会计师事务所", "医院", "学校"):
        if value.endswith(suffix):
            return f"{value[0]}某{suffix}"
    for suffix in ("分行", "支行", "营业部"):
        if "银行" in value and value.endswith(suffix):
            return f"{value[0]}某{suffix}"
    return None


def build_company_mask_plan(
    *,
    value: str,
    source_text: str,
    known_locations: dict[str, str],
    get_location_prefix: Callable[[str], str],
    get_brand_mask: Callable[[str], str],
) -> CompanyMaskPlan | None:
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
    if not legal_suffix:
        return None

    body = value[: -len(legal_suffix)]
    location_mask, body = strip_leading_locations(body, known_locations)
    body = strip_parenthetical_admin(body).strip("（）() ")
    location_updates: list[tuple[str, str]] = []

    if not location_mask:
        place, body = _split_leading_place_prefix(body)
        if place:
            location_mask = _place_mask(place, get_location_prefix)
            location_updates.append((place, location_mask))

    industry, brand = _industry_and_brand_from_body(body)
    if len(brand) < 2 or (
        legal_suffix in {"公司", "集团"}
        and _is_false_org(f"{brand}公司")
        and not has_explicit_short_company_alias(source_text, brand)
        and not has_explicit_bare_brand_alias(source_text, brand)
    ):
        return None

    brand_mask = get_brand_mask(brand)
    full_mask = f"{location_mask}{brand_mask}{industry}{simple_legal_suffix(legal_suffix)}"
    aliases = explicit_organization_aliases(source_text, value)
    return CompanyMaskPlan(
        value=value,
        full_mask=full_mask,
        brand=brand,
        brand_mask=brand_mask,
        legal_suffix=legal_suffix,
        location_updates=tuple(location_updates),
        aliases=tuple(aliases),
    )


def alias_mask_for_organization(alias: str, plan: CompanyMaskPlan) -> str:
    if alias.endswith("公司") and not any(alias.endswith(suffix) for suffix in LEGAL_SUFFIXES[:-1]):
        return f"{plan.brand_mask}公司"
    return plan.full_mask


def organization_brand_key(value: str) -> str:
    """Extract the brand core from a company surface form."""
    cleaned = _clean_organization_text(value) or value.strip()
    cleaned = cleaned.strip(" ：:，,。；;、\n\t")
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if cleaned.endswith(suffix)), "")
    body = cleaned[: -len(legal_suffix)] if legal_suffix else cleaned
    body = strip_parenthetical_admin(body).strip("（）() ")
    body = strip_known_place_prefix(body)
    _, body = _split_leading_place_prefix(body)
    _, brand = _industry_and_brand_from_body(body)
    return brand


def organization_short_mask(plan: CompanyMaskPlan) -> str:
    return f"{plan.brand_mask}{simple_legal_suffix(plan.legal_suffix)}"


def is_short_company_surface(value: str, *, brand: str = "") -> bool:
    cleaned = (_clean_organization_text(value) or value).strip()
    if not cleaned:
        return False
    if brand and cleaned == brand:
        return True
    if brand and cleaned == f"{brand}公司":
        return True
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if cleaned.endswith(suffix)), "")
    if legal_suffix in {"公司", "集团"} and len(cleaned) <= max(len(brand or cleaned) + 2, 8):
        return not any(
            cleaned.endswith(suffix)
            for suffix in ("有限责任公司", "股份有限公司", "集团有限公司", "有限公司")
        )
    return False


def _strip_leading_city_name(body: str) -> tuple[str, str]:
    from ._registry import _ADMIN_SHORT_MAP

    for city in sorted(set(_ADMIN_SHORT_MAP.values()), key=len, reverse=True):
        if body.startswith(city) and len(body) > len(city) + 1:
            return city, body[len(city) :]
    city_match = re.match(r"^([\u4e00-\u9fa5]{2,8}(?:市|州|盟))", body)
    if city_match:
        city = city_match.group(1)
        return city, body[len(city) :]
    return "", body


def full_organization_mask_for_plan(
    value: str,
    plan: CompanyMaskPlan,
    known_locations: Mapping[str, str],
    get_location_prefix: Callable[[str], str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Build a full company mask for a longer surface that shares one brand plan."""
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
    if not legal_suffix:
        return plan.full_mask, plan.location_updates

    body = value[: -len(legal_suffix)]
    location_mask, body = strip_leading_locations(body, known_locations)
    body = strip_parenthetical_admin(body).strip("（）() ")
    location_updates: list[tuple[str, str]] = []

    if not location_mask:
        place, body = _split_leading_place_prefix(body)
        if place:
            location_mask = _place_mask(place, get_location_prefix)
            location_updates.append((place, location_mask))

    industry, _ = _industry_and_brand_from_body(body)
    return (
        f"{location_mask}{plan.brand_mask}{industry}{simple_legal_suffix(legal_suffix)}",
        tuple(location_updates),
    )


def organization_mask_for_surface(
    value: str,
    plan: CompanyMaskPlan,
    *,
    known_locations: Mapping[str, str] | None = None,
    get_location_prefix: Callable[[str], str] | None = None,
) -> str:
    cleaned = _clean_organization_text(value) or value.strip()
    if is_short_company_surface(cleaned, brand=plan.brand):
        if cleaned == plan.brand:
            return plan.brand_mask
        return organization_short_mask(plan)
    if (
        cleaned != plan.value
        and known_locations is not None
        and get_location_prefix is not None
    ):
        full_mask, _ = full_organization_mask_for_plan(
            value,
            plan,
            known_locations,
            get_location_prefix,
        )
        return full_mask
    return plan.full_mask


_SAME_COMPANY_RELATION_RE = (
    r"后更名为|更名为|变更为|改名为|原名称|原名|曾用名|原公司名称|原为|原系|现名称|现名|"
    r"以下简称|简称为|简称|下称"
)


def _company_names_explicitly_related(source_text: str, left: str, right: str) -> bool:
    if not source_text or not left or not right or left == right:
        return False
    pairs = ((left, right), (right, left))
    for first, second in pairs:
        first_escaped = re.escape(first)
        second_escaped = re.escape(second)
        if re.search(
            rf"{first_escaped}[^。！？\n]{{0,100}}(?:{_SAME_COMPANY_RELATION_RE})[^。！？\n]{{0,100}}{second_escaped}",
            source_text,
        ):
            return True
    return False


def _is_locationless_company_variant(value: str, organization: str) -> bool:
    if value == organization:
        return True
    return len(value) >= 4 and organization.endswith(value)


def find_related_company_plan(
    value: str,
    plans: Mapping[str, CompanyMaskPlan],
    alias_cores_cache: Mapping[str, frozenset[str]],
    *,
    source_text: str = "",
) -> CompanyMaskPlan | None:
    cleaned = _clean_organization_text(value) or value.strip()
    if not cleaned:
        return None
    brand_key = organization_brand_key(cleaned)
    matches: list[tuple[int, str, CompanyMaskPlan]] = []

    for organization, plan in plans.items():
        if cleaned == organization:
            matches.append((100, organization, plan))
            continue
        if cleaned in plan.aliases:
            matches.append((95, organization, plan))
            continue
        if cleaned == f"{plan.brand}公司":
            matches.append((90, organization, plan))
            continue
        if cleaned == plan.brand:
            matches.append((90, organization, plan))
            continue
        if (
            plan.brand
            and brand_key == plan.brand
            and is_short_company_surface(cleaned, brand=plan.brand)
        ):
            matches.append((85, organization, plan))
            continue
        if _is_locationless_company_variant(cleaned, organization):
            matches.append((80, organization, plan))
            continue
        if (
            source_text
            and plan.brand
            and (brand_key == plan.brand or plan.brand in cleaned)
            and _company_names_explicitly_related(source_text, organization, cleaned)
        ):
            matches.append((75, organization, plan))

    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    best_score = matches[0][0]
    best = [item for item in matches if item[0] == best_score]
    if len({item[1] for item in best}) > 1:
        return None
    return best[0][2]
