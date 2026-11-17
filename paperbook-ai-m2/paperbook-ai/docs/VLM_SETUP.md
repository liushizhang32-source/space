# 接上 VLM：三条路怎么选

> 视觉模块的 `vlm.json` 需要「画面描述 + 物体列表 + 场景标签」。
> 三条路都能出这个结果，**代码完全一样**，只改 `.env` 里的 `QWEN_VL_BASE_URL`。

## 结论：本地优先

| 路线 | 用在哪 | 优点 | 风险 |
|---|---|---|---|
| **本地 Ollama**（推荐） | 校赛演示、日常开发 | 免费、不怕断网、**授权绘本不出本机** | 8GB 显存只能跑 4B 级 |
| **云端 vLLM** | 企业赛现场（组委会给云 GPU） | 快、能上 7B/32B | 要自己部署 |
| **云 API** | 只用于**非授权图**（合成页、自拍页） | 零部署 | **不得传组委会绘本**，有合规风险 |

> 规则原文：绘本样本「不得转发、公开、出售」。把授权页发给第三方 API 属于转发，
> 所以**真书只能用本地方案**。

## 路线 A：本地 Ollama

### 1. 拉模型

```powershell
ollama pull qwen3-vl:4b     # 约 3.3 GB，8GB 显存够用
# 或者更小的：
ollama pull qwen2.5vl:3b    # 约 3.2 GB
```

下载中断不要紧，重跑同一条命令会**续传**。

### 2. 确认服务在跑

```powershell
ollama list
curl http://127.0.0.1:11434/v1/models
```

### 3. 写进 `.env`

```ini
VISION_VLM_BACKEND=http
QWEN_VL_BASE_URL=http://127.0.0.1:11434/v1
QWEN_VL_API_KEY=ollama
QWEN_VL_MODEL=qwen3-vl:4b
```

### 4. 验证

```powershell
python scripts/check_vlm.py
```

它会打一次真实调用，量耗时，并把 `objects` 按 C2 契约校验一遍。
看到 `contract : ok` 就通了。

### 5. 跑整页

```powershell
python run.py --image samples/demo_page.png --book-id book01 --page-no 1
```

`vlm.json` 默认不写 `producer`（保持与契约字段一致；按 §1.2.5 未知字段本应被忽略，这里只是少一层歧义）。
想看是哪个后端产出的，临时设 `VISION_EMIT_EXTRA=1`，会附加 `producer.backend`。

## 路线 B：企业赛云 GPU（vLLM）

完整步骤见 **[deploy/README.md](../deploy/README.md)**：Docker 与裸机两种启动方式、SSH 隧道、显存不足的降级、无外网时怎么放权重。

最短路径：

```bash
# 云主机上（二选一）
cd deploy && docker compose up -d
bash deploy/serve.sh

# 本机验证（直连或已建 ssh -L 隧道）
python scripts/check_vlm.py --base-url http://127.0.0.1:8100/v1 \
                            --model qwen2.5-vl-7b-instruct
```

通了之后写进 `.env`：

```ini
VISION_VLM_BACKEND=http
QWEN_VL_BASE_URL=http://127.0.0.1:8100/v1
QWEN_VL_MODEL=qwen2.5-vl-7b-instruct
QWEN_VL_MAX_TOKENS=1200
```

**本地代码一行不用改**——vLLM、Ollama、云 API 都是 OpenAI 兼容协议。

> 若在 vLLM 上部署 Qwen3-VL（默认会思考），加 `QWEN_VL_DISABLE_THINKING=1`，
> 代码会带 `chat_template_kwargs.enable_thinking=false`，延迟能降一半以上。

## 路线 C：云 API（仅限非授权图）

任何 OpenAI 兼容网关都能用，例如：

```ini
QWEN_VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VL_API_KEY=sk-xxxx
QWEN_VL_MODEL=qwen-vl-plus
```

⚠️ 只对 `samples/books_demo/` 里的合成图或自己拍的图用；组委会绘本走这条 = 违反数据协议。

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `VLM 请求失败: <urlopen error ...>` | 服务没起，或 base_url 少了 `/v1` | `curl .../v1/models` 先确认 |
| `VLM 返回非 JSON` | 模型没按 prompt 输出 | 换更大模型；或降 `max_tokens` 看是否被截断 |
| 单次 8–10 秒 | 模型太大 / 图像分辨率高 | 换 3B/4B，或把送图长边降到 960 |
| `objects` 为空但描述正常 | 画面太抽象 | 正常；`status=empty` 契约允许 |
| 显存不足 OOM | 7B + 高分辨率 | 换 4B；或 `OLLAMA_NUM_PARALLEL=1` |
| 首次调用特别慢 | 模型加载进显存 | 正常，预热后 1–2 秒 |

## 性能参考（RTX 5060 Laptop 8GB，实测 2026-11-06）

| 模型 | 单页耗时（热） | 物体召回 | 说明 |
|---|---|---|---|
| `qwen2.5vl:3b` | **0.6 s** | 1 个（偏低） | 快，适合交互兜底；物体漏检明显 |
| `qwen3-vl:4b` | **12.9 s** | 3–4 个（准） | 准确，适合离线生成；Ollama 里是 thinking 变体 |

冷启动（模型加载）另加 5–8 s。给 8 页绘本做一遍 ≈ 100 s，仍在 Video 阶段 180 s 预算内。

### 关于 qwen3-vl 的"思考模式"

`ollama show qwen3-vl:4b` 显示 `renderer: qwen3-vl-thinking`，它**强制先输出思维链**：

- `think: false`（OpenAI 端点和原生 `/api/chat` 都试过）**不生效**；
- 预算给小了（≤900 token）会变成"只有思考、正文为空"；
- 解决办法：`QWEN_VL_MAX_TOKENS=2400`，让思考跑完还能挤出 JSON。

如果只想要速度，用 `qwen2.5vl:3b`（非思考模型）。

### 让模型常驻显存

默认空闲 5 分钟卸载，下次调用又要等 5–8 s。启动 Ollama 前设：

```powershell
setx OLLAMA_KEEP_ALIVE "-1"
```

（设完重启 Ollama 服务；`-1` 表示一直常驻。）
