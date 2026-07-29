"""Mapping review logic: sanitize, classify, renumber, manual mask suggestions."""
from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from typing import Any

from . import deps
from .deps import (
    CN_ORDINALS,
    File,
    Form,
    HTMLResponse,
    JSONResponse,
    MAPPING_REVIEW_CATEGORY_LABELS,
    MappingEntry,
    RESTORE_RISK_REASON_LABELS,
    RedactionMap,
    Request,
    TypeCounters,
    redaction_map_from_json,
    _filter_noise_entity_mappings,
    derived_organization_alias_cores,
    is_noise_entity_text,
    sort_mapping_entries,
)
from .documents import _form_list_value


_ORG_ALIAS_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "公司",
    "集团",
    "银行",
    "信用社",
    "合作社",
    "事务所",
    "律所",
    "学校",
    "医院",
    "法院",
    "检察院",
    "委员会",
    "村委会",
    "居委会",
    "商行",
    "经营部",
    "店",
    "厂",
    "机构",
)


def _entity_group_is_noise(group: dict) -> bool:
    full = str(group.get("full_name", "")).strip()
    if full and is_noise_entity_text(full):
        return True
    aliases = group.get("aliases", [])
    if isinstance(aliases, list):
        for alias in aliases:
            alias_text = str(alias).strip()
            if alias_text and is_noise_entity_text(alias_text):
                return True
    return False



def _sanitize_redaction_map(redaction_map: RedactionMap) -> RedactionMap:
    manual_mappings = [
        mapping for mapping in redaction_map.mappings
        if _source_indicates_manual(mapping.source)
    ]
    automatic_mappings = [
        mapping for mapping in redaction_map.mappings
        if not _source_indicates_manual(mapping.source)
    ]
    filtered = [*manual_mappings, *_filter_noise_entity_mappings(automatic_mappings)]
    if len(filtered) == len(redaction_map.mappings):
        return redaction_map
    return replace(redaction_map, mappings=sort_mapping_entries(filtered))



async def suggest_mapping_entry(request: Request) -> JSONResponse:
    body = await request.json()
    selected_text = str(body.get("selected_text", "")).strip()
    entity_type = str(body.get("entity_type", "")).strip()
    map_json = str(body.get("map_json", ""))
    if not selected_text:
        return JSONResponse({"status": "error", "message": "未选择文字"}, status_code=400)
    if len(selected_text) > 80:
        return JSONResponse({"status": "error", "message": "选择文字过长，请只选择一个实体"}, status_code=400)
    if entity_type not in {"person", "organization", "location"}:
        return JSONResponse({"status": "error", "message": "不支持的实体类型"}, status_code=400)
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"映射表解析失败: {exc}"}, status_code=400)

    existing = _find_mapping_by_original(redaction_map.mappings, selected_text)
    if existing:
        return JSONResponse({
            "status": "exists",
            "entry": existing.to_dict(),
            "message": f"已存在映射：{existing.original} → {existing.masked}",
        })

    entry = _suggest_manual_mapping_entry(selected_text, entity_type, redaction_map.mappings)
    return JSONResponse({"status": "success", "entry": entry.to_dict()})



def _source_indicates_manual(source: str) -> bool:
    return str(source or "").strip().lower().startswith(("manual", "user", "selection"))



def _source_indicates_sample(source: str) -> bool:
    return "sample" in str(source or "").strip().lower()



def _review_candidate_text_set(review_candidates: list) -> set[str]:
    values: set[str] = set()
    for candidate in review_candidates or []:
        text = getattr(candidate, "text", None)
        if text:
            values.add(str(text))
    return values



def _classify_mapping_review_row(
    entry: MappingEntry,
    *,
    original_entry: dict[str, Any] | MappingEntry | None = None,
    deleted: bool = False,
    review_candidate_texts: set[str] | None = None,
    is_new_row: bool = False,
) -> list[str]:
    categories: list[str] = []
    review_candidate_texts = review_candidate_texts or set()
    if entry.confidence < 0.85 or entry.original in review_candidate_texts:
        categories.append("low_confidence")
    if _source_indicates_manual(entry.source) or (
        is_new_row and entry.source not in {"rule", "regex", "llm"}
    ):
        categories.append("manual_added")
    if original_entry is not None:
        old_masked = original_entry.masked if isinstance(original_entry, MappingEntry) else str(original_entry.get("masked", ""))
        if old_masked and old_masked != entry.masked:
            categories.append("modified")
    if deleted:
        categories.append("delete_candidate")
    if _restore_risk_reasons(entry, deleted=deleted):
        categories.append("restore_risk")
    if _source_indicates_sample(entry.source):
        categories.append("sample_reused")
    return [name for name in MAPPING_REVIEW_CATEGORY_LABELS if name in categories]



def _restore_risk_reasons(entry: MappingEntry, *, deleted: bool = False) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    if deleted:
        reasons.append({
            "reason_code": "delete_candidate",
            "message": RESTORE_RISK_REASON_LABELS["delete_candidate"],
        })
    if not entry.masked:
        reasons.append({
            "reason_code": "empty_mask",
            "message": RESTORE_RISK_REASON_LABELS["empty_mask"],
        })
    return reasons



def _redaction_map_from_rows(
    version: str, created_at: str, mode: str, source_file: str,
    map_type: list[str], map_original: list[str], map_masked: list[str],
    map_role: list[str], map_source: list[str], map_confidence: list[str],
    map_reason: list[str], map_restore_by_default: list[str],
    map_entity_id: list[str], map_do_not_merge: list[str], map_restore_original: list[str],
    row_delete: list[str],
) -> RedactionMap:
    deleted = set(row_delete)
    row_count = max(len(map_original), len(map_masked), len(map_type))
    mappings: list[MappingEntry] = []
    for index in range(row_count):
        if str(index) in deleted:
            continue
        original = _form_list_value(map_original, index).strip()
        masked = _form_list_value(map_masked, index).strip()
        if not original or not masked:
            continue
        role = _form_list_value(map_role, index).strip() or None
        try:
            confidence = float(_form_list_value(map_confidence, index) or "1.0")
        except ValueError:
            confidence = 1.0
        raw_do_not_merge = _form_list_value(map_do_not_merge, index)
        try:
            parsed_do_not_merge = json.loads(raw_do_not_merge or "[]")
        except json.JSONDecodeError:
            parsed_do_not_merge = []
        do_not_merge = (
            tuple(str(value) for value in parsed_do_not_merge)
            if isinstance(parsed_do_not_merge, list)
            else ()
        )
        mappings.append(MappingEntry(
            type=_form_list_value(map_type, index).strip() or "manual",
            original=original, masked=masked, role=role,
            source=_form_list_value(map_source, index).strip() or "manual",
            confidence=confidence,
            restore_by_default=_form_list_value(map_restore_by_default, index) != "0",
            reason=_form_list_value(map_reason, index).strip() or None,
            entity_id=_form_list_value(map_entity_id, index).strip() or None,
            do_not_merge=do_not_merge,
            restore_original=_form_list_value(map_restore_original, index).strip() or None,
        ))
    return RedactionMap(
        version=version or "1.0",
        created_at=created_at,
        mode=mode or "normal",
        source_file=source_file or None,
        mappings=sort_mapping_entries(mappings),
    )



def _find_mapping_by_original(mappings: list[MappingEntry], original: str) -> MappingEntry | None:
    value = original.strip()
    for entry in mappings:
        if entry.original == value:
            return entry
    return None



def _organization_originals_are_aliases(left: str, right: str) -> bool:
    a = left.strip()
    b = right.strip()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if longer.startswith(shorter):
        tail = longer[len(shorter):]
        if not tail or tail in _ORG_ALIAS_SUFFIXES:
            return True
    for full_name in (a, b):
        if full_name.endswith(_ORG_ALIAS_SUFFIXES):
            cores = derived_organization_alias_cores(full_name)
            other = b if full_name == a else a
            if other in cores or f"{other}公司" == full_name or other == full_name.replace("公司", ""):
                return True
    return False



def _mapping_entries_share_entity(left: MappingEntry, right: MappingEntry) -> bool:
    if left.type == right.type == "person":
        return left.original.strip() == right.original.strip()
    if left.type in {"organization", "individual_business"} and right.type in {"organization", "individual_business"}:
        return _organization_originals_are_aliases(left.original, right.original)
    return left.type == right.type and left.original.strip() == right.original.strip()



def _mapping_entity_group_ids(mappings: list[MappingEntry]) -> list[int]:
    parent = list(range(len(mappings)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left in range(len(mappings)):
        for right in range(left + 1, len(mappings)):
            if _mapping_entries_share_entity(mappings[left], mappings[right]):
                union(left, right)

    leaders: dict[int, int] = {}
    group_ids: list[int] = []
    for index in range(len(mappings)):
        root = find(index)
        if root not in leaders:
            leaders[root] = len(leaders)
        group_ids.append(leaders[root])
    return group_ids



def _renumber_mapping_placeholders(mappings: list[MappingEntry]) -> list[MappingEntry]:
    if not mappings:
        return []
    group_ids = _mapping_entity_group_ids(mappings)
    members: dict[int, list[int]] = {}
    for index, group_id in enumerate(group_ids):
        members.setdefault(group_id, []).append(index)

    ordered_group_ids = sorted(members, key=lambda group_id: min(members[group_id]))
    group_ordinals: dict[int, str] = {}
    type_counts: dict[str, int] = {}
    person_counts: dict[str, int] = {}
    for group_id in ordered_group_ids:
        representative = mappings[members[group_id][0]]
        group_ordinals[group_id] = _next_group_ordinal(representative, type_counts, person_counts)

    renumbered: list[MappingEntry] = []
    for index, entry in enumerate(mappings):
        masked = _mask_with_group_ordinal(entry, group_ordinals[group_ids[index]])
        renumbered.append(replace(entry, masked=masked) if masked != entry.masked else entry)
    return renumbered



def _next_group_ordinal(
    entry: MappingEntry,
    type_counts: dict[str, int],
    person_counts: dict[str, int],
) -> str:
    if entry.type == "person":
        stem = _person_mask_stem(entry)
        person_counts[stem] = person_counts.get(stem, 0) + 1
        return _ordinal_value(person_counts[stem])
    counter_key = _renumber_counter_key(entry)
    type_counts[counter_key] = type_counts.get(counter_key, 0) + 1
    return _ordinal_value(type_counts[counter_key])



def _renumber_counter_key(entry: MappingEntry) -> str:
    if entry.type in {"organization", "individual_business"}:
        return "organization"
    if entry.type in {"location", "grassroots_org"}:
        return "location"
    if entry.type == "project":
        return "project"
    return entry.type or "manual"



def _person_mask_stem(entry: MappingEntry) -> str:
    match = re.match(r"^(.+?某)(?:[甲乙丙丁戊己庚辛壬癸]|\d+)$", entry.masked or "")
    if match:
        return match.group(1)
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", entry.original or ""):
        return f"{entry.original[0]}某"
    return "自然人"



def _mask_with_group_ordinal(entry: MappingEntry, ordinal: str) -> str:
    if entry.type == "person":
        return f"{_person_mask_stem(entry)}{ordinal}"
    if entry.type in {"organization", "individual_business"}:
        return _mask_with_ordinal_prefix(entry, ordinal, _manual_organization_suffix)
    if entry.type in {"location", "grassroots_org"}:
        return _mask_with_ordinal_prefix(entry, ordinal, _manual_location_suffix)
    if entry.type == "project":
        return _mask_with_ordinal_prefix(entry, ordinal, _project_suffix)
    return entry.masked



def _mask_with_ordinal_prefix(entry: MappingEntry, ordinal: str, suffix_from_original) -> str:
    match = re.match(r"^([甲乙丙丁戊己庚辛壬癸]|\d+)(.*)$", entry.masked or "")
    if match:
        suffix = match.group(2)
        if not suffix:
            return ordinal
        return f"{ordinal}{suffix}"
    return f"{ordinal}{suffix_from_original(entry.original)}"



def _project_suffix(original: str) -> str:
    if original.endswith("工程"):
        return "工程"
    return "项目"



def _suggest_manual_mapping_entry(original: str, entity_type: str, existing: list[MappingEntry]) -> MappingEntry:
    value = original.strip()
    masked = _suggest_manual_mask(value, entity_type, existing)
    return MappingEntry(
        type=entity_type,
        original=value,
        masked=masked,
        role=None,
        source="manual_selection",
        confidence=1.0,
        restore_by_default=True,
    )



def _suggest_manual_mask(original: str, entity_type: str, existing: list[MappingEntry]) -> str:
    if entity_type == "person":
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", original):
            surname = original[0]
            return f"{surname}某{_next_person_ordinal(surname, existing)}"
        return f"自然人{_next_mask_ordinal(existing, {'person'}, '自然人')}"
    if entity_type == "organization":
        suffix = _manual_organization_suffix(original)
        return f"{_next_mask_ordinal(existing, {'organization', 'individual_business'}, '')}{suffix}"
    if entity_type == "location":
        suffix = _manual_location_suffix(original)
        return f"{_next_mask_ordinal(existing, {'location', 'grassroots_org'}, '')}{suffix}"
    return f"敏感信息{_next_mask_ordinal(existing, {entity_type}, '敏感信息')}"



def _next_person_ordinal(surname: str, existing: list[MappingEntry]) -> str:
    used = 0
    pattern = re.compile(rf"^{re.escape(surname)}某([甲乙丙丁戊己庚辛壬癸]|\d+)$")
    for entry in existing:
        if entry.type != "person":
            continue
        match = pattern.match(entry.masked)
        if not match:
            continue
        used = max(used, _ordinal_index(match.group(1)))
    return _ordinal_value(used + 1)



def _next_mask_ordinal(existing: list[MappingEntry], entity_types: set[str], prefix: str) -> str:
    used = 0
    pattern = re.compile(rf"^{re.escape(prefix)}([甲乙丙丁戊己庚辛壬癸]|\d+)")
    for entry in existing:
        if entry.type not in entity_types:
            continue
        match = pattern.match(entry.masked)
        if match:
            used = max(used, _ordinal_index(match.group(1)))
    return _ordinal_value(used + 1)



def _ordinal_index(value: str) -> int:
    if value in CN_ORDINALS:
        return CN_ORDINALS.index(value) + 1
    try:
        return int(value)
    except ValueError:
        return 0



def _ordinal_value(index: int) -> str:
    if index <= len(CN_ORDINALS):
        return CN_ORDINALS[index - 1]
    return str(index)



def _manual_organization_suffix(original: str) -> str:
    for suffix in (
        "有限公司", "股份有限公司", "公司", "集团", "银行", "信用社", "合作社",
        "事务所", "律所", "学校", "医院", "法院", "检察院", "委员会",
        "村委会", "居委会", "商行", "经营部", "店", "厂",
    ):
        if original.endswith(suffix):
            if suffix in {"有限公司", "股份有限公司"}:
                return "公司"
            return suffix
    return "机构"



def _manual_location_suffix(original: str) -> str:
    for suffix in (
        "自治区", "自治州", "居民委员会", "村民委员会", "街道", "社区",
        "省", "市", "区", "县", "旗", "镇", "乡", "村", "小区", "项目", "工程",
    ):
        if original.endswith(suffix):
            if suffix in {"居民委员会", "村民委员会"}:
                return suffix
            return suffix
    return "地"



def _guess_location_mask(text: str) -> str:
    """为无后缀的纯地名（如'石家庄''沧州'）猜测合适的掩码。"""
    # 如果原本就是带后缀的，直接返回通用掩码
    for sfx, mask in [("自治区", "某自治区"), ("自治州", "某自治州"),
                       ("街道", "某街道"), ("省", "某省"), ("市", "某市"),
                       ("区", "某区"), ("县", "某县"), ("镇", "某镇"),
                       ("乡", "某乡"), ("村", "某村")]:
        if text.endswith(sfx):
            return mask
    # 无后缀的地名简称：根据常见模式推测
    if re.fullmatch(r"[一-龥]{2,4}", text):
        return "某市"  # 最常见的地名简称是城市名
    return "地点"



def _simple_mask(text: str, counters: TypeCounters) -> str:
    """为用户确认的实体生成简单掩码，供增量脱敏使用。"""
    # 公司/机构
    if re.search(r"(公司|集团|厂|店|经营部|商行|事务所|律所|银行|信用社)$", text):
        return f"公司{counters.next('company')}"
    # 地名后缀（必须在自然人检查之前，避免"河南省"被误判为姓名）
    # 注意：长后缀必须在短后缀之前检查，避免"内蒙古自治区"被"区"截断
    if text.endswith("自治区"):
        return "某自治区"
    if text.endswith("自治州"):
        return "某自治州"
    if text.endswith("街道"):
        return "某街道"
    if text.endswith("省"):
        return "某省"
    if text.endswith("市"):
        return "某市"
    if text.endswith("区"):
        return "某区"
    if text.endswith("县"):
        return "某县"
    if text.endswith("镇"):
        return "某镇"
    if text.endswith("乡"):
        return "某乡"
    if text.endswith("村"):
        return "某村"
    # 法院
    if "法院" in text:
        return "某法院"
    # 自然人（2-4字，不含地名后缀）
    if re.fullmatch(r"[一-龥]{2,4}", text):
        return f"自然人{counters.next('person')}"
    # 项目/工程
    if "工程" in text or "项目" in text:
        return f"项目{counters.next('project')}"
    # 其他
    return f"敏感信息{counters.next('other')}"



# Compatibility re-exports (prefer mapping_render for new UI work).
from .mapping_render import (  # noqa: E402,F401
    _highlight_replaced_text,
    _render_blank_mapping_row,
    _render_category_badges,
    _render_mapping_edit_row,
    _render_mapping_edit_rows,
    _render_mapping_review_toolbar,
    _review_candidate_texts_json,
)
