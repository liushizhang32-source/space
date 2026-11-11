#!/usr/bin/env bash
# AutoDL / 任意 Linux GPU 机器上的一键部署脚本
#
#   bash bootstrap_autodl.sh
#   MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ bash bootstrap_autodl.sh
#
# 做的事：检查 GPU → 装 vllm → 下模型（ModelScope 加速）→ 起服务（端口 6006）→ 自检
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
NAME="${NAME:-qwen2.5-vl-7b-instruct}"
PORT="${PORT:-6006}"                      # AutoDL 自定义服务只开放 6006
ROOT="${ROOT:-/root/autodl-tmp}"          # AutoDL 数据盘；其他机器改成 /data
LOCAL_DIR="$ROOT/models/$(basename "$MODEL")"

echo "=============================================="
echo " 模型   : $MODEL"
echo " 服务名 : $NAME"
echo " 端口   : $PORT"
echo " 目录   : $LOCAL_DIR"
echo "=============================================="
echo

# ---------- 1. 检查 GPU ----------
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[x] 没找到 nvidia-smi，这台机器没有 NVIDIA GPU 驱动"
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
echo

# ---------- 2. 装 vllm ----------
if python -c "import vllm" >/dev/null 2>&1; then
  echo "[1/3] vllm 已安装：$(python -c 'import vllm; print(vllm.__version__)')"
else
  echo "[1/3] 安装 vllm（首次约 3-5 分钟）…"
  pip install -U vllm -i https://mirrors.aliyun.com/pypi/simple/ || pip install -U vllm
fi
echo

# ---------- 3. 下模型 ----------
if [ -d "$LOCAL_DIR" ] && [ -n "$(ls -A "$LOCAL_DIR" 2>/dev/null)" ]; then
  echo "[2/3] 模型已存在，跳过下载：$LOCAL_DIR"
else
  echo "[2/3] 下载模型到 $LOCAL_DIR …"
  mkdir -p "$ROOT/models"
  if python -c "import modelscope" >/dev/null 2>&1 || pip install -q modelscope; then
    modelscope download --model "$MODEL" --local_dir "$LOCAL_DIR"
  else
    export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
    huggingface-cli download "$MODEL" --local-dir "$LOCAL_DIR"
  fi
fi
echo

# ---------- 4. 起服务 ----------
echo "[3/3] 启动 vLLM（端口 $PORT）…"
echo "--------------------------------------------------"
echo "启动后，在你自己的电脑上建隧道："
echo "  ssh -N -L $PORT:127.0.0.1:$PORT root@<这台机器的地址> -p <端口>"
echo "然后验证："
echo "  python scripts/check_vlm.py --base-url http://127.0.0.1:$PORT/v1 --model $NAME"
echo "--------------------------------------------------"
echo

exec vllm serve "$LOCAL_DIR" \
  --served-model-name "$NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --limit-mm-per-prompt image=2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
