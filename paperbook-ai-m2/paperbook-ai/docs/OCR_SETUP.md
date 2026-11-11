# 接上 PaddleOCR，跑通第一张真实绘本页

> 目标：`python run.py --ocr-backend paddle` 能对一张真实拍摄的绘本页产出合规的 `ocr.json`。
> 预计耗时：首次 15–25 分钟（大头是装包和下载模型），之后每次 3–5 秒。

## 第 0 步：先自检

```bash
python scripts/check_env.py
```

它会告诉你：Python 版本是否合适、依赖是否齐、`DATA_DIR` 能不能写、stub 链路是否正常。
**这一步不通，先别装 Paddle**——省的以为是模型问题。

## 第 1 步：建独立虚拟环境（强烈建议）

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -U pip
pip install -r requirements.txt
```

理由：Paddle 会拉 `opencv`、`numpy` 等重依赖，和别的项目混装极易冲突；
独立 venv 也方便最后打包到企业赛的云 GPU 环境。

## 第 2 步：装 PaddlePaddle 和 PaddleOCR

```bash
pip install paddlepaddle paddleocr
```

国内加速（任选镜像）：

```bash
pip install paddlepaddle paddleocr -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

**版本对齐（最容易卡住的地方）**

| 你的 Python | 装什么 |
|---|---|
| 3.10 / 3.11 / 3.12 | `paddlepaddle` 3.x（当前 3.3.x）+ `paddleocr` 3.x |
| 3.13+ | 没有 wheel，先装 3.12 再建 venv |
| 3.9 及以下 | 用 `paddlepaddle==2.6.2` + `paddleocr==2.7.3` |

## 第 3 步：验证安装（两条命令）

```bash
python -c "import paddle; paddle.utils.run_check()"
python -c "from paddleocr import PaddleOCR; print('paddleocr import ok')"
```

第一条要打印 `PaddlePaddle is installed successfully!`。没打印就先别往下走。

## 第 4 步：跑第一张真实绘本页

拍照要求：**正对、铺平、别反光**，长边 ≤ 4096，格式 jpg/png/webp。

```bash
python run.py --image "D:\book\p01.jpg" --book-id book01 --page-no 1 --ocr-backend paddle
```

首次运行会自动下载 PP-OCRv5 检测/识别模型（约 20MB），之后走缓存。

预期输出：

```
page_id   : book01_p01
ocr.json  : data\json\book01_p01_ocr.json  [ok] blocks=6 conf=0.93 1830ms backend=paddleocr
vlm.json  : data\json\book01_p01_vlm.json  [ok] objects=2 1ms backend=stub
contract  : ok
```

`backend=paddleocr` 说明真的走了模型，不是打桩。

## 第 4.5 步：实测数据（2026-11-05，Windows + CPU）

已在本机用 `samples/demo_page.png`（1240×1754，三行中文）跑通，结果如下：

| 配置 | 冷启动（进程+模型加载） | 热推理 | 识别结果 |
|---|---|---|---|
| 默认 v6 medium | 9.6 s | ~8.1 s | 3/3 行正确 |
| **v5 mobile（当前默认）** | 3.7 s | **~2.0 s** | 3/3 行正确，1 个符号误检被过滤 |
| 开启 oneDNN | 直接报错 | — | 见下表第一条 |

结论：**默认用 v5 mobile**。企业赛云 GPU 上会再快一个数量级；服务化后模型常驻，
每次 `python run.py` 是冷启动，别拿它当在线延迟。

产物（真实识别，非打桩）：

```json
{
  "status": "ok",
  "text_blocks": [
    {"block_id": "book01_p01_t01", "order": 1, "text": "小兔子找胡萝卜",
     "bbox": [106, 1205, 486, 1272], "confidence": 0.9913},
    {"block_id": "book01_p01_t02", "order": 2, "text": "森林里，小兔子发现了一根胡萝卜。",
     "bbox": [102, 1300, 787, 1359], "confidence": 0.997},
    {"block_id": "book01_p01_t03", "order": 3, "text": "它高兴地跳了起来。",
     "bbox": [107, 1382, 479, 1437], "confidence": 0.9994}
  ],
  "page_confidence": 0.9964
}
```

## 第 5 步：三分钟验收结果

打开 `data/json/book01_p01_ocr.json`，只看三件事：

1. **块数**是否接近页面文字行数（差太多 = 漏检）；
2. **文本**有没有错字、串行、把插图当文字；
3. **bbox** 是否正好框在文字上（前端按 `image_width/height` 等比缩放，框歪了说明坐标还原有问题）。

再看 `status`：有字却是 `empty` → 检测阈值过高；整页 `failed` → 看 `error.msg`。

## 第 6 步：常见错误对照表

| 现象 | 原因 | 解决 |
|---|---|---|
| `(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support` | Paddle 3.x 的 oneDNN 路径 bug | 代码已默认 `enable_mkldnn=False`；别手动开 `PADDLE_OCR_MKLDNN=1` |
| 识别出 `-`、`—` 等符号块 | 插画边缘被误检 | 已内置过滤：纯符号块和置信度 <0.35 的块会被丢弃 |
| `ModuleNotFoundError: No module named 'paddle'` | 只装了 paddleocr | `pip install paddlepaddle` |
| `numpy.core.multiarray failed to import` / ABI 报错 | numpy 2.x 与 paddle 不兼容 | `pip install "numpy<2"` |
| 模型下载失败、提示 `No model source is available` | 缓存目录不可写或网络不通 | 设 `PADDLE_PDX_CACHE_HOME` 到一个可写目录（默认 `~/.paddlex`） |
| 路径含中文报错 | OpenCV 读中文路径问题 | 图片复制到英文路径再跑 |
| `protobuf` 版本冲突 | 与 paddle 编译版本不匹配 | `pip install "protobuf>=3.20,<5"` |
| 第一次很慢（1–2 分钟） | 下载模型 + 初始化 | 正常，之后 3–5 秒 |
| 文字是倒的/竖排识别乱 | 方向分类默认关（更快） | 设 `PADDLE_OCR_ORIENTATION=1` 打开文字行方向分类 |

代码里已经做了兼容：2.x 的 `ocr()` 与 3.x 的 `predict()` 两种返回结构都能解析
（`tests/test_paddle_normalize.py` 用假引擎验证过）。如果报的是别的错，把堆栈发我。

## 第 7 步：万一装不上（兜底方案）

Paddle 在部分 Windows + Python 组合上确实难装。兜底：让 Qwen2.5-VL 直接读文字
（它本身具备 OCR 能力），加一个 `vlm` 版 OCR 后端，契约完全不变。
这条路的前提是你已经把 VLM 服务起起来了（第 3 步的 `--vlm-backend http`）。

## 接上之后立刻做

1. 把组委会给的 6 本绘本各跑 3 页，统计 `ok` / `empty` / `failed` 比例；
2. 我下一步给你 `eval/ocr_eval.py`，算字符准确率（1-CER）并输出 badcase 表；
3. 把 badcase 截图发我，一起决定是调预处理还是换模型。
