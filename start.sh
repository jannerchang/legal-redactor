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
  [[ -n "$http_host" && -n "$http_port" ]] && export HTTP_PROXY="http://$http_host:$http_port" http_proxy="http://$http_host:$http_port"
  [[ -n "$https_host" && -n "$https_port" ]] && export HTTPS_PROXY="http://$https_host:$https_port" https_proxy="http://$https_host:$https_port"
}
sync_macos_proxy_env

[[ -d .venv ]] || "$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
if [[ "${1:-}" == "--install-deps" ]]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi
python - <<'PY'
try:
    import fastapi, uvicorn, docx, multipart, pypdf, cryptography  # noqa: F401
except ImportError as exc:
    raise SystemExit("缺少依赖。首次运行请执行：./start.sh --install-deps") from exc
PY

if [[ "${LEGAL_REDACTOR_SKIP_MLX:-0}" != "1" ]]; then
  bash scripts/start_model_manager.sh
else
  echo "已跳过本地模型 API；新的脱敏将被阻止。"
fi

if curl -fsS -m 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
  echo "Web 服务已在 http://$HOST:$PORT 运行。"
  exit 0
fi
# Do not use lsof or kill arbitrary processes. A bind error belongs to the
# process owner, rather than this startup script.
exec python -m uvicorn legal_redactor.web_app:app --host "$HOST" --port "$PORT"
