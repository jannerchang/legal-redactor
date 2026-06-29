from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import invalid_workflow_decision_fields
from .models import RedactionMap

SCHEMA_VERSION = "M6-regression-report/v1"

_METRIC_FIELDS = (
    "case_count",
    "true_positive",
    "false_positive",
    "false_negative",
    "precision",
    "recall",
    "f1",
)
_CASE_FIELDS = (
    "name",
    "expected_count",
    "actual_count",
    "true_positive",
    "false_positive",
    "false_negative",
    "precision",
    "recall",
    "f1",
)
_RAW_DIAGNOSTIC_KEYS = {
    "original",
    "masked",
    "mappings",
    "matched",
    "missing",
    "extra",
    "warnings",
    "leaks",
    "redacted_text",
    "restored_text",
    "debug_trace",
    "diff",
    "lookup_entries",
    "delete_blacklist_candidates",
    "suppressed_risky_entries",
}
_SENSITIVE_TEXT_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def project_gold_report(report: dict[str, Any] | None) -> dict[str, Any]:
    """Project the existing eval report into M6's privacy-safe gold section."""

    if not report:
        return {
            "available": False,
            "case_count": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "cases": [],
        }

    projected: dict[str, Any] = {"available": True}
    for field in _METRIC_FIELDS:
        projected[field] = report.get(field)

    projected_cases: list[dict[str, Any]] = []
    cases = report.get("cases", [])
    if isinstance(cases, list):
        for index, case in enumerate(cases, 1):
            if not isinstance(case, dict):
                continue
            safe_case = {"case_id": f"case-{index}"}
            for field in _CASE_FIELDS:
                if field == "name":
                    continue
                safe_case[field] = case.get(field)
            projected_cases.append(safe_case)
    projected["cases"] = projected_cases
    return projected


def aggregate_sample_summaries(summaries: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate M5 sample_summary payloads without retaining raw entry text."""

    summaries = summaries or []
    totals = {
        "summary_count": 0,
        "manual_corrections": 0,
        "false_positive_deletes": 0,
        "missing_adds": 0,
        "lookup_entry_count": 0,
        "delete_blacklist_candidate_count": 0,
        "suppressed_risky_entry_count": 0,
        "restore_unresolved_placeholder_count": None,
        "ignored_browser_fields": [],
        "regression_suggestions": [],
    }
    ignored_fields: set[str] = set()
    suggestions: list[str] = []
    unresolved_total = 0
    unresolved_seen = False

    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        totals["summary_count"] += 1
        totals["manual_corrections"] += _int_value(summary.get("manual_corrections"))
        totals["false_positive_deletes"] += _int_value(summary.get("false_positive_deletes"))
        totals["missing_adds"] += _int_value(summary.get("missing_adds"))
        totals["lookup_entry_count"] += _list_count(summary.get("lookup_entries"))
        totals["delete_blacklist_candidate_count"] += _list_count(summary.get("delete_blacklist_candidates"))
        totals["suppressed_risky_entry_count"] += _list_count(summary.get("suppressed_risky_entries"))

        unresolved = summary.get("restore_unresolved_placeholders")
        if isinstance(unresolved, int):
            unresolved_total += max(0, unresolved)
            unresolved_seen = True

        ignored_fields.update(invalid_workflow_decision_fields(summary))
        raw_suggestions = summary.get("regression_suggestions")
        if isinstance(raw_suggestions, list):
            suggestions.extend(str(item) for item in raw_suggestions if item)

    if unresolved_seen:
        totals["restore_unresolved_placeholder_count"] = unresolved_total
    totals["ignored_browser_fields"] = sorted(ignored_fields)
    totals["regression_suggestions"] = _dedupe_preserve_order(suggestions)
    return totals


def sample_provenance(sample_file: str | Path | None) -> dict[str, Any]:
    """Return metadata-only sample provenance for M6 reports."""

    if not sample_file:
        return {
            "exists": False,
            "sample_file": None,
            "mtime": None,
            "size_bytes": None,
            "entry_count": None,
            "has_updated_at": False,
            "updated_at": None,
            "freshness": "missing",
        }

    path = Path(sample_file)
    provenance: dict[str, Any] = {
        "exists": path.exists(),
        "sample_file": path.name,
        "mtime": None,
        "size_bytes": None,
        "entry_count": None,
        "has_updated_at": False,
        "updated_at": None,
        "freshness": "missing" if not path.exists() else "metadata_only",
    }
    if not path.exists():
        return provenance

    try:
        stat = path.stat()
    except OSError:
        provenance["freshness"] = "stat_error"
        return provenance

    provenance["mtime"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    provenance["size_bytes"] = stat.st_size
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        provenance["freshness"] = "unreadable"
        return provenance

    if isinstance(data, dict):
        entries = data.get("entries")
        provenance["entry_count"] = len(entries) if isinstance(entries, list) else None
        updated_at = data.get("updated_at") or data.get("created_at")
        if isinstance(updated_at, str) and updated_at:
            provenance["has_updated_at"] = True
            provenance["updated_at"] = updated_at
    return provenance


def restore_placeholder_metric(
    redacted_text: str | None,
    redaction_map: RedactionMap | None,
) -> dict[str, Any] | None:
    """Count unresolved placeholders only when both text and map evidence are present."""

    if not redacted_text or redaction_map is None:
        return None

    unresolved = 0
    mapped_placeholders = 0
    seen: set[str] = set()
    for entry in redaction_map.mappings:
        masked = entry.masked
        if not masked or masked in seen:
            continue
        seen.add(masked)
        count = redacted_text.count(masked)
        if count:
            mapped_placeholders += 1
            unresolved += count
    return {
        "unresolved_placeholder_count": unresolved,
        "mapped_placeholder_count": mapped_placeholders,
        "evidence": "supplied",
    }


def timing_metrics(
    *,
    report_started_monotonic: float,
    report_finished_monotonic: float | None,
    document_input_at: str | None = None,
    saved_case_at: str | None = None,
    gold_evaluation_ms: int | None = None,
) -> dict[str, Any]:
    report_generation_ms = _elapsed_ms(report_started_monotonic, report_finished_monotonic)
    timing: dict[str, Any] = {
        "report_generation_ms": report_generation_ms,
        "gold_evaluation_ms": gold_evaluation_ms,
        "document_input_to_saved_case_ms": None,
        "document_input_to_saved_case_reason": "missing_timestamp_evidence",
        "discord_thread_to_restored_ms": None,
        "discord_thread_to_restored_reason": "deferred_to_M7",
    }
    if document_input_at and saved_case_at:
        try:
            input_time = _parse_datetime(document_input_at)
            saved_time = _parse_datetime(saved_case_at)
        except ValueError:
            timing["document_input_to_saved_case_reason"] = "invalid_timestamp_evidence"
        else:
            delta_ms = _elapsed_ms(input_time.timestamp(), saved_time.timestamp())
            if saved_time < input_time:
                timing["document_input_to_saved_case_reason"] = "invalid_timestamp_order"
            else:
                timing["document_input_to_saved_case_ms"] = delta_ms
                timing["document_input_to_saved_case_reason"] = "computed_from_supplied_timestamps"
    return timing


def build_regression_report(
    *,
    gold_report: dict[str, Any] | None = None,
    sample_summaries: list[dict[str, Any]] | None = None,
    sample_file: str | Path | None = None,
    redacted_text: str | None = None,
    redaction_map: RedactionMap | None = None,
    report_started_monotonic: float,
    report_finished_monotonic: float,
    document_input_at: str | None = None,
    saved_case_at: str | None = None,
    gold_evaluation_ms: int | None = None,
) -> dict[str, Any]:
    workflow = aggregate_sample_summaries(sample_summaries)
    gold = project_gold_report(gold_report)
    samples = {
        "newest_sample_provenance": sample_provenance(sample_file),
    }
    restore = restore_placeholder_metric(redacted_text, redaction_map)
    finished_monotonic = time.monotonic() if report_finished_monotonic is None else report_finished_monotonic
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold": gold,
        "workflow": {key: value for key, value in workflow.items() if key != "regression_suggestions"},
        "samples": samples,
        "restore": restore,
        "timing": timing_metrics(
            report_started_monotonic=report_started_monotonic,
            report_finished_monotonic=finished_monotonic,
            document_input_at=document_input_at,
            saved_case_at=saved_case_at,
            gold_evaluation_ms=gold_evaluation_ms,
        ),
        "privacy": {
            "safe_by_default": True,
            "gold_raw_diagnostics": "omitted",
            "sample_entries": "omitted",
            "map_values": "omitted",
            "restored_content": "omitted",
            "debug_traces": "omitted",
        },
        "regression_suggestions": workflow["regression_suggestions"],
    }
    assert_privacy_safe_report(report)
    return report


def regression_report_to_json(report: dict[str, Any]) -> str:
    assert_privacy_safe_report(report)
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def load_json_object(path: str | Path, *, description: str) -> dict[str, Any]:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{description} 不是合法 JSON: {target}") from exc
    except OSError as exc:
        raise ValueError(f"无法读取 {description}: {target}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{description} 必须是 JSON object: {target}")
    return data


def assert_privacy_safe_report(report: dict[str, Any]) -> None:
    key_violations: list[str] = []
    value_violations: list[str] = []
    _collect_raw_key_violations(report, path="$", violations=key_violations)
    _collect_sensitive_value_violations(report, path="$", violations=value_violations)
    errors: list[str] = []
    if key_violations:
        errors.append("raw diagnostic fields: " + ", ".join(key_violations))
    if value_violations:
        errors.append("sensitive report values: " + ", ".join(value_violations))
    if errors:
        raise ValueError("M6 regression report contains " + "; ".join(errors))


def _collect_raw_key_violations(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text in _RAW_DIAGNOSTIC_KEYS:
                violations.append(child_path)
            _collect_raw_key_violations(child, path=child_path, violations=violations)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_raw_key_violations(child, path=f"{path}[{index}]", violations=violations)


def _collect_sensitive_value_violations(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _collect_sensitive_value_violations(child, path=f"{path}.{key}", violations=violations)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_value_violations(child, path=f"{path}[{index}]", violations=violations)
    elif isinstance(value, str) and _SENSITIVE_TEXT_RE.search(value):
        violations.append(path)


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _elapsed_ms(start: float, finish: float) -> int:
    return max(0, int(round((finish - start) * 1000)))


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
