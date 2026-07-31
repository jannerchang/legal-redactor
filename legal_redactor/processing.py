from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import LLMAPIConfig, PipelineConfig, RedactionProfile
from .excel_io import EXCEL_INPUT_SUFFIXES, extract_workbook_text, redact_workbook
from .io import read_document, save_redaction_map_encrypted
from .model_manager import DEFAULT_MODEL_ID
from .models import BatchRedactionResult, RedactedDocument
from .pipeline import RedactionPipeline

SUPPORTED_PROCESSING_SUFFIXES = frozenset({".txt", ".md", ".docx", ".pdf", *EXCEL_INPUT_SUFFIXES})


@dataclass(frozen=True)
class ProcessingRequest:
    input_paths: tuple[Path, ...]
    output_dir: Path
    model: str = DEFAULT_MODEL_ID
    model_host: str = "127.0.0.1"
    model_port: int = 18080
    profile: str = "standard"


@dataclass(frozen=True)
class ProcessedFile:
    source_name: str
    source_suffix: str
    redacted_filename: str
    redacted_path: str
    media_type: str
    size_bytes: int
    leak_count: int


@dataclass(frozen=True)
class ProcessingResult:
    status: str
    output_dir: str
    redaction_map_path: str
    mapping_count: int
    leak_count: int
    review_candidate_count: int
    warnings: list[str]
    recognition_stats: dict[str, Any] | None
    files: list[ProcessedFile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [asdict(item) for item in self.files]
        return payload


def process_paths(request: ProcessingRequest) -> ProcessingResult:
    if not request.input_paths:
        raise ValueError("未提供待脱敏文件")
    inputs = [_load_input(path) for path in request.input_paths]
    request.output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = RedactionPipeline(config=_pipeline_config(request))
    batch = pipeline.redact_many([(item[0].name, item[2]) for item in inputs])

    if len(inputs) != len(batch.documents):
        raise RuntimeError("脱敏结果文件数与输入不一致")
    processed_files: list[ProcessedFile] = []
    for index, document in enumerate(batch.documents):
        source, suffix, _text, source_bytes = inputs[index]
        processed_files.append(
            _write_redacted_document(
                output_dir=request.output_dir,
                source=source,
                suffix=suffix,
                source_bytes=source_bytes,
                document=document,
                batch=batch,
                pipeline=pipeline,
            )
        )

    map_path = request.output_dir / "redaction_map.enc"
    save_redaction_map_encrypted(map_path, batch.redaction_map)
    result = ProcessingResult(
        status="completed",
        output_dir=str(request.output_dir.resolve()),
        redaction_map_path=str(map_path.resolve()),
        mapping_count=len(batch.redaction_map.mappings),
        leak_count=len(batch.leaks),
        review_candidate_count=len(batch.review_candidates),
        warnings=list(batch.warnings),
        recognition_stats=batch.recognition_stats.to_dict() if batch.recognition_stats else None,
        files=processed_files,
    )
    _write_json_atomic(request.output_dir / "result.json", result.to_dict())
    return result


def processing_request_from_manifest(path: str | Path) -> ProcessingRequest:
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("processing manifest 必须是 JSON object")
    base = manifest_path.parent
    raw_inputs = payload.get("input_paths")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("processing manifest 缺少 input_paths")
    input_paths = tuple(_resolve_path(base, value) for value in raw_inputs)
    output_dir = _resolve_path(base, payload.get("output_dir", "redacted-output"))
    model_host = str(payload.get("model_host") or os.getenv("LEGAL_REDACTOR_MODEL_MANAGER_HOST", "127.0.0.1"))
    raw_port = payload.get("model_port") or os.getenv("LEGAL_REDACTOR_MODEL_MANAGER_PORT", "18080")
    return ProcessingRequest(
        input_paths=input_paths,
        output_dir=output_dir,
        model=str(payload.get("model") or DEFAULT_MODEL_ID),
        model_host=model_host,
        model_port=int(raw_port),
        profile=str(payload.get("profile") or "standard"),
    )


def _pipeline_config(request: ProcessingRequest) -> PipelineConfig:
    package_root = Path(__file__).resolve().parents[1]
    data_root = package_root / "data"
    llm = replace(
        LLMAPIConfig(model=request.model),
        model_manager_host=request.model_host,
        model_manager_port=request.model_port,
    )
    return PipelineConfig(
        enable_hebei_admin_db=(data_root / "hebei_admin_divisions.sqlite").exists(),
        hebei_admin_db_path=str(data_root / "hebei_admin_divisions.sqlite"),
        enable_china_admin_db=(data_root / "china_admin_divisions.sqlite").exists(),
        china_admin_db_path=str(data_root / "china_admin_divisions.sqlite"),
        enable_llm=True,
        llm=llm,
        redaction_profile=RedactionProfile.from_preset(request.profile),
    )


def _load_input(path: Path) -> tuple[Path, str, str, bytes | None]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_PROCESSING_SUFFIXES:
        raise ValueError(f"不支持的输入格式：{suffix}")
    if suffix in EXCEL_INPUT_SUFFIXES:
        source_bytes = source.read_bytes()
        return source, suffix, extract_workbook_text(source_bytes, source.name), source_bytes
    return source, suffix, read_document(source), None


def _write_redacted_document(
    *,
    output_dir: Path,
    source: Path,
    suffix: str,
    source_bytes: bytes | None,
    document: RedactedDocument,
    batch: BatchRedactionResult,
    pipeline: RedactionPipeline,
) -> ProcessedFile:
    if suffix in EXCEL_INPUT_SUFFIXES:
        content = redact_workbook(
            source_bytes or b"",
            source.name,
            batch.redaction_map,
            pipeline.apply_mappings,
        )
        filename = f"{source.stem}.redacted.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        leak_count = len(pipeline.scan_high_risk_leaks(extract_workbook_text(content, filename)))
        output_path = output_dir / filename
        _write_bytes_atomic(output_path, content)
    else:
        filename = f"{source.stem}.redacted.txt"
        media_type = "text/plain"
        leak_count = len(document.leaks)
        output_path = output_dir / filename
        _write_text_atomic(output_path, document.redacted_text)
    return ProcessedFile(
        source_name=source.name,
        source_suffix=suffix,
        redacted_filename=filename,
        redacted_path=str(output_path.resolve()),
        media_type=media_type,
        size_bytes=output_path.stat().st_size,
        leak_count=leak_count,
    )


def _resolve_path(base: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
