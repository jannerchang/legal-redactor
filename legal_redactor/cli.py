from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PipelineConfig
from .io import (
    load_redaction_map_auto,
    read_document,
    save_redaction_map,
    write_document,
)
from .pipeline import RedactionPipeline
from .restore import preview_restore, restore_docx, restore_text


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
        help="本地 LLM 语义识别模式；max-effect 使用当前最高稳定本地模型",
    )

    restore_parser = subparsers.add_parser("restore", help="按 redaction_map 反向还原")
    restore_parser.add_argument("input", help="AI 修改后的脱敏文档")
    restore_parser.add_argument("map", help="redaction_map.json")
    restore_parser.add_argument("--out", default="output/restored.txt", help="还原输出路径")
    restore_parser.add_argument("--preview", action="store_true", help="输出差异预览")

    samples_parser = subparsers.add_parser("samples", help="查看样本库")
    samples_subparsers = samples_parser.add_subparsers(dest="samples_command", required=True)
    recent_errors_parser = samples_subparsers.add_parser("recent-errors", help="按时间查看最新错误样本")
    recent_errors_parser.add_argument("--limit", type=int, default=50, help="最多输出条数")

    args = parser.parse_args(argv)
    if args.command == "redact":
        return _run_redact(args)
    if args.command == "restore":
        return _run_restore(args)
    if args.command == "samples" and args.samples_command == "recent-errors":
        return _run_recent_errors(args)
    return 1


def _run_redact(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    text = read_document(input_path)
    config = PipelineConfig.offline_without_llm() if args.no_llm else PipelineConfig.from_llm_mode(args.llm_mode)
    pipeline = RedactionPipeline(config=config)
    result = pipeline.redact(text, source_file=input_path.name)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    redacted_path = output_dir / f"{input_path.stem}.redacted{input_path.suffix if input_path.suffix else '.txt'}"
    map_path = output_dir / "redaction_map.json"
    write_document(redacted_path, result.redacted_text)
    save_redaction_map(map_path, result.redaction_map)

    print(f"redacted: {redacted_path}")
    print(f"map: {map_path}")
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


if __name__ == "__main__":
    sys.exit(main())
