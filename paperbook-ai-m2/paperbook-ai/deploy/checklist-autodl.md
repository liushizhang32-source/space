# AutoDL 部署清单（照着点，约 30 分钟）

> 目标：租一台 4090 24G，起 vLLM，本机连上，验证 `vlm.json` 出真数据。
> 费用：约 **2.5–3.5 元/小时**，测试 3 小时不到 10 元。**用完记得关机**。

## 第 1 步：注册与充值

1. 打开 <https://www.autodl.com>，注册（要手机号）。
2. **实名认证**（学生也需要，1 分钟，支付宝/微信人脸）。
3. 充值 **20 元**（够测 5–6 小时）。

## 第 2 步：租机器

1. 左侧「算力市场」→ 筛选 **RTX 4090 / 24GB**。
2. 镜像选 **PyTorch 2.5.0 / Python 3.12 / CUDA 12.4**（或更新的 PyTorch 镜像）。
3. 磁盘：系统盘 30G 够，**数据盘给 50G**（模型 16G）。
4. 计费方式选 **按量计费**，创建。

> 为什么 4090：24G 显存能跑 bf16 的 7B VLM，价格又比 A100 便宜一个量级。
> 只有 16G 卡（如 4080）就用 `-AWQ` 量化版，见文末。

## 第 3 步：开机并进入终端

1. 实例列表 →「开机」→「JupyterLab」或「SSH 登录」。
2. 打开终端，先确认卡在：

```bash
nvidia-smi
# 应看到 RTX 4090, 24564MiB
```

## 第 4 步：上传脚本并执行

把 `deploy/bootstrap_autodl.sh` 拖进 JupyterLab 的 `/root/autodl-tmp/`，然后：

```bash
cd /root/autodl-tmp
bash bootstrap_autodl.sh
```

脚本会自动：装 vllm → 用 ModelScope 下模型 → 起服务（端口 6006）。

首次约 **15–25 分钟**（vllm 3–5 分钟 + 模型 16G 下载）。

看到这行就成功了：

```
INFO:     Uvicorn running on http://0.0.0.0:6006
```

## 第 5 步：本机建隧道

AutoDL 的「自定义服务」能直接给一个公网地址，但更稳的是 SSH 隧道。

在 AutoDL 实例页复制 **SSH 登录指令**，形如：

```
ssh -p 12345 root@region-1.autodl.com
```

在**本机**（Windows PowerShell）加 `-N -L`：

```powershell
ssh -N -L 6006:127.0.0.1:6006 -p 12345 root@region-1.autodl.com
```

输入密码后保持这个窗口开着（`-N` 表示不执行命令，只转发）。

## 第 6 步：本机验证

**另开**一个 PowerShell：

```powershell
cd paperbook-ai
python scripts/check_vlm.py --base-url http://127.0.0.1:6006/v1 --model qwen2.5-vl-7b-instruct
```

期望：

```
后端    : qwen2.5-vl-http
base_url: http://127.0.0.1:6006/v1
model   : qwen2.5-vl-7b-instruct
调用中（1240x1754）…
耗时    : 1.8s
物体    : 4 个
contract : ok
```

## 第 7 步：写进 .env

```ini
VISION_VLM_BACKEND=http
QWEN_VL_BASE_URL=http://127.0.0.1:6006/v1
QWEN_VL_MODEL=qwen2.5-vl-7b-instruct
QWEN_VL_MAX_TOKENS=1200
QWEN_VL_TIMEOUT=60
```

然后跑整页：

```powershell
python run.py --image samples/demo_page.png --book-id book01 --page-no 1
```

## 第 8 步：用完关机

AutoDL 实例列表 → **关机**。按量计费关机后只收磁盘费（约 0.1 元/小时）。

> 别只关 JupyterLab，那不停止计费。

---

## 备选：只有 16G 显存

用 AWQ 量化版，显存约 8G：

```bash
MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ \
NAME=qwen2.5-vl-7b-awq \
bash bootstrap_autodl.sh
```

`.env` 里 `QWEN_VL_MODEL=qwen2.5-vl-7b-awq`。

## 常见问题

| 现象 | 解决 |
|---|---|
| `pip install vllm` 报 torch 版本冲突 | 换 AutoDL 的「社区镜像」搜索 vllm，直接选带 vllm 的镜像 |
| 模型下载卡住 | 脚本已用 ModelScope；再慢就 `export HF_ENDPOINT=https://hf-mirror.com` |
| 启动报 CUDA OOM | 加 `--gpu-memory-utilization 0.85 --max-model-len 4096` |
| 本机连不上 | 隧道没开、端口不是 6006、或 AutoDL 实例已关机 |
| 每次重启都要重新装 | vllm 装在系统盘会保留；模型在数据盘保留；只有服务要重启 |
