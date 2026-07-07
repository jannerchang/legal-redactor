"""Post-processing pipeline for redaction mappings.

Holds the filter/merge steps that run after candidate collection. Depends only
on lexicon / filters / models / location_utils (plus lazy imports of org_masking
and llm), so it can be reused by both the legacy and linear redaction paths and
by a future judgment layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .filters import clean_organization_text as _clean_organization_text
from .filters import _clean_unbalanced_brackets
from .lexicon import GENERIC_BRAND_BLACKLIST
from .location_utils import get_location_core
from .models import MappingEntry


@dataclass
class PostprocessConfig:
    """Selects which postprocess steps run for a given redaction path.

    The step order is fixed in apply_postprocess; these flags only toggle the
    two optional steps whose presence differs between the legacy, linear, and
    redact_many paths.
    """
    include_fragments: bool = False
    include_alias_merge: bool = False
    protected_texts: set[str] | None = None


def _span_inside_any(span: tuple[int, int], containers: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start >= c_start and end <= c_end for c_start, c_end in containers)


def _find_all_spans(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    start = text.find(needle)
    while start >= 0:
        spans.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return spans


def _filter_locations_inside_organizations(
    text: str,
    mappings: list[MappingEntry],
    protected_texts: set[str] | None = None,
) -> list[MappingEntry]:
    """Drop location mappings that only occur inside organization or rejected phrases."""
    organization_spans: list[tuple[int, int]] = []
    for mapping in mappings:
        if mapping.type not in {"organization", "individual_business"}:
            continue
        organization_spans.extend(_find_all_spans(text, mapping.original))
    if protected_texts:
        for protected in protected_texts:
            if protected and len(protected) >= 2:
                organization_spans.extend(_find_all_spans(text, protected))
    if not organization_spans:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if spans and all(_span_inside_any(span, organization_spans) for span in spans):
            continue
        filtered.append(mapping)
    return filtered


def _filter_mappings_inside_trusted_samples(text: str, mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop rule-discovered fragments that are fully covered by a trusted sample mapping."""
    trusted_spans: list[tuple[int, int, str]] = []
    for mapping in mappings:
        if not str(mapping.source or "").startswith("sample_library:"):
            continue
        if mapping.type not in {"organization", "individual_business", "location", "grassroots_org", "person", "project"}:
            continue
        for start, end in _find_all_spans(text, mapping.original):
            trusted_spans.append((start, end, mapping.original))
    if not trusted_spans:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if str(mapping.source or "").startswith("sample_library:"):
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if mapping.type in {"location", "grassroots_org"} and spans and all(
            len({
                container
                for c_start, c_end, container in trusted_spans
                if c_start >= start and c_end <= end and mapping.original != container
            })
            >= 2
            for start, end in spans
        ):
            continue
        if spans and all(
            any(start >= c_start and end <= c_end and mapping.original != container for c_start, c_end, container in trusted_spans)
            for start, end in spans
        ):
            continue
        filtered.append(mapping)
    return filtered


def _filter_noise_entity_mappings(mappings: list[MappingEntry]) -> list[MappingEntry]:
    from .llm import _is_valid_company_variant, is_noise_entity_text, is_noise_project_text

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        original = (mapping.original or "").strip()
        if not original or is_noise_entity_text(original):
            continue
        if mapping.type in {"organization", "individual_business"} and not _is_valid_company_variant(original):
            continue
        if mapping.type == "project" and is_noise_project_text(original):
            continue
        filtered.append(mapping)
    return filtered


def _filter_fragments_inside_longer_entities(text: str, mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop short model/rule fragments that only occur inside longer accepted entities."""
    container_types = {"organization", "individual_business", "project", "case_number", "person"}
    containers: list[tuple[int, int, str, str]] = []
    for mapping in mappings:
        if mapping.type not in container_types or len(mapping.original) < 3:
            continue
        for start, end in _find_all_spans(text, mapping.original):
            containers.append((start, end, mapping.original, mapping.type))
    if not containers:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if str(mapping.source or "").startswith("sample_library:"):
            filtered.append(mapping)
            continue
        if (
            mapping.type == "person"
            and len(mapping.original) <= 2
            and any(
                mapping.original in container
                and mapping.original != container
                and c_type in {"organization", "individual_business", "person"}
                for _, _, container, c_type in containers
            )
        ):
            continue
        if mapping.type == "location" and mapping.original.startswith(("（", "(")):
            continue
        if mapping.type not in {"person", "location", "grassroots_org", "organization"}:
            filtered.append(mapping)
            continue
        if len(mapping.original) > 4 and not mapping.original.startswith("（"):
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if not spans:
            filtered.append(mapping)
            continue
        if all(
            any(
                start >= c_start
                and end <= c_end
                and mapping.original != container
                and (
                    mapping.type != c_type
                    or mapping.type == "person"
                    or mapping.original.startswith("（")
                )
                for c_start, c_end, container, c_type in containers
            )
            for start, end in spans
        ):
            continue
        filtered.append(mapping)
    return filtered


def _filter_org_alias_prefixed_locations(mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop pseudo-locations formed as organization alias + an already accepted location."""
    from .org_masking import derived_organization_alias_cores as _derived_organization_alias_cores

    org_aliases: set[str] = set()
    location_originals = {
        mapping.original
        for mapping in mappings
        if mapping.type in {"location", "grassroots_org"} and len(mapping.original) >= 2
    }
    for mapping in mappings:
        if mapping.type != "organization":
            continue
        org_aliases.update(_derived_organization_alias_cores(mapping.original))

    if not org_aliases or not location_originals:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            filtered.append(mapping)
            continue
        original = mapping.original
        should_drop = False
        for alias in sorted(org_aliases, key=len, reverse=True):
            if not original.startswith(alias) or len(original) <= len(alias):
                continue
            suffix = original[len(alias):]
            if suffix in location_originals:
                should_drop = True
                break
        if not should_drop:
            filtered.append(mapping)
    return filtered


def _strip_organization_legal_suffix(value: str, legal_suffixes: tuple[str, ...]) -> tuple[str, str]:
    for suffix in sorted(legal_suffixes, key=len, reverse=True):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)], suffix
    return value, ""


def _strip_organization_place_prefix(value: str, place_prefixes: set[str]) -> str:
    body = value
    for _ in range(3):
        stripped = False
        for prefix in sorted(place_prefixes, key=len, reverse=True):
            if body.startswith(prefix) and len(body) >= len(prefix) + 2:
                body = body[len(prefix) :]
                stripped = True
                break
        if not stripped:
            break
    return body


def _strip_organization_industry_suffix(value: str, industry_terms: tuple[str, ...]) -> str:
    body = value
    for term in sorted((*industry_terms, "建设", "工程", "电力", "能源"), key=len, reverse=True):
        if body.endswith(term) and len(body) >= len(term) + 2:
            return body[: -len(term)]
    return body


def _organization_number_aliases(value: str) -> set[str]:
    aliases: set[str] = set()
    cn_digits = {
        "1": "一",
        "2": "二",
        "3": "三",
        "4": "四",
        "5": "五",
        "6": "六",
        "7": "七",
        "8": "八",
        "9": "九",
        "10": "十",
    }
    for match in re.finditer(r"电建(?P<num>[一二三四五六七八九十]|\d{1,2})", value):
        num = cn_digits.get(match.group("num"), match.group("num"))
        aliases.add(f"{num}建")
    for match in re.finditer(r"第(?P<num>[一二三四五六七八九十]|\d{1,2})工程", value):
        num = cn_digits.get(match.group("num"), match.group("num"))
        aliases.add(f"{num}建")
    return aliases


def _usable_organization_alias_key(value: str, place_prefixes: set[str]) -> bool:
    if len(value) < 2 or len(value) > 16:
        return False
    if value in place_prefixes or value in GENERIC_BRAND_BLACKLIST:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9·]+", value):
        return False
    return True


def _organization_alias_profile(
    mapping: MappingEntry,
    place_prefixes: set[str],
) -> dict[str, set[str] | str]:
    from .lexicon import INDUSTRY_TERMS, LEGAL_SUFFIXES
    from .org_masking import derived_organization_alias_cores as _derived_organization_alias_cores

    cleaned = _clean_organization_text(mapping.original) or mapping.original.strip()
    cleaned = re.sub(r"\s+", "", cleaned.strip(" ：:，,。；;、\n\t"))
    cleaned = re.sub(r"[（(][^）)]{0,20}[）)]", "", cleaned)
    body, legal_suffix = _strip_organization_legal_suffix(cleaned, LEGAL_SUFFIXES)
    body = body.strip("（）() ")
    body_without_place = _strip_organization_place_prefix(body, place_prefixes)

    raw_cores = {body, body_without_place}
    raw_cores.update(_derived_organization_alias_cores(cleaned))

    tokens: set[str] = set()
    exact_alias_keys: set[str] = set()
    for core in raw_cores:
        core = re.sub(r"\s+", "", core.strip(" ：:，,。；;、（）()"))
        if not core:
            continue
        variants = {
            core,
            _strip_organization_place_prefix(core, place_prefixes),
        }
        for variant in list(variants):
            variants.add(_strip_organization_industry_suffix(variant, INDUSTRY_TERMS))
            variants.update(_organization_number_aliases(variant))
        for token in variants:
            token = token.strip(" ：:，,。；;、（）()")
            if _usable_organization_alias_key(token, place_prefixes):
                tokens.add(token)

    compact_body = _strip_organization_industry_suffix(body_without_place, INDUSTRY_TERMS)
    from .org_masking import organization_brand_key as _organization_brand_key

    brand_key = _organization_brand_key(cleaned)
    alias_candidates = {body_without_place, *_organization_number_aliases(body_without_place)}
    if compact_body == brand_key:
        alias_candidates.add(compact_body)
    if _usable_organization_alias_key(brand_key, place_prefixes) and 2 <= len(brand_key) <= 4:
        alias_candidates.add(brand_key)
    party_alias_candidates: set[str] = set()
    if _mapping_has_party_anchor(mapping):
        for core in raw_cores:
            core = re.sub(r"\s+", "", str(core).strip(" ：:，,。；;、（）()"))
            if _usable_organization_alias_key(core, place_prefixes) and 2 <= len(core) <= 4:
                party_alias_candidates.add(core)
                alias_candidates.add(core)

    for alias_key in alias_candidates:
        alias_key = alias_key.strip(" ：:，,。；;、（）()")
        if (
            _usable_organization_alias_key(alias_key, place_prefixes)
            and len(alias_key) <= 4
            and (
                alias_key == body_without_place
                or alias_key == brand_key
                or alias_key in party_alias_candidates
                or legal_suffix in {"公司", "集团", ""}
                or cleaned.endswith((f"{alias_key}公司", f"{alias_key}集团"))
            )
        ):
            exact_alias_keys.add(alias_key)

    return {
        "cleaned": cleaned,
        "tokens": tokens,
        "exact_alias_keys": exact_alias_keys,
    }


_ORG_MERGE_BRAND_MASK_RE = re.compile(
    r"^(?:(?P<loc>[\u4e00-\u9fa5]{1,8}省))?(?P<brand>[甲乙丙丁戊己庚辛壬癸])(?P<rest>.+?)(?P<suffix>公司|集团)$"
)


def _short_company_mask_from_full_masked(masked: str) -> str | None:
    match = _ORG_MERGE_BRAND_MASK_RE.fullmatch(masked.strip())
    if match:
        return f"{match.group('brand')}{match.group('suffix')}"
    if masked.endswith(("公司", "集团")) and len(masked) <= 4:
        return masked
    return None


def _full_company_mask_parts(masked: str) -> tuple[str, str, str] | None:
    match = _ORG_MERGE_BRAND_MASK_RE.fullmatch(masked.strip())
    if not match or not match.group("loc"):
        return None
    return match.group("brand"), match.group("rest"), match.group("suffix")


def _organization_location_anchor(original: str, place_prefixes: set[str]) -> str:
    from .lexicon import LEGAL_SUFFIXES
    from .org_masking import _split_leading_place_prefix

    cleaned = _clean_organization_text(original) or original.strip()
    cleaned = re.sub(r"\s+", "", cleaned.strip(" ：:，,。；;、\n\t"))
    legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if cleaned.endswith(suffix)), "")
    body = cleaned[: -len(legal_suffix)] if legal_suffix else cleaned
    place, _ = _split_leading_place_prefix(body)
    if place and (place in place_prefixes or f"{place}省" in place_prefixes):
        return place
    for place in sorted(place_prefixes, key=len, reverse=True):
        if cleaned.startswith(place) and len(cleaned) > len(place) + 1:
            return place
    return ""


def _mapping_has_party_anchor(mapping: MappingEntry) -> bool:
    source = str(mapping.source or "")
    return "party_section" in source or bool(mapping.role)


def _organization_profiles_same_subject(
    left_profile: dict,
    right_profile: dict,
    *,
    left_mapping: MappingEntry,
    right_mapping: MappingEntry,
    place_prefixes: set[str],
) -> bool:
    left_keys = left_profile.get("exact_alias_keys", set())
    right_keys = right_profile.get("exact_alias_keys", set())
    if not isinstance(left_keys, set) or not isinstance(right_keys, set):
        return False
    shared_keys = left_keys & right_keys
    if not shared_keys:
        return False

    left_anchor = _organization_location_anchor(left_mapping.original, place_prefixes)
    right_anchor = _organization_location_anchor(right_mapping.original, place_prefixes)
    if left_anchor and right_anchor and left_anchor != right_anchor:
        return False
    if left_anchor != right_anchor and not (
        _mapping_has_party_anchor(left_mapping) or _mapping_has_party_anchor(right_mapping)
    ):
        return False
    return True


def _merged_organization_mask(mapping: MappingEntry, anchor: MappingEntry) -> str:
    from .org_masking import is_short_company_surface, organization_brand_key

    brand = organization_brand_key(anchor.original)
    is_short_surface = is_short_company_surface(mapping.original, brand=brand) or (
        mapping.original.endswith(("公司", "集团"))
        and not mapping.original.endswith(("有限责任公司", "股份有限公司", "集团有限公司", "有限公司"))
        and len(mapping.original) <= 8
    )
    if is_short_surface:
        short_mask = _short_company_mask_from_full_masked(anchor.masked)
        if short_mask:
            return short_mask
        if anchor.masked.endswith(("公司", "集团")) and len(anchor.masked) <= 4:
            return anchor.masked
    own_short_mask = _short_company_mask_from_full_masked(mapping.masked)
    anchor_short_mask = _short_company_mask_from_full_masked(anchor.masked)
    own_full_parts = _full_company_mask_parts(mapping.masked)
    anchor_full_parts = _full_company_mask_parts(anchor.masked)
    if (
        own_short_mask
        and anchor_short_mask
        and own_short_mask == anchor_short_mask
        and own_full_parts is not None
        and anchor_full_parts is not None
        and own_full_parts == anchor_full_parts
    ):
        return mapping.masked
    return anchor.masked


def _organization_canonical_score(mapping: MappingEntry) -> tuple[int, int, str]:
    source = str(mapping.source or "")
    original = mapping.original or ""
    masked = mapping.masked or ""
    score = 0
    if source.startswith("sample_library:"):
        score += 9000
    if mapping.role:
        score += 7000
    if "party_section" in source:
        score += 5000
    if original.endswith(("有限责任公司", "股份有限公司", "集团有限公司", "有限公司")):
        score += 1500
    elif original.endswith(("公司", "集团")):
        score += 500
    if masked.endswith("机构"):
        score -= 800
    if masked.endswith(("公司", "集团")):
        score += 100
    score += min(len(original), 80)
    return score, len(original), original


def _merge_organization_alias_mappings(mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Make same-subject organization variants share one mask inside a batch map."""
    from .lexicon import PROVINCE_NAMES

    org_indices = [index for index, mapping in enumerate(mappings) if mapping.type == "organization"]
    if len(org_indices) < 2:
        return mappings

    place_prefixes: set[str] = set()
    for province in PROVINCE_NAMES:
        place_prefixes.add(province)
        place_prefixes.add(f"{province}省")
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            continue
        original = _clean_unbalanced_brackets(mapping.original.strip(" ：:，,。；;、\n\t"))
        if 2 <= len(original) <= 10:
            place_prefixes.add(original)
        core = get_location_core(original)
        if 2 <= len(core) <= 8:
            place_prefixes.add(core)

    profiles = {
        index: _organization_alias_profile(mappings[index], place_prefixes)
        for index in org_indices
    }
    parent = {index: index for index in org_indices}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_index: dict[str, list[int]] = {}
    for index, profile in profiles.items():
        exact_keys = profile.get("exact_alias_keys", set())
        if not isinstance(exact_keys, set):
            continue
        for token in exact_keys:
            if isinstance(token, str) and token:
                token_index.setdefault(token, []).append(index)

    for indices in token_index.values():
        if len(indices) < 2:
            continue
        first = indices[0]
        for index in indices[1:]:
            if _organization_profiles_same_subject(
                profiles[first],
                profiles[index],
                left_mapping=mappings[first],
                right_mapping=mappings[index],
                place_prefixes=place_prefixes,
            ):
                union(first, index)

    for position, left in enumerate(org_indices):
        for right in org_indices[position + 1 :]:
            if _organization_profiles_same_subject(
                profiles[left],
                profiles[right],
                left_mapping=mappings[left],
                right_mapping=mappings[right],
                place_prefixes=place_prefixes,
            ):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in org_indices:
        groups.setdefault(find(index), []).append(index)

    canonical_mask_by_index: dict[int, str] = {}
    for indices in groups.values():
        if len(indices) < 2:
            continue
        masks = {mappings[index].masked for index in indices}
        if len(masks) < 2:
            continue
        canonical = max((mappings[index] for index in indices), key=_organization_canonical_score)
        for index in indices:
            merged_mask = _merged_organization_mask(mappings[index], canonical)
            if mappings[index].original != canonical.original or merged_mask != mappings[index].masked:
                canonical_mask_by_index[index] = merged_mask

    if not canonical_mask_by_index:
        return mappings

    merged: list[MappingEntry] = []
    for index, mapping in enumerate(mappings):
        canonical_mask = canonical_mask_by_index.get(index)
        if canonical_mask and mapping.masked != canonical_mask:
            merged.append(replace(mapping, masked=canonical_mask))
        else:
            merged.append(mapping)
    return merged

def apply_postprocess(
    text: str,
    mappings: list[MappingEntry],
    config: PostprocessConfig,
) -> list[MappingEntry]:
    """Run the fixed postprocess chain over collected mappings.

    Step order is load-bearing and mirrors the per-path sequences previously
    inlined in pipeline.py. Callers express path differences via config flags
    rather than by reordering calls.
    """
    mappings = _filter_mappings_inside_trusted_samples(text, mappings)
    mappings = _filter_locations_inside_organizations(text, mappings, config.protected_texts)
    mappings = _filter_org_alias_prefixed_locations(mappings)
    if config.include_fragments:
        mappings = _filter_fragments_inside_longer_entities(text, mappings)
    mappings = _filter_noise_entity_mappings(mappings)
    if config.include_alias_merge:
        mappings = _merge_organization_alias_mappings(mappings)
    return mappings
