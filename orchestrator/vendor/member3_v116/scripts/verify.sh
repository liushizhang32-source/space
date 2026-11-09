#!/usr/bin/env bash
# 成员 3 代码包一键验证（macOS / Linux）
# 用法：bash scripts/verify.sh
#       PYTHON=/usr/bin/python3 bash scripts/verify.sh 可指定解释器
set -euo pipefail

PYTHON="${PYTHON:-python3}"
cd "$(dirname "$0")/.."

echo "== 0/4 解释器 =="
"$PYTHON" --version

echo "== 1/4 依赖 =="
"$PYTHON" -c "import pydantic, fastapi, uvicorn, PIL; print('deps ok')"

echo "== 2/4 测试 =="
"$PYTHON" -m pytest

echo "== 3/4 安装示例页 =="
export DATA_DIR="${DATA_DIR:-_verify_data}"
"$PYTHON" examples/install_example.py

echo "== 4/4 跑全链路 =="
"$PYTHON" -m agents.generation run --page-id book01_p03 --age-level 3-6

echo
echo "产物目录：$DATA_DIR"
ls -la "$DATA_DIR/json" "$DATA_DIR/videos" "$DATA_DIR/audios"
