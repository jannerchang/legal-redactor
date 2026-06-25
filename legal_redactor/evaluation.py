from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PipelineConfig
from .io import read_document
from .models import MappingEntry
from .pipeline import RedactionPipeline


@dataclass(frozen=True)
class ExpectedEntity:
    original: str
    type: str | None = None
    masked: str | None = None

    def to_dict(self) -> dict[str, str]:
        data = {"original": self.original}
        if self.type:
            data["type"] = self.type
        if self.masked:
            data["masked"] = self.masked
        return data


def evaluate_gold_file(
    gold_path: str | Path,
    *,
    config: PipelineConfig | None = None,
) -> dict[str, Any]:
    path = Path(gold_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("gold 文件必须是 case 数组，或包含 cases 数组的 JSON 对象")

    pipeline = RedactionPipeline(config=config or PipelineConfig.max_effect())
    case_reports = []
    totals = {"tp": 0, "fp": 0, "fn": 0}
    for index, raw_case in enumerate(cases, 1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"case #{index} 必须是 JSON 对象")
        case_report = evaluate_case(raw_case, pipeline=pipeline, base_dir=path.parent, index=index)
        case_reports.append(case_report)
        totals["tp"] += int(case_report["true_positive"])
        totals["fp"] += int(case_report["false_positive"])
        totals["fn"] += int(case_report["false_negative"])

    metrics = _metrics(totals["tp"], totals["fp"], totals["fn"])
    return {
        "version": "1.0",
        "gold_file": str(path),
        "case_count": len(case_reports),
        **totals,
        "true_positive": totals["tp"],
        "false_positive": totals["fp"],
        "false_negative": totals["fn"],
        **metrics,
        "cases": case_reports,
    }


def evaluate_case(
    raw_case: dict[str, Any],
    *,
    pipeline: RedactionPipeline,
    base_dir: Path,
    index: int = 1,
) -> dict[str, Any]:
    name = str(raw_case.get("name") or raw_case.get("source_file") or raw_case.get("file") or f"case-{index}")
    source_file = raw_case.get("source_file") or raw_case.get("file") or name
    text = _case_text(raw_case, base_dir)
    expected = _expected_entities(raw_case)
    result = pipeline.redact(text, source_file=str(source_file))
    actual = _actual_entities(result.redaction_map.mappings)
    matches, missing, extra = _match_entities(expected, actual)
    metrics = _metrics(len(matches), len(extra), len(missing))
    return {
        "name": name,
        "source_file": str(source_file),
        "expected_count": len(expected),
        "actual_count": len(actual),
        "true_positive": len(matches),
        "false_positive": len(extra),
        "false_negative": len(missing),
        **metrics,
        "matched": [item.to_dict() for item in matches],
        "missing": [item.to_dict() for item in missing],
        "extra": [item.to_dict() for item in extra],
        "warnings": result.warnings,
        "leaks": [leak.to_dict() for leak in result.leaks],
    }


def evaluation_report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def _case_text(raw_case: dict[str, Any], base_dir: Path) -> str:
    text = raw_case.get("text")
    if isinstance(text, str):
        return text
    file_value = raw_case.get("file") or raw_case.get("path")
    if isinstance(file_value, str) and file_value:
        file_path = Path(file_value)
        if not file_path.is_absolute():
            file_path = base_dir / file_path
        return read_document(file_path)
    raise ValueError("每个 case 必须包含 text，或包含 file/path 指向输入文档")


def _expected_entities(raw_case: dict[str, Any]) -> list[ExpectedEntity]:
    raw_entries = (
        raw_case.get("expected")
        or raw_case.get("mappings")
        or raw_case.get("entities")
        or raw_case.get("expected_mappings")
        or []
    )
    if not isinstance(raw_entries, list):
        raise ValueError("expected/mappings/entities 必须是数组")
    seen: set[tuple[str | None, str, str | None]] = set()
    expected: list[ExpectedEntity] = []
    for item in raw_entries:
        entity = _expected_entity(item)
        key = (entity.type, entity.original, entity.masked)
        if key in seen:
            continue
        seen.add(key)
        expected.append(entity)
    return expected


def _expected_entity(item: Any) -> ExpectedEntity:
    if isinstance(item, str):
        return ExpectedEntity(original=item)
    if not isinstance(item, dict):
        raise ValueError("expected 条目必须是字符串或 JSON 对象")
    original = item.get("original") or item.get("text") or item.get("name") or item.get("full")
    if not isinstance(original, str) or not original:
        raise ValueError("expected 条目缺少 original/text/name/full")
    entity_type = item.get("type")
    masked = item.get("masked")
    return ExpectedEntity(
        original=original,
        type=str(entity_type) if entity_type else None,
        masked=str(masked) if masked else None,
    )


def _actual_entities(mappings: list[MappingEntry]) -> list[ExpectedEntity]:
    seen: set[tuple[str, str, str]] = set()
    actual: list[ExpectedEntity] = []
    for mapping in mappings:
        key = (mapping.type, mapping.original, mapping.masked)
        if key in seen:
            continue
        seen.add(key)
        actual.append(ExpectedEntity(type=mapping.type, original=mapping.original, masked=mapping.masked))
    return actual


def _match_entities(
    expected: list[ExpectedEntity],
    actual: list[ExpectedEntity],
) -> tuple[list[ExpectedEntity], list[ExpectedEntity], list[ExpectedEntity]]:
    used_actual: set[int] = set()
    matched: list[ExpectedEntity] = []
    missing: list[ExpectedEntity] = []
    for expected_item in expected:
        match_index = _find_match(expected_item, actual, used_actual)
        if match_index is None:
            missing.append(expected_item)
            continue
        used_actual.add(match_index)
        matched.append(expected_item)
    extra = [item for index, item in enumerate(actual) if index not in used_actual]
    return matched, missing, extra


def _find_match(
    expected: ExpectedEntity,
    actual: list[ExpectedEntity],
    used_actual: set[int],
) -> int | None:
    for index, actual_item in enumerate(actual):
        if index in used_actual:
            continue
        if expected.original != actual_item.original:
            continue
        if expected.type and expected.type != actual_item.type:
            continue
        if expected.masked and expected.masked != actual_item.masked:
            continue
        return index
    return None


def _metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }
