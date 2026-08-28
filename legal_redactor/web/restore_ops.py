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


from .documents import (
    _binary_download,
    _data_download,
    _decode_text_bytes,
    _docx_bytes_to_text,
    _read_restore_map_text,
    _suffix_for_filename,
)
from .mapping_ops import _restore_risk_reasons


async def restore_preview_page(
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    map_json: str = Form(default=""),
    map_file: UploadFile | None = File(default=None),
    restore_docx_format: str | None = Form(default=None),
) -> str:
    try:
        redacted_text = text.strip()
        redacted_docx_bytes: bytes | None = None
        redacted_filename = ""
        if file and file.filename:
            data = await file.read()
            redacted_filename = file.filename
            if _suffix_for_filename(file.filename) == ".docx":
                redacted_docx_bytes = data
                redacted_text = _docx_bytes_to_text(data)
            else:
                redacted_text = _decode_text_bytes(data, file.filename)
        map_text = await _read_restore_map_text(map_json, map_file)

        if not map_text or not redacted_text:
            return _page("参数缺失", '<nav><a href="/">返回</a></nav><section class="warning"><p>请粘贴或上传脱敏文本/Word，并提供映射表。</p></section>')

        redaction_map = redaction_map_from_json(map_text)
        if redacted_docx_bytes is not None and restore_docx_format:
            return _render_docx_restore_result(redacted_docx_bytes, redacted_filename, redaction_map)
        preview = preview_restore(redacted_text, redaction_map)
    except Exception as exc:
        return _page("还原错误", f'<nav><a href="/">返回</a></nav><section class="warning"><p>{html.escape(str(exc))}</p></section>')

    restored_url = _data_download("restored.txt", "text/plain", preview.restored_text)
    restored_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in preview.restored_entries
    )
    return _page("还原预览", f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads"><a download="restored.txt" href="{restored_url}" class="btn">下载还原文本</a></div>



        <section class="grid">
          <div><h2>脱敏文本</h2><textarea rows="20" readonly>{html.escape(redacted_text)}</textarea></div>
          <div><h2>还原后</h2><textarea id="restored-output" rows="20" readonly>{html.escape(preview.restored_text)}</textarea></div>
        </section>
        <section>
          <h2>已还原</h2><table><thead><tr><th>类型</th><th>占位符</th><th>原文</th></tr></thead><tbody>{restored_rows}</tbody></table>
          <details><summary>差异预览</summary><pre>{html.escape(preview.diff)}</pre></details>
        </section>
    """)



def _render_docx_restore_result(
    redacted_docx_bytes: bytes,
    redacted_filename: str,
    redaction_map: RedactionMap,
) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "redacted.docx"
        output_path = temp_path / "restored.docx"
        input_path.write_bytes(redacted_docx_bytes)
        replacements = restore_docx(input_path, output_path, redaction_map)
        restored_bytes = output_path.read_bytes()

    stem = Path(redacted_filename or "restored.docx").stem
    restored_filename = f"{stem}.restored.docx"
    restored_url = _binary_download(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        restored_bytes,
    )
    restored_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in redaction_map.mappings
    )
    return _page("Word 还原完成", f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{html.escape(restored_filename)}" href="{restored_url}" class="btn">下载还原 Word</a>
        </div>
        <section class="info-card">
          <h2>还原完成</h2>
          <p>已按映射表生成保留格式的 Word 文档。</p>
          <p class="hint">替换次数：{replacements}；映射条目：{len(redaction_map.mappings)}。</p>
        </section>
        <section>
          <h2>映射表条目</h2>
          <table><thead><tr><th>类型</th><th>占位符</th><th>原文</th></tr></thead><tbody>{restored_rows}</tbody></table>
        </section>
    """)
