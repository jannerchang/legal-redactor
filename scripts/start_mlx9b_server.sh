#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${LEGAL_REDACTOR_MLX_HOST:-127.0.0.1}"
PORT="${LEGAL_REDACTOR_MLX_PORT:-18080}"
MODEL="mlx-community/Qwen3.5-9B-MLX-4bit"
HF_HOME="${HF_HOME:-/Volumes/SSD2T/.cache/huggingface}"
LOG_FILE="${LEGAL_REDACTOR_MLX_LOG:-$ROOT_DIR/.mlx9b-server.log}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export HF_HOME
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "缺少 $PYTHON_BIN，无法检测 MLX 服务端口。" >&2
  exit 1
fi

if "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.5)
    if sock.connect_ex((host, port)) == 0:
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  echo "MLX server already listening at http://$HOST:$PORT"
  exit 0
fi

if ! command -v mlx_lm.server >/dev/null 2>&1; then
  echo "缺少 mlx_lm.server。请先执行：uv tool install mlx-lm --python /opt/homebrew/bin/python3.11" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
nohup mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --chat-template-args '{"enable_thinking":false}' \
  --temp 0 \
  --max-tokens 4096 \
  --prompt-cache-size 2 \
  >>"$LOG_FILE" 2>&1 &

for _ in $(seq 1 60); do
  if "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.5)
    raise SystemExit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
  then
    echo "MLX server ready at http://$HOST:$PORT"
    exit 0
  fi
  sleep 2
done

echo "MLX server 启动超时，请查看日志：$LOG_FILE" >&2
exit 1
