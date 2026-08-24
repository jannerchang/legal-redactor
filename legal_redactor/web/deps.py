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
from ..ocr import (
    OCRUnavailableError,
    extract_pdf_text,
    ocr_runtime,
    pdf_page_texts,
    take_ocr_output_paths,
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
    "CN_ORDINALS",
    "DEFAULT_MODEL_ID",
    "EXCEL_INPUT_SUFFIXES",
    "MAPPING_REVIEW_CATEGORY_LABELS",
    "RESTORE_RISK_REASON_LABELS",
    "XLSX_MEDIA_TYPE",
    "ExcelFormulaLeakError",
    "File",
    "Form",
    "HTMLResponse",
    "JSONResponse",
    "MappingEntry",
    "OCRUnavailableError",
    "PipelineConfig",
    "RecognitionRunStats",
    "RecognitionUnavailableError",
    "RedactedDocument",
    "RedactionMap",
    "RedactionPipeline",
    "Request",
    "TypeCounters",
    "UploadFile",
    "_filter_noise_entity_mappings",
    "_page",
    "build_status_payload",
    "config_value",
    "derived_organization_alias_cores",
    "extract_pdf_text",
    "extract_workbook_text",
    "is_noise_entity_text",
    "load_json_config",
    "ocr_runtime",
    "pdf_page_texts",
    "preview_restore",
    "probe_model_manager",
    "redact_workbook",
    "redaction_map_from_json",
    "redaction_map_to_json",
    "render_batch_redaction_result_page",
    "render_home_page",
    "render_redaction_result_page",
    "render_status_panel",
    "restore_docx",
    "sort_mapping_entries",
    "take_ocr_output_paths",
]
