#!/usr/bin/env bash
# 裸机启动 vLLM（没有 Docker 时用这个）
#   bash deploy/serve.sh
#   VLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ bash deploy/serve.sh
set -euo pipefail

MODEL="${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
NAME="${VLM_NAME:-qwen2.5-vl-7b-instruct}"
PORT="${VLM_PORT:-8100}"

echo "模型      : $MODEL"
echo "服务名    : $NAME"
echo "端口      : $PORT"
echo

if ! python -c "import vllm" >/dev/null 2>&1; then
  echo "[1/2] 安装 vllm（首次约 2-3 分钟）…"
  pip install -U vllm
fi

echo "[2/2] 启动 vLLM…"
exec vllm serve "$MODEL" \
  --served-model-name "$NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --limit-mm-per-prompt image=2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
