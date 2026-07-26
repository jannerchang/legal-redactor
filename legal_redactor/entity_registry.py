from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
from typing import Any, Iterable

from .models import Candidate

_ALLOWED_ENTITY_TYPES = frozenset({"person", "organization", "location"})
_MAX_PAYLOAD_CHARS = 1_000_000
_MAX_ENTITY_TEXT_CHARS = 240
_MAX_EVIDENCE_CHARS = 160
_MAX_ENTITY_COUNT = 2_000
_MAX_NAMES_PER_ENTITY = 16
_DEFAULT_ENTITY_CONFIDENCE = 0.9



@dataclass(frozen=True)
class RegistryEntity:
    entity_id: str
    entity_type: str
    primary_text: str
    variants: tuple[str, ...] = ()
    confidence: float = _DEFAULT_ENTITY_CONFIDENCE
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class DoNotMergePair:
    left_id: str
    right_id: str

    def normalized(self) -> tuple[str, str]:
        return tuple(sorted((self.left_id, self.right_id)))  # type: ignore[return-value]


_COURT_PERSONNEL_PREFIXES = (
    "审判长",
    "审判员",
    "代理审判员",
    "人民陪审员",
    "法官助理",
    "书记员",
    "执行员",
    "执行法官",
)
_ALLOWED_LOCATION_SUFFIXES = ("省", "市", "区", "县", "旗", "自治区", "特别行政区", "自治州")


@dataclass(frozen=True)
class UncertainEntity:
    text: str
    possible_type: str | None = None
    possible_entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FullDocumentEntityRegistry:
    entities: tuple[RegistryEntity, ...] = ()
    do_not_merge: tuple[DoNotMergePair, ...] = ()
    uncertain: tuple[UncertainEntity, ...] = ()

    def entity_by_id(self) -> dict[str, RegistryEntity]:
        return {entity.entity_id: entity for entity in self.entities}

    def blocked_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(pair.normalized() for pair in self.do_not_merge)


@dataclass(frozen=True)
class RegistryConflict:
    entity_type: str
    text: str
    entity_ids: tuple[str, ...]
    reason: str = "duplicate_claim"


@dataclass(frozen=True)
class RegistryValidationResult:
    registry: FullDocumentEntityRegistry = field(default_factory=FullDocumentEntityRegistry)
    warnings: tuple[str, ...] = ()
    conflicts: tuple[RegistryConflict, ...] = ()
    error: str | None = None
    dropped_variant_count: int = 0
    dropped_evidence_count: int = 0

    @property
    def valid(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RegistryMaterialization:
    candidates: tuple[Candidate, ...] = ()
    review_candidates: tuple[Candidate, ...] = ()
    conflicts: tuple[RegistryConflict, ...] = ()
    registry: FullDocumentEntityRegistry = field(default_factory=FullDocumentEntityRegistry)

    @property
    def constraints(self) -> FullDocumentEntityRegistry:
        return self.registry



def parse_full_document_registry(payload: object) -> RegistryValidationResult:
    """Parse model output into a bounded registry without trusting its contents."""
    try:
        data = _payload_object(payload)
        registry = _normalize_registry(data)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return RegistryValidationResult(error=_safe_error_kind(exc))
    return RegistryValidationResult(registry=registry)


def merge_full_document_registries(
    text: str,
    primary: RegistryValidationResult,
    supplement: RegistryValidationResult,
) -> RegistryValidationResult:
    """Union two validated passes while preserving the first pass identity groups."""
    if not primary.valid:
        return primary
    if not supplement.valid:
        return supplement

    primary_entities = list(primary.registry.entities)
    type_by_variant = {
        value: entity.entity_type
        for entity in primary_entities
        for value in entity.variants
    }
    id_map: dict[str, str] = {}
    used_ids = {entity.entity_id for entity in primary_entities}
    next_index: dict[str, int] = {}
    for entity in primary_entities:
        prefix = _entity_id_prefix(entity.entity_type)
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", entity.entity_id)
        if match:
            next_index[prefix] = max(next_index.get(prefix, 0), int(match.group(1)))

    for entity in supplement.registry.entities:
        overlaps = [
            existing
            for existing in primary_entities
            if existing.entity_type == entity.entity_type
            and set(existing.variants) & set(entity.variants)
        ]
        if overlaps:
            target = overlaps[0]
            merged_variants = tuple(
                dict.fromkeys(
                    (
                        *target.variants,
                        *(
                            value
                            for value in entity.variants
                            if type_by_variant.get(value, entity.entity_type) == entity.entity_type
                        ),
                    )
                )
            )[:_MAX_NAMES_PER_ENTITY]
            merged_evidence = tuple(dict.fromkeys((*target.evidence, *entity.evidence)))
            updated = replace(
                target,
                primary_text=max(merged_variants, key=len),
                variants=merged_variants,
                confidence=max(target.confidence, entity.confidence),
                evidence=merged_evidence,
            )
            primary_entities[primary_entities.index(target)] = updated
            id_map[entity.entity_id] = target.entity_id
            for value in merged_variants:
                type_by_variant[value] = entity.entity_type
            continue

        variants = tuple(value for value in entity.variants if value not in type_by_variant)
        if not variants:
            continue
        prefix = _entity_id_prefix(entity.entity_type)
        next_index[prefix] = next_index.get(prefix, 0) + 1
        entity_id = f"{prefix}-{next_index[prefix]}"
        while entity_id in used_ids:
            next_index[prefix] += 1
            entity_id = f"{prefix}-{next_index[prefix]}"
        used_ids.add(entity_id)
        id_map[entity.entity_id] = entity_id
        added = replace(
            entity,
            entity_id=entity_id,
            primary_text=max(variants, key=len),
            variants=variants,
        )
        primary_entities.append(added)
        for value in variants:
            type_by_variant[value] = entity.entity_type

    primary_by_variant = {
        value: entity.entity_id
        for entity in primary_entities
        for value in entity.variants
    }
    for entity in supplement.registry.entities:
        id_map.setdefault(
            entity.entity_id,
            next(
                (
                    primary_by_variant[value]
                    for value in entity.variants
                    if value in primary_by_variant
                ),
                "",
            ),
        )

    merged_pairs = list(primary.registry.do_not_merge)
    seen_pairs = {pair.normalized() for pair in merged_pairs}
    for pair in supplement.registry.do_not_merge:
        left_id = id_map.get(pair.left_id)
        right_id = id_map.get(pair.right_id)
        if not left_id or not right_id or left_id == right_id:
            continue
        merged_pair = DoNotMergePair(left_id, right_id)
        if merged_pair.normalized() not in seen_pairs:
            seen_pairs.add(merged_pair.normalized())
            merged_pairs.append(merged_pair)

    merged_uncertain = [*primary.registry.uncertain]
    for uncertain in supplement.registry.uncertain:
        mapped_ids = tuple(
            dict.fromkeys(
                id_map[entity_id]
                for entity_id in uncertain.possible_entity_ids
                if entity_id in id_map
            )
        )
        merged_uncertain.append(replace(uncertain, possible_entity_ids=mapped_ids))

    merged = RegistryValidationResult(
        registry=FullDocumentEntityRegistry(
            entities=tuple(primary_entities),
            do_not_merge=tuple(merged_pairs),
            uncertain=tuple(_dedupe_uncertain(merged_uncertain)),
        ),
        warnings=tuple(dict.fromkeys((*primary.warnings, *supplement.warnings))),
    )
    return validate_registry_against_text(text, merged)


def _entity_id_prefix(entity_type: str) -> str:
    return "org" if entity_type == "organization" else entity_type


_PERSON_IDENTITY_MARKERS = (
    "又名",
    "别名",
    "原名",
    "曾用名",
    "化名",
    "本名",
    "真实姓名",
    "系同一人",
    "为同一人",
    "是同一人",
    "同一自然人",
)
_IDENTITY_CONTEXT_BREAKS = "。！？；;\n"


def _split_unverified_person_identity_groups(
    text: str,
    registry: FullDocumentEntityRegistry,
) -> tuple[FullDocumentEntityRegistry, int]:
    entities: list[RegistryEntity] = []
    do_not_merge = list(registry.do_not_merge)
    blocked_pairs = {pair.normalized() for pair in do_not_merge}
    used_ids = {entity.entity_id for entity in registry.entities}
    next_index = max(
        (
            int(match.group(1))
            for entity in registry.entities
            if (match := re.fullmatch(r"person-(\d+)", entity.entity_id))
        ),
        default=0,
    )
    split_count = 0

    for entity in registry.entities:
        if entity.entity_type != "person" or len(entity.variants) < 2:
            entities.append(entity)
            continue
        verified_groups: list[list[str]] = []
        for variant in entity.variants:
            target = next(
                (
                    group
                    for group in verified_groups
                    if any(_has_explicit_person_identity_evidence(text, variant, known) for known in group)
                ),
                None,
            )
            if target is None:
                verified_groups.append([variant])
            else:
                target.append(variant)
        if len(verified_groups) == 1:
            entities.append(entity)
            continue

        split_count += len(verified_groups) - 1
        split_entities: list[RegistryEntity] = []
        for group_index, group in enumerate(verified_groups):
            if group_index == 0:
                entity_id = entity.entity_id
            else:
                next_index += 1
                entity_id = f"person-{next_index}"
                while entity_id in used_ids:
                    next_index += 1
                    entity_id = f"person-{next_index}"
                used_ids.add(entity_id)
            split_entity = replace(
                entity,
                entity_id=entity_id,
                primary_text=max(group, key=len),
                variants=tuple(group),
            )
            split_entities.append(split_entity)
            entities.append(split_entity)
        for left_index, left in enumerate(split_entities):
            for right in split_entities[left_index + 1 :]:
                pair = DoNotMergePair(left.entity_id, right.entity_id)
                if pair.normalized() not in blocked_pairs:
                    blocked_pairs.add(pair.normalized())
                    do_not_merge.append(pair)

    return (
        FullDocumentEntityRegistry(
            entities=tuple(entities),
            do_not_merge=tuple(do_not_merge),
            uncertain=registry.uncertain,
        ),
        split_count,
    )


def _has_explicit_person_identity_evidence(text: str, left: str, right: str) -> bool:
    if left == right:
        return True
    for left_match in re.finditer(re.escape(left), text):
        for right_match in re.finditer(re.escape(right), text):
            start = min(left_match.start(), right_match.start())
            end = max(left_match.end(), right_match.end())
            if end - start > 48:
                continue
            context = text[start:end]
            if any(break_char in context for break_char in _IDENTITY_CONTEXT_BREAKS):
                continue
            if any(marker in context for marker in _PERSON_IDENTITY_MARKERS):
                return True
    return False


def validate_registry_against_text(
    text: str,
    registry_or_result: FullDocumentEntityRegistry | RegistryValidationResult,
) -> RegistryValidationResult:
    """Keep only exact document strings and turn ambiguous claims into review conflicts."""
    if isinstance(registry_or_result, RegistryValidationResult):
        if not registry_or_result.valid:
            return registry_or_result
        registry = registry_or_result.registry
        inherited_warnings = list(registry_or_result.warnings)
    else:
        registry = registry_or_result
        inherited_warnings = []
    registry, split_person_identity_count = _split_unverified_person_identity_groups(text, registry)
    if split_person_identity_count:
        inherited_warnings.append(f"registry_person_identity_splits:{split_person_identity_count}")

    entity_ids = {entity.entity_id for entity in registry.entities}
    for pair in registry.do_not_merge:
        if pair.left_id not in entity_ids or pair.right_id not in entity_ids or pair.left_id == pair.right_id:
            return RegistryValidationResult(
                registry=FullDocumentEntityRegistry(),
                warnings=tuple(inherited_warnings),
                error="invalid_do_not_merge_reference",
            )
    for uncertain in registry.uncertain:
        if any(entity_id not in entity_ids for entity_id in uncertain.possible_entity_ids):
            return RegistryValidationResult(
                registry=FullDocumentEntityRegistry(),
                warnings=tuple(inherited_warnings),
                error="invalid_uncertain_reference",
            )


    dropped_variants = 0
    dropped_evidence = 0
    validated_entities: list[RegistryEntity] = []
    claims: dict[tuple[str, str], list[str]] = {}
    for entity in registry.entities:
        variants: list[str] = []
        for value in entity.variants:
            if value not in text:
                dropped_variants += 1
                continue
            if value not in variants:
                variants.append(value)
                claims.setdefault((entity.entity_type, value), []).append(entity.entity_id)
        if not variants:
            continue
        primary_text = entity.primary_text if entity.primary_text in variants else variants[0]
        evidence: list[str] = []
        for value in entity.evidence:
            if len(value) > _MAX_EVIDENCE_CHARS or value not in text:
                dropped_evidence += 1
                continue
            if value not in evidence:
                evidence.append(value)
        validated_entities.append(
            RegistryEntity(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                primary_text=primary_text,
                variants=tuple(variants),
                confidence=entity.confidence,
                evidence=tuple(evidence),
            )
        )

    conflicts: list[RegistryConflict] = []
    conflict_keys = {key for key, ids in claims.items() if len(set(ids)) > 1}
    text_claims: dict[str, list[tuple[str, str]]] = {}
    for (entity_type, value), ids in claims.items():
        text_claims.setdefault(value, []).extend((entity_type, entity_id) for entity_id in ids)
    for value, typed_ids in text_claims.items():
        if len({entity_id for _, entity_id in typed_ids}) <= 1:
            continue
        for entity_type, _entity_id in typed_ids:
            conflict_keys.add((entity_type, value))
    if conflict_keys:
        for entity_type, value in sorted(conflict_keys):
            entity_ids = tuple(
                dict.fromkeys(
                    entity_id
                    for claimed_type, entity_id in text_claims[value]
                    if claimed_type == entity_type or len({item[0] for item in text_claims[value]}) > 1
                )
            )
            conflicts.append(
                RegistryConflict(
                    entity_type=entity_type,
                    text=value,
                    entity_ids=entity_ids,
                )
            )
        validated_entities = [
            RegistryEntity(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                primary_text=entity.primary_text,
                variants=tuple(
                    value
                    for value in entity.variants
                    if (entity.entity_type, value) not in conflict_keys
                ),
                confidence=entity.confidence,
                evidence=entity.evidence,
            )
            for entity in validated_entities
        ]

    warnings = inherited_warnings
    if dropped_variants:
        warnings.append(f"registry_variants_missing:{dropped_variants}")
    if dropped_evidence:
        warnings.append(f"registry_evidence_dropped:{dropped_evidence}")
    if conflicts:
        warnings.append(f"registry_conflicts:{len(conflicts)}")

    uncertain = list(registry.uncertain)
    for conflict in conflicts:
        uncertain.append(
            UncertainEntity(
                text=conflict.text,
                possible_type=conflict.entity_type,
                possible_entity_ids=conflict.entity_ids,
            )
        )
    retained_ids = {entity.entity_id for entity in validated_entities if entity.variants}
    retained_pairs = tuple(
        pair
        for pair in registry.do_not_merge
        if pair.left_id in retained_ids and pair.right_id in retained_ids
    )
    retained_uncertain = tuple(
        replace(
            uncertain,
            possible_entity_ids=tuple(
                entity_id for entity_id in uncertain.possible_entity_ids if entity_id in retained_ids
            ),
        )
        for uncertain in _dedupe_uncertain(uncertain)
    )
    return RegistryValidationResult(
        registry=FullDocumentEntityRegistry(
            entities=tuple(entity for entity in validated_entities if entity.variants),
            do_not_merge=retained_pairs,
            uncertain=retained_uncertain,
        ),
        warnings=tuple(warnings),
        conflicts=tuple(conflicts),
        dropped_variant_count=dropped_variants,
        dropped_evidence_count=dropped_evidence,
    )


def materialize_registry_candidates(
    text: str,
    validation: RegistryValidationResult,
) -> RegistryMaterialization:
    """Locate every exact occurrence; model offsets are never accepted."""
    if not validation.valid:
        return RegistryMaterialization()
    conflict_keys = {
        (conflict.entity_type, conflict.text)
        for conflict in validation.conflicts
    }
    candidates: list[Candidate] = []
    review_candidates: list[Candidate] = []
    for entity in validation.registry.entities:
        for value in entity.variants:
            if (entity.entity_type, value) in conflict_keys:
                continue
            if not _registry_variant_allowed(entity.entity_type, value, text):
                continue
            variant_kind = "primary" if value == entity.primary_text else "variant"
            for match in re.finditer(re.escape(value), text):
                candidate = Candidate(
                    type=entity.entity_type,
                    text=value,
                    start=match.start(),
                    end=match.end(),
                    source="full_document_llm",
                    confidence=entity.confidence,
                    risk_level="medium",
                    auto_redact=True,
                    metadata={
                        "registry_entity_id": entity.entity_id,
                        "registry_primary_text": entity.primary_text,
                        "registry_confidence": entity.confidence,
                        "registry_do_not_merge": list(
                            _blocked_entity_ids(validation.registry, entity.entity_id)
                        ),
                        "registry_variant_kind": variant_kind,
                        "provenance_sources": ["full_document_llm"],
                    },
                )
                candidates.append(candidate)


    for uncertain in validation.registry.uncertain:
        if uncertain.possible_type not in _ALLOWED_ENTITY_TYPES or uncertain.text not in text:
            continue
        for match in re.finditer(re.escape(uncertain.text), text):
            review_candidates.append(
                Candidate(
                    type=uncertain.possible_type,
                    text=uncertain.text,
                    start=match.start(),
                    end=match.end(),
                    source="full_document_llm_uncertain",
                    confidence=0.0,
                    risk_level="medium",
                    auto_redact=False,
                    needs_review=True,
                    reason="registry_uncertain",
                    metadata={
                        "registry_possible_entity_ids": list(uncertain.possible_entity_ids),
                    },
                )
            )
    return RegistryMaterialization(
        candidates=tuple(candidates),
        review_candidates=tuple(review_candidates),
        conflicts=validation.conflicts,
        registry=validation.registry,
    )

def _blocked_entity_ids(
    registry: FullDocumentEntityRegistry,
    entity_id: str,
) -> tuple[str, ...]:
    blocked: list[str] = []
    for pair in registry.do_not_merge:
        if pair.left_id == entity_id:
            blocked.append(pair.right_id)
        elif pair.right_id == entity_id:
            blocked.append(pair.left_id)
    return tuple(dict.fromkeys(blocked))



def _registry_variant_allowed(entity_type: str, value: str, text: str) -> bool:
    if entity_type == "location":
        return value.endswith(_ALLOWED_LOCATION_SUFFIXES)
    if entity_type != "person":
        return True
    if value.endswith(("经理", "主任", "书记", "法官", "律师", "先生", "女士")):
        return False
    for match in re.finditer(re.escape(value), text):
        line_start = max(text.rfind("\n", 0, match.start()) + 1, text.rfind("。", 0, match.start()) + 1)
        prefix = text[line_start:match.start()].strip(" ：:")
        if not prefix.endswith(_COURT_PERSONNEL_PREFIXES):
            return True
    return False


def _payload_object(payload: object) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        raise TypeError("payload_type")
    if len(payload) > _MAX_PAYLOAD_CHARS:
        raise ValueError("payload_too_large")
    value = payload.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, count=1, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value, count=1)
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("invalid registry JSON", value, 0)
    parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("payload_structure")
    return parsed


def _normalize_registry(data: dict[str, Any]) -> FullDocumentEntityRegistry:
    minimal_fields = {"persons", "organizations", "locations", "same_entities"}
    if set(data) & minimal_fields or not data:
        minimal_data = {key: data.get(key, []) for key in minimal_fields}
        return _normalize_minimal_registry(minimal_data)
    return _normalize_detailed_registry(data)


def _normalize_minimal_registry(data: dict[str, Any]) -> FullDocumentEntityRegistry:
    category_specs = (
        ("persons", "person", "person"),
        ("organizations", "organization", "org"),
        ("locations", "location", "location"),
    )
    if set(data) != {key for key, _entity_type, _id_prefix in category_specs} | {"same_entities"}:
        raise ValueError("invalid_entities")

    names_by_type: dict[str, tuple[str, ...]] = {}
    type_by_name: dict[str, str] = {}
    total_count = 0
    for key, entity_type, _id_prefix in category_specs:
        names = _text_list(data.get(key), max_length=_MAX_ENTITY_TEXT_CHARS)
        names_by_type[entity_type] = tuple(name for name in names if name not in type_by_name)
        total_count += len(names_by_type[entity_type])
        if total_count > _MAX_ENTITY_COUNT:
            raise ValueError("invalid_entities")
        for name in names_by_type[entity_type]:
            type_by_name[name] = entity_type

    parent = {name: name for name in type_by_name}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    same_entities = data.get("same_entities")
    if not isinstance(same_entities, list) or len(same_entities) > _MAX_ENTITY_COUNT:
        raise ValueError("invalid_entities")
    for pair in same_entities:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("invalid_entity")
        left, right = pair
        if not isinstance(left, str) or not isinstance(right, str):
            raise ValueError("invalid_entity")
        if left not in type_by_name or right not in type_by_name:
            continue
        if type_by_name[left] != type_by_name[right]:
            continue
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    entities: list[RegistryEntity] = []
    for _key, entity_type, id_prefix in category_specs:
        groups: dict[str, list[str]] = {}
        for name in names_by_type[entity_type]:
            groups.setdefault(find(name), []).append(name)
        for index, names in enumerate(groups.values(), 1):
            variants = tuple(names[:_MAX_NAMES_PER_ENTITY])
            entities.append(
                RegistryEntity(
                    entity_id=f"{id_prefix}-{index}",
                    entity_type=entity_type,
                    primary_text=max(variants, key=len),
                    variants=variants,
                )
            )
    return FullDocumentEntityRegistry(entities=tuple(entities))


def _normalize_detailed_registry(data: dict[str, Any]) -> FullDocumentEntityRegistry:
    if set(data) != {"entities", "do_not_merge", "uncertain"}:
        raise ValueError("invalid_entities")
    raw_entities = data.get("entities", [])
    if not isinstance(raw_entities, list) or len(raw_entities) > _MAX_ENTITY_COUNT:
        raise ValueError("invalid_entities")
    entities: list[RegistryEntity] = []
    seen_ids: set[str] = set()
    for item in raw_entities:
        if not isinstance(item, dict):
            raise ValueError("invalid_entity")
        entity_id = _required_text(item.get("entity_id") or item.get("id"), "entity_id", 80)
        entity_type = _required_text(item.get("entity_type") or item.get("type"), "entity_type", 32)
        if entity_type not in _ALLOWED_ENTITY_TYPES or entity_id in seen_ids:
            raise ValueError("invalid_entity_identity")
        primary_text = _required_text(item.get("primary_text") or item.get("primary"), "primary_text", _MAX_ENTITY_TEXT_CHARS)
        confidence = _confidence(item.get("confidence", _DEFAULT_ENTITY_CONFIDENCE))
        variants = tuple(dict.fromkeys((primary_text, *_text_list(item.get("variants", []), max_length=_MAX_ENTITY_TEXT_CHARS))))
        evidence = _text_list(item.get("evidence", []), max_length=_MAX_EVIDENCE_CHARS * 4)
        seen_ids.add(entity_id)
        entities.append(RegistryEntity(entity_id, entity_type, primary_text, variants, confidence, evidence))

    pairs: list[DoNotMergePair] = []
    seen_pairs: set[tuple[str, str]] = set()
    raw_pairs = data.get("do_not_merge", [])
    if not isinstance(raw_pairs, list):
        raise ValueError("invalid_do_not_merge")
    for item in raw_pairs:
        if isinstance(item, dict):
            left = item.get("left_id") or item.get("left")
            right = item.get("right_id") or item.get("right")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            left, right = item
        else:
            raise ValueError("invalid_do_not_merge")
        pair = DoNotMergePair(_required_text(left, "left_id", 80), _required_text(right, "right_id", 80))
        if pair.normalized() not in seen_pairs:
            seen_pairs.add(pair.normalized())
            pairs.append(pair)

    uncertain: list[UncertainEntity] = []
    raw_uncertain = data.get("uncertain", [])
    if not isinstance(raw_uncertain, list):
        raise ValueError("invalid_uncertain")
    for item in raw_uncertain:
        if not isinstance(item, dict):
            raise ValueError("invalid_uncertain")
        possible_type = item.get("possible_type") or item.get("type")
        if possible_type is not None:
            possible_type = str(possible_type).strip()
            if possible_type not in _ALLOWED_ENTITY_TYPES:
                possible_type = None
        uncertain.append(
            UncertainEntity(
                _required_text(item.get("text"), "uncertain_text", _MAX_ENTITY_TEXT_CHARS),
                possible_type,
                _text_list(item.get("possible_entity_ids", item.get("entity_ids", [])), max_length=80),
            )
        )
    return FullDocumentEntityRegistry(tuple(entities), tuple(pairs), tuple(uncertain))




def _required_text(value: object, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid_{field_name}")
    result = value.strip()
    if not result or len(result) > max_length:
        raise ValueError(f"invalid_{field_name}")
    return result


def _text_list(value: object, *, max_length: int) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("invalid_text_list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped and len(stripped) <= max_length and stripped not in result:
            result.append(stripped)
    return tuple(result)


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_confidence")
    return max(0.0, min(1.0, float(value)))


def _dedupe_uncertain(values: Iterable[UncertainEntity]) -> list[UncertainEntity]:
    seen: set[tuple[str, str | None, tuple[str, ...]]] = set()
    result: list[UncertainEntity] = []
    for value in values:
        key = (value.text, value.possible_type, value.possible_entity_ids)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result






def _safe_error_kind(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, (TypeError, ValueError)) and exc.args and exc.args[0] in {
        "payload_too_large",
        "payload_type",
        "payload_structure",
        "invalid_entities",
        "invalid_entity_identity",
        "invalid_entity",
        "invalid_confidence",
        "invalid_do_not_merge",
        "invalid_uncertain",
    }:
        return str(exc.args[0])
    if "invalid_entity_identity" in message:
        return "invalid_entity_identity"
    return "invalid_registry_payload"
