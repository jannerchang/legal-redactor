#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${LEGAL_REDACTOR_HOST:-127.0.0.1}"
PORT="${LEGAL_REDACTOR_PORT:-7860}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

sync_macos_proxy_env() {
  [[ "$(uname -s)" == "Darwin" ]] || return 0
  local proxy_dump http_host http_port https_host https_port
  proxy_dump="$(scutil --proxy 2>/dev/null || true)"
  http_host="$(printf '%s\n' "$proxy_dump" | sed -n 's/^[[:space:]]*HTTPProxy : //p' | head -n 1)"
  http_port="$(printf '%s\n' "$proxy_dump" | sed -n 's/^[[:space:]]*HTTPPort : //p' | head -n 1)"
  https_host="$(printf '%s\n' "$proxy_dump" | sed -n 's/^[[:space:]]*HTTPSProxy : //p' | head -n 1)"
  https_port="$(printf '%s\n' "$proxy_dump" | sed -n 's/^[[:space:]]*HTTPSPort : //p' | head -n 1)"
  if [[ -n "$http_host" && -n "$http_port" ]]; then
    export HTTP_PROXY="http://$http_host:$http_port"
    export http_proxy="$HTTP_PROXY"
  fi
  if [[ -n "$https_host" && -n "$https_port" ]]; then
    export HTTPS_PROXY="http://$https_host:$https_port"
    export https_proxy="$HTTPS_PROXY"
  fi
}

sync_macos_proxy_env

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
    import multipart  # noqa: F401
    import pypdf  # noqa: F401
    import cryptography  # noqa: F401
except ImportError as exc:
    raise SystemExit(
        "缺少依赖。首次运行请执行：./start.sh --install-deps\n"
        "或手动安装：pip install -r requirements.txt"
    ) from exc
PY

if [[ "${LEGAL_REDACTOR_SKIP_MLX:-0}" != "1" ]]; then
  bash scripts/start_model_manager.sh
else
  echo "已跳过本地模型 API；Web 将使用纯规则模式。"
fi


free_port_if_unhealthy() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -n "$pids" ]] || return 0

  for _ in 1 2 3; do
    if curl -fsS -m 2 "http://$HOST:$port/health" >/dev/null 2>&1; then
      echo "Web 服务已在 http://$HOST:$port 运行。"
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
