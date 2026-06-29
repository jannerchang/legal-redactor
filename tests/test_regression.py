from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from legal_redactor.models import MappingEntry, RedactionMap
from legal_redactor.regression import (
    aggregate_sample_summaries,
    assert_privacy_safe_report,
    build_regression_report,
    project_gold_report,
    restore_placeholder_metric,
    sample_provenance,
    timing_metrics,
)


RAW_PERSON = "张三"
RAW_COMPANY = "星河建设有限公司"
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_gold_report_keeps_metrics_and_drops_raw_diagnostics() -> None:
    sensitive_case_name = "张三诉星河建设有限公司案"
    raw_report = {
        "case_count": 1,
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
        "cases": [
            {
                "name": "case-a",
                "source_file": "case-a.txt",
                "expected_count": 2,
                "actual_count": 2,
                "true_positive": 1,
                "false_positive": 1,
                "false_negative": 1,
                "precision": 0.5,
                "recall": 0.5,
                "f1": 0.5,
                "matched": [{"original": RAW_PERSON, "masked": "张某"}],
                "missing": [{"original": RAW_COMPANY, "masked": "某公司"}],
                "extra": [{"original": "李四", "masked": "李某"}],
                "warnings": [RAW_COMPANY],
                "leaks": [{"text": RAW_PERSON}],
            }
        ],
    }

    gold = project_gold_report(raw_report)

    assert gold["case_count"] == 1
    assert gold["precision"] == 0.5
    assert gold["recall"] == 0.5
    assert gold["f1"] == 0.5
    assert gold["cases"] == [
        {
            "case_id": "case-1",
            "expected_count": 2,
            "actual_count": 2,
            "true_positive": 1,
            "false_positive": 1,
            "false_negative": 1,
            "precision": 0.5,
            "recall": 0.5,
            "f1": 0.5,
        }
    ]
    encoded = json.dumps(gold, ensure_ascii=False)
    assert RAW_PERSON not in encoded
    assert RAW_COMPANY not in encoded
    raw_report["cases"][0]["name"] = sensitive_case_name
    assert sensitive_case_name not in json.dumps(project_gold_report(raw_report), ensure_ascii=False)
    assert "matched" not in encoded
    assert "missing" not in encoded
    assert "extra" not in encoded


def test_workflow_summary_aggregates_counts_without_forged_labels() -> None:
    summaries = [
        {
            "manual_corrections": 2,
            "false_positive_deletes": 1,
            "missing_adds": 1,
            "lookup_entries": [{"original": RAW_COMPANY, "masked": "某公司"}],
            "delete_blacklist_candidates": [{"original": RAW_PERSON}],
            "suppressed_risky_entries": [{"original": "冀"}],
            "regression_suggestions": ["pytest tests/test_sample_integration.py"],
            "workflow_state": "sent_discord",
            "status": "all_green",
        },
        {
            "manual_corrections": 1,
            "false_positive_deletes": 0,
            "missing_adds": 1,
            "lookup_entries": [{"original": "李四", "masked": "李某"}],
            "delete_blacklist_candidates": [],
            "suppressed_risky_entries": [],
            "regression_suggestions": ["pytest tests/test_web_app.py"],
        },
    ]

    workflow = aggregate_sample_summaries(summaries)

    assert workflow["summary_count"] == 2
    assert workflow["manual_corrections"] == 3
    assert workflow["false_positive_deletes"] == 1
    assert workflow["missing_adds"] == 2
    assert workflow["lookup_entry_count"] == 2
    assert workflow["delete_blacklist_candidate_count"] == 1
    assert workflow["suppressed_risky_entry_count"] == 1
    assert workflow["ignored_browser_fields"] == ["status", "workflow_state"]
    encoded = json.dumps(workflow, ensure_ascii=False)
    assert RAW_PERSON not in encoded
    assert RAW_COMPANY not in encoded


def test_sample_provenance_is_metadata_only(tmp_path) -> None:
    sample_file = tmp_path / "_auto.sample.json"
    sample_file.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-29T08:00:00+00:00",
                "entries": [
                    {"action": "add", "original": RAW_PERSON, "masked": "张某"},
                    {"action": "delete", "original": RAW_COMPANY},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provenance = sample_provenance(sample_file)

    assert provenance["sample_file"] == "_auto.sample.json"
    assert provenance["exists"] is True
    assert provenance["entry_count"] == 2
    assert provenance["has_updated_at"] is True
    encoded = json.dumps(provenance, ensure_ascii=False)
    assert RAW_PERSON not in encoded
    assert RAW_COMPANY not in encoded


def test_restore_placeholder_metric_requires_text_and_map() -> None:
    redaction_map = RedactionMap(
        version="1.0",
        created_at="2026-06-29T08:00:00+08:00",
        mode="normal",
        source_file="case.txt",
        mappings=[
            MappingEntry("person", RAW_PERSON, "张某", None, "rule", 1.0, True),
            MappingEntry("organization", RAW_COMPANY, "某公司", None, "rule", 1.0, True),
        ],
    )

    assert restore_placeholder_metric(None, redaction_map) is None
    assert restore_placeholder_metric("原告张某仍与某公司有关，某公司重复出现。", None) is None

    metric = restore_placeholder_metric("原告张某仍与某公司有关，某公司重复出现。", redaction_map)
    assert metric == {
        "unresolved_placeholder_count": 3,
        "mapped_placeholder_count": 2,
        "evidence": "supplied",
    }


def test_timing_metrics_are_integer_or_null_with_reason() -> None:
    missing = timing_metrics(
        report_started_monotonic=10.0,
        report_finished_monotonic=10.125,
    )
    assert missing["report_generation_ms"] == 125
    assert missing["document_input_to_saved_case_ms"] is None
    assert missing["document_input_to_saved_case_reason"] == "missing_timestamp_evidence"
    assert missing["discord_thread_to_restored_ms"] is None
    assert missing["discord_thread_to_restored_reason"] == "deferred_to_M7"

    measured = timing_metrics(
        report_started_monotonic=10.0,
        report_finished_monotonic=10.25,
        document_input_at="2026-06-29T08:00:00+00:00",
        saved_case_at="2026-06-29T08:00:01.250000+00:00",
    )
    assert measured["report_generation_ms"] == 250
    assert measured["document_input_to_saved_case_ms"] == 1250
    assert measured["document_input_to_saved_case_reason"] == "computed_from_supplied_timestamps"


def test_build_regression_report_schema_and_privacy(tmp_path) -> None:
    report = build_regression_report(
        gold_report={"case_count": 0, "true_positive": 0, "false_positive": 0, "false_negative": 0},
        sample_summaries=[{"manual_corrections": 1, "regression_suggestions": ["pytest focused"]}],
        sample_file=None,
        redacted_text=None,
        redaction_map=None,
        report_started_monotonic=1.0,
        report_finished_monotonic=1.01,
    )

    assert set(report) == {
        "schema_version",
        "generated_at",
        "gold",
        "workflow",
        "samples",
        "restore",
        "timing",
        "privacy",
        "regression_suggestions",
    }
    assert report["schema_version"] == "M6-regression-report/v1"
    assert report["restore"] is None
    assert report["samples"]["newest_sample_provenance"]["exists"] is False
    assert report["privacy"]["safe_by_default"] is True
    assert report["regression_suggestions"] == ["pytest focused"]
    assert_privacy_safe_report(report)


def test_build_regression_report_measures_assembly_when_finish_time_omitted(monkeypatch) -> None:
    monkeypatch.setattr("legal_redactor.regression.time.monotonic", lambda: 2.25)

    report = build_regression_report(
        gold_report={"case_count": 0, "true_positive": 0, "false_positive": 0, "false_negative": 0},
        sample_summaries=[],
        sample_file=None,
        redacted_text=None,
        redaction_map=None,
        report_started_monotonic=1.0,
        report_finished_monotonic=None,
    )

    assert report["timing"]["report_generation_ms"] == 1250


def test_privacy_sanitizer_rejects_sensitive_free_text_values() -> None:
    unsafe_report = {
        "schema_version": "M6-regression-report/v1",
        "gold": {"cases": [{"case_id": RAW_PERSON}]},
    }

    try:
        assert_privacy_safe_report(unsafe_report)
    except ValueError as exc:
        assert "sensitive report values" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected privacy sanitizer to reject sensitive value")


def test_cli_writes_privacy_safe_regression_report_and_thresholds(tmp_path) -> None:
    gold_path = tmp_path / "gold.json"
    report_path = tmp_path / "regression.json"
    summary_path = tmp_path / "summary.json"
    sample_path = tmp_path / "_auto.sample.json"
    redacted_path = tmp_path / "redacted.txt"
    map_path = tmp_path / "redaction_map.json"

    gold_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "synthetic",
                        "text": "原告张三提交证据。",
                        "expected": [{"type": "person", "original": RAW_PERSON}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"manual_corrections": 1, "missing_adds": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    sample_path.write_text(
        json.dumps({"entries": [{"action": "add", "original": RAW_PERSON, "masked": "张某"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    redacted_path.write_text("原告张某提交证据。", encoding="utf-8")
    map_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "created_at": "2026-06-29T08:00:00+08:00",
                "mode": "normal",
                "source_file": "synthetic.txt",
                "mappings": [
                    {
                        "type": "person",
                        "original": RAW_PERSON,
                        "masked": "张某",
                        "role": None,
                        "source": "test",
                        "confidence": 1.0,
                        "restore_by_default": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--llm",
            "off",
            "--eval-gold",
            str(gold_path),
            "--eval-fail-under-recall",
            "0.0",
            "--eval-fail-under-precision",
            "0.0",
            "--regression-report",
            str(report_path),
            "--regression-sample-summary",
            str(summary_path),
            "--regression-sample-file",
            str(sample_path),
            "--regression-redacted",
            str(redacted_path),
            "--regression-map",
            str(map_path),
            "--regression-input-at",
            "2026-06-29T08:00:00+00:00",
            "--regression-saved-at",
            "2026-06-29T08:00:01+00:00",
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "[回归报告]" in result.stdout

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["gold"]["case_count"] == 1
    assert payload["workflow"]["manual_corrections"] == 1
    assert payload["restore"]["unresolved_placeholder_count"] == 1
    assert payload["timing"]["document_input_to_saved_case_ms"] == 1000
    encoded = json.dumps(payload, ensure_ascii=False)
    assert RAW_PERSON not in encoded
    assert '"matched"' not in encoded
    assert '"missing"' not in encoded
    assert '"extra"' not in encoded

    failing = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--llm",
            "off",
            "--eval-gold",
            str(gold_path),
            "--eval-fail-under-recall",
            "1.1",
            "--regression-report",
            str(tmp_path / "regression-fail.json"),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert failing.returncode == 2


def test_cli_reports_malformed_inputs_without_traceback(tmp_path) -> None:
    bad_gold = tmp_path / "bad-gold.json"
    bad_summary = tmp_path / "bad-summary.json"
    report_path = tmp_path / "regression.json"
    bad_gold.write_text("{", encoding="utf-8")
    bad_summary.write_text("{", encoding="utf-8")

    gold_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--llm",
            "off",
            "--eval-gold",
            str(bad_gold),
            "--regression-report",
            str(report_path),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert gold_result.returncode == 1
    assert "[回归报告错误]" in gold_result.stderr
    assert "Traceback" not in gold_result.stderr
    assert not report_path.exists()

    summary_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_redactor",
            "--regression-report",
            str(report_path),
            "--regression-sample-summary",
            str(bad_summary),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert summary_result.returncode == 1
    assert "[回归报告错误]" in summary_result.stderr
    assert "Traceback" not in summary_result.stderr
    assert not report_path.exists()
