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




SAMPLE_SUMMARY_KEYS = (
    "lookup_entries",
    "delete_blacklist_candidates",
    "suppressed_risky_entries",
    "manual_corrections",
    "false_positive_deletes",
    "missing_adds",
    "manual_modify_count",
    "restore_unresolved_placeholders",
    "newest_sample_provenance",
    "regression_suggestions",
)


SUPPORTED_UPLOAD_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".pdf", *EXCEL_INPUT_SUFFIXES}


RECOGNITION_MODE_LABELS = {
    "full_document": "整篇文书（LLM 双轮补漏）",
}


RECOGNITION_STATUS_LABELS = {
    "not_requested": "未请求",
    "success": "成功",
    "partial": "部分成功",
    "no_targets": "未发现目标",
    "fallback": "已降级",
    "hard_failure": "失败",
}


@dataclass(frozen=True)
class InputDocument:
    source_file: str
    text: str
    source_bytes: bytes | None = None
    source_suffix: str = ".txt"



class DiscordApiError(RuntimeError):
    code = "discord_api_error"
