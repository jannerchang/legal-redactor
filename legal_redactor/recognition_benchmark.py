from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import PipelineConfig
from .evaluation import evaluate_gold_file
from .regression import build_regression_report

SCHEMA_VERSION = "recognition-benchmark-report/v2"
MANIFEST_SCHEMA_VERSION = "recognition-benchmark-manifest/v1"
LENGTH_STRATA = ("<10k", "10k-30k", "30k-60k", ">=60k")
MODES = ("full_document",)
MODELS = ("bonsai-27b", "qwen3.5-9b")


@dataclass(frozen=True)
class BenchmarkMatrixRow:
    recognition_mode: str
    model_id: str
    audited: bool = False


def benchmark_matrix() -> tuple[BenchmarkMatrixRow, ...]:
    return tuple(BenchmarkMatrixRow("full_document", model) for model in MODELS)


def load_benchmark_manifest(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("benchmark manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("benchmark manifest schema_version is invalid")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("benchmark manifest inputs must be a non-empty array")
    if "cold_warm_policy" in manifest and not isinstance(manifest["cold_warm_policy"], str):
        raise ValueError("benchmark manifest cold_warm_policy must be a string")
    for item in inputs:
        _validate_manifest_input(item)
    return manifest


def build_benchmark_manifest(
    paths: Iterable[str | Path],
    *,
    base_dir: str | Path,
    input_set_kind: str,
    scenario_labels: dict[str, list[str]] | None = None,
    gold_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = Path(base_dir).resolve()
    rows: list[dict[str, Any]] = []
    for path_value in paths:
        path = Path(path_value).resolve()
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError as exc:
            raise ValueError("benchmark inputs must be inside base_dir") from exc
        data = path.read_bytes()
        text = data.decode("utf-8")
        labels = (scenario_labels or {}).get(relative, [])
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise ValueError("benchmark scenario labels must be strings")
        rows.append(
            {
                "input_id": hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16],
                "relative_path": relative,
                "character_count": len(text),
                "length_stratum": length_stratum(len(text)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "scenario_labels": list(labels),
            }
        )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "input_set_kind": input_set_kind,
        "gold_evidence": gold_evidence or {
            "status": "missing_gold_evidence",
            "reason": "no_expected_entity_contract",
        },
        "inputs": rows,
    }


def run_recognition_benchmark(
    manifest: dict[str, Any],
    *,
    base_dir: str | Path,
    gold_path: str | Path | None,
    code_commit: str,
    replicate_count: int = 1,
    evaluate: Callable[..., dict[str, Any]] = evaluate_gold_file,
) -> dict[str, Any]:
    if replicate_count <= 0:
        raise ValueError("replicate_count must be positive")
    base = Path(base_dir)
    manifest_hash = _stable_hash(manifest)
    runs: list[dict[str, Any]] = []
    for row in benchmark_matrix():
        for replicate_index in range(replicate_count):
            config = _config_for_row(row)
            evaluation: dict[str, Any] | None = None
            regression: dict[str, Any] | None = None
            recognition: dict[str, Any] = {"status": "failed"}
            try:
                if gold_path is None:
                    evaluation = None
                    failure_reason = "missing_gold_evidence"
                else:
                    evaluation = evaluate(gold_path, config=config)
                    failure_reason = None
                recognition = _recognition_summary(evaluation)
                regression = build_regression_report(
                    gold_report=evaluation,
                    sample_summaries=[],
                    sample_file=None,
                    report_started_monotonic=0.0,
                    report_finished_monotonic=0.0,
                    recognition=recognition,
                )
                status = "success" if evaluation is not None else "missing_evidence"
                error_type = failure_reason
            except Exception as exc:
                evaluation = None
                regression = None
                status = "failed"
                error_type = type(exc).__name__
            runs.append(
                {
                    "recognition_mode": row.recognition_mode,
                    "model_id": row.model_id,
                    "audited": row.audited,
                    "code_commit": code_commit,
                    "manifest_hash": manifest_hash,
                    "profile": config.profile,
                    "input_set_hash": _input_set_hash(manifest),
                    "gold_set_hash": _gold_hash(gold_path, base),
                    "temperature": config.llm.temperature if config.enable_llm else None,
                    "max_output_tokens": (
                        config.llm.full_document_max_output_tokens
                        if row.recognition_mode.startswith("full_document")
                        else None
                    ),
                    "timeout_seconds": (
                        config.llm.full_document_timeout_seconds
                        if row.recognition_mode.startswith("full_document")
                        else config.llm.timeout_seconds
                    ) if config.enable_llm else None,
                    "reasoning": "disabled_no_think" if config.enable_llm else "not_applicable",
                    "cold_warm_policy": str(manifest.get("cold_warm_policy") or "unspecified"),
                    "replicate_index": replicate_index,
                    "status": status,
                    "error_type": error_type,
                    "first_token_latency_ms": None,
                    "first_token_latency_reason": "stream_false_no_evidence",
                    "regression": regression,
                    "recognition": recognition,
                    "quality": _quality_summary(regression),
                    "workflow": _workflow_summary(regression),
                    "scenario_labels": _scenario_label_counts(manifest),
                }
            )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_hash": manifest_hash,
        "input_set_kind": manifest.get("input_set_kind"),
        "length_strata": _strata_counts(manifest),
        "runs": runs,
        "recommendation": _recommendation(runs),
        "privacy": {
            "safe_by_default": True,
            "raw_inputs": "omitted",
            "entity_values": "omitted",
            "prompt_bodies": "omitted",
            "absolute_paths": "omitted",
        },
    }
    assert_privacy_safe_recognition_report(report)
    return report


def recognition_benchmark_report_to_json(report: dict[str, Any]) -> str:
    assert_privacy_safe_recognition_report(report)
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def assert_privacy_safe_recognition_report(report: dict[str, Any]) -> None:
    forbidden_keys = {"prompt", "body", "completion", "entities", "mappings", "response", "request_body"}
    if any(key in forbidden_keys for _path, key in _key_paths(report)):
        raise ValueError("recognition benchmark contains raw diagnostic fields")
    for value in _string_values(report):
        if _contains_absolute_path(value):
            raise ValueError("recognition benchmark contains absolute path")


def length_stratum(character_count: int) -> str:
    if character_count < 10_000:
        return "<10k"
    if character_count < 30_000:
        return "10k-30k"
    if character_count < 60_000:
        return "30k-60k"
    return ">=60k"


def _config_for_row(row: BenchmarkMatrixRow) -> PipelineConfig:
    if not row.recognition_mode.startswith("full_document"):
        raise ValueError(f"unsupported benchmark recognition mode: {row.recognition_mode}")
    return PipelineConfig.max_effect(model=row.model_id, recognition_mode="full_document")


def _recognition_summary(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evaluation, dict):
        return {"status": "missing_evidence"}
    cases = evaluation.get("cases") if isinstance(evaluation.get("cases"), list) else []
    summaries = [case.get("recognition_stats") for case in cases if isinstance(case, dict)]
    summaries = [item for item in summaries if isinstance(item, dict)]
    return {
        "status": "success",
        "document_count": len(cases),
        "call_count": sum(int(item.get("call_count", 0)) for item in summaries),
        "retry_count": sum(int(item.get("retry_count", 0)) for item in summaries),
        "fallback_count": sum(int(item.get("fallback_count", 0)) for item in summaries),
        "conflict_count": sum(int(item.get("conflict_count", 0)) for item in summaries),
        "duration_ms": sum(int(item.get("duration_ms", 0)) for item in summaries),
        "prompt_token_count": _sum_optional_stats(summaries, "prompt_token_count"),
        "completion_token_count": _sum_optional_stats(summaries, "completion_token_count"),
        "total_token_count": _sum_optional_stats(summaries, "total_token_count"),
        "json_request_count": sum(int(item.get("call_count", 0)) for item in summaries),
        "json_success_count": sum(
            int(item.get("call_count", 0))
            for item in summaries
            if item.get("status") in {"success", "partial", "no_targets"}
        ),
        "category_counts": _sum_category_counts(summaries),
        "json_parse_failure_count": sum(
            int(item.get("fallback_count", 0))
            for item in summaries
            if _is_parse_failure_reason(item.get("reason"))
        ),
        "transport_failure_count": sum(
            int(item.get("fallback_count", 0))
            for item in summaries
            if item.get("reason") and not _is_parse_failure_reason(item.get("reason"))
        ),
    }


def _quality_summary(regression: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(regression, dict):
        return None
    gold = regression.get("gold")
    if not isinstance(gold, dict):
        return None
    allowed = (
        "case_count",
        "true_positive",
        "false_positive",
        "false_negative",
        "precision",
        "recall",
        "f1",
        "by_type",
        "high_risk_miss_count",
        "high_risk_miss_reason",
        "wrong_merge_count",
        "wrong_split_count",
        "identity_metric_reason",
    )
    return {key: gold.get(key) for key in allowed}


def _workflow_summary(regression: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(regression, dict):
        return None
    workflow = regression.get("workflow")
    if not isinstance(workflow, dict):
        return None
    allowed = (
        "manual_add_count",
        "manual_delete_count",
        "manual_modify_count",
        "manual_modify_reason",
        "review_action_total",
        "review_action_total_reason",
    )
    return {key: workflow.get(key) for key in allowed}


def _scenario_label_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in manifest.get("inputs", []):
        if not isinstance(item, dict):
            continue
        labels = item.get("scenario_labels")
        if not isinstance(labels, list):
            continue
        for label in labels:
            if isinstance(label, str) and label:
                counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))



def _sum_category_counts(summaries: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for summary in summaries:
        counts = summary.get("category_counts")
        if not isinstance(counts, dict):
            continue
        for category, count in counts.items():
            if isinstance(category, str) and isinstance(count, int) and not isinstance(count, bool):
                totals[category] = totals.get(category, 0) + max(0, count)
    return dict(sorted(totals.items()))



def _sum_optional_stats(summaries: list[dict[str, Any]], key: str) -> int | None:
    values = [item.get(key) for item in summaries]
    numeric = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return sum(numeric) if numeric else None


def _is_parse_failure_reason(reason: object) -> bool:
    return isinstance(reason, str) and any(
        marker in reason
        for marker in ("json", "registry_payload", "missing_entities", "invalid_registry")
    )


def _validate_manifest_input(item: object) -> None:
    if not isinstance(item, dict):
        raise ValueError("benchmark manifest input must be an object")
    for key in ("input_id", "relative_path", "character_count", "length_stratum", "sha256"):
        if key not in item:
            raise ValueError(f"benchmark manifest input missing {key}")
    path = str(item["relative_path"])
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("benchmark manifest paths must be relative")
    character_count = item["character_count"]
    if not isinstance(character_count, int) or isinstance(character_count, bool) or character_count < 0:
        raise ValueError("benchmark manifest character_count is invalid")
    if item["length_stratum"] not in LENGTH_STRATA:
        raise ValueError("benchmark manifest length_stratum is invalid")
    if item["length_stratum"] != length_stratum(character_count):
        raise ValueError("benchmark manifest length_stratum does not match character_count")
    digest = item["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest.lower())
    ):
        raise ValueError("benchmark manifest sha256 is invalid")
    labels = item.get("scenario_labels", [])
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise ValueError("benchmark manifest scenario_labels is invalid")


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _input_set_hash(manifest: dict[str, Any]) -> str:
    return _stable_hash([item.get("sha256") for item in manifest.get("inputs", []) if isinstance(item, dict)])


def _gold_hash(gold_path: str | Path | None, base_dir: Path) -> str | None:
    if gold_path is None:
        return None
    path = Path(gold_path)
    if not path.is_absolute():
        path = base_dir / path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strata_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts = {stratum: 0 for stratum in LENGTH_STRATA}
    for item in manifest.get("inputs", []):
        if isinstance(item, dict) and item.get("length_stratum") in counts:
            counts[str(item["length_stratum"])] += 1
    return counts


def _recommendation(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if any(run["status"] == "failed" for run in runs):
        return {"action": "manual_review", "reason": "failed_runs_present"}
    if any(run["status"] == "missing_evidence" for run in runs):
        return {"action": "manual_review", "reason": "missing_evidence"}
    full_document_runs = [run for run in runs if run["recognition_mode"].startswith("full_document")]
    if not full_document_runs:
        return {"action": "manual_review", "reason": "missing_full_document_rows"}
    if _has_quality_or_workflow_regression(full_document_runs, full_document_runs):
        return {"action": "manual_review", "reason": "quality_or_workflow_regression"}
    return {"action": "keep_full_document", "reason": "only_supported_recognition_mode"}


def _has_quality_or_workflow_regression(
    baseline_runs: list[dict[str, Any]],
    candidate_runs: list[dict[str, Any]],
) -> bool:
    baseline_quality = _average_run_metrics(
        baseline_runs,
        "quality",
        ("precision", "recall", "f1", "high_risk_miss_count", "wrong_merge_count"),
    )
    for run in candidate_runs:
        quality = run.get("quality") if isinstance(run.get("quality"), dict) else {}
        for field in ("precision", "recall", "f1"):
            if _number(quality.get(field)) is not None and _number(baseline_quality.get(field)) is not None:
                if quality[field] < baseline_quality[field]:
                    return True
        for field in ("high_risk_miss_count", "wrong_merge_count"):
            if _number(quality.get(field)) is not None and _number(baseline_quality.get(field)) is not None:
                if quality[field] > baseline_quality[field]:
                    return True
    return False


def _has_meaningful_improvement(
    baseline_runs: list[dict[str, Any]],
    candidate_runs: list[dict[str, Any]],
) -> bool:
    baseline_workflow = _average_run_metrics(baseline_runs, "workflow", ("review_action_total",))
    baseline_total = _number(baseline_workflow.get("review_action_total"))
    if baseline_total is None:
        return False
    return any(
        _number((run.get("workflow") or {}).get("review_action_total")) is not None
        and run["workflow"]["review_action_total"] < baseline_total
        for run in candidate_runs
        if isinstance(run.get("workflow"), dict)
    )


def _average_run_metrics(
    runs: list[dict[str, Any]],
    section: str,
    fields: tuple[str, ...],
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for field in fields:
        values = [
            number
            for run in runs
            if isinstance(run.get(section), dict)
            for number in [_number(run[section].get(field))]
            if number is not None
        ]
        result[field] = sum(values) / len(values) if values else None
    return result


def _number(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _key_paths(value: object, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            yield child_path, key_text
            yield from _key_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _key_paths(child, f"{path}[{index}]")


def _contains_absolute_path(value: str) -> bool:
    normalized = value.strip()
    return (
        normalized.startswith(("/", "~/", "~\\"))
        or ":\\" in normalized
        or " /Users/" in normalized
        or " /Volumes/" in normalized
        or " ~/" in normalized
    )


def _string_values(value: object):
    if isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child)
    elif isinstance(value, str):
        yield value
