from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "start_vllm_worker.sh"


def _run(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    log = tmp_path / "python.log"
    python = tmp_path / "python"
    python.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$FAKE_PYTHON_LOG"\n'
        "if [[ \"$1\" == \"-c\" ]]; then exit 0; fi\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    run_env = {
        "PATH": os.environ["PATH"],
        "PYTHON_BIN": str(python),
        "FAKE_PYTHON_LOG": str(log),
        "VLLM_MODEL": "/models/private",
        **env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    ), log


def test_start_vllm_worker_requires_served_model_name(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)

    assert result.returncode != 0
    assert "VLLM_SERVED_MODEL_NAME" in result.stderr


def test_start_vllm_worker_rejects_non_loopback_host(tmp_path: Path) -> None:
    result, log = _run(tmp_path, VLLM_SERVED_MODEL_NAME="catalog-upstream", VLLM_HOST="0.0.0.0")

    assert result.returncode == 2
    assert "127.0.0.1 or localhost" in result.stderr
    assert not log.exists()


def test_start_vllm_worker_preflights_and_executes_configured_python(tmp_path: Path) -> None:
    result, log = _run(tmp_path, VLLM_SERVED_MODEL_NAME="catalog-upstream")

    assert result.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "-c import vllm",
        "-m vllm.entrypoints.openai.api_server --host 127.0.0.1 --port 8000 "
        "--model /models/private --served-model-name catalog-upstream",
    ]
