#!/usr/bin/env bash
set -euo pipefail

HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-8000}"
MODEL="${VLLM_MODEL:?Set VLLM_MODEL to the local model path or Hugging Face ID}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-$MODEL}"

args=(
  -m vllm.entrypoints.openai.api_server
  --host "$HOST"
  --port "$PORT"
  --model "$MODEL"
  --served-model-name "$SERVED_MODEL_NAME"
)
if [[ -n "${VLLM_EXTRA_ARGS:-}" ]]; then
  read -r -a extra_args <<<"$VLLM_EXTRA_ARGS"
  args+=("${extra_args[@]}")
fi
exec python "${args[@]}"
