from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from legal_redactor.runtime_benchmark import (
    BenchmarkCandidateInput,
    assert_privacy_safe_benchmark_report,
    build_runtime_benchmark_report,
    summarize_models_probe,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _context(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "gold_set_id": "spc-public-v1",
        "gold_set_hash": "a" * 64,
        "input_set_id": "public-spc-samples-v1",
        "input_set_kind": "public_spc_sample",
        "input_set_hash": "b" * 64,
        "sample_provenance_id": "sample-meta-v1",
        "benchmark_profile": "m8-default-v1",
    }
    value.update(overrides)
    return value


def _m6_report(
    *,
    f1: float = 1.0,
    precision: float = 1.0,
    recall: float = 1.0,
    manual_corrections: int = 0,
    false_positive_deletes: int = 0,
    missing_adds: int = 0,
    suppressed_risky_entry_count: int = 0,
    restore_unresolved_placeholder_count: int | None = None,
    gold_evaluation_ms: int | None = 900,
    report_generation_ms: int | None = 100,
    document_input_to_saved_case_ms: int | None = None,
) -> dict[str, object]:
    restore = None
    if restore_unresolved_placeholder_count is not None:
        restore = {
            "unresolved_placeholder_count": restore_unresolved_placeholder_count,
            "mapped_placeholder_count": 1,
            "evidence": "supplied",
        }
    return {
        "schema_version": "M6-regression-report/v1",
        "generated_at": "2026-07-03T00:00:00+00:00",
        "gold": {
            "available": True,
            "case_count": 2,
            "true_positive": 4,
            "false_positive": 0,
            "false_negative": 0,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "cases": [],
        },
        "workflow": {
            "summary_count": 1,
            "manual_corrections": manual_corrections,
            "false_positive_deletes": false_positive_deletes,
            "missing_adds": missing_adds,
            "lookup_entry_count": 0,
            "delete_blacklist_candidate_count": 0,
            "suppressed_risky_entry_count": suppressed_risky_entry_count,
            "restore_unresolved_placeholder_count": restore_unresolved_placeholder_count,
            "ignored_browser_fields": [],
        },
        "samples": {
            "newest_sample_provenance": {
                "exists": True,
                "sample_file": "_auto.sample.json",
                "mtime": "2026-07-03T00:00:00+00:00",
                "size_bytes": 120,
                "entry_count": 3,
                "has_updated_at": True,
                "updated_at": "2026-07-03T00:00:00+00:00",
                "freshness": "metadata_only",
            }
        },
        "restore": restore,
        "timing": {
            "report_generation_ms": report_generation_ms,
            "gold_evaluation_ms": gold_evaluation_ms,
            "document_input_to_saved_case_ms": document_input_to_saved_case_ms,
            "document_input_to_saved_case_reason": "missing_timestamp_evidence",
            "discord_thread_to_restored_ms": None,
            "discord_thread_to_restored_reason": "deferred_to_M7",
        },
        "privacy": {
            "safe_by_default": True,
            "gold_raw_diagnostics": "omitted",
            "sample_entries": "omitted",
            "map_values": "omitted",
            "restored_content": "omitted",
            "debug_traces": "omitted",
        },
        "regression_suggestions": [],
    }


def _candidate(
    label: str,
    report: dict[str, object],
    *,
    context: dict[str, object] | None = None,
    observation: dict[str, object] | None = None,
) -> BenchmarkCandidateInput:
    return BenchmarkCandidateInput(
        label=label,
        runtime_kind="mlx" if label != "rules-only" else "rules_only",
        runtime_config_id=f"{label}-config",
        m6_report_path=Path("output") / f"{label}.json",
        m6_report=report,
        benchmark_context=context or _context(),
        observation=observation or {},
    )


def test_build_report_blocks_auto_switch_when_required_metric_evidence_is_missing() -> None:
    report = build_runtime_benchmark_report(
        [_candidate("baseline", _m6_report()), _candidate("rapid-mlx", _m6_report(gold_evaluation_ms=700))],
        generated_at="2026-07-03T00:00:00+00:00",
    )

    assert report["schema_version"] == "M8-runtime-benchmark-report/v1"
    assert report["comparison"]["compatible"] is True
    assert report["comparison"]["deltas"][0]["label"] == "rapid-mlx"
    assert report["comparison"]["deltas"][0]["timing"]["total_redaction_eval_ms_delta"] == -200
    assert report["candidates"][1]["timing"]["first_token_latency_ms"] is None
    assert report["candidates"][1]["timing"]["first_token_latency_reason"] == "missing_probe_evidence"
    assert report["candidates"][1]["resources"]["peak_memory_mb"] is None
    assert report["candidates"][1]["resources"]["peak_memory_reason"] == "missing_resource_evidence"
    assert report["candidates"][1]["errors"]["error_count"] == 0
    assert report["candidates"][1]["errors"]["error_rate"] is None
    assert report["candidates"][1]["errors"]["error_rate_reason"] == "missing_error_rate_evidence"
    assert report["recommendation"]["action"] == "manual_review"
    assert report["recommendation"]["reason"] == "missing_metric_evidence"
    assert "first_token_latency_ms" in report["recommendation"]["missing_evidence"]
    assert_privacy_safe_benchmark_report(report)


def test_complete_evidence_can_recommend_faster_candidate_without_quality_regression() -> None:
    observation = {
        "timing": {"first_token_latency_ms": 120, "web_workflow_ms": 1000},
        "resources": {"peak_memory_mb": 2400},
        "errors": {"error_count": 0, "error_rate": 0.0},
        "probe": {"model_match": True, "endpoint_label": "local-mlx"},
    }

    report = build_runtime_benchmark_report(
        [
            _candidate("baseline", _m6_report(gold_evaluation_ms=900), observation=observation),
            _candidate("rapid-mlx", _m6_report(gold_evaluation_ms=600), observation=observation),
        ],
        generated_at="2026-07-03T00:00:00+00:00",
    )

    assert report["recommendation"] == {
        "action": "candidate_faster_no_regression",
        "reason": "best_candidate_faster_with_no_regression",
        "winner": "rapid-mlx",
        "missing_evidence": [],
    }


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("precision", {"precision": 0.99}),
        ("recall", {"recall": 0.99}),
        ("f1", {"f1": 0.99}),
        ("manual_corrections", {"manual_corrections": 1}),
        ("false_positive_deletes", {"false_positive_deletes": 1}),
        ("missing_adds", {"missing_adds": 1}),
        ("suppressed_risky_entry_count", {"suppressed_risky_entry_count": 1}),
        ("restore_unresolved_placeholder_count", {"restore_unresolved_placeholder_count": 1}),
    ],
)
def test_quality_or_workflow_regression_blocks_runtime_switch(field: str, kwargs: dict[str, object]) -> None:
    observation = {
        "timing": {"first_token_latency_ms": 120, "web_workflow_ms": 1000},
        "resources": {"peak_memory_mb": 2400},
        "errors": {"error_count": 0, "error_rate": 0.0},
        "probe": {"model_match": True, "endpoint_label": "local-mlx"},
    }

    report = build_runtime_benchmark_report(
        [
            _candidate("baseline", _m6_report(gold_evaluation_ms=900), observation=observation),
            _candidate("rapid-mlx", _m6_report(gold_evaluation_ms=600, **kwargs), observation=observation),
        ],
        generated_at="2026-07-03T00:00:00+00:00",
    )

    assert report["recommendation"]["action"] == "no_switch"
    assert report["recommendation"]["reason"] == "quality_or_workflow_regression"
    assert report["comparison"]["quality_regressions"] == [
        {
            "label": "rapid-mlx",
            "fields": [field],
        }
    ]


def test_context_mismatch_blocks_winner_selection() -> None:
    report = build_runtime_benchmark_report(
        [
            _candidate("baseline", _m6_report()),
            _candidate("rapid-mlx", _m6_report(), context=_context(input_set_hash="c" * 64)),
        ],
        generated_at="2026-07-03T00:00:00+00:00",
    )

    assert report["comparison"]["compatible"] is False
    assert report["comparison"]["context_mismatches"] == [
        {
            "label": "rapid-mlx",
            "fields": ["input_set_hash"],
        }
    ]
    assert report["recommendation"]["action"] == "manual_review"
    assert report["recommendation"]["reason"] == "benchmark_context_mismatch"


def test_privacy_boundary_rejects_raw_diagnostics_but_allows_m6_omitted_flags() -> None:
    report = build_runtime_benchmark_report(
        [_candidate("rules-only", _m6_report()), _candidate("mlx", _m6_report())],
        generated_at="2026-07-03T00:00:00+00:00",
    )
    assert report["privacy"]["sample_entries"] == "omitted"
    assert_privacy_safe_benchmark_report(report)

    unsafe_m6 = _m6_report()
    unsafe_m6["matched"] = [{"original": "Zhang San"}]
    with pytest.raises(ValueError, match="raw diagnostic fields"):
        build_runtime_benchmark_report([_candidate("baseline", unsafe_m6), _candidate("mlx", _m6_report())])

    unsafe_report = dict(report)
    unsafe_report["sample_entries"] = [{"original": "Zhang San"}]
    with pytest.raises(ValueError, match="sample_entries"):
        assert_privacy_safe_benchmark_report(unsafe_report)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "private manifest at /Users/jannerchang/legal-redactor/output/private",
        "private manifest at /Volumes/cases/output/private",
        "private manifest at ~/cases/output/private",
        r"private manifest at C:\\Users\\janner\\cases\\private",
    ],
)
def test_privacy_boundary_rejects_embedded_absolute_paths(unsafe_value: str) -> None:
    observation = {
        "timing": {"first_token_latency_ms": 120, "web_workflow_ms": 1000},
        "resources": {"peak_memory_mb": 2400},
        "errors": {"error_count": 0, "error_rate": 0.0},
        "probe": {"model_match": True, "endpoint_label": unsafe_value},
    }

    with pytest.raises(ValueError, match="absolute path|sensitive report values"):
        build_runtime_benchmark_report(
            [
                _candidate("baseline", _m6_report(), observation=observation),
                _candidate(
                    "rapid-mlx",
                    _m6_report(gold_evaluation_ms=600),
                    context=_context(input_set_id=unsafe_value),
                    observation=observation,
                ),
            ],
            generated_at="2026-07-03T00:00:00+00:00",
        )


def test_models_probe_summary_uses_logical_identity_without_prompt_or_body() -> None:
    selected_model = "bonsai-27b"
    ready = summarize_models_probe({"data": [{"id": selected_model}]}, expected_model=selected_model)
    wrong = summarize_models_probe({"data": [{"id": "other-model"}]}, expected_model=selected_model)

    assert ready == {
        "model_match": True,
        "expected_model": selected_model,
        "observed_model_count": 1,
        "status": "ready",
    }
    assert wrong["model_match"] is False
    assert wrong["status"] == "model_mismatch"
    encoded = json.dumps(ready, ensure_ascii=False)
    assert "prompt" not in encoded
    assert "body" not in encoded


def test_cli_writes_runtime_benchmark_report_and_errors_without_traceback(tmp_path) -> None:
    context_path = tmp_path / "context.json"
    baseline_path = tmp_path / "baseline.json"
    rapid_path = tmp_path / "rapid.json"
    output_path = tmp_path / "benchmark.json"
    context_path.write_text(json.dumps(_context()), encoding="utf-8")
    baseline_path.write_text(json.dumps(_m6_report()), encoding="utf-8")
    rapid_path.write_text(json.dumps(_m6_report(gold_evaluation_ms=700)), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--runtime-benchmark-report",
            str(output_path),
            "--benchmark-context",
            str(context_path),
            "--benchmark-candidate",
            "baseline",
            "mlx",
            "mlx-lm",
            str(baseline_path),
            "--benchmark-candidate",
            "rapid-mlx",
            "mlx",
            "rapid-mlx",
            str(rapid_path),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[运行时基准]" in result.stdout
    assert "baseline" in result.stdout
    assert "rapid-mlx" in result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "M8-runtime-benchmark-report/v1"
    assert payload["recommendation"]["action"] == "manual_review"
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)

    bad_report = tmp_path / "bad.json"
    bad_output = tmp_path / "bad-benchmark.json"
    bad_report.write_text("{", encoding="utf-8")
    failing = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--runtime-benchmark-report",
            str(bad_output),
            "--benchmark-context",
            str(context_path),
            "--benchmark-candidate",
            "baseline",
            "mlx",
            "mlx-lm",
            str(bad_report),
            "--benchmark-candidate",
            "rapid-mlx",
            "mlx",
            "rapid-mlx",
            str(rapid_path),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert failing.returncode == 1
    assert "[基准报告错误]" in failing.stderr
    assert "Traceback" not in failing.stderr
    assert not bad_output.exists()


def test_runtime_benchmark_tests_are_not_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "tests/test_runtime_benchmark.py"],
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
