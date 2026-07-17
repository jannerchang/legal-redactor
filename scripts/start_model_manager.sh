#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${LEGAL_REDACTOR_MODEL_MANAGER_HOST:-127.0.0.1}"
PORT="${LEGAL_REDACTOR_MODEL_MANAGER_PORT:-18080}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
LOG_FILE="${LEGAL_REDACTOR_MODEL_MANAGER_LOG:-$ROOT_DIR/.model-manager.log}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "未找到项目 Python：$PYTHON_BIN。请先执行 ./start.sh --install-deps，或设置 PYTHON_BIN。" >&2
  exit 1
fi

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "模型管理器仅允许绑定本机地址；当前 HOST=$HOST" >&2
  exit 1
fi

manager_is_healthy() {
  local models
  curl -fsS -m 2 "http://$HOST:$PORT/health" >/dev/null 2>&1 || return 1
  models="$(curl -fsS -m 2 "http://$HOST:$PORT/v1/models" 2>/dev/null)" || return 1
  "$PYTHON_BIN" -c 'import json, sys; payload=json.load(sys.stdin); sys.exit(0 if any(item.get("id") == "bonsai-27b" for item in payload.get("data", []) if isinstance(item, dict)) else 1)' <<<"$models"
}

if manager_is_healthy; then
  echo "本地模型管理器已在 http://$HOST:$PORT 运行。"
  exit 0
fi

if lsof -ti tcp:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已被非健康模型管理器占用；不会终止未知进程。" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
nohup "$PYTHON_BIN" -m uvicorn legal_redactor.model_manager:app --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &

for _ in $(seq 1 30); do
  if manager_is_healthy; then
    echo "本地模型管理器已在 http://$HOST:$PORT 运行。"
    exit 0
  fi
  sleep 1
done

echo "模型管理器启动或探活超时，请查看日志: $LOG_FILE" >&2
exit 1
