> 这是给「企业赛云 GPU / 自租 GPU」用的部署包。
> 目标：在 Linux GPU 机器上起一个 OpenAI 兼容的 VLM 服务，本机 `.env` 指过去即可。
> 代码**一行不用改**——`qwen_vl.py` 走的就是标准 `/v1/chat/completions`。

# 路线 B：云 GPU + vLLM

## 0. 机器要求

| 项 | 最低 | 推荐 |
|---|---|---|
| GPU | 16 GB（用 AWQ 量化版） | 24 GB（bf16 7B/8B） |
| 系统 | Linux + NVIDIA 驱动 + CUDA 12.x | 同左 |
| 磁盘 | 30 GB | 50 GB（放模型权重） |
| 网络 | 能访问 HuggingFace 或 ModelScope | — |

> 企业赛给的是统一云 GPU，**大概率没有公网**。那种情况先把权重下到数据盘，
> 启动时用本地路径 `--model /data/models/Qwen2.5-VL-7B-Instruct`，不要依赖运行时下载。

## 1. 选模型

| 模型 | 显存(bf16) | 单页耗时 | 说明 |
|---|---|---|---|
| `Qwen/Qwen2.5-VL-7B-Instruct` | ~16 GB | 1–3 s | 稳，无思考模式，**首选** |
| `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` | ~8 GB | 1–2 s | 16 GB 卡用这个 |
| `Qwen/Qwen3-VL-8B-Instruct` | ~17 GB | 2–4 s | 更准；vLLM 里可关思考 |

## 2. 启动（二选一）

### 2A. Docker（推荐，环境最省心）

```bash
cd deploy
export HF_CACHE=$HOME/.cache/huggingface
docker compose up -d
docker compose logs -f          # 看到 "Uvicorn running on http://0.0.0.0:8000" 即可
```

对外端口是 **8100**（容器内 8000）。

### 2B. 裸机 pip

```bash
bash deploy/serve.sh
# 或手动：
pip install -U vllm
vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --served-model-name qwen2.5-vl-7b-instruct \
  --port 8100 \
  --limit-mm-per-prompt image=2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
```

> AutoDL 的「自定义服务」只映射 **6006** 端口，那种机器把 `--port 6006`。

## 3. 在服务器上自检

```bash
curl -s http://127.0.0.1:8100/v1/models | head -c 300
```

应返回 `{"object":"list","data":[{"id":"qwen2.5-vl-7b-instruct",...}]}`。

## 4. 本机连过去

**方式一：直连**（机器有公网 IP 且端口开放）

```ini
# paperbook-ai/.env
VISION_VLM_BACKEND=http
QWEN_VL_BASE_URL=http://<公网IP>:8100/v1
QWEN_VL_API_KEY=EMPTY
QWEN_VL_MODEL=qwen2.5-vl-7b-instruct
QWEN_VL_TIMEOUT=60
QWEN_VL_MAX_TOKENS=1200
```

**方式二：SSH 隧道**（云主机只开 22 端口时最常用）

```powershell
ssh -N -L 8100:127.0.0.1:8100 root@<主机IP>
```

然后本机用 `http://127.0.0.1:8100/v1`。

## 5. 验证

```powershell
python scripts/check_vlm.py --base-url http://127.0.0.1:8100/v1 --model qwen2.5-vl-7b-instruct
```

看到 `contract : ok` 且 `objects` 有内容，就通了。

## 6. 直接跑整页

```powershell
python run.py --image samples/demo_page.png --book-id book01 --page-no 1
```

## 7. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 启动时报 `CUDA out of memory` | 显存不够 | 换 AWQ 量化版；`--gpu-memory-utilization 0.85`；`--max-model-len 4096` |
| 卡在下载权重 | 无外网 / 下载慢 | 提前下到本地目录，`--model /path/to/weights` |
| `404 model not found` | `served-model-name` 与 `.env` 不一致 | 两处写成同一个字符串 |
| 图片报 `invalid image` | data URI 太大 | 本机 `_encode_jpeg` 已限长边 1280，仍失败就降到 960 |
| 第一次请求 30 s+ | 引擎编译/预热 | 正常；先发一次空请求预热 |
| 中文乱码 | 终端编码 | 只是显示问题，JSON 里是 UTF-8 |

## 8. 企业赛现场要准备什么

1. **权重提前放数据盘**，启动脚本写死本地路径；
2. 启动命令写成 `deploy/serve.sh`，现场一条命令起服务；
3. 本机 `.env` 准备两套：本地 Ollama（兜底）+ 云 GPU（正式），演示前切；
4. 现场网络不确定 → 提前测 `ssh -L` 隧道；
5. 记录首次启动耗时（评委可能问"部署要多久"）。
