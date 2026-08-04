#!/usr/bin/env bash
set -euo pipefail

HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-8000}"
MODEL="${VLLM_MODEL:?Set VLLM_MODEL to the local model path or Hugging Face ID}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:?Set VLLM_SERVED_MODEL_NAME to the catalog upstream_id}"

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "VLLM_HOST must be 127.0.0.1 or localhost" >&2
  exit 2
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x /opt/legal-redactor/.venv/bin/python ]]; then
  PYTHON=/opt/legal-redactor/.venv/bin/python
else
  echo "Set PYTHON_BIN to the Python executable that has vllm installed" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "PYTHON_BIN is not executable: $PYTHON" >&2
  exit 2
fi

"$PYTHON" -c 'import vllm'

exec "$PYTHON" \
  -m vllm.entrypoints.openai.api_server \
  --host "$HOST" \
  --port "$PORT" \
  --model "$MODEL" \
  --served-model-name "$SERVED_MODEL_NAME"
