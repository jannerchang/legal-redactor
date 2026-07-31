from __future__ import annotations

import argparse
import json

from .processing import process_paths, processing_request_from_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="执行本地法律材料脱敏 processing manifest")
    parser.add_argument("manifest", help="JSON manifest 路径")
    args = parser.parse_args()
    result = process_paths(processing_request_from_manifest(args.manifest))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
