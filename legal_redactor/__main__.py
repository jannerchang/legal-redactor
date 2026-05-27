"""命令行入口 —— 可直接通过 python -m legal_redactor 启动。

用法示例：
  # 标准脱敏
  python -m legal_redactor samples/labor_dispute.txt

  # 最小脱敏
  python -m legal_redactor --profile minimal samples/document.txt

  # 还原
  python -m legal_redactor --restore output/redaction_map.json output/redacted.txt

  # 完整还原（含高敏字段）
  python -m legal_redactor --restore --restore-all output/redaction_map.json output/redacted.txt

  # 启动 Web 界面
  python -m legal_redactor --web
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PipelineConfig
from .io import is_encrypted_map, load_redaction_map, load_redaction_map_encrypted, read_document, write_document
from .pipeline import RedactionPipeline
from .restore import restore_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m legal_redactor",
        description="本地中文法律文书脱敏工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python -m legal_redactor --profile minimal samples/doc.txt
  python -m legal_redactor --profile strong --batch samples/*.txt
  python -m legal_redactor --web
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="要脱敏的文件路径（支持 .txt / .md / .docx / .pdf）",
    )
    parser.add_argument(
        "--profile", "-p",
        choices=("minimal", "standard", "strong"),
        default="standard",
        help="脱敏策略（默认 standard）：\n"
             "  minimal  - 仅地名+人名+身份证+手机号\n"
             "  standard - 最小 + 机构/公司/项目 + 银行账号/信用代码\n"
             "  strong   - 全部：含案号/地址/金额/日期",
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
        help="本地 LLM 模式（需运行 Ollama）：max-effect / balanced / off（默认 max-effect）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="自定义 Ollama 模型名，如 qwen3:8b / qwen2.5:7b",
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
        help="还原模式：第一个参数是 redaction_map.json，第二个是脱敏后的文件",
    )
    parser.add_argument(
        "--restore-all",
        action="store_true",
        help="还原所有字段（含身份证、手机号等高敏字段）",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.web:
        _start_web(args.host, args.port)

    if args.restore:
        if len(args.inputs) < 2:
            print("还原模式需要两个参数：redaction_map.json 脱敏文件.txt")
            sys.exit(1)
        _do_restore(args.inputs[0], args.inputs[1], args.restore_all, args.output_dir)
        return

    if not args.inputs:
        parser.print_help()
        sys.exit(1)

    _do_redact(args)


def _do_redact(args: argparse.Namespace) -> None:
    input_paths = [Path(p) for p in args.inputs]
    config = PipelineConfig.from_llm_mode(args.llm, profile_name=args.profile, model=args.model)
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
            _print_warnings_and_leaks(result.warnings, result.leaks)


def _do_restore(map_path: str, redacted_path: str, restore_all: bool, output_dir: str) -> None:
    """还原脱敏文本。先试明文 JSON，失败再试解密。"""
    try:
        redaction_map = load_redaction_map(map_path)
        print(f"[还原] 已加载明文映射表：{map_path}")
    except Exception as json_exc:
        try:
            redaction_map = load_redaction_map_encrypted(map_path)
            print(f"[还原] 已解密映射表：{map_path}")
        except Exception as crypto_exc:
            print(f"无法读取映射表：{map_path}")
            print(f"  明文解析：{json_exc}")
            print(f"  解密：{crypto_exc}")
            print(f"  提示：请确认映射表与脱敏时在同一台机器生成。")
            sys.exit(1)

    redacted_text = read_document(redacted_path)
    restored = restore_text(redacted_text, redaction_map, restore_all=restore_all)

    p = Path(redacted_path)
    out_path = Path(output_dir) / f"{p.stem}.restored{p.suffix}"
    write_document(str(out_path), restored)
    print(f"[还原完成] {out_path}")
    print(f"  还原条目：{len(redaction_map.mappings)}（{'全部' if restore_all else '默认可还原'}）")


def _print_warnings_and_leaks(warnings: list[str], leaks: list) -> None:
    if warnings:
        for w in warnings:
            print(f"[警告] {w}")
    if leaks:
        print(f"[高危泄漏] 脱敏后仍发现 {len(leaks)} 处高危字段，请人工核查：")
        for leak in leaks:
            print(f"  - {leak.type}: {leak.text}")


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
    parts = [args.profile, f"llm_{args.llm}"]
    if args.batch:
        parts.insert(0, "batch")
    return "_".join(parts)


if __name__ == "__main__":
    main()
