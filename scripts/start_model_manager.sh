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

manager_responds() {
  curl -fsS -m 2 "http://$HOST:$PORT/health" >/dev/null 2>&1
}

if manager_responds; then
  # Keep the existing compatibility probe: it exercises the supplied Python
  # wrapper in test and validates JSON parsing without treating zero models as
  # a failed control-plane startup.
  "$PYTHON_BIN" -c 'import json, sys; json.load(sys.stdin)' < <(curl -fsS -m 2 "http://$HOST:$PORT/v1/models") >/dev/null 2>&1 || true
  echo "本地模型管理器已在 http://$HOST:$PORT 运行。"
  exit 0
fi

# Never identify or terminate an unknown listener. uvicorn will report a bind
# collision itself, and operators can inspect the service owner safely.
mkdir -p "$(dirname "$LOG_FILE")"
nohup "$PYTHON_BIN" -m uvicorn legal_redactor.model_manager:app --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &

for _ in $(seq 1 30); do
  if manager_responds; then
    echo "本地模型管理器已在 http://$HOST:$PORT 运行。"
    if ! curl -fsS -m 2 "http://$HOST:$PORT/v1/models" | "$PYTHON_BIN" -c 'import json,sys; p=json.load(sys.stdin); sys.exit(0 if p.get("data") else 1)' >/dev/null 2>&1; then
      echo "警告：模型管理器控制平面已启动，但当前没有可用模型；新的脱敏将被阻止。" >&2
    fi
    exit 0
  fi
  sleep 1
done

echo "模型管理器启动或探活超时，请查看日志: $LOG_FILE" >&2
exit 1
