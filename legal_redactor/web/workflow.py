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




def _redaction_failure_body(exc: Exception) -> str:
    suggestion = "建议：确认所选 API 模型仍可用后重试。"
    return f"<p>{html.escape(str(exc))}</p><p>{html.escape(suggestion)}</p>"



def _reject_forged_workflow_fields(body: dict) -> JSONResponse | None:
    try:
        raise_for_forged_workflow_fields(body)
    except InvalidWorkflowInputError as exc:
        return JSONResponse(
            {
                "status": "error",
                "code": exc.code,
                "fields": exc.fields,
                "message": str(exc),
            },
            status_code=400,
        )
    return None



def _reject_forged_workflow_form_data(form: dict) -> HTMLResponse | None:
    try:
        raise_for_forged_workflow_fields(form)
    except InvalidWorkflowInputError as exc:
        return HTMLResponse(
            _page(
                "请求无效",
                (
                    f'<p class="error">INVALID_INPUT：请求包含不能由浏览器提交的工作流决策字段。</p>'
                    f'<p class="hint">字段：{html.escape(", ".join(exc.fields))}</p>'
                ),
            ),
            status_code=400,
        )
    return None



def _case_error_response(message: str, *, code: str = "case_error", status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {
            "status": "error",
            "workflow_state": "attach_failed",
            "code": code,
            "message": _safe_public_error_message(message),
        },
        status_code=status_code,
    )



def _waiting_hermes_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "pending",
            "workflow_state": "waiting_hermes",
            "message": "等待 Hermes 写回 Discord 帖子链接",
        },
        status_code=202,
    )



def _render_case_workflow_panel(
    *,
    case_root: str = "",
    case_folder: str = "",
    discord_thread_url: str = "",
    saved_local: bool = False,
    hermes_requested: bool = False,
    attach_status: str = "",
    attach_error: str | None = None,
) -> str:
    status = case_workflow_public(
        case_root=case_root,
        case_folder=case_folder,
        discord_thread_url=discord_thread_url,
        saved_local=saved_local,
        hermes_requested=hermes_requested,
        attach_status=attach_status,
        attach_error=attach_error,
    )
    state = str(status.get("workflow_state", "not_saved"))
    message = str(status.get("message") or workflow_state_message(state, attach_error=attach_error))
    case_label = case_folder.strip() or "未选择案件"
    thread_url = str(status.get("discord_thread_url") or discord_thread_url or "").strip()
    next_action = {
        "not_saved": "可先保存到本地案件，或填写案件目录后请求 Hermes 建帖。",
        "saved_local": "可继续绑定 Discord 帖子。",
        "bound_thread": "可发送脱敏附件到 Discord。",
        "sent_discord": "等待 Discord/Hermes 后续审查起草。",
        "waiting_hermes": "稍后继续检查并绑定帖子。",
        "attach_failed": "检查失败原因后可再次发送附件。",
    }.get(state, "可继续处理案件流程。")
    thread_html = (
        f'<a href="{html.escape(thread_url, quote=True)}" target="_blank" rel="noopener">打开 Discord 帖子</a>'
        if thread_url
        else '<span class="hint">尚未绑定 Discord 帖子</span>'
    )
    manifest = status.get("manifest") if isinstance(status.get("manifest"), dict) else {}
    restore = manifest.get("restore") if isinstance(manifest.get("restore"), dict) else {}
    mapping_label = "已就绪" if manifest.get("mapping_present") else "缺失"
    restore_filename = str(restore.get("restored_filename") or "")
    restore_label = restore_filename or {
        "missing_map": "等待映射表",
        "no_restore_yet": "尚无还原文件",
        "metadata_unknown": "已有文件，缺少元数据",
        "restore_failed": "最近还原失败",
    }.get(str(restore.get("status") or ""), "尚无还原文件")
    unresolved = restore.get("unresolved_placeholder_count")
    unresolved_label = "未知" if unresolved is None else str(unresolved)
    return f"""
        <section class="case-workflow-panel" data-workflow-state="{html.escape(state, quote=True)}">
          <div class="workflow-head">
            <span class="workflow-pill workflow-{html.escape(state, quote=True)}">{html.escape(_workflow_state_label(state))}</span>
            <strong>案件流程状态</strong>
          </div>
          <div class="workflow-grid">
            <span><b>案件</b>{html.escape(case_label)}</span>
            <span><b>状态</b>{html.escape(message)}</span>
            <span><b>线程</b>{thread_html}</span>
            <span><b>下一步</b>{html.escape(next_action)}</span>
            <span><b>映射表</b>{html.escape(mapping_label)}</span>
            <span><b>还原状态</b>{html.escape(restore_label)}</span>
            <span><b>未解析占位符</b>{html.escape(unresolved_label)}</span>
          </div>
        </section>
    """



def _workflow_state_label(state: str) -> str:
    return {
        "not_saved": "未保存",
        "saved_local": "本地已保存",
        "bound_thread": "已绑定",
        "sent_discord": "已发送",
        "waiting_hermes": "等 Hermes",
        "attach_failed": "附件失败",
    }.get(state, state)



def _should_apply_auto_prefill(current_value: str, previous_auto_value: str) -> bool:
    current = current_value.strip()
    return not current or current == previous_auto_value



def _persist_optional_case_redaction(
    case_root: str,
    case_folder: str,
    discord_thread_url: str,
    documents: list[RedactedDocument],
    redaction_map: RedactionMap,
    *,
    source_dir: str = "",
) -> None:
    has_case_folder = bool(case_folder.strip())
    has_thread_url = bool(discord_thread_url.strip())
    if not has_case_folder and not has_thread_url:
        return
    if not has_case_folder and has_thread_url:
        raise CaseError("填写 Discord 帖子链接时必须同时填写案件文件夹名")
    source_root = case_root_from_source_dir(source_dir, case_folder)
    root = str(source_root) if source_root is not None else case_root.strip()
    root = root or str(default_case_root())
    persist_case_redaction(
        root,
        case_folder,
        discord_thread_url,
        documents,
        redaction_map,
        source_dir=source_dir.strip() or None,
    )



def _apply_requested_thread_preflight(result: dict[str, object], requested_thread: str) -> None:
    try:
        binding = case_thread_binding_status(
            str(result.get("case_root", "")),
            str(result.get("case_folder", "")),
            requested_thread,
        )
    except CaseError as exc:
        result.update(
            {
                "status": "conflict",
                "conflict": True,
                "conflict_code": getattr(exc, "code", "case_error"),
                "conflict_message": str(exc),
            }
        )
        return
    if binding.get("conflict"):
        result.update(
            {
                "status": "conflict",
                "conflict": True,
                "conflict_code": binding.get("code"),
                "conflict_message": binding.get("message"),
            }
        )



def _safe_public_error_message(message: str) -> str:
    text = str(message)
    path_pattern = re.compile(
        r"(?:"
        r"[A-Za-z]:[\\/](?:[^\s\"'，。；;\\/]+[\\/])*[^\s\"'，。；;\\/]+"
        r"|\\\\[^\s\"'，。；;\\/]+[\\/][^\s\"'，。；;\\/]+(?:[\\/][^\s\"'，。；;\\/]+)*"
        r"|/(?:[^\s\"'，。；;/]+/)*[^\s\"'，。；;/]+"
        r"|~/(?:[^\s\"'，。；;/]+/)*[^\s\"'，。；;/]+"
        r")"
    )
    return path_pattern.sub("<local-path>", text)



def _case_manifest_fields(case_dir_path: Path) -> dict[str, str]:
    return {
        key: value
        for key, value in manifest_fields_for_case_dir(case_dir_path).items()
        if key in {"discord_thread_url", "discord_thread_id", "workflow_state", "manifest"}
    }
