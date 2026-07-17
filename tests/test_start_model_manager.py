from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _HealthyManagerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = {"status": "ok", "active_model": None, "worker_state": "stopped"}
        elif self.path == "/v1/models":
            payload = {"object": "list", "data": [{"id": "bonsai-27b", "object": "model"}]}
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        del format, args


def test_start_manager_script_reuses_healthy_manager_without_spawning(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthyManagerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    invocation_log = tmp_path / "python-invocations.log"
    python_wrapper = tmp_path / "python-wrapper"
    python_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$LEGAL_REDACTOR_TEST_PYTHON_LOG\"\n"
        "exec \"$REAL_PYTHON\" \"$@\"\n",
        encoding="utf-8",
    )
    python_wrapper.chmod(0o755)
    try:
        result = subprocess.run(
            ["bash", "scripts/start_model_manager.sh"],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "LEGAL_REDACTOR_MODEL_MANAGER_HOST": "127.0.0.1",
                "LEGAL_REDACTOR_MODEL_MANAGER_PORT": str(server.server_address[1]),
                "LEGAL_REDACTOR_TEST_PYTHON_LOG": str(invocation_log),
                "PYTHON_BIN": str(python_wrapper),
                "REAL_PYTHON": sys.executable,
            },
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert "本地模型管理器已在" in result.stdout
    invocations = invocation_log.read_text(encoding="utf-8")
    assert "-c" in invocations
    assert "-m uvicorn" not in invocations
