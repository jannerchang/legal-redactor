from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .regression import SCHEMA_VERSION as M6_SCHEMA_VERSION
from .regression import assert_privacy_safe_report


SCHEMA_VERSION = "M8-runtime-benchmark-report/v1"
_CONTEXT_REQUIRED_FIELDS = (
    "gold_set_id",
    "gold_set_hash",
    "input_set_id",
    "input_set_kind",
    "input_set_hash",
    "benchmark_profile",
)
_INPUT_SET_KINDS = {"synthetic", "public_spc_sample", "operator_private_local"}
_QUALITY_FIELDS = (
    "case_count",
    "true_positive",
    "false_positive",
    "false_negative",
    "precision",
    "recall",
    "f1",
)
_WORKFLOW_FIELDS = (
    "summary_count",
    "manual_corrections",
    "false_positive_deletes",
    "missing_adds",
    "lookup_entry_count",
    "delete_blacklist_candidate_count",
    "suppressed_risky_entry_count",
    "restore_unresolved_placeholder_count",
)
_RAW_KEYS = {
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
    "tokens",
    "api_token",
    "authorization",
    "prompt",
    "completion",
    "body",
}
_SENSITIVE_TEXT_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s\"'(:=])(?:/[^,\s;]+|~[/\\][^,\s;]+|[A-Za-z]:[\\/][^,\s;]+)")
_REQUIRED_EVIDENCE_FIELDS = (
    "first_token_latency_ms",
    "total_redaction_eval_ms",
    "web_workflow_ms",
    "peak_memory_mb",
    "error_rate",
)
_WORKFLOW_REGRESSION_FIELDS = (
    "manual_corrections",
    "false_positive_deletes",
    "missing_adds",
    "suppressed_risky_entry_count",
    "restore_unresolved_placeholder_count",
)


@dataclass(frozen=True)
class BenchmarkCandidateInput:
    label: str
    runtime_kind: str
    runtime_config_id: str
    m6_report_path: str | Path
    m6_report: dict[str, Any]
    benchmark_context: dict[str, Any]
    observation: dict[str, Any] = field(default_factory=dict)


def build_runtime_benchmark_report(
    candidates: Sequence[BenchmarkCandidateInput],
    *,
    generated_at: str | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    if len(candidates) < 2:
        raise ValueError("runtime benchmark requires at least two candidates")
    base = Path.cwd() if base_dir is None else Path(base_dir)
    candidate_reports = [_build_candidate(candidate, base_dir=base) for candidate in candidates]
    baseline = candidate_reports[0]
    context_mismatches = _context_mismatches(candidate_reports)
    compatible = not context_mismatches
    deltas = [_candidate_delta(baseline, candidate) for candidate in candidate_reports[1:]]
    missing_evidence = _missing_required_evidence(candidate_reports)
    quality_regressions = _quality_regressions(baseline, candidate_reports[1:])
    recommendation = _recommendation(
        compatible=compatible,
        missing_evidence=missing_evidence,
        quality_regressions=quality_regressions,
        deltas=deltas,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "benchmark_context": baseline["benchmark_context"],
        "candidates": candidate_reports,
        "comparison": {
            "baseline": baseline["label"],
            "compatible": compatible,
            "context_mismatches": context_mismatches,
            "quality_regressions": quality_regressions,
            "deltas": deltas,
        },
        "recommendation": recommendation,
        "privacy": {
            "safe_by_default": True,
            "gold_raw_diagnostics": "omitted",
            "sample_entries": "omitted",
            "map_values": "omitted",
            "restored_content": "omitted",
            "debug_traces": "omitted",
            "prompt_bodies": "omitted",
            "absolute_paths": "omitted",
        },
    }
    assert_privacy_safe_benchmark_report(report)
    return report


def benchmark_report_to_json(report: dict[str, Any]) -> str:
    assert_privacy_safe_benchmark_report(report)
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def summarize_models_probe(payload: dict[str, Any], *, expected_model: str) -> dict[str, Any]:
    model_ids = [
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    model_match = expected_model in model_ids
    return {
        "model_match": model_match,
        "expected_model": expected_model,
        "observed_model_count": len(model_ids),
        "status": "ready" if model_match else "model_mismatch",
    }


def assert_privacy_safe_benchmark_report(report: dict[str, Any]) -> None:
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
        raise ValueError("M8 runtime benchmark report contains " + "; ".join(errors))


def _build_candidate(candidate: BenchmarkCandidateInput, *, base_dir: Path) -> dict[str, Any]:
    _validate_label(candidate.label, "candidate label")
    _validate_label(candidate.runtime_kind, "runtime kind")
    _validate_label(candidate.runtime_config_id, "runtime config id")
    _validate_context(candidate.benchmark_context)
    _validate_m6_report(candidate.m6_report)
    observation = candidate.observation if isinstance(candidate.observation, dict) else {}
    timing_observation = observation.get("timing") if isinstance(observation.get("timing"), dict) else {}
    resource_observation = observation.get("resources") if isinstance(observation.get("resources"), dict) else {}
    error_observation = observation.get("errors") if isinstance(observation.get("errors"), dict) else {}
    probe_observation = observation.get("probe") if isinstance(observation.get("probe"), dict) else {}

    timing = _candidate_timing(candidate.m6_report, timing_observation, probe_observation)
    resources = _candidate_resources(resource_observation)
    errors = _candidate_errors(error_observation)
    candidate_report = {
        "label": candidate.label,
        "runtime_kind": candidate.runtime_kind,
        "runtime_config_id": candidate.runtime_config_id,
        "benchmark_context": dict(candidate.benchmark_context),
        "m6_report_path": _safe_report_path(candidate.m6_report_path, base_dir=base_dir),
        "quality": _project_quality(candidate.m6_report),
        "workflow": _project_workflow(candidate.m6_report),
        "timing": timing,
        "resources": resources,
        "errors": errors,
        "probe": _candidate_probe(probe_observation),
    }
    assert_privacy_safe_benchmark_report(candidate_report)
    return candidate_report


def _validate_m6_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ValueError("M6 report must be a JSON object")
    assert_privacy_safe_report(report)
    if report.get("schema_version") != M6_SCHEMA_VERSION:
        raise ValueError(f"M6 report schema_version must be {M6_SCHEMA_VERSION}")
    required_paths = (
        ("gold", "case_count"),
        ("gold", "precision"),
        ("gold", "recall"),
        ("gold", "f1"),
        ("gold", "true_positive"),
        ("gold", "false_positive"),
        ("gold", "false_negative"),
        ("workflow", "manual_corrections"),
        ("workflow", "false_positive_deletes"),
        ("workflow", "missing_adds"),
        ("workflow", "suppressed_risky_entry_count"),
        ("samples", "newest_sample_provenance", "exists"),
        ("samples", "newest_sample_provenance", "sample_file"),
        ("samples", "newest_sample_provenance", "mtime"),
        ("samples", "newest_sample_provenance", "entry_count"),
        ("samples", "newest_sample_provenance", "has_updated_at"),
        ("samples", "newest_sample_provenance", "updated_at"),
        ("timing", "gold_evaluation_ms"),
        ("timing", "report_generation_ms"),
        ("timing", "document_input_to_saved_case_ms"),
        ("timing", "discord_thread_to_restored_ms"),
        ("privacy", "safe_by_default"),
    )
    for path in required_paths:
        _require_path(report, path)
    if report["privacy"].get("safe_by_default") is not True:
        raise ValueError("M6 report privacy.safe_by_default must be true")
    restore = report.get("restore")
    if restore is not None and not isinstance(restore, dict):
        raise ValueError("M6 report restore must be null or object")
    if isinstance(restore, dict):
        _require_path(report, ("restore", "unresolved_placeholder_count"))


def _validate_context(context: dict[str, Any]) -> None:
    if not isinstance(context, dict):
        raise ValueError("benchmark_context must be a JSON object")
    for field in _CONTEXT_REQUIRED_FIELDS:
        if not context.get(field):
            raise ValueError(f"benchmark_context.{field} is required")
    if context.get("input_set_kind") not in _INPUT_SET_KINDS:
        raise ValueError("benchmark_context.input_set_kind is invalid")


def _validate_label(value: str, description: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} is required")
    if _SENSITIVE_TEXT_RE.search(value) or _ABSOLUTE_PATH_RE.search(value):
        raise ValueError(f"{description} is not privacy-safe")


def _project_quality(report: dict[str, Any]) -> dict[str, Any]:
    gold = report["gold"]
    return {field: gold.get(field) for field in _QUALITY_FIELDS}


def _project_workflow(report: dict[str, Any]) -> dict[str, Any]:
    workflow = report["workflow"]
    projected = {field: workflow.get(field) for field in _WORKFLOW_FIELDS if field in workflow}
    restore = report.get("restore")
    if isinstance(restore, dict):
        projected["restore_unresolved_placeholder_count"] = restore.get("unresolved_placeholder_count")
    return projected


def _candidate_timing(
    report: dict[str, Any],
    timing_observation: dict[str, Any],
    probe_observation: dict[str, Any],
) -> dict[str, Any]:
    m6_timing = report["timing"]
    total = _number_or_none(timing_observation.get("total_redaction_eval_ms"))
    total_reason = None
    if total is None:
        gold_ms = _number_or_none(m6_timing.get("gold_evaluation_ms"))
        report_ms = _number_or_none(m6_timing.get("report_generation_ms"))
        if gold_ms is not None and report_ms is not None:
            total = gold_ms + report_ms
            total_reason = "computed_from_m6_gold_and_report_generation"
        else:
            total_reason = "missing_total_duration_evidence"

    first_token = _number_or_none(timing_observation.get("first_token_latency_ms"))
    if first_token is None:
        first_token = _number_or_none(probe_observation.get("first_token_latency_ms"))
    first_token_reason = None if first_token is not None else "missing_probe_evidence"

    web_workflow = _number_or_none(timing_observation.get("web_workflow_ms"))
    web_reason = None
    if web_workflow is None:
        web_workflow = _number_or_none(m6_timing.get("document_input_to_saved_case_ms"))
        if web_workflow is None:
            web_reason = str(m6_timing.get("document_input_to_saved_case_reason") or "missing_web_workflow_evidence")
        else:
            web_reason = "from_m6_document_input_to_saved_case_ms"

    return {
        "total_redaction_eval_ms": total,
        "total_redaction_eval_reason": total_reason,
        "first_token_latency_ms": first_token,
        "first_token_latency_reason": first_token_reason,
        "web_workflow_ms": web_workflow,
        "web_workflow_reason": web_reason,
    }


def _candidate_resources(resource_observation: dict[str, Any]) -> dict[str, Any]:
    peak_memory = _number_or_none(resource_observation.get("peak_memory_mb"))
    return {
        "peak_memory_mb": peak_memory,
        "peak_memory_reason": None if peak_memory is not None else "missing_resource_evidence",
    }


def _candidate_errors(error_observation: dict[str, Any]) -> dict[str, Any]:
    error_count = _int_or_none(error_observation.get("error_count"))
    error_rate = _number_or_none(error_observation.get("error_rate"))
    return {
        "error_count": 0 if error_count is None else error_count,
        "error_rate": error_rate,
        "error_rate_reason": None if error_rate is not None else "missing_error_rate_evidence",
    }


def _candidate_probe(probe_observation: dict[str, Any]) -> dict[str, Any] | None:
    if not probe_observation:
        return None
    allowed = {
        "model_match",
        "expected_model",
        "observed_model_count",
        "status",
        "endpoint_label",
    }
    return {key: probe_observation[key] for key in allowed if key in probe_observation}


def _context_mismatches(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = candidates[0]["benchmark_context"]
    mismatches: list[dict[str, Any]] = []
    for candidate in candidates[1:]:
        fields = [
            field
            for field in _CONTEXT_REQUIRED_FIELDS + ("sample_provenance_id",)
            if baseline.get(field) != candidate["benchmark_context"].get(field)
        ]
        if fields:
            mismatches.append({"label": candidate["label"], "fields": fields})
    return mismatches


def _candidate_delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": candidate["label"],
        "quality": {
            "precision_delta": _delta(candidate["quality"].get("precision"), baseline["quality"].get("precision")),
            "recall_delta": _delta(candidate["quality"].get("recall"), baseline["quality"].get("recall")),
            "f1_delta": _delta(candidate["quality"].get("f1"), baseline["quality"].get("f1")),
        },
        "workflow": {
            f"{field}_delta": _delta(candidate["workflow"].get(field), baseline["workflow"].get(field))
            for field in _WORKFLOW_REGRESSION_FIELDS
        },
        "timing": {
            "total_redaction_eval_ms_delta": _delta(
                candidate["timing"].get("total_redaction_eval_ms"),
                baseline["timing"].get("total_redaction_eval_ms"),
            ),
            "first_token_latency_ms_delta": _delta(
                candidate["timing"].get("first_token_latency_ms"),
                baseline["timing"].get("first_token_latency_ms"),
            ),
            "web_workflow_ms_delta": _delta(
                candidate["timing"].get("web_workflow_ms"),
                baseline["timing"].get("web_workflow_ms"),
            ),
        },
        "resources": {
            "peak_memory_mb_delta": _delta(
                candidate["resources"].get("peak_memory_mb"),
                baseline["resources"].get("peak_memory_mb"),
            )
        },
        "errors": {
            "error_rate_delta": _delta(candidate["errors"].get("error_rate"), baseline["errors"].get("error_rate"))
        },
    }


def _missing_required_evidence(candidates: Sequence[dict[str, Any]]) -> list[str]:
    missing: set[str] = set()
    for candidate in candidates:
        timing = candidate["timing"]
        resources = candidate["resources"]
        errors = candidate["errors"]
        if timing.get("first_token_latency_ms") is None:
            missing.add("first_token_latency_ms")
        if timing.get("total_redaction_eval_ms") is None:
            missing.add("total_redaction_eval_ms")
        if timing.get("web_workflow_ms") is None:
            missing.add("web_workflow_ms")
        if resources.get("peak_memory_mb") is None:
            missing.add("peak_memory_mb")
        if errors.get("error_rate") is None:
            missing.add("error_rate")
    return [field for field in _REQUIRED_EVIDENCE_FIELDS if field in missing]


def _quality_regressions(baseline: dict[str, Any], candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    for candidate in candidates:
        fields: list[str] = []
        for field in ("precision", "recall", "f1"):
            if _is_regression(candidate["quality"].get(field), baseline["quality"].get(field)):
                fields.append(field)
        for field in (
            "manual_corrections",
            "false_positive_deletes",
            "missing_adds",
            "suppressed_risky_entry_count",
        ):
            if _is_count_regression(candidate["workflow"].get(field), baseline["workflow"].get(field)):
                fields.append(field)
        if _is_optional_count_regression(
            candidate["workflow"].get("restore_unresolved_placeholder_count"),
            baseline["workflow"].get("restore_unresolved_placeholder_count"),
        ):
            fields.append("restore_unresolved_placeholder_count")
        if fields:
            regressions.append({"label": candidate["label"], "fields": fields})
    return regressions


def _recommendation(
    *,
    compatible: bool,
    missing_evidence: list[str],
    quality_regressions: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> dict[str, Any]:
    if not compatible:
        return {
            "action": "manual_review",
            "reason": "benchmark_context_mismatch",
            "missing_evidence": missing_evidence,
        }
    if missing_evidence:
        return {
            "action": "manual_review",
            "reason": "missing_metric_evidence",
            "missing_evidence": missing_evidence,
        }
    if quality_regressions:
        return {
            "action": "no_switch",
            "reason": "quality_or_workflow_regression",
            "missing_evidence": [],
        }
    faster = [
        delta
        for delta in deltas
        if _number_or_none(delta["timing"].get("total_redaction_eval_ms_delta")) is not None
        and delta["timing"]["total_redaction_eval_ms_delta"] < 0
    ]
    if not faster:
        return {"action": "no_switch", "reason": "no_candidate_improvement", "missing_evidence": []}
    winner = min(faster, key=lambda item: item["timing"]["total_redaction_eval_ms_delta"])
    return {
        "action": "candidate_faster_no_regression",
        "reason": "best_candidate_faster_with_no_regression",
        "winner": winner["label"],
        "missing_evidence": [],
    }


def _require_path(value: dict[str, Any], path: Iterable[str]) -> Any:
    current: Any = value
    walked: list[str] = []
    for part in path:
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            raise ValueError("M6 report missing required field: " + ".".join(walked))
        current = current[part]
    return current


def _safe_report_path(path: str | Path, *, base_dir: Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        return target.as_posix()
    try:
        return target.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        rel = os.path.relpath(target, base_dir)
        if rel.startswith(".."):
            return target.name
        return rel


def _number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    return None


def _delta(value: Any, baseline: Any) -> int | float | None:
    value_number = _number_or_none(value)
    baseline_number = _number_or_none(baseline)
    if value_number is None or baseline_number is None:
        return None
    return value_number - baseline_number


def _is_regression(value: Any, baseline: Any) -> bool:
    value_number = _number_or_none(value)
    baseline_number = _number_or_none(baseline)
    return value_number is not None and baseline_number is not None and value_number < baseline_number


def _is_count_regression(value: Any, baseline: Any) -> bool:
    value_number = _number_or_none(value)
    baseline_number = _number_or_none(baseline)
    return value_number is not None and baseline_number is not None and value_number > baseline_number


def _is_optional_count_regression(value: Any, baseline: Any) -> bool:
    value_number = _number_or_none(value)
    baseline_number = _number_or_none(baseline)
    if value_number is None:
        return False
    return value_number > (0 if baseline_number is None else baseline_number)


def _collect_raw_key_violations(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text == "sample_entries":
                if not (child_path == "$.privacy.sample_entries" and child == "omitted"):
                    violations.append(child_path)
            elif key_text in _RAW_KEYS:
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
    elif isinstance(value, str):
        if _SENSITIVE_TEXT_RE.search(value) or _ABSOLUTE_PATH_RE.search(value):
            violations.append(path)
