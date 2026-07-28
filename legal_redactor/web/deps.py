"""Injectable dependencies for the web layer.

Routes and services import patchable names from this module so tests can
``patch("legal_redactor.web.deps.RedactionPipeline", ...)`` (and the
``legal_redactor.web_app`` facade re-exports the same names for older imports).
"""
from __future__ import annotations

from ..config import PipelineConfig
from ..counters import CN_ORDINALS, TypeCounters
from ..excel_io import (
    EXCEL_INPUT_SUFFIXES,
    XLSX_MEDIA_TYPE,
    ExcelFormulaLeakError,
    extract_workbook_text,
    redact_workbook,
)
from ..io import redaction_map_from_json, redaction_map_to_json
from ..llm import is_noise_entity_text
from ..local_config import config_value, load_json_config
from ..model_manager import DEFAULT_MODEL_ID
from ..models import (
    MappingEntry,
    RecognitionRunStats,
    RedactedDocument,
    RedactionMap,
    sort_mapping_entries,
)
from ..org_masking import derived_organization_alias_cores
from ..pipeline import RecognitionUnavailableError, RedactionPipeline
from ..postprocess import _filter_noise_entity_mappings
from ..restore import preview_restore, restore_docx
from ..status import build_status_payload, probe_model_manager
from ..web_templates import (
    MAPPING_REVIEW_CATEGORY_LABELS,
    RESTORE_RISK_REASON_LABELS,
    _page,
    render_batch_redaction_result_page,
    render_home_page,
    render_redaction_result_page,
    render_status_panel,
)

try:
    from fastapi import File, Form, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:
    raise RuntimeError("启动 Web UI 需要先安装依赖：pip install -r requirements.txt") from exc

__all__ = [
    "PipelineConfig",
    "CN_ORDINALS",
    "TypeCounters",
    "EXCEL_INPUT_SUFFIXES",
    "XLSX_MEDIA_TYPE",
    "ExcelFormulaLeakError",
    "extract_workbook_text",
    "redact_workbook",
    "redaction_map_from_json",
    "redaction_map_to_json",
    "is_noise_entity_text",
    "config_value",
    "load_json_config",
    "DEFAULT_MODEL_ID",
    "MappingEntry",
    "RecognitionRunStats",
    "RedactedDocument",
    "RedactionMap",
    "sort_mapping_entries",
    "derived_organization_alias_cores",
    "RecognitionUnavailableError",
    "RedactionPipeline",
    "_filter_noise_entity_mappings",
    "preview_restore",
    "restore_docx",
    "build_status_payload",
    "probe_model_manager",
    "MAPPING_REVIEW_CATEGORY_LABELS",
    "RESTORE_RISK_REASON_LABELS",
    "_page",
    "render_batch_redaction_result_page",
    "render_home_page",
    "render_redaction_result_page",
    "render_status_panel",
    "File",
    "Form",
    "Request",
    "UploadFile",
    "HTMLResponse",
    "JSONResponse",
]
