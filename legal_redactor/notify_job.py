from __future__ import annotations

import argparse
import json
from pathlib import Path

from .web.discord_ops import post_case_workflow_notification


def main() -> int:
    parser = argparse.ArgumentParser(description="从可信 Mac 发送本地司法工作流完成通知")
    parser.add_argument("result", help="notify-request.json 路径")
    args = parser.parse_args()
    payload = json.loads(Path(args.result).expanduser().read_text(encoding="utf-8"))
    response = post_case_workflow_notification(
        case_folder=str(payload.get("case_folder") or ""),
        workflow_state=str(payload.get("workflow_state") or ""),
        validation_status=str(payload.get("validation_status") or ""),
        report_summary=str(payload.get("report_summary") or ""),
        job_id=str(payload.get("job_id") or ""),
    )
    print(json.dumps({"status": "sent", **response}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
