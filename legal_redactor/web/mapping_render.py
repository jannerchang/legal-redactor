"""HTML fragments for mapping review / edit UI.

Pure mapping logic stays in ``mapping_ops``. Future treelist-style review can
replace or extend these helpers without touching HTTP handlers.
"""
from __future__ import annotations

import html
import json
from typing import Any

from .deps import (
    MAPPING_REVIEW_CATEGORY_LABELS,
    MappingEntry,
    RedactionMap,
    sort_mapping_entries,
)
from .mapping_ops import (
    _classify_mapping_review_row,
    _restore_risk_reasons,
    _review_candidate_text_set,
    _source_indicates_manual,
    _source_indicates_sample,
)


def _render_mapping_review_toolbar(redaction_map: RedactionMap, review_candidates: list | None = None) -> str:
    review_texts = _review_candidate_text_set(review_candidates or [])
    counts = {key: 0 for key in MAPPING_REVIEW_CATEGORY_LABELS}
    for entry in redaction_map.mappings:
        for category in _classify_mapping_review_row(entry, review_candidate_texts=review_texts):
            counts[category] += 1
    buttons = [
        f'<button type="button" class="mapping-filter active" data-map-filter="all">'
        f'全部 <span>{len(redaction_map.mappings)}</span></button>'
    ]
    for category, label in MAPPING_REVIEW_CATEGORY_LABELS.items():
        buttons.append(
            f'<button type="button" class="mapping-filter" data-map-filter="{category}">'
            f'{html.escape(label)} <span>{counts[category]}</span></button>'
        )
    return (
        '<div id="mapping-review-toolbar" class="mapping-toolbar">'
        '<div class="mapping-toolbar-head"><strong>复核筛选</strong>'
        '<span class="hint">默认显示全部；点击分类只看需要处理的行。</span></div>'
        f'<div class="mapping-filter-row">{"".join(buttons)}</div>'
        '</div>'
    )



def _render_category_badges(categories: list[str], *, restore_reasons: list[dict[str, str]] | None = None) -> str:
    if not categories:
        return ""
    badges = ""
    for category in categories:
        attrs = ""
        label = MAPPING_REVIEW_CATEGORY_LABELS[category]
        if category == "restore_risk" and restore_reasons:
            codes = ",".join(str(item.get("reason_code") or "") for item in restore_reasons if item.get("reason_code"))
            messages = "；".join(str(item.get("message") or "") for item in restore_reasons if item.get("message"))
            attrs = f' data-restore-risk-codes="{html.escape(codes)}" title="{html.escape(messages)}"'
        badges += (
            f'<span class="row-badge row-badge-{html.escape(category)}"{attrs}>'
            f'{html.escape(label)}</span>'
        )
    return f'<div class="row-tags">{badges}</div>'



def _review_candidate_texts_json(review_candidates: list | None = None) -> str:
    return json.dumps(sorted(_review_candidate_text_set(review_candidates or [])), ensure_ascii=False)



def _render_mapping_edit_rows(redaction_map: RedactionMap, review_candidates: list | None = None) -> str:
    review_texts = _review_candidate_text_set(review_candidates or [])
    mappings = sort_mapping_entries(list(redaction_map.mappings))
    rows = [
        _render_mapping_edit_row(i, e, review_candidate_texts=review_texts)
        for i, e in enumerate(mappings)
    ]
    rows.append(_render_blank_mapping_row(len(rows)))
    return "".join(rows)



def _render_mapping_edit_row(index: int, entry: MappingEntry, review_candidate_texts: set[str] | None = None) -> str:
    role = entry.role or ""
    reason = entry.reason or ""
    restore = "1" if entry.restore_by_default else "0"
    categories = _classify_mapping_review_row(entry, review_candidate_texts=review_candidate_texts or set())
    category_attr = html.escape(" ".join(categories))
    tags_html = _render_category_badges(categories, restore_reasons=_restore_risk_reasons(entry))
    return f"""
        <tr data-map-row="{index}" data-categories="{category_attr}">
          <td><input name="map_type" value="{html.escape(entry.type)}"></td>
          <td><textarea name="map_original" rows="2">{html.escape(entry.original)}</textarea>
            <input type="hidden" name="map_original_before" value="{html.escape(entry.original)}">
          </td>
          <td><textarea name="map_masked" rows="2">{html.escape(entry.masked)}</textarea></td>
          <td><textarea name="map_reason" rows="2" placeholder="为什么删除/修改/添加">{html.escape(reason)}</textarea></td>
          <td>{html.escape(entry.source)}</td>
          <td>{entry.confidence:.2f}</td>
          <td><label class="inline"><input type="checkbox" name="row_delete" value="{index}"> 删除</label>
            {tags_html}
            <input type="hidden" name="map_role" value="{html.escape(role)}">
            <input type="hidden" name="map_source" value="{html.escape(entry.source)}">
            <input type="hidden" name="map_confidence" value="{entry.confidence}">
            <input type="hidden" name="map_restore_by_default" value="{restore}">
            <input type="hidden" name="map_entity_id" value="{html.escape(entry.entity_id or '')}">
            <input type="hidden" name="map_do_not_merge" value="{html.escape(json.dumps(entry.do_not_merge, ensure_ascii=False))}">
            <input type="hidden" name="map_restore_original" value="{html.escape(entry.restore_original or '')}">
          </td>
        </tr>
    """



def _render_blank_mapping_row(index: int) -> str:
    return f"""
        <tr data-map-row="{index}" data-categories="">
          <td><input name="map_type" value="manual" placeholder="person/org"></td>
          <td><textarea name="map_original" rows="2" placeholder="新增要替换的原文"></textarea>
            <input type="hidden" name="map_original_before" value="">
          </td>
          <td><textarea name="map_masked" rows="2" placeholder="替换为"></textarea></td>
          <td><textarea name="map_reason" rows="2" placeholder="为什么新增这条"></textarea></td>
          <td>manual</td>
          <td>1.0</td>
          <td><label class="inline"><input type="checkbox" name="row_delete" value="{index}"> 删除</label>
            <input type="hidden" name="map_role" value="">
            <input type="hidden" name="map_source" value="manual">
            <input type="hidden" name="map_confidence" value="1.0">
            <input type="hidden" name="map_restore_by_default" value="1">
            <input type="hidden" name="map_entity_id" value="">
            <input type="hidden" name="map_do_not_merge" value="[]">
            <input type="hidden" name="map_restore_original" value="">
          </td>
        </tr>
    """



def _highlight_replaced_text(text: str, entries: list[MappingEntry], *, reverse: bool = False) -> str:
    """生成带 <mark> 高亮的 HTML 文本。

    reverse=False：高亮原文中被替换的词（title 显示替换后的内容）。
    reverse=True：高亮脱敏文本中的占位符（title 显示原文）。
    """
    if not entries:
        return html.escape(text)

    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []

    sorted_entries = sorted(
        entries, key=lambda e: len(e.masked if reverse else e.original), reverse=True
    )

    for entry in sorted_entries:
        search_key = entry.masked if reverse else entry.original
        if not search_key:
            continue
        tooltip = entry.original if reverse else entry.masked

        pos = 0
        while True:
            idx = text.find(search_key, pos)
            if idx < 0:
                break
            end = idx + len(search_key)
            if not any(not (end <= occ_start or idx >= occ_end) for occ_start, occ_end in occupied):
                spans.append((idx, end, search_key, tooltip))
                occupied.append((idx, end))
            pos = idx + 1

    if not spans:
        return html.escape(text)

    spans.sort(key=lambda s: s[0])

    parts: list[str] = []
    last = 0
    for start, end, display, tooltip_text in spans:
        if start > last:
            parts.append(html.escape(text[last:start]))
        title = f"原文：{tooltip_text}" if reverse else f"→ {tooltip_text}"
        parts.append(f'<mark title="{html.escape(title)}">{html.escape(display)}</mark>')
        last = end

    if last < len(text):
        parts.append(html.escape(text[last:]))

    return "".join(parts)
