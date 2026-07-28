from __future__ import annotations

import asyncio
import http.client
import html
import json
import os
import re
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import base64
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile

from . import deps
from .deps import (
    CN_ORDINALS,
    DEFAULT_MODEL_ID,
    EXCEL_INPUT_SUFFIXES,
    ExcelFormulaLeakError,
    File,
    Form,
    HTMLResponse,
    JSONResponse,
    MappingEntry,
    PipelineConfig,
    RecognitionRunStats,
    RedactedDocument,
    RedactionMap,
    Request,
    TypeCounters,
    UploadFile,
    XLSX_MEDIA_TYPE,
    _filter_noise_entity_mappings,
    _page,
    derived_organization_alias_cores,
    extract_workbook_text,
    is_noise_entity_text,
    preview_restore,
    redact_workbook,
    redaction_map_from_json,
    redaction_map_to_json,
    render_batch_redaction_result_page,
    render_home_page,
    render_redaction_result_page,
    render_status_panel,
    restore_docx,
    sort_mapping_entries,
    MAPPING_REVIEW_CATEGORY_LABELS,
    RESTORE_RISK_REASON_LABELS,
)

from ..cases import (
    CaseError,
    InvalidDiscordThreadError,
    InvalidWorkflowInputError,
    case_dir,
    create_or_update_manifest,
    case_root_from_source_dir,
    case_workflow_public,
    case_workflow_state,
    default_case_root,
    load_manifest,
    manifest_fields_for_case_dir,
    parse_discord_thread_id,
    persist_case_redaction,
    raise_for_forged_workflow_fields,
    record_hermes_thread_request,
    suggest_case_location_from_filenames,
    case_location_search_roots,
    case_thread_binding_status,
    validate_case_folder_name,
    workflow_state_message,
)


from .models import SAMPLE_SUMMARY_KEYS


def _sample_entry_original(entry: dict[str, Any]) -> str:
    if entry.get("action") == "modify":
        return str(entry.get("new_original") or entry.get("old_original") or "")
    return str(entry.get("original") or "")



def _sample_entry_core(entry: dict[str, Any]) -> dict[str, str]:
    keys = (
        "action",
        "type",
        "original",
        "masked",
        "old_original",
        "new_original",
        "old_masked",
        "new_masked",
        "reason",
    )
    return {key: str(entry.get(key) or "") for key in keys if entry.get(key) not in (None, "")}



def _sample_effective_delta(existing_entries: list[dict[str, Any]], incoming_entries: list[dict[str, Any]]) -> dict[str, int]:
    existing_by_original = {
        _sample_entry_original(entry): _sample_entry_core(entry)
        for entry in existing_entries
        if _sample_entry_original(entry)
    }
    delta = {"created": 0, "updated": 0, "unchanged": 0}
    for entry in incoming_entries:
        original = _sample_entry_original(entry)
        if not original:
            continue
        current_core = _sample_entry_core(entry)
        previous_core = existing_by_original.get(original)
        if previous_core is None:
            delta["created"] += 1
        elif previous_core == current_core:
            delta["unchanged"] += 1
        else:
            delta["updated"] += 1
        existing_by_original[original] = current_core
    return delta



def _load_sample_entries_for_delta(samples_dir: str | Path | None = None) -> list[dict[str, Any]]:
    from .._samples import _auto_sample_path

    path = _auto_sample_path(samples_dir) if samples_dir is not None else _auto_sample_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries", [])
    return entries if isinstance(entries, list) else []



def _summary_item_from_entry(entry: dict[str, Any], *, action: str | None = None) -> dict[str, Any]:
    actual_action = action or str(entry.get("action") or "")
    if actual_action == "modify":
        original = str(entry.get("new_original") or entry.get("old_original") or "")
        masked = str(entry.get("new_masked") or entry.get("old_masked") or "")
    else:
        original = str(entry.get("original") or "")
        masked = str(entry.get("masked") or "")
    item = {
        "action": actual_action,
        "type": str(entry.get("type") or "other"),
        "original": original,
        "masked": masked,
    }
    reason = str(entry.get("reason") or "").strip()
    if reason:
        item["reason"] = reason
    return item



def _empty_sample_summary(source_file: str = "") -> dict[str, Any]:
    return {
        "lookup_entries": [],
        "delete_blacklist_candidates": [],
        "suppressed_risky_entries": [],
        "manual_corrections": 0,
        "false_positive_deletes": 0,
        "missing_adds": 0,
        "manual_modify_count": 0,
        "restore_unresolved_placeholders": None,
        "newest_sample_provenance": {
            "source": "web_ui",
            "source_file_present": bool(source_file),
        },
        "regression_suggestions": [],
    }



def _sample_provenance(source_file: str = "", sample_path: str | Path | None = None) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "source": "web_ui",
        "source_file_present": bool(source_file),
    }
    if sample_path:
        path = Path(sample_path)
        provenance["sample_file"] = path.name
        try:
            provenance["sample_updated_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        except OSError:
            provenance["sample_updated_at"] = None
    return provenance



def _build_sample_save_summary(
    entries: list[dict[str, Any]],
    *,
    skipped_risky_entries: list[dict[str, Any]] | None = None,
    source_file: str = "",
    sample_path: str | Path | None = None,
) -> dict[str, Any]:
    from .._samples import is_sample_lookup_allowed

    skipped_risky_entries = skipped_risky_entries or []
    summary = _empty_sample_summary(source_file)
    summary["newest_sample_provenance"] = _sample_provenance(source_file, sample_path)
    for entry in entries:
        action = str(entry.get("action") or "")
        if action in {"add", "modify"}:
            item = _summary_item_from_entry(entry, action=action)
            lookup_entry = {
                "action": action,
                "type": item["type"],
                "original": item["original"],
                "masked": item["masked"],
            }
            if is_sample_lookup_allowed(entry, item["original"], item["masked"]):
                summary["lookup_entries"].append(lookup_entry)
            else:
                summary["suppressed_risky_entries"].append({
                    **lookup_entry,
                    "reason_code": "lookup_guard",
                    "message": RESTORE_RISK_REASON_LABELS["lookup_guard"],
                })
            if action == "add":
                summary["missing_adds"] += 1
            elif action == "modify":
                summary["manual_modify_count"] += 1
        elif action == "delete":
            item = _summary_item_from_entry(entry, action=action)
            summary["delete_blacklist_candidates"].append({
                "action": action,
                "type": item["type"],
                "original": item["original"],
                "reason_code": "delete_candidate",
                "message": RESTORE_RISK_REASON_LABELS["delete_candidate"],
            })
            summary["false_positive_deletes"] += 1
    summary["suppressed_risky_entries"].extend(skipped_risky_entries)
    summary["manual_corrections"] = len(entries) + len(skipped_risky_entries)
    suggestions: list[str] = []
    if entries or skipped_risky_entries:
        suggestions.append(".venv/bin/python -m pytest tests/test_sample_integration.py")
    if any(item.get("action") in {"add", "modify"} for item in entries):
        suggestions.append(".venv/bin/python -m pytest tests/test_web_app.py")
    summary["regression_suggestions"] = suggestions
    return {key: summary[key] for key in SAMPLE_SUMMARY_KEYS}



def _sample_summary_response(msg: str, summary: dict[str, Any], *, cls: str = "") -> HTMLResponse:
    payload: dict[str, Any] = {
        "type": "sample_summary",
        "msg": msg,
        "summary": summary,
    }
    if cls:
        payload["cls"] = cls
    return HTMLResponse(
        f"<script>parent.postMessage({json.dumps(payload, ensure_ascii=False)},\"*\")</script>"
    )



async def save_sample_page(request: Request) -> str:
    form = await request.form()
    map_type = form.getlist("map_type")
    map_original = form.getlist("map_original")
    map_original_before = form.getlist("map_original_before")
    map_masked = form.getlist("map_masked")
    map_reason = form.getlist("map_reason")
    row_delete = form.getlist("row_delete")
    map_source_file = form.get("map_source_file", "")
    original_mapping_json = form.get("original_mapping_json", "")

    from .. import _samples as samples_module
    from .._samples import is_global_delete_sample_allowed, save_sample_auto

    try:
        original_data = json.loads(original_mapping_json) if original_mapping_json else {}
    except json.JSONDecodeError:
        original_data = {}
    original_mappings = original_data.get("mappings", [])
    original_index = {e.get("original", ""): e for e in original_mappings}

    deleted = set(str(r) for r in row_delete)
    edited_index: dict[str, tuple[str, str, str, str]] = {}
    for i in range(max(len(map_original), len(map_masked), len(map_original_before))):
        if str(i) in deleted:
            continue
        orig = (map_original[i] if i < len(map_original) else "").strip()
        original_before = (map_original_before[i] if i < len(map_original_before) else "").strip()
        masked = (map_masked[i] if i < len(map_masked) else "").strip()
        t = (map_type[i] if i < len(map_type) else "other").strip()
        reason = (map_reason[i] if i < len(map_reason) else "").strip()
        if orig and masked:
            edited_index[orig] = (original_before, masked, t, reason)

    entries: list[dict] = []
    processed: set[str] = set()
    skipped_risky_deletes: list[dict[str, Any]] = []
    for i_str in deleted:
        try:
            i = int(i_str)
            if i < len(map_original):
                orig = map_original[i].strip()
                if orig and orig not in processed:
                    entry = {"action": "delete", "type": map_type[i] if i < len(map_type) else "other", "original": orig}
                    reason = (map_reason[i] if i < len(map_reason) else "").strip()
                    if reason:
                        entry["reason"] = reason
                    if is_global_delete_sample_allowed(entry):
                        entries.append(entry)
                    else:
                        skipped_risky_deletes.append({
                            "action": "delete",
                            "type": entry["type"],
                            "original": orig,
                            "reason_code": "risky_delete_guard",
                            "message": "短中文人名未写入全局黑名单",
                        })
                    processed.add(orig)
        except (ValueError, IndexError):
            continue
    for orig, (original_before, masked, t, reason) in edited_index.items():
        if orig in processed:
            continue
        processed.add(orig)
        baseline_original = original_before or orig
        original_entry = original_index.get(baseline_original)
        if original_entry is not None:
            old_masked = str(original_entry.get("masked", ""))
            if orig != baseline_original or masked != old_masked:
                entry = {
                    "action": "modify",
                    "type": t,
                    "old_original": baseline_original,
                    "new_original": orig,
                    "old_masked": old_masked,
                    "new_masked": masked,
                }
                if reason:
                    entry["reason"] = reason
                entries.append(entry)
            # keep 条目不保存（识别正确的无需记录）
        else:
            entry = {"action": "add", "type": t, "original": orig, "masked": masked}
            if reason:
                entry["reason"] = reason
            entries.append(entry)

    if not entries:
        summary = _build_sample_save_summary(
            entries,
            skipped_risky_entries=skipped_risky_deletes,
            source_file=str(map_source_file),
        )
        if skipped_risky_deletes:
            return _sample_summary_response(
                "短中文人名未写入全局黑名单，请用修改映射或规则修正处理",
                summary,
                cls="warn",
            )
        return _sample_summary_response("无变化，未追加", summary)

    existing_sample_entries = _load_sample_entries_for_delta(samples_module.DEFAULT_SAMPLES_DIR)
    effective_delta = _sample_effective_delta(existing_sample_entries, entries)

    try:
        sample_path = save_sample_auto(entries, source=map_source_file or "web_ui")
    except Exception as exc:
        return HTMLResponse(f'<script>parent.postMessage({{type:"toast",msg:"保存失败:{html.escape(str(exc))}",cls:"warn"}},"*")</script>')

    new_count = sum(1 for e in entries if e["action"] in ("add", "modify"))
    del_count = sum(1 for e in entries if e["action"] == "delete")
    summary = _build_sample_save_summary(
        entries,
        skipped_risky_entries=skipped_risky_deletes,
        source_file=str(map_source_file),
        sample_path=sample_path,
    )
    msg = (
        f'已处理 {len(entries)} 条 | 新增 {effective_delta["created"]} | '
        f'更新 {effective_delta["updated"]} | 未变化 {effective_delta["unchanged"]} | '
        f'匹配 {new_count} | 黑名单 {del_count}'
    )
    if skipped_risky_deletes:
        msg += f' | 跳过短人名黑名单 {len(skipped_risky_deletes)}'
    return _sample_summary_response(msg, summary, cls="warn" if skipped_risky_deletes else "")



def _diagnose_sample_entry(entry: dict) -> str:
    action = entry.get("action", "")
    orig = entry.get("original") or entry.get("new_original", "")
    masked = entry.get("masked") or entry.get("new_masked", "")
    manual_reason = str(entry.get("reason") or "").strip()
    if manual_reason:
        return html.escape(manual_reason)

    if action == "delete":
        matched_rules = []
        # 1. 手机/电话
        if re.search(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", orig):
            matched_rules.append("手机号正则")
        # 2. 身份证
        if re.search(r"(?<![0-9Xx])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])", orig):
            matched_rules.append("身份证号正则")
        # 3. 信用代码
        if re.search(r"(?<![A-Z0-9])[0-9A-Z]{18}(?![A-Z0-9])", orig):
            matched_rules.append("信用代码正则")
        # 4. 案号
        if re.search(r"[（(][12]\d{3}[）)][\u4e00-\u9fa5A-Za-z0-9]{1,16}?(?:知民初|知民终|执异|执复|民辖终|民辖初|民辖|民初|民终|民申|民再|行初|行终|行申|刑初|刑终|刑申|刑再|商初|商终|破申|执|民撤|民特|民保|强清|管辖)", orig):
            matched_rules.append("案号结构化正则")
        # 5. 行政区划数据库或全文地点登记
        if re.search(r"[\u4e00-\u9fa5]{2,6}?(?:省|自治区|市|自治州|盟|区|县|旗)$", orig):
            matched_rules.append("行政区划数据库或全文地点登记")
        # 6. 全文人名登记
        if len(orig) in (2, 3):
            matched_rules.append("全文人名登记")
        # 7. 全文机构登记
        if any(orig.endswith(sfx) for sfx in ["有限责任公司", "股份有限公司", "集团有限公司", "有限公司", "公司", "集团", "律师事务所", "会计师事务所", "经营部", "商行", "工作室", "厂", "店"]):
            matched_rules.append("全文机构登记")

        if not matched_rules:
            matched_rules.append("全文 LLM 实体登记")

        rules_str = "、".join(matched_rules)
        return (
            f"<span style='color:var(--danger);font-weight:500'>误匹配为实体</span>"
            f"（触发「{html.escape(rules_str)}」）。"
            f"<b>已记入优化黑名单，供规则/评估优化使用；运行时脱敏不会读取样本库。</b>"
        )

    elif action == "modify":
        old_masked = entry.get("old_masked", "")
        new_masked = entry.get("new_masked", "")
        return (
            f"<span style='color:#e65100;font-weight:500'>修正脱敏掩码</span>"
            f"（从「{html.escape(old_masked)}」修正为「{html.escape(new_masked)}」）。"
            f"<b>已记入优化样本，不参与运行时脱敏。</b>"
        )

    elif action == "add":
        return (
            f"<span style='color:#1565c0;font-weight:500'>手动新增实体</span>。"
            f"<b>已记入优化样本（目标掩码「{html.escape(masked)}」），不参与运行时脱敏。</b>"
        )

    elif action == "keep":
        return (
            "<span style='color:#2e7d32;font-weight:500'>确认无误（保留）</span>。"
            "<b>已记入优化样本，不参与运行时脱敏。</b>"
        )

    return "已作为优化样本记录（不参与运行时脱敏）。"



def edit_samples_page() -> str:
    from .._samples import _auto_sample_path
    filepath = _auto_sample_path()
    entries = []
    if filepath.exists():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except (json.JSONDecodeError, KeyError):
            pass
    rows = ""
    for i, e in enumerate(entries):
        action = e.get("action", "?")
        original_before = e.get("old_original", "")
        orig = e.get("original") or e.get("new_original", "")
        masked = e.get("masked") or e.get("new_masked", "")
        old_masked = e.get("old_masked", "")
        reason = e.get("reason", "")
        action_label = {"keep": "保留", "delete": "黑名单", "add": "新增", "modify": "修改"}.get(action, action)
        row_class = "style='opacity:.6'" if action == "delete" else ""
        row_diagnose = _diagnose_sample_entry(e)
        prior_mapping = (
            f"原文：{html.escape(original_before)}<br>掩码：{html.escape(old_masked)}"
            if action == "modify"
            else ""
        )
        rows += f"""<tr {row_class}>
          <td><span class="tag tag-{action}">{action_label}</span></td>
          <td><input name="orig_{i}" value="{html.escape(orig)}" style="width:180px"></td>
          <td><input name="masked_{i}" value="{html.escape(masked)}" style="width:140px"></td>
          <td style="font-size:11px;color:var(--muted)">{prior_mapping}</td>
          <td><textarea name="reason_{i}" rows="2" style="width:220px" placeholder="为什么删除/修改/添加">{html.escape(reason)}</textarea></td>
          <td style="font-size:12px;color:var(--ink);max-width:320px;word-break:break-all">{row_diagnose}</td>
          <td>
            <button class="btn btn-sm" onclick="saveRow({i},this)">保存</button>
            <a href="/samples/delete/{i}" class="btn btn-sm btn-secondary" style="margin-left:4px">删除</a>
          </td>
        </tr>"""
    rows += f"""<tr>
      <td><select id="new-action" style="width:80px"><option value="add">新增</option><option value="delete">黑名单</option></select></td>
      <td><input id="new-orig" placeholder="原文" style="width:180px"></td>
      <td><input id="new-masked" placeholder="替换为" style="width:140px"></td>
      <td></td>
      <td><textarea id="new-reason" rows="2" style="width:220px" placeholder="为什么新增/删除"></textarea></td>
      <td></td>
      <td><button class="btn btn-sm" onclick="saveNewRow({len(entries)},this)">＋</button></td>
    </tr>"""

    return _page(
        "编辑样本库",
        f"""
        <nav><a href="/">返回首页</a></nav>
        <style>
          .tag{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}}
          .tag-keep{{background:#e8f5e9;color:#2e7d32}}
          .tag-delete{{background:#fce4ec;color:#c62828}}
          .tag-add{{background:#e3f2fd;color:#1565c0}}
          .tag-modify{{background:#fff3e0;color:#e65100}}
        </style>
        <section>
          <h2>样本库（{len(entries)} 条）</h2>
          <p class="hint">样本库仅用于后续规则/评估优化，不参与运行时脱敏或 LLM few-shot。编辑后自动保存。删除操作立即生效。</p>
          <p style="margin:8px 0 16px 0;">
            <a href="/samples/clear" class="btn btn-secondary" onclick="return confirm('确认清空全部样本？清空后可继续写入新样本。');">清空样本库</a>
            <a href="/samples/compact" class="btn btn-secondary" style="margin-left:8px;">整理去重</a>
          </p>
          <table>
            <thead><tr><th>类型</th><th>现原文</th><th>现替换为</th><th>修改前映射</th><th>修改理由</th><th>诊断与优化分析</th><th>操作</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """,
    )



async def update_sample_entry(idx: int, request: Request) -> JSONResponse:
    from .._samples import _auto_sample_path, save_sample_auto
    filepath = _auto_sample_path()
    body = await request.json()
    if not filepath.exists():
        return JSONResponse({"msg": "样本库为空"})
    data = json.loads(filepath.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if 0 <= idx < len(entries):
        e = entries[idx]
        action = e.get("action", "")
        if action in ("keep", "add"):
            e["original"] = body.get("original", e.get("original", ""))
            e["masked"] = body.get("masked", e.get("masked", ""))
        elif action == "modify":
            e["new_original"] = body.get("original", e.get("new_original", ""))
            e["new_masked"] = body.get("masked", e.get("new_masked", ""))
        e["reason"] = body.get("reason", e.get("reason", "")).strip()
        save_sample_auto([e], source=e.get("source", "samples_edit"))
        return JSONResponse({"msg": "已保存"})
    return JSONResponse({"msg": "索引无效"}, status_code=400)



async def add_sample_entry(request: Request) -> JSONResponse:
    from .._samples import is_global_delete_sample_allowed, save_sample_auto
    body = await request.json()
    action = body.get("action", "add")
    orig = body.get("original", "").strip()
    masked = body.get("masked", "").strip()
    reason = body.get("reason", "").strip()
    if not orig:
        return JSONResponse({"msg": "原文不能为空"}, status_code=400)
    if action == "delete":
        entry = {"action": "delete", "type": "manual", "original": orig}
        if reason:
            entry["reason"] = reason
        if not is_global_delete_sample_allowed(entry):
            return JSONResponse({"msg": "短中文人名不写入全局黑名单，请改用精确映射校准。"}, status_code=400)
        save_sample_auto([entry], source="samples_edit")
    else:
        if not masked:
            return JSONResponse({"msg": "替换为不能为空"}, status_code=400)
        entry = {"action": "add", "type": "manual", "original": orig, "masked": masked}
        if reason:
            entry["reason"] = reason
        save_sample_auto([entry], source="samples_edit")
    return JSONResponse({"msg": "已添加"})



def delete_sample_entry(idx: int) -> str:
    from .._samples import _auto_sample_path
    filepath = _auto_sample_path()
    if not filepath.exists():
        return _page("错误", '<p>样本库为空。</p><a href="/samples/edit">返回</a>')
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if 0 <= idx < len(entries):
            entries.pop(idx)
            data["entries"] = entries
            data["total"] = len(entries)
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return _page("已删除", f'<p>第 {idx+1} 条已删除。</p><a href="/samples/edit">返回样本库</a>')
    except Exception as exc:
        return _page("错误", f'<p>{html.escape(str(exc))}</p><a href="/samples/edit">返回</a>')



def compact_samples_page() -> str:
    from .._samples import compact_samples
    compact_samples()
    return _page("整理完成", '<p class="success">样本库已去重并优化。</p><nav><a href="/">返回首页</a></nav>')



def clear_samples_page() -> str:
    from .._samples import clear_sample_library

    result = clear_sample_library()
    return _page(
        "样本库已清空",
        (
            f'<p class="success">已删除 {result["removed_entries"]} 条样本（{result["removed_files"]} 个文件），'
            f'并重建空自动样本 {html.escape(str(result["sample_file"]))}。</p>'
            '<nav><a href="/samples/edit">返回样本库</a> · <a href="/">返回首页</a></nav>'
        ),
    )



def api_clear_samples() -> JSONResponse:
    from .._samples import clear_sample_library

    result = clear_sample_library()
    return JSONResponse({"status": "ok", **result})



def _render_sample_summary_panel() -> str:
    return (
        '<div id="sample-summary-panel" class="sample-summary-panel" hidden>'
        '<strong>样本学习摘要</strong>'
        '<div id="sample-summary-content" class="sample-summary-content"></div>'
        '</div>'
    )
