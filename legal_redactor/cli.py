from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import PipelineConfig
from .io import (
    load_redaction_map_auto,
    read_document,
    save_redaction_map_auto,
    write_document,
)
from .pipeline import RedactionPipeline
from .restore import preview_restore, restore_docx, restore_text
from .recognition_benchmark import (
    load_benchmark_manifest,
    recognition_benchmark_report_to_json,
    run_recognition_benchmark,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legal-redactor", description="本地中文法律文书脱敏系统")
    subparsers = parser.add_subparsers(dest="command", required=True)

    redact_parser = subparsers.add_parser("redact", help="脱敏 txt/md/docx")
    redact_parser.add_argument("input", help="输入文档路径")
    redact_parser.add_argument("--out", default="output", help="输出目录")
    redact_parser.add_argument("--no-llm", action="store_true", help="禁用本地 LLM，使用离线规则兜底")
    redact_parser.add_argument(
        "--llm-mode",
        choices=("max-effect", "balanced", "off"),
        default="max-effect",
        help="本地 model-manager 的语义识别模式",
    )
    redact_parser.add_argument(
        "--recognition-mode",
        choices=("sentence_windows", "full_document"),
        default="sentence_windows",
        help="实体识别路径；整篇文书为实验模式",
    )
    redact_parser.add_argument("--model", default="bonsai-27b", help="model-manager 返回的逻辑模型 ID")
    redact_parser.add_argument("--debug-trace", action="store_true", help="额外输出 debug_trace.json")

    restore_parser = subparsers.add_parser("restore", help="按 redaction_map 反向还原")
    restore_parser.add_argument("input", help="AI 修改后的脱敏文档")
    restore_parser.add_argument("map", help="redaction_map.enc/.json")
    restore_parser.add_argument("--out", default="output/restored.txt", help="还原输出路径")
    restore_parser.add_argument("--preview", action="store_true", help="输出差异预览")

    samples_parser = subparsers.add_parser("samples", help="管理样本库（仅优化用途，不参与运行时脱敏）")
    samples_subparsers = samples_parser.add_subparsers(dest="samples_command", required=True)
    recent_errors_parser = samples_subparsers.add_parser("recent-errors", help="按时间查看最新错误样本")
    recent_errors_parser.add_argument("--limit", type=int, default=50, help="最多输出条数")
    clear_parser = samples_subparsers.add_parser("clear", help="清空样本库并重建可写空自动样本")
    clear_parser.add_argument(
        "--samples-dir",
        default="",
        help="样本目录（默认 samples/）",
    )

    eval_parser = subparsers.add_parser("eval", help="用 gold set 评估识别率")
    eval_parser.add_argument("gold", help="gold set JSON 路径")
    eval_parser.add_argument("--out", default="", help="保存完整 JSON 报告的路径")
    eval_parser.add_argument("--no-llm", action="store_true", help="禁用本地 LLM，评估离线规则")
    eval_parser.add_argument(
        "--llm-mode",
        choices=("max-effect", "balanced", "off"),
        default="max-effect",
        help="评估使用的本地 model-manager 模式",
    )
    eval_parser.add_argument(
        "--recognition-mode",
        choices=("sentence_windows", "full_document"),
        default="sentence_windows",
        help="评估使用的实体识别路径",
    )
    eval_parser.add_argument("--model", default="bonsai-27b", help="model-manager 返回的逻辑模型 ID")
    eval_parser.add_argument("--fail-under-recall", type=float, default=None, help="低于该 recall 时返回非零")
    eval_parser.add_argument("--fail-under-precision", type=float, default=None, help="低于该 precision 时返回非零")
    benchmark_parser = subparsers.add_parser(
        "recognition-benchmark",
        help="对固定 manifest 运行识别模式/模型配对实验",
    )
    benchmark_parser.add_argument("--manifest", required=True, help="输入 manifest JSON")
    benchmark_parser.add_argument("--base-dir", required=True, help="manifest 相对路径基准目录")
    benchmark_parser.add_argument("--gold", default=None, help="可选 gold JSON")
    benchmark_parser.add_argument("--code-commit", required=True, help="当前代码提交 ID")
    benchmark_parser.add_argument("--replicates", type=int, default=1, help="每个矩阵单元重复次数")
    benchmark_parser.add_argument("--out", required=True, help="隐私安全报告输出路径")

    args = parser.parse_args(argv)
    if args.command == "redact":
        return _run_redact(args)
    if args.command == "restore":
        return _run_restore(args)
    if args.command == "samples" and args.samples_command == "recent-errors":
        return _run_recent_errors(args)
    if args.command == "samples" and args.samples_command == "clear":
        return _run_clear_samples(args)
    if args.command == "eval":
        return _run_eval(args)
    if args.command == "recognition-benchmark":
        return _run_recognition_benchmark(args)
    return 1


def _run_redact(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    text = read_document(input_path)
    config = PipelineConfig.offline_without_llm() if args.no_llm else PipelineConfig.from_llm_mode(
        args.llm_mode,
        model=args.model,
        recognition_mode=args.recognition_mode,
    )
    pipeline = RedactionPipeline(config=config)
    result = pipeline.redact(text, source_file=input_path.name)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    redacted_path = output_dir / f"{input_path.stem}.redacted{input_path.suffix if input_path.suffix else '.txt'}"
    map_path = output_dir / "redaction_map.enc"
    write_document(redacted_path, result.redacted_text)
    save_redaction_map_auto(map_path, result.redaction_map)
    if args.debug_trace:
        from .debug_trace import debug_trace_to_json, redaction_debug_trace

        trace_path = output_dir / "debug_trace.json"
        trace_path.write_text(debug_trace_to_json(redaction_debug_trace(result)), encoding="utf-8")

    print(f"redacted: {redacted_path}")
    print(f"map: {map_path}")
    if args.debug_trace:
        print(f"debug_trace: {trace_path}")
    print(f"candidates: {len(result.candidates)}")
    if result.review_candidates:
        print(f"review_candidates: {len(result.review_candidates)}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if result.leaks:
        print("high_risk_leaks:")
        for leak in result.leaks:
            print(f"- {leak.type}: {leak.text}")
        return 2
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    redaction_map = load_redaction_map_auto(args.map)
    input_path = Path(args.input)
    if input_path.suffix.lower() == ".docx" and not args.preview:
        out_path = args.out
        if out_path == "output/restored.txt":
            out_path = "output/restored.docx"
        replacements = restore_docx(input_path, out_path, redaction_map)
        print(f"restored: {out_path}")
        print(f"replacements: {replacements}")
        return 0

    text = read_document(args.input)
    if args.preview:
        preview = preview_restore(text, redaction_map)
        print(preview.diff)
    restored = restore_text(text, redaction_map)
    write_document(args.out, restored)
    print(f"restored: {args.out}")
    return 0


def _run_recent_errors(args: argparse.Namespace) -> int:
    from ._samples import load_recent_error_samples

    for entry in load_recent_error_samples(limit=max(1, args.limit)):
        updated_at = entry.get("updated_at") or entry.get("last_seen_at") or ""
        entity_type = entry.get("type", "")
        original = entry.get("original", "")
        source = entry.get("last_source") or entry.get("source") or ""
        print(f"{updated_at}\t{entity_type}\t{original}\t{source}")
    return 0


def _run_clear_samples(args: argparse.Namespace) -> int:
    from ._samples import DEFAULT_SAMPLES_DIR, clear_sample_library

    samples_dir = Path(args.samples_dir) if args.samples_dir else DEFAULT_SAMPLES_DIR
    result = clear_sample_library(samples_dir)
    print(
        "cleared samples: removed_entries={removed_entries} removed_files={removed_files} "
        "sample_file={sample_file} updated_at={updated_at}".format(**result)
    )
    return 0


def _run_eval(args: argparse.Namespace) -> int:
    from .evaluation import evaluate_gold_file, evaluation_report_to_json

    config = PipelineConfig.offline_without_llm() if args.no_llm else PipelineConfig.from_llm_mode(
        args.llm_mode,
        model=args.model,
        recognition_mode=args.recognition_mode,
    )
    report = evaluate_gold_file(args.gold, config=config)
    print(
        "cases={case_count} precision={precision:.4f} recall={recall:.4f} f1={f1:.4f} "
        "tp={true_positive} fp={false_positive} fn={false_negative}".format(**report)
    )
    for case in report["cases"]:
        if case["false_negative"] or case["false_positive"]:
            print(
                "- {name}: precision={precision:.4f} recall={recall:.4f} "
                "missing={false_negative} extra={false_positive}".format(**case)
            )
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(evaluation_report_to_json(report), encoding="utf-8")
        print(f"report: {output_path}")

    if args.fail_under_recall is not None and report["recall"] < args.fail_under_recall:
        return 2
    if args.fail_under_precision is not None and report["precision"] < args.fail_under_precision:
        return 2
    return 0


def _run_recognition_benchmark(args: argparse.Namespace) -> int:
    output_path = Path(args.out)
    try:
        manifest = load_benchmark_manifest(args.manifest)
        report = run_recognition_benchmark(
            manifest,
            base_dir=args.base_dir,
            gold_path=args.gold,
            code_commit=args.code_commit,
            replicate_count=args.replicates,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"recognition benchmark failed: {exc}", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(recognition_benchmark_report_to_json(report), encoding="utf-8")
    print(f"report: {output_path}")
    print(f"runs: {len(report['runs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
