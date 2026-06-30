"""Shared location parsing helpers for linear redaction and pipeline post-processing."""

from __future__ import annotations

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


def is_compound_admin_path(value: str) -> bool:
    return any(marker in value for marker in ("省", "自治区", "特别行政区"))


def get_location_core(name: str) -> str:
    """Recursively strip administrative suffixes, keeping at least two core characters."""
    if name.endswith("小镇"):
        return name
    core = name
    while True:
        stripped = False
        for suffix in ADMIN_SUFFIXES:
            if core.endswith(suffix) and len(core) > len(suffix):
                if len(core) - len(suffix) >= 2:
                    core = core[: -len(suffix)]
                    stripped = True
                    break
        if not stripped:
            break
    return core


def location_suffix(value: str) -> str:
    for suffix in ADMIN_SUFFIXES:
        if value.endswith(suffix):
            return suffix
    return "地"


def strip_leading_locations(value: str, known_locations: dict[str, str]) -> tuple[str, str]:
    """Strip one or more known location prefixes from the start of an organization body."""
    prefix = ""
    remaining = value
    changed = True
    while changed and remaining:
        changed = False
        for location in sorted(known_locations, key=len, reverse=True):
            if remaining.startswith(location) and len(remaining) > len(location):
                prefix += known_locations[location]
                remaining = remaining[len(location) :]
                changed = True
                break
    return prefix, remaining


def mask_admin_cascade_path(text: str, get_loc_prefix) -> str:
    """Cascade-mask a single administrative path from province down to village."""
    pattern = __import__("re").compile(
        r"^(?:(?P<prov>[\u4e00-\u9fa5]+?(?:省|自治区|特别行政区)))?"
        r"(?:(?P<city>[\u4e00-\u9fa5]+?(?:市|自治州|地区|盟)))?"
        r"(?:(?P<county>[\u4e00-\u9fa5]+?(?:(?<!社)区|县|旗|市)))?"
        r"(?:(?P<town>[\u4e00-\u9fa5]+?(?:街道|镇|乡)))?"
        r"(?:(?P<village>[\u4e00-\u9fa5]+?(?:居民委员会|居委会|村民委员会|村委会|社区|村)))?$"
    )
    match = pattern.match(text)
    if not match:
        return text
    parts: list[str] = []
    if match.group("prov"):
        piece = match.group("prov")
        prefix = get_loc_prefix(piece)
        parts.append(f"{prefix}省" if piece.endswith("省") else f"{prefix}自治区" if piece.endswith("自治区") else f"{prefix}特别行政区")
    if match.group("city"):
        piece = match.group("city")
        prefix = get_loc_prefix(piece)
        if piece.endswith("市"):
            parts.append(f"{prefix}市")
        elif piece.endswith("自治州"):
            parts.append(f"{prefix}自治州")
        else:
            parts.append(f"{prefix}盟")
    if match.group("county"):
        piece = match.group("county")
        prefix = get_loc_prefix(piece)
        parts.append(f"{prefix}{piece[-1]}")
    if match.group("town"):
        piece = match.group("town")
        prefix = get_loc_prefix(piece)
        if piece.endswith("街道"):
            parts.append(f"{prefix}街道")
        elif piece.endswith("镇"):
            parts.append(f"{prefix}镇")
        else:
            parts.append(f"{prefix}乡")
    if match.group("village"):
        piece = match.group("village")
        prefix = get_loc_prefix(piece)
        if piece.endswith("居民委员会"):
            parts.append(f"{prefix}社区居民委员会")
        elif piece.endswith("居委会"):
            parts.append(f"{prefix}社区居委会")
        elif piece.endswith("村民委员会"):
            parts.append(f"{prefix}村民委员会")
        elif piece.endswith("村委会"):
            parts.append(f"{prefix}村委会")
        elif piece.endswith("社区"):
            parts.append(f"{prefix}社区")
        else:
            parts.append(f"{prefix}村")
    return "".join(parts) if parts else text