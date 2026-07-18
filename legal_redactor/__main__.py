"""命令行入口 —— 可直接通过 python -m legal_redactor 启动。

用法示例：
  # 标准脱敏
  python -m legal_redactor samples/labor_dispute.txt

  # 还原
  python -m legal_redactor --restore output/redaction_map.enc output/redacted.txt

  # 启动 Web 界面
  python -m legal_redactor --web
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import PipelineConfig
from .io import load_redaction_map_auto, read_document, write_document
from .pipeline import RedactionPipeline
from .restore import restore_docx, restore_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m legal_redactor",
        description="本地中文法律文书脱敏工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python -m legal_redactor samples/doc.txt
  python -m legal_redactor --batch samples/*.txt
  python -m legal_redactor --web
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="要脱敏的文件路径（支持 .txt / .md / .doc / .docx / .pdf；.doc 建议走 Web 或先转换）",
    )
    parser.add_argument(
        "--batch", "-b",
        action="store_true",
        help="多文件批量模式：所有文件使用同一张映射表",
    )
    parser.add_argument(
        "--llm",
        choices=("max-effect", "balanced", "off"),
        default="max-effect",
        help="本地模型识别模式",
    )
    parser.add_argument(
        "--model",
        default="bonsai-27b",
        help="model-manager 返回的逻辑模型 ID（例如 bonsai-27b 或 qwen3.5-9b）",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="output",
        help="输出目录（默认 output）",
    )
    parser.add_argument(
        "--web", "-w",
        action="store_true",
        help="启动 Web 界面",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Web 服务绑定地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="Web 服务端口（默认 7860）",
    )
    parser.add_argument(
        "--restore", "-r",
        action="store_true",
        help="还原模式：第一个参数是 redaction_map.enc/.json，第二个是脱敏后的文件",
    )
    parser.add_argument(
        "--debug-trace",
        action="store_true",
        help="脱敏时额外输出 debug_trace.json，便于排查每个实体的来源和替换次数",
    )
    parser.add_argument(
        "--eval-gold",
        type=str,
        default="",
        help="运行识别率评估：传入 gold set JSON 路径",
    )
    parser.add_argument(
        "--eval-report",
        type=str,
        default="",
        help="评估时保存完整 JSON 报告的路径",
    )
    parser.add_argument(
        "--eval-fail-under-recall",
        type=float,
        default=None,
        help="评估 recall 低于该值时返回失败",
    )
    parser.add_argument(
        "--eval-fail-under-precision",
        type=float,
        default=None,
        help="评估 precision 低于该值时返回失败",
    )
    parser.add_argument(
        "--regression-report",
        type=str,
        default="",
        help="写入 M6 隐私安全回归测量 JSON 报告",
    )
    parser.add_argument(
        "--regression-sample-summary",
        action="append",
        default=[],
        help="读取一个 M5 sample_summary JSON 文件；可重复传入",
    )
    parser.add_argument(
        "--regression-sample-file",
        type=str,
        default="",
        help="样本库 provenance 元数据路径；只输出文件名、mtime、条数等元数据",
    )
    parser.add_argument(
        "--regression-redacted",
        type=str,
        default="",
        help="用于 restore placeholder 计数的脱敏文本路径；需与 --regression-map 同用",
    )
    parser.add_argument(
        "--regression-map",
        type=str,
        default="",
        help="用于 restore placeholder 计数的映射表路径；需与 --regression-redacted 同用",
    )
    parser.add_argument(
        "--regression-input-at",
        type=str,
        default="",
        help="文档输入时间 ISO 字符串，用于 document_input_to_saved_case_ms",
    )
    parser.add_argument(
        "--regression-saved-at",
        type=str,
        default="",
        help="案件保存时间 ISO 字符串，用于 document_input_to_saved_case_ms",
    )
    parser.add_argument(
        "--runtime-benchmark-report",
        type=str,
        default="",
        help="写入 M8 隐私安全运行时基准 JSON 报告",
    )
    parser.add_argument(
        "--benchmark-context",
        type=str,
        default="",
        help="M8 benchmark_context JSON 路径",
    )
    parser.add_argument(
        "--benchmark-candidate",
        nargs=4,
        action="append",
        default=[],
        metavar=("LABEL", "RUNTIME_KIND", "RUNTIME_CONFIG_ID", "M6_REPORT"),
        help="添加一个 M8 候选运行：label runtime_kind runtime_config_id m6_report.json；可重复",
    )
    parser.add_argument(
        "--benchmark-observation",
        nargs=2,
        action="append",
        default=[],
        metavar=("LABEL", "OBSERVATION_JSON"),
        help="可选：添加候选的本地计时/内存/错误/探测元数据 JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.web:
        _start_web(args.host, args.port)

    if args.eval_gold:
        _do_eval(args)
        return

    if args.runtime_benchmark_report:
        _write_runtime_benchmark_report(args)
        return

    if args.regression_report:
        _write_regression_report(args, gold_report=None)
        return

    if args.restore:
        if len(args.inputs) < 2:
            print("还原模式需要两个参数：redaction_map.enc/.json 脱敏文件.txt")
            sys.exit(1)
        _do_restore(args.inputs[0], args.inputs[1], args.output_dir)
        return

    if not args.inputs:
        parser.print_help()
        sys.exit(1)

    _do_redact(args)


def _do_redact(args: argparse.Namespace) -> None:
    input_paths = [Path(p) for p in args.inputs]
    config = PipelineConfig.from_llm_mode(args.llm, profile_name="standard", model=args.model)
    pipeline = RedactionPipeline(config=config)
    output_dir = Path(args.output_dir)

    if args.batch and len(input_paths) > 1:
        documents = [(p.name, read_document(str(p))) for p in input_paths]
        result = pipeline.redact_many(documents)
        session_dir = output_dir / _session_name(args)
        session_dir.mkdir(parents=True, exist_ok=True)
        for doc in result.documents:
            out_path = session_dir / _redacted_filename(doc.source_file)
            write_document(str(out_path), doc.redacted_text)
            print(f"[写入] {out_path}")
        map_path = session_dir / "redaction_map.enc"
        from .io import save_redaction_map_auto
        save_redaction_map_auto(str(map_path), result.redaction_map)
        print(f"[映射表] {map_path}")
        if args.debug_trace:
            from .debug_trace import batch_debug_trace, debug_trace_to_json

            trace_path = session_dir / "debug_trace.json"
            trace_path.write_text(debug_trace_to_json(batch_debug_trace(result)), encoding="utf-8")
            print(f"[调试追踪] {trace_path}")
        _print_warnings_and_leaks(result.warnings, result.leaks)
    else:
        for input_path in input_paths:
            text = read_document(str(input_path))
            result = pipeline.redact(text, source_file=input_path.name)
            session_dir = output_dir / _session_name(args)
            session_dir.mkdir(parents=True, exist_ok=True)
            out_path = session_dir / _redacted_filename(input_path.name)
            write_document(str(out_path), result.redacted_text)
            print(f"[写入] {out_path}")
            map_path = session_dir / "redaction_map.enc"
            from .io import save_redaction_map_auto
            save_redaction_map_auto(str(map_path), result.redaction_map)
            print(f"[映射表] {map_path}")
            if args.debug_trace:
                from .debug_trace import debug_trace_to_json, redaction_debug_trace

                trace_path = session_dir / "debug_trace.json"
                trace_path.write_text(debug_trace_to_json(redaction_debug_trace(result)), encoding="utf-8")
                print(f"[调试追踪] {trace_path}")
            _print_warnings_and_leaks(result.warnings, result.leaks)


def _do_restore(map_path: str, redacted_path: str, output_dir: str) -> None:
    """还原脱敏文档。映射表支持明文 JSON 或本机加密格式。"""
    try:
        redaction_map = load_redaction_map_auto(map_path)
        print(f"[还原] 已加载映射表：{map_path}")
    except Exception as exc:
        print(f"无法读取映射表：{map_path}")
        print(f"  {exc}")
        print("  提示：如果是加密映射表，请确认映射表与脱敏时在同一台机器生成。")
        sys.exit(1)

    p = Path(redacted_path)
    out_path = Path(output_dir) / f"{p.stem}.restored{p.suffix}"
    if p.suffix.lower() == ".docx":
        replacements = restore_docx(redacted_path, out_path, redaction_map)
        print(f"[还原完成] {out_path}")
        print(f"  替换次数：{replacements}")
        print(f"  还原条目：{len(redaction_map.mappings)}（全部）")
        return

    redacted_text = read_document(redacted_path)
    restored = restore_text(redacted_text, redaction_map)
    write_document(str(out_path), restored)
    print(f"[还原完成] {out_path}")
    print(f"  还原条目：{len(redaction_map.mappings)}（全部）")


def _print_warnings_and_leaks(warnings: list[str], leaks: list) -> None:
    if warnings:
        for w in warnings:
            print(f"[警告] {w}")
    if leaks:
        print(f"[高危泄漏] 脱敏后仍发现 {len(leaks)} 处高危字段，请人工核查：")
        for leak in leaks:
            print(f"  - {leak.type}: {leak.text}")


def _do_eval(args: argparse.Namespace) -> None:
    from .evaluation import evaluate_gold_file, evaluation_report_to_json

    config = PipelineConfig.from_llm_mode(args.llm, profile_name="standard", model=args.model)
    eval_started = time.monotonic()
    try:
        report = evaluate_gold_file(args.eval_gold, config=config)
    except (OSError, ValueError) as exc:
        print(f"[回归报告错误] {exc}", file=sys.stderr)
        sys.exit(1)
    eval_finished = time.monotonic()
    print(
        "[评估] cases={case_count} precision={precision:.4f} recall={recall:.4f} "
        "f1={f1:.4f} tp={true_positive} fp={false_positive} fn={false_negative}".format(**report)
    )
    for case in report["cases"]:
        if case["false_negative"] or case["false_positive"]:
            print(
                "  - {name}: precision={precision:.4f} recall={recall:.4f} "
                "missing={false_negative} extra={false_positive}".format(**case)
            )
    if args.eval_report:
        output_path = Path(args.eval_report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(evaluation_report_to_json(report), encoding="utf-8")
        print(f"[评估报告] {output_path}")
    if args.regression_report:
        _write_regression_report(
            args,
            gold_report=report,
            gold_evaluation_ms=max(0, int(round((eval_finished - eval_started) * 1000))),
        )
    if args.eval_fail_under_recall is not None and report["recall"] < args.eval_fail_under_recall:
        sys.exit(2)
    if args.eval_fail_under_precision is not None and report["precision"] < args.eval_fail_under_precision:
        sys.exit(2)


def _write_regression_report(
    args: argparse.Namespace,
    *,
    gold_report: dict | None,
    gold_evaluation_ms: int | None = None,
) -> None:
    from .regression import build_regression_report, load_json_object, regression_report_to_json

    report_started = time.monotonic()
    try:
        sample_summaries = [
            load_json_object(path, description="M5 sample_summary")
            for path in (args.regression_sample_summary or [])
        ]
        redacted_text = None
        redaction_map = None
        if args.regression_redacted and args.regression_map:
            redacted_text = read_document(args.regression_redacted)
            redaction_map = load_redaction_map_auto(args.regression_map)
        report = build_regression_report(
            gold_report=gold_report,
            sample_summaries=sample_summaries,
            sample_file=args.regression_sample_file or None,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            report_started_monotonic=report_started,
            report_finished_monotonic=None,
            document_input_at=args.regression_input_at or None,
            saved_case_at=args.regression_saved_at or None,
            gold_evaluation_ms=gold_evaluation_ms,
        )
    except ValueError as exc:
        print(f"[回归报告错误] {exc}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.regression_report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(regression_report_to_json(report), encoding="utf-8")
    print(f"[回归报告] {output_path}")
    gold = report["gold"]
    if gold.get("available"):
        print(
            "[回归摘要] cases={case_count} precision={precision} recall={recall} f1={f1}".format(
                **gold
            )
        )
    workflow = report["workflow"]
    if workflow.get("summary_count"):
        print(
            "[样本摘要] summaries={summary_count} manual={manual_corrections} "
            "delete={false_positive_deletes} add={missing_adds}".format(**workflow)
        )
    timing = report["timing"]
    if timing.get("document_input_to_saved_case_ms") is not None:
        print(f"[计时] document_input_to_saved_case_ms={timing['document_input_to_saved_case_ms']}")


def _write_runtime_benchmark_report(args: argparse.Namespace) -> None:
    from .regression import load_json_object
    from .runtime_benchmark import (
        BenchmarkCandidateInput,
        benchmark_report_to_json,
        build_runtime_benchmark_report,
    )

    output_path = Path(args.runtime_benchmark_report)
    try:
        if not args.benchmark_context:
            raise ValueError("--benchmark-context is required")
        if len(args.benchmark_candidate or []) < 2:
            raise ValueError("at least two --benchmark-candidate entries are required")
        context = load_json_object(args.benchmark_context, description="M8 benchmark_context")
        observations: dict[str, dict] = {}
        for label, observation_path in args.benchmark_observation or []:
            observations[label] = load_json_object(observation_path, description=f"M8 observation {label}")
        candidates = []
        for label, runtime_kind, runtime_config_id, report_path in args.benchmark_candidate or []:
            m6_report = load_json_object(report_path, description=f"M6 report {label}")
            observation = observations.get(label, {})
            candidate_context = observation.get("benchmark_context", context) if isinstance(observation, dict) else context
            candidates.append(
                BenchmarkCandidateInput(
                    label=label,
                    runtime_kind=runtime_kind,
                    runtime_config_id=runtime_config_id,
                    m6_report_path=report_path,
                    m6_report=m6_report,
                    benchmark_context=candidate_context,
                    observation=observation,
                )
            )
        report = build_runtime_benchmark_report(candidates)
    except ValueError as exc:
        print(f"[基准报告错误] {exc}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(benchmark_report_to_json(report), encoding="utf-8")
    labels = ", ".join(candidate["label"] for candidate in report["candidates"])
    print(f"[运行时基准] {output_path}")
    print(f"[候选] {labels}")
    recommendation = report["recommendation"]
    print(f"[建议] action={recommendation['action']} reason={recommendation['reason']}")
    for delta in report["comparison"]["deltas"]:
        timing = delta["timing"]
        print(f"[差值] {delta['label']} total_redaction_eval_ms_delta={timing['total_redaction_eval_ms_delta']}")


def _start_web(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError:
        print("启动 Web 界面需要 uvicorn，请先执行：pip install -r requirements.txt")
        sys.exit(1)
    from .web_app import app
    print(f"启动 Web 服务：http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def _redacted_filename(source_file: str) -> str:
    stem = Path(source_file).stem
    return f"{stem}.redacted.txt"


def _session_name(args: argparse.Namespace) -> str:
    parts = ["standard", f"llm_{args.llm}"]
    if args.batch:
        parts.insert(0, "batch")
    return "_".join(parts)


if __name__ == "__main__":
    main()
