"""HTML assembly for redaction result / audit pages.

Route handlers live in ``redact_routes``; this module only builds page HTML so
future UI surfaces (e.g. treelist mapping review) can plug in without touching
HTTP handlers.
"""
from __future__ import annotations

import base64
import html
import json
import os
from pathlib import PurePosixPath
from typing import Any

from . import deps
from .deps import (
    DEFAULT_MODEL_ID,
    MappingEntry,
    RecognitionRunStats,
    RedactedDocument,
    RedactionMap,
    XLSX_MEDIA_TYPE,
    _page,
    redaction_map_to_json,
    render_batch_redaction_result_page,
    render_redaction_result_page,
)
from .models import InputDocument, RECOGNITION_MODE_LABELS, RECOGNITION_STATUS_LABELS
from . import workflow as workflow
from .documents import (
    _binary_download,
    _data_download,
    _documents_bundle_json,
)
from .mapping_ops import (
    _highlight_replaced_text,
    _render_mapping_edit_rows,
    _render_mapping_review_toolbar,
    _review_candidate_texts_json,
)
from .discord_ops import _discord_create_thread_section, _discord_send_section
from .samples_ops import _render_sample_summary_panel

def _render_audit_dashboard(
    analysis: dict,
    original_documents: list[InputDocument],
    profile: str,
    llm_mode: str,
    model: str = DEFAULT_MODEL_ID,
    recognition_mode: str = "full_document",
    round_num: int = 0,
    previous_map_json: str = "{}",
    previous_deselected_json: str = "[]",
    locked_entries: list[MappingEntry] | None = None,
) -> str:
    locked_entries = locked_entries or []

    # 已锁定的实体展示
    locked_html = ""
    if locked_entries and round_num > 0:
        locked_rows = ""
        for e in locked_entries:
            locked_rows += f'<tr class="locked-row"><td><span class="tag tag-locked">已替换</span></td><td colspan="2">{html.escape(e.original)} → {html.escape(e.masked)}</td></tr>'
        locked_html = f"""
        <details class="locked-section" {'open' if len(locked_entries) <= 8 else ''}>
          <summary>已确认并替换 <span class="badge">{len(locked_entries)}</span> 条</summary>
          <table class="locked-table"><tbody>{locked_rows}</tbody></table>
        </details>
        """

    groups = analysis.get("entity_groups", [])
    groups_html = ""
    for g in groups:
        aliases = [a for a in g.get("aliases", []) if a]
        aliases_str = "、".join(aliases) if aliases else "无"
        entity_type_label = "公司/机构" if g.get("type") == "organization" else "个人"
        groups_html += f"""
        <tr class="entity-row">
          <td><input type="checkbox" checked name="group_{g.get('id')}_enabled" value="1"></td>
          <td><span class="tag type-{g.get('type')}">{entity_type_label}</span></td>
          <td><span class="tag role-{g.get('role')}">{g.get('role', '') or ''}</span></td>
          <td class="full-name"><strong>{html.escape(g.get('full_name', ''))}</strong></td>
          <td class="aliases">{html.escape(aliases_str)}</td>
          <td><input type="text" name="group_{g.get('id')}_mask" placeholder="自动生成" class="mask-input"></td>
        </tr>
        """

    locations = analysis.get("locations", [])
    locations_html = "".join(
        f'<li><label><input type="checkbox" checked name="loc_{idx}" value="{html.escape(str(location))}"> {html.escape(str(location))}</label></li>'
        for idx, location in enumerate(locations)
    )

    bundle_json = json.dumps([{"source_file": d.source_file, "text": d.text} for d in original_documents], ensure_ascii=False)

    round_badge = f' <span class="round-badge">第 {round_num + 1} 轮</span>' if round_num > 0 else ""
    subtitle = "（基于已脱敏文本的二次扫描）" if round_num > 0 else "（基于原文首次扫描）"

    return _page(
        f"分级确认 - 语义审计{round_badge}",
        f"""
        <nav><a href="/">返回首页</a></nav>
        <section class="info-card">
          <h2>识别到的主体与关联关系 {round_badge}</h2>
          <p class="hint">{subtitle} 大模型已自动将"全称"与"简称"归组。您可以取消勾选不需脱敏的项，或手动指定脱敏后的代号。</p>
          {locked_html}
          <form action="/redact/confirmed" method="post">
            <input type="hidden" name="profile" value="{profile}">
            <input type="hidden" name="llm_mode" value="{llm_mode}">
            <input type="hidden" name="model" value="{html.escape(model)}">
            <input type="hidden" name="recognition_mode" value="{html.escape(recognition_mode)}">
            <input type="hidden" name="bundle_json" value="{html.escape(bundle_json)}">
            <input type="hidden" name="analysis_json" value="{html.escape(json.dumps(analysis, ensure_ascii=False))}">
            <input type="hidden" name="round" value="{round_num}">
            <input type="hidden" name="previous_map_json" value="{html.escape(previous_map_json)}">
            <input type="hidden" name="previous_deselected_json" value="{html.escape(previous_deselected_json)}">
            {'<p class="hint" style="color:var(--muted)">未发现新实体 — 点击"完成脱敏"查看最终结果。</p>' if not groups and not locations else ''}
            {'<table class="audit-table">'
             '<thead><tr><th>脱敏</th><th>类型</th><th>角色</th><th>全称</th><th>关联简称</th><th>指定代号</th></tr></thead>'
             '<tbody>' + groups_html + '</tbody></table>' if groups else ''}
            {'<h3>识别到的地名</h3><ul class="tag-list">' + locations_html + '</ul>' if locations else ''}
            <div style="margin-top:30px; border-top:1px solid #eee; padding-top:20px; display:flex; gap:10px">
              <button type="submit" name="action" value="continue" class="btn">确认并继续分析</button>
              <button type="submit" name="action" value="finish" class="btn btn-secondary">完成脱敏</button>
            </div>
          </form>
        </section>
        <style>
          .audit-table {{ width:100%; border-collapse:collapse; margin:20px 0; }}
          .audit-table th, .audit-table td {{ padding:12px; border-bottom:1px solid #eee; text-align:left; }}
          .tag {{ padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
          .type-organization {{ background:#f0f7ff; color:#0052cc; }}
          .type-person {{ background:#fff7e6; color:#d46b08; }}
          .role-原告 {{ color:#52c41a; }}
          .role-被告 {{ color:#ff4d4f; }}
          .mask-input {{ border:1px solid #ddd; padding:5px; border-radius:4px; width:100px; }}
          .tag-list {{ list-style:none; padding:0; display:flex; flex-wrap:wrap; gap:10px; }}
          .tag-list li {{ background:#f5f5f5; padding:5px 12px; border-radius:20px; font-size:13px; }}
          .round-badge {{ font-size:13px; background:var(--accent); color:#fff; padding:2px 10px; border-radius:99px; font-weight:500 }}
          .locked-section {{ margin-bottom:18px; padding:12px; background:var(--bg); border-radius:var(--radius-sm); border:1px solid var(--border) }}
          .locked-section summary {{ cursor:pointer; font-weight:600; color:var(--muted); font-size:13px }}
          .locked-table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:12px }}
          .locked-table td {{ padding:6px 8px; border-bottom:1px solid var(--border) }}
          .locked-row {{ opacity:0.55 }}
          .tag-locked {{ background:#d4edda; color:#155724 }}
          .badge {{ background:var(--ink); color:#fff; padding:1px 7px; border-radius:99px; font-size:11px; font-weight:600 }}
        </style>
        """
    )


def _recognition_stats_from_analysis(analysis: dict[str, Any]) -> RecognitionRunStats | None:
    payload = analysis.get("recognition_stats")
    if not isinstance(payload, dict):
        return None
    try:
        return RecognitionRunStats(
            mode=str(payload["mode"]),
            model_id=str(payload["model_id"]) if payload.get("model_id") is not None else None,
            status=str(payload["status"]),
            document_count=int(payload.get("document_count", 1)),
            call_count=int(payload.get("call_count", 0)),
            retry_count=int(payload.get("retry_count", 0)),
            fallback_count=int(payload.get("fallback_count", 0)),
            conflict_count=int(payload.get("conflict_count", 0)),
            duration_ms=int(payload.get("duration_ms", 0)),
            reason=str(payload["reason"]) if payload.get("reason") is not None else None,
            fallback_from_mode=str(payload["fallback_from_mode"]) if payload.get("fallback_from_mode") is not None else None,
            http_status=int(payload["http_status"]) if payload.get("http_status") is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _recognition_reason_label(reason: str | None) -> str:
    labels = {
        "input_too_large": "文书超过全文模式字符上限",
        "llm_disabled": "LLM 未启用",
        "invalid_registry_payload": "模型返回的实体登记 JSON 无效或不完整",
        "invalid_do_not_merge_reference": "模型返回了无效的不合并引用",
        "invalid_uncertain_reference": "模型返回了无效的不确定实体引用",
        "timeout": "模型调用超时",
    }
    value = reason or "unknown"
    if value.startswith("http_"):
        return f"模型 API 返回 HTTP {value.removeprefix('http_')}"
    return labels.get(value, value)


def _render_recognition_stats(stats: RecognitionRunStats | None) -> str:
    if stats is None:
        return ""
    mode_label = RECOGNITION_MODE_LABELS.get(stats.mode, stats.mode)
    status_label = RECOGNITION_STATUS_LABELS.get(stats.status, stats.status)
    model_id = stats.model_id or "无"
    seconds = max(0, stats.duration_ms) / 1000
    fallback_label = "是" if stats.fallback_count else "否"
    fallback_details = ""
    if stats.fallback_count:
        source_mode = RECOGNITION_MODE_LABELS.get(stats.fallback_from_mode or "", stats.fallback_from_mode or "未知")
        reason = stats.reason or "unknown"
        reason_label = _recognition_reason_label(reason)
        http_status = str(stats.http_status) if stats.http_status is not None else "无"
        fallback_details = (
            f'<p class="hint">Fallback 来源：{html.escape(source_mode)}；'
            f'原因：{html.escape(reason_label)}（{html.escape(reason)}）；HTTP：{html.escape(http_status)}</p>'
        )
    return (
        '<section class="info-card recognition-summary">'
        '<h2>识别运行摘要</h2>'
        f'<p class="hint">模式：{html.escape(mode_label)}；'
        f'逻辑模型：{html.escape(model_id)}；状态：{html.escape(status_label)}；'
        f'文档数：{stats.document_count}；调用数：{stats.call_count}；'
        f'识别耗时：{seconds:.2f} 秒；降级：{fallback_label}；'
        f'冲突数：{stats.conflict_count}</p>'
        f'{fallback_details}'
        '</section>'
    )


def _render_redaction_result(
    title: str, original_text: str, redacted_text: str, redaction_map: RedactionMap,
    review_candidates: list, leaks: list, warnings: list[str], save_dir: str = "",
    discord_thread_url: str = "", case_root: str = "", case_folder: str = "", source_dir: str = "",
    recognition_stats: RecognitionRunStats | None = None, document: RedactedDocument | None = None,
    source_document: InputDocument | None = None,
) -> str:
    default_dir = save_dir.strip() or os.path.expanduser("~/Desktop")
    map_json = redaction_map_to_json(redaction_map)
    from ..debug_trace import debug_trace_from_parts, debug_trace_to_json
    debug_json = debug_trace_to_json(debug_trace_from_parts(mode=redaction_map.mode, source_file=redaction_map.source_file, mappings=redaction_map.mappings, documents=[{"source_file": redaction_map.source_file, "original_text": original_text, "redacted_text": redacted_text}], review_candidates=review_candidates, leaks=leaks, warnings=warnings))
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    artifact = document if document and document.output_bytes is not None else None
    redacted_filename = artifact.output_filename if artifact else "redacted.txt"
    redacted_url = _binary_download(XLSX_MEDIA_TYPE, artifact.output_bytes) if artifact else _data_download(redacted_filename, "text/plain", redacted_text)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
    debug_url = _data_download("debug_trace.json", "application/json", debug_json)
    disable_discord = artifact is not None
    workflow_panel = workflow._render_case_workflow_panel(case_root=case_root, case_folder=case_folder, discord_thread_url=discord_thread_url, saved_local=bool(case_folder))
    mapping_edit_rows = _render_mapping_edit_rows(redaction_map, review_candidates)
    discord_create_section = "" if disable_discord else _discord_create_thread_section(discord_thread_url=discord_thread_url, case_root=case_root, case_folder=case_folder, source_dir=source_dir or save_dir, filename=redacted_filename, textarea_id="redacted-output", map_textarea_id="mapping-json-output", message_id="discord-create-message")
    discord_section = "" if disable_discord else _discord_send_section(discord_thread_url, redacted_filename, "redacted-output", "discord-message")
    bundle_json = _documents_bundle_json([document], sources=[source_document]) if document and source_document else ""
    return render_redaction_result_page(title=title, redacted_filename=redacted_filename, redacted_url=redacted_url, map_url=map_url, debug_url=debug_url, workflow_panel=workflow_panel, default_dir=default_dir, redacted_filename_json=json.dumps(redacted_filename, ensure_ascii=False), save_dir=save_dir, discord_create_section=discord_create_section, discord_section=discord_section, leaks_html=leaks_html, warnings_html=warnings_html, recognition_summary=_render_recognition_stats(recognition_stats), original_highlight=_highlight_replaced_text(original_text, redaction_map.mappings), redacted_text=redacted_text, redacted_highlight=_highlight_replaced_text(redacted_text, redaction_map.mappings, reverse=True), mapping_review_toolbar=_render_mapping_review_toolbar(redaction_map, review_candidates), sample_summary_panel=_render_sample_summary_panel(), original_text=original_text, map_json=map_json, review_candidate_texts_json=_review_candidate_texts_json(review_candidates), debug_json=debug_json, discord_thread_url=discord_thread_url, case_root=case_root, case_folder=case_folder, source_dir=source_dir, redaction_map=redaction_map, mapping_edit_rows=mapping_edit_rows, review_html="".join("<tr><td>{}</td><td>{}</td><td>{}</td><td>{:.2f}</td><td>{}</td></tr>".format(html.escape(c.type), html.escape(c.text), html.escape(c.source), c.confidence, html.escape(c.reason or "")) for c in review_candidates), bundle_json=bundle_json)


def _render_batch_redaction_result(
    title: str,
    documents: list[RedactedDocument],
    redaction_map: RedactionMap,
    review_candidates: list,
    leaks: list,
    warnings: list[str],
    save_dir: str = "",
    discord_thread_url: str = "",
    case_root: str = "",
    case_folder: str = "",
    source_dir: str = "",
    recognition_stats: RecognitionRunStats | None = None,
    source_documents: list[InputDocument] | None = None,
) -> str:
    default_dir = save_dir.strip() or os.path.expanduser("~/Desktop")

    individual_files = []
    used_names: dict[str, int] = {}
    for index, document in enumerate(documents, start=1):
        if document.output_bytes is not None:
            stem = PurePosixPath(document.source_file.replace("\\", "/")).stem or "redacted"
            base_name = f"{stem}.redacted.xlsx"
            used_names[base_name] = used_names.get(base_name, 0) + 1
            count = used_names[base_name]
            out_name = base_name if count == 1 else f"{stem}-{count}.redacted.xlsx"
            individual_files.append({"filename": out_name, "mime": XLSX_MEDIA_TYPE, "base64": base64.b64encode(document.output_bytes).decode("ascii")})
        else:
            out_name = f"document-{index}.redacted.txt"
            individual_files.append({"filename": out_name, "content": document.redacted_text, "mime": "text/plain"})
    individual_files_json = json.dumps(individual_files, ensure_ascii=False)
    map_json = redaction_map_to_json(redaction_map)
    bundle_json = _documents_bundle_json(documents, sources=source_documents or [InputDocument(d.source_file, d.original_text) for d in documents])
    combined_redacted = "\n\n".join(d.redacted_text for d in documents)
    from ..debug_trace import debug_trace_from_parts, debug_trace_to_json

    debug_json = debug_trace_to_json(
        debug_trace_from_parts(
            mode=redaction_map.mode,
            source_file=redaction_map.source_file,
            mappings=redaction_map.mappings,
            documents=[
                {
                    "source_file": document.source_file,
                    "original_text": document.original_text,
                    "redacted_text": document.redacted_text,
                }
                for document in documents
            ],
            review_candidates=review_candidates,
            leaks=leaks,
            warnings=warnings,
        )
    )
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    recognition_summary = _render_recognition_stats(recognition_stats)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
    debug_url = _data_download("debug_trace.json", "application/json", debug_json)
    combined_filename = "batch.redacted.txt"
    combined_filename_json = json.dumps(combined_filename, ensure_ascii=False)
    redacted_url = _data_download(combined_filename, "text/plain", combined_redacted)
    disable_discord = any(document.output_bytes is not None for document in documents)
    discord_create_section = "" if disable_discord else _discord_create_thread_section(
        discord_thread_url=discord_thread_url,
        case_root=case_root,
        case_folder=case_folder,
        source_dir=source_dir or save_dir,
        filename=combined_filename,
        textarea_id="redacted-output",
        map_textarea_id="mapping-json-output",
        message_id="discord-create-message-batch",
    )
    discord_section = "" if disable_discord else _discord_send_section(discord_thread_url, combined_filename, "redacted-output", "discord-message-batch")
    workflow_panel = workflow._render_case_workflow_panel(
        case_root=case_root,
        case_folder=case_folder,
        discord_thread_url=discord_thread_url,
        saved_local=bool(case_folder),
    )
    mapping_review_toolbar = _render_mapping_review_toolbar(redaction_map, review_candidates)
    sample_summary_panel = _render_sample_summary_panel()
    review_candidate_texts_json = _review_candidate_texts_json(review_candidates)
    doc_sections_parts: list[str] = []
    for index, document in enumerate(documents):
        if document.output_bytes is not None:
            item = individual_files[index]
            filename = str(item["filename"])
            link = _binary_download(XLSX_MEDIA_TYPE, document.output_bytes)
            download_html = f'<p><a class="btn" data-no-intercept="true" download="{html.escape(filename, quote=True)}" href="{link}">下载脱敏 Excel</a></p>'
        else:
            filename = str(individual_files[index]["filename"])
            link = _data_download(filename, "text/plain", document.redacted_text)
            download_html = f'<p><a class="btn" data-no-intercept="true" download="{html.escape(filename, quote=True)}" href="{link}">下载脱敏文本</a></p>'
        doc_sections_parts.append(
            f'<article class="doc-result"><h3>{html.escape(document.source_file)}</h3>{download_html}'
            f'<h4>原文高亮</h4><div class="highlight-box original-highlight selection-add-source">{_highlight_replaced_text(document.original_text, redaction_map.mappings)}</div>'
            f'<h4>脱敏文</h4><div class="highlight-box redacted-highlight">{_highlight_replaced_text(document.redacted_text, redaction_map.mappings, reverse=True)}</div></article>'
        )
    doc_sections = "".join(doc_sections_parts)
    mapping_edit_rows = _render_mapping_edit_rows(redaction_map, review_candidates)
    return render_batch_redaction_result_page(
        title=title,
        combined_filename=combined_filename,
        redacted_url=redacted_url,
        map_url=map_url,
        debug_url=debug_url,
        combined_redacted=combined_redacted,
        workflow_panel=workflow_panel,
        default_dir=default_dir,
        combined_filename_json=combined_filename_json,
        save_dir=save_dir,
        individual_files_json=individual_files_json,
        discord_create_section=discord_create_section,
        discord_section=discord_section,
        leaks_html=leaks_html,
        warnings_html=warnings_html,
        recognition_summary=recognition_summary,
        doc_sections=doc_sections,
        mapping_review_toolbar=mapping_review_toolbar,
        sample_summary_panel=sample_summary_panel,
        bundle_json=bundle_json,
        map_json=map_json,
        review_candidate_texts_json=review_candidate_texts_json,
        debug_json=debug_json,
        discord_thread_url=discord_thread_url,
        case_root=case_root,
        case_folder=case_folder,
        source_dir=source_dir,
        redaction_map=redaction_map,
        mapping_edit_rows=mapping_edit_rows,
    )

