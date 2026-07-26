from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from legal_redactor.evaluation import evaluate_case
from legal_redactor.models import MappingEntry, RecognitionRunStats, RedactionMap
from legal_redactor.recognition_benchmark import (
    MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    assert_privacy_safe_recognition_report,
    benchmark_matrix,
    build_benchmark_manifest,
    length_stratum,
    run_recognition_benchmark,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict[str, object]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "input_set_kind": "synthetic",
        "gold_evidence": {"status": "supplied", "annotation_contract": "gold-v1"},
        "inputs": [
            {
                "input_id": "case-a",
                "relative_path": "case-a.txt",
                "character_count": 12,
                "length_stratum": "<10k",
                "sha256": "a" * 64,
                "scenario_labels": ["aliases"],
            }
        ],
    }


def _evaluation_for_config(_gold_path, *, config):
    stats = RecognitionRunStats(
        mode=config.llm.recognition_mode if config.enable_llm else "rules_ner",
        model_id=config.llm.model if config.enable_llm else None,
        status="success",
        call_count=1 if config.enable_llm else 0,
        retry_count=0,
        fallback_count=0,
        conflict_count=2 if config.llm.recognition_mode == "full_document" else 0,
        duration_ms=125 if config.enable_llm else 5,
        prompt_token_count=100 if config.enable_llm else None,
        completion_token_count=20 if config.enable_llm else None,
        total_token_count=120 if config.enable_llm else None,
        category_counts={"agreed": 1},
    )
    return {
        "case_count": 1,
        "true_positive": 1,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "by_type": {"person": {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}},
        "high_risk_miss_count": 0,
        "high_risk_miss_reason": None,
        "wrong_merge_count": 0,
        "wrong_split_count": 0,
        "identity_metric_reason": None,
        "cases": [{"recognition_stats": stats.to_dict()}],
    }


def test_benchmark_matrix_covers_supported_full_document_models() -> None:
    rows = benchmark_matrix()

    assert len(rows) == 2
    assert {(row.recognition_mode, row.model_id) for row in rows} == {
        ("full_document", "bonsai-27b"),
        ("full_document", "qwen3.5-9b"),
    }
    assert all(not row.audited for row in rows)


@pytest.mark.parametrize(
    ("character_count", "expected"),
    [
        (9_999, "<10k"),
        (10_000, "10k-30k"),
        (29_999, "10k-30k"),
        (30_000, "30k-60k"),
        (59_999, "30k-60k"),
        (60_000, ">=60k"),
    ],
)
def test_length_stratum_boundaries(character_count: int, expected: str) -> None:
    assert length_stratum(character_count) == expected


def test_build_manifest_uses_relative_paths_hashes_and_declared_labels(tmp_path) -> None:
    document = tmp_path / "case-a.txt"
    document.write_text("原告张三。", encoding="utf-8")

    manifest = build_benchmark_manifest(
        [document],
        base_dir=tmp_path,
        input_set_kind="synthetic",
        scenario_labels={"case-a.txt": ["person-name"]},
    )

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["inputs"][0]["relative_path"] == "case-a.txt"
    assert manifest["inputs"][0]["scenario_labels"] == ["person-name"]
    encoded = json.dumps(manifest, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "原告张三" not in encoded


def test_runner_keeps_all_runs_and_numeric_recognition_evidence(tmp_path) -> None:
    gold_path = tmp_path / "gold.json"
    gold_path.write_text("{}", encoding="utf-8")

    report = run_recognition_benchmark(
        _manifest(),
        base_dir=tmp_path,
        gold_path=gold_path,
        code_commit="abc123",
        replicate_count=2,
        evaluate=_evaluation_for_config,
    )

    assert report["schema_version"] == SCHEMA_VERSION
    assert len(report["runs"]) == 4
    assert {run["replicate_index"] for run in report["runs"]} == {0, 1}
    assert all(run["code_commit"] == "abc123" for run in report["runs"])
    assert all(run["manifest_hash"] == report["manifest_hash"] for run in report["runs"])
    assert all(run["recognition_mode"] == "full_document" for run in report["runs"])
    assert all(run["recognition"]["call_count"] == 1 for run in report["runs"])
    assert all(run["recognition"]["total_token_count"] == 120 for run in report["runs"])
    assert all(run["first_token_latency_ms"] is None for run in report["runs"])
    assert all(run["first_token_latency_reason"] == "stream_false_no_evidence" for run in report["runs"])
    assert report["recommendation"] == {
        "action": "keep_full_document",
        "reason": "only_supported_recognition_mode",
    }


def test_runner_preserves_failed_rows(tmp_path) -> None:
    gold_path = tmp_path / "gold.json"
    gold_path.write_text("{}", encoding="utf-8")
    call_count = 0

    def sometimes_fails(_gold_path, *, config):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TimeoutError("synthetic timeout")
        return _evaluation_for_config(_gold_path, config=config)

    report = run_recognition_benchmark(
        _manifest(),
        base_dir=tmp_path,
        gold_path=gold_path,
        code_commit="abc123",
        evaluate=sometimes_fails,
    )

    assert len(report["runs"]) == 2
    assert sum(run["status"] == "failed" for run in report["runs"]) == 1
    assert report["recommendation"] == {"action": "manual_review", "reason": "failed_runs_present"}


def test_missing_gold_is_explicit_and_never_runs_evaluator(tmp_path) -> None:
    def unexpected_evaluate(*_args, **_kwargs):
        raise AssertionError("evaluator must not run without gold evidence")

    report = run_recognition_benchmark(
        _manifest(),
        base_dir=tmp_path,
        gold_path=None,
        code_commit="abc123",
        evaluate=unexpected_evaluate,
    )

    assert len(report["runs"]) == 2
    assert all(run["status"] == "missing_evidence" for run in report["runs"])
    assert report["recommendation"] == {"action": "manual_review", "reason": "missing_evidence"}


def test_privacy_sanitizer_rejects_raw_fields_and_absolute_paths() -> None:
    with pytest.raises(ValueError, match="raw diagnostic fields"):
        assert_privacy_safe_recognition_report({"runs": [{"prompt": "private"}]})
    with pytest.raises(ValueError, match="absolute path"):
        assert_privacy_safe_recognition_report({"runs": [{"error_type": "/Users/example/private"}]})


def test_evaluation_reports_type_and_identity_metrics_from_annotations(tmp_path) -> None:
    class FixedPipeline:
        def redact(self, _text, source_file=None):
            mappings = [
                MappingEntry(
                    type="person",
                    original="甲某",
                    masked="当事人A",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                    entity_id="person-1",
                ),
                MappingEntry(
                    type="person",
                    original="甲先生",
                    masked="当事人B",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                    entity_id="person-1",
                ),
                MappingEntry(
                    type="person",
                    original="乙某",
                    masked="当事人A",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                    entity_id="person-2",
                ),
                MappingEntry(
                    type="organization",
                    original="示例公司",
                    masked="某公司",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                ),
            ]
            return type(
                "Result",
                (),
                {
                    "redaction_map": RedactionMap.create(mappings, source_file=source_file),
                    "warnings": [],
                    "leaks": [],
                    "recognition_stats": None,
                },
            )()

    report = evaluate_case(
        {
            "name": "synthetic",
            "text": "甲某又称甲先生，与乙某及示例公司有关。",
            "expected": [
                {
                    "type": "person",
                    "original": "甲某",
                    "entity_id": "person-1",
                    "alias_group": "person-1",
                    "do_not_merge": ["person-2"],
                    "high_risk": True,
                },
                {
                    "type": "person",
                    "original": "甲先生",
                    "entity_id": "person-1",
                    "alias_group": "person-1",
                },
                {"type": "person", "original": "乙某", "entity_id": "person-2"},
            ],
        },
        pipeline=FixedPipeline(),
        base_dir=tmp_path,
    )

    assert report["by_type_counts"]["person"] == {"tp": 3, "fp": 0, "fn": 0}
    assert report["by_type_counts"]["organization"] == {"tp": 0, "fp": 1, "fn": 0}
    assert report["high_risk_miss_count"] == 0
    assert report["wrong_merge_count"] == 1
    assert report["wrong_split_count"] == 1


def test_cli_writes_report_and_bad_json_has_no_traceback(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "recognition-report.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--recognition-benchmark-manifest",
            str(manifest_path),
            "--recognition-benchmark-base-dir",
            str(tmp_path),
            "--recognition-benchmark-code-commit",
            "abc123",
            "--recognition-benchmark-report",
            str(output_path),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[识别基准]" in result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload["runs"]) == 2
    assert all(run["status"] == "missing_evidence" for run in payload["runs"])

    bad_manifest = tmp_path / "bad-manifest.json"
    bad_output = tmp_path / "bad-report.json"
    bad_manifest.write_text("{", encoding="utf-8")
    failing = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--recognition-benchmark-manifest",
            str(bad_manifest),
            "--recognition-benchmark-code-commit",
            "abc123",
            "--recognition-benchmark-report",
            str(bad_output),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )

    assert failing.returncode == 1
    assert "[识别基准错误]" in failing.stderr
    assert "Traceback" not in failing.stderr
    assert not bad_output.exists()
