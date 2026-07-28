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


from .models import SUPPORTED_UPLOAD_SUFFIXES
from .documents import _suffix_for_filename
from .workflow import _apply_requested_thread_preflight, _reject_forged_workflow_fields


async def suggest_case_location(request: Request) -> JSONResponse:
    body = await request.json()
    invalid = _reject_forged_workflow_fields(body)
    if invalid is not None:
        return invalid
    filenames = body.get("filenames", [])
    roots = []
    case_root = str(body.get("case_root", "")).strip()
    if case_root and not _is_default_case_root_value(case_root):
        roots.append(Path(case_root).expanduser())
    relative_paths = body.get("relative_paths") or body.get("upload_relative_paths") or []
    safe_relative_paths = _safe_upload_relative_paths(relative_paths)
    if safe_relative_paths:
        relative_suggestion = _suggest_case_location_from_relative_paths(
            safe_relative_paths,
            roots or None,
            discord_thread_url=str(body.get("discord_thread_url", "")).strip(),
        )
        return JSONResponse(relative_suggestion)
    suggestion = suggest_case_location_from_filenames(
        filenames,
        roots or None,
        source_dir=str(body.get("source_dir") or body.get("upload_source_dir") or "").strip(),
        discord_thread_url=str(body.get("discord_thread_url", "")).strip(),
    )
    return JSONResponse(suggestion)



def _is_default_case_root_value(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    try:
        return Path(candidate).expanduser().resolve() == default_case_root().expanduser().resolve()
    except OSError:
        return Path(candidate).expanduser() == default_case_root().expanduser()



def _resolve_case_location(upload_source_dir: str, source_files: list[str], upload_relative_paths: str = "") -> dict[str, object]:
    source_dir = upload_source_dir.strip()
    if source_dir:
        return suggest_case_location_from_filenames(source_files, source_dir=source_dir)
    relative_paths = _safe_upload_relative_paths(upload_relative_paths)
    if relative_paths:
        return _suggest_case_location_from_relative_paths(relative_paths)
    suggestion = suggest_case_location_from_filenames(source_files)
    if suggestion.get("status") == "ok":
        return suggestion
    return {"status": "not_found"}



def _find_case_directories(
    root: Path,
    case_folder: str,
    *,
    max_depth: int = 5,
    max_entries: int = 30000,
) -> list[Path]:
    try:
        resolved_root = root.expanduser().resolve()
    except OSError:
        return []
    if not resolved_root.is_dir():
        return []
    if resolved_root.name == case_folder:
        return [resolved_root]

    matches: list[Path] = []
    visited = 0
    for current, dirs, files in os.walk(resolved_root):
        visited += len(dirs) + len(files)
        if visited > max_entries:
            break
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(resolved_root).parts)
        except ValueError:
            continue
        dirs[:] = [
            item
            for item in dirs
            if not item.startswith(".")
            and item not in {"__pycache__", ".git", ".venv", ".ff-state", "node_modules"}
        ]
        if case_folder in dirs:
            matches.append((current_path / case_folder).resolve())
        if depth >= max_depth:
            dirs[:] = []
    return matches



def _suggest_case_location_from_relative_paths(
    relative_paths: object,
    search_roots: list[Path] | None = None,
    *,
    discord_thread_url: str = "",
) -> dict[str, object]:
    paths = _safe_upload_relative_paths(relative_paths)
    case_folder = _case_folder_from_relative_paths(paths)
    if not case_folder:
        return {"status": "not_found", "workflow_state": "not_saved", "evidence": []}

    roots = search_roots or case_location_search_roots()
    existing_dirs: list[Path] = []
    for root in roots:
        existing_dirs.extend(_find_case_directories(Path(root), case_folder))

    unique_dirs = sorted({path for path in existing_dirs}, key=str)
    if len(unique_dirs) > 1:
        return {
            "status": "ambiguous",
            "workflow_state": "not_saved",
            "confidence": 0.0,
            "matches": [str(path) for path in unique_dirs[:8]],
            "candidates": [_case_folder_hint_summary(path.parent, case_folder, matched_dir=path) for path in unique_dirs[:8]],
            "evidence": [{"kind": "ambiguous_case_directory", "count": len(unique_dirs)}],
        }

    if not unique_dirs:
        return {
            "status": "not_found",
            "workflow_state": "not_saved",
            "evidence": [{"kind": "upload_relative_path", "case_folder": case_folder}],
        }
    result = _case_folder_hint_summary(unique_dirs[0].parent, case_folder, matched_dir=unique_dirs[0])
    result["confidence"] = 0.98
    result["status"] = "ok"
    result["evidence"] = [
        {"kind": "upload_relative_path", "case_folder": case_folder},
        *list(result.get("evidence", [])),
    ]
    requested_thread = discord_thread_url.strip()
    if requested_thread:
        _apply_requested_thread_preflight(result, requested_thread)
    return result



def _safe_upload_relative_paths(value: object) -> list[str]:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = [raw]
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []

    paths: list[str] = []
    for item in parsed:
        path = str(item or "").replace("\\", "/").strip()
        if not path or path.startswith("/") or path.startswith("~"):
            continue
        pure = PurePosixPath(path)
        if any(part in {"", ".", ".."} for part in pure.parts):
            continue
        if pure.name.startswith("._") or _suffix_for_filename(pure.name) not in SUPPORTED_UPLOAD_SUFFIXES:
            continue
        paths.append(str(pure))
    return paths



def _case_folder_from_relative_paths(paths: list[str]) -> str:
    folder = ""
    for value in paths:
        parts = PurePosixPath(value).parts
        if len(parts) < 2:
            continue
        current = parts[0]
        if not folder:
            folder = current
        elif folder != current:
            return ""
    if not folder:
        return ""
    try:
        return validate_case_folder_name(folder)
    except CaseError:
        return ""



def _case_folder_hint_summary(case_root: Path, case_folder: str, *, matched_dir: Path | None = None) -> dict[str, object]:
    case_path = matched_dir or (case_root / case_folder)
    result: dict[str, object] = {
        "case_folder": case_folder,
        "case_root": str(Path(case_root).expanduser()),
        "matched_dir": str(matched_dir) if matched_dir else "",
        "ambiguous": False,
        "conflict": False,
    }
    evidence = list(result.get("evidence", []))
    manifest_data = manifest_fields_for_case_dir(case_path)
    result.update(manifest_data)
    result["evidence"] = evidence + list(manifest_data.get("evidence", []))
    result.setdefault("workflow_state", case_workflow_state(discord_thread_url=str(result.get("discord_thread_url", ""))))
    return result
