#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${LEGAL_REDACTOR_HOST:-127.0.0.1}"
PORT="${LEGAL_REDACTOR_PORT:-7860}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d ".venv" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

if [[ "${1:-}" == "--install-deps" ]]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi

python - <<'PY'
try:
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
    import docx  # noqa: F401
    import cryptography  # noqa: F401
except ImportError as exc:
    raise SystemExit(
        "缺少依赖。首次运行请执行：./start.sh --install-deps\n"
        "然后手动安装：pip install cryptography"
    ) from exc
PY

if [[ "${LEGAL_REDACTOR_SKIP_MLX:-0}" != "1" ]]; then
  bash scripts/start_mlx9b_server.sh
fi

exec python -m uvicorn legal_redactor.web_app:app --host "$HOST" --port "$PORT"
