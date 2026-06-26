#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${LEGAL_REDACTOR_MLX_HOST:-127.0.0.1}"
PORT="${LEGAL_REDACTOR_MLX_PORT:-18080}"
MODEL="mlx-community/Qwen3.5-9B-MLX-4bit"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
LOG_FILE="${LEGAL_REDACTOR_MLX_LOG:-$ROOT_DIR/.mlx9b-server.log}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export HF_HOME
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export COPYFILE_DISABLE="${COPYFILE_DISABLE:-1}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "缺少 $PYTHON_BIN，无法检测 MLX 服务端口。" >&2
  exit 1
fi

check_mlx_health() {
  "$PYTHON_BIN" - "$HOST" "$PORT" "$MODEL" <<'PY'
import http.client
import json
import sys

host, port, expected_model = sys.argv[1], int(sys.argv[2]), sys.argv[3]
conn = http.client.HTTPConnection(host, port, timeout=2)
try:
    conn.request("GET", "/v1/models")
    response = conn.getresponse()
    data = response.read().decode("utf-8", errors="replace")
except (OSError, http.client.HTTPException):
    raise SystemExit(1)
finally:
    conn.close()

if response.status >= 400:
    raise SystemExit(1)

try:
    payload = json.loads(data)
except json.JSONDecodeError:
    raise SystemExit(1)

model_ids = {
    item.get("id")
    for item in payload.get("data", [])
    if isinstance(item, dict)
}
raise SystemExit(0 if expected_model in model_ids else 1)
PY
}

port_is_listening() {
  "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.5)
    raise SystemExit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
}

clean_macos_appledouble_files() {
  local model_cache_dir="$HF_HOME/hub/models--${MODEL//\//--}"
  if [[ -d "$model_cache_dir" ]]; then
    if command -v xattr >/dev/null 2>&1; then
      xattr -cr "$model_cache_dir" 2>/dev/null || true
    fi
    if command -v dot_clean >/dev/null 2>&1; then
      dot_clean -m "$model_cache_dir" >/dev/null 2>&1 || true
    fi
    find "$model_cache_dir" -name '._*' -type f -delete
  fi
}

clean_macos_appledouble_files

if check_mlx_health; then
  echo "MLX server already ready at http://$HOST:$PORT with ${MODEL}"
  exit 0
fi

if port_is_listening; then
  echo "端口 $HOST:$PORT 已被占用，但 /v1/models 未返回目标模型 ${MODEL}。" >&2
  echo "请停止占用该端口的进程，或设置 LEGAL_REDACTOR_MLX_PORT 使用其他端口。" >&2
  exit 1
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
  if check_mlx_health; then
    echo "MLX server ready at http://$HOST:$PORT with ${MODEL}"
    exit 0
  fi
  sleep 2
done

echo "MLX server 启动或模型探活超时，请查看日志：$LOG_FILE" >&2
exit 1
