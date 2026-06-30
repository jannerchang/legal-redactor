"""Organization parsing, alias derivation, and masking helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .detectors import _clean_organization_text, _is_false_org
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


def explicit_organization_aliases(text: str, organization: str) -> list[str]:
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


def mask_institution(value: str, known_locations: dict[str, str]) -> str | None:
    masked = value
    for location in sorted(known_locations, key=len, reverse=True):
        masked = masked.replace(location, known_locations[location])
    if masked == value:
        return None
    return masked


def build_company_mask_plan(
    *,
    value: str,
    source_text: str,
    known_locations: dict[str, str],
    get_location_prefix: Callable[[str], str],
    next_brand_mask: Callable[[], str],
) -> CompanyMaskPlan | None:
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
    if not legal_suffix:
        return None

    body = value[: -len(legal_suffix)]
    location_mask, body = strip_leading_locations(body, known_locations)
    body = strip_parenthetical_admin(body).strip("（）() ")
    location_updates: list[tuple[str, str]] = []

    if not location_mask:
        province = next(
            (name for name in PROVINCE_NAMES if body.startswith(name) and len(body) > len(name) + 1),
            "",
        )
        if province:
            location_prefix = get_location_prefix(province)
            location_mask = f"{location_prefix}省"
            location_updates.append((province, location_mask))
            body = body[len(province) :]

    industry = next((term for term in INDUSTRY_TERMS_BY_LEN if body.endswith(term)), "")
    brand = body[: -len(industry)] if industry else body
    brand = brand.strip("（）() ")
    if len(brand) < 2 or (legal_suffix in {"公司", "集团"} and _is_false_org(f"{brand}公司")):
        return None

    brand_mask = next_brand_mask()
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