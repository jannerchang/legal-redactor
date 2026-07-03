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

free_port_if_unhealthy() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "$pids" ]] || return 0

  for _ in 1 2 3; do
    if curl -fsS -m 2 "http://$HOST:$port/health" >/dev/null 2>&1; then
      echo "Web 服务已在 http://$HOST:$port 运行。"
      if [[ "${LEGAL_REDACTOR_SKIP_MLX:-0}" != "1" ]]; then
        if curl -fsS -m 2 "http://${LEGAL_REDACTOR_MLX_HOST:-127.0.0.1}:${LEGAL_REDACTOR_MLX_PORT:-18080}/v1/models" >/dev/null 2>&1; then
          echo "MLX 服务已在 http://${LEGAL_REDACTOR_MLX_HOST:-127.0.0.1}:${LEGAL_REDACTOR_MLX_PORT:-18080} 运行。"
        else
          echo "警告：Web 已运行，但 MLX 未响应。上方已尝试启动 MLX；若仍失败请查看 .mlx9b-server.log" >&2
        fi
      fi
      exit 0
    fi
    sleep 1
  done

  echo "端口 $port 上的旧 Web 进程无响应，正在清理..."
  kill $pids 2>/dev/null || true
  sleep 1
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
}

free_port_if_unhealthy "$PORT"

exec python -m uvicorn legal_redactor.web_app:app --host "$HOST" --port "$PORT"
