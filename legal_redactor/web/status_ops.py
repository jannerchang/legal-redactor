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




_render_status_panel = render_status_panel


def health() -> dict[str, str]:
    return {"status": "ok", "bind_host": "127.0.0.1", "network": "offline"}



def api_status() -> dict:
    return _status_payload()



def api_models() -> JSONResponse:
    try:
        payload = _model_manager_json("/v1/models")
    except (OSError, ValueError, http.client.HTTPException):
        return JSONResponse({"object": "list", "data": []}, status_code=503)
    return JSONResponse(payload)



def api_model_status() -> dict[str, Any]:
    return deps.probe_model_manager().to_dict()



def _model_manager_json(path: str, *, timeout: float = 1.5) -> dict[str, Any]:
    status = deps.probe_model_manager(timeout=timeout)
    control_plane_reachable = status.state == "ready" or (
        status.state == "error" and status.details.get("reason") == "worker_error"
    )
    if not control_plane_reachable:
        raise OSError("model manager unavailable")
    host = str(status.details.get("host") or "")
    port = int(status.details.get("port") or 0)
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status >= 400:
        raise OSError("model manager request failed")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("invalid model manager response")
    return payload



def _available_model_options() -> list[dict[str, str]]:
    try:
        payload = _model_manager_json("/v1/models", timeout=0.4)
    except (OSError, ValueError, http.client.HTTPException, json.JSONDecodeError):
        return []
    options: list[dict[str, str]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            options.append({"id": model_id, "label": str(item.get("name") or model_id)})
    return options


def _available_model_default() -> str | None:
    try:
        payload = _model_manager_json("/v1/models", timeout=0.4)
    except (OSError, ValueError, http.client.HTTPException, json.JSONDecodeError):
        return None
    value = str(payload.get("default_model_id") or "").strip()
    return value or None



def _pipeline_config_for_model_status(
    *,
    profile: str = "standard",
    llm_mode: str = "max-effect",
    model: str = DEFAULT_MODEL_ID,
    recognition_mode: str = "full_document",
) -> tuple[PipelineConfig, list[str]]:
    status = deps.probe_model_manager()
    recoverable_worker_error = status.state == "error" and status.details.get("reason") == "worker_error"
    if status.state != "ready" and not recoverable_worker_error:
        raise deps.RecognitionUnavailableError("本地模型 API 未就绪")
    try:
        model_ids = {item["id"] for item in _available_model_options()}
    except (KeyError, TypeError) as exc:
        raise deps.RecognitionUnavailableError("本地模型列表无效") from exc
    if model not in model_ids:
        raise deps.RecognitionUnavailableError("所选模型当前不可用")
    try:
        return PipelineConfig.from_llm_mode(
            llm_mode,
            profile_name=profile,
            model=model,
            recognition_mode=recognition_mode,
        ), []
    except ValueError as exc:
        raise deps.RecognitionUnavailableError("本地模型 API 配置无效") from exc



def _status_payload() -> dict:
    return deps.build_status_payload(model_timeout=0.4)
