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