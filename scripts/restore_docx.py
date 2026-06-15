#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from legal_redactor.io import load_redaction_map_auto
from legal_redactor.restore import restore_docx


def main() -> int:
    parser = argparse.ArgumentParser(description="按映射表一键还原 Word docx，并保留原文档格式")
    parser.add_argument("docx", help="脱敏后的 .docx 文件")
    parser.add_argument("map", help="redaction_map.json 或 redaction_map.enc")
    parser.add_argument("--out", help="输出 .docx 路径；默认写到同目录 *.restored.docx")
    args = parser.parse_args()

    input_path = Path(args.docx)
    if input_path.suffix.lower() != ".docx":
        parser.error("输入文件必须是 .docx")

    output_path = Path(args.out) if args.out else input_path.with_name(f"{input_path.stem}.restored.docx")
    redaction_map = load_redaction_map_auto(args.map)
    replacements = restore_docx(input_path, output_path, redaction_map)
    print(f"还原完成：{output_path}")
    print(f"替换次数：{replacements}")
    print(f"映射条目：{len(redaction_map.mappings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
