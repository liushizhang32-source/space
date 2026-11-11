"""Qwen2.5-VL 后端（OpenAI 兼容 HTTP，vLLM / 任意网关均可）。

用 HTTP 而不是本地 transformers 的原因：企业赛给的是统一云 GPU，
vLLM 起一个 OpenAI 兼容服务最省事，本地/云上代码不用改。

注意：VLM 的 bbox 只作参考（模型 grounding 不稳），
正式版应由检测模型给框、VLM 只负责「是什么」。
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import socket
import urllib.error
import urllib.request

from PIL import Image

from ..safety import strict_safety
from .base import VlmObject, VlmResult


class VlmTimeout(RuntimeError):
    """HTTP / 连接超时；pipeline 依赖它把错误码映射成 2002。"""


class VlmOutputOverflow(RuntimeError):
    """模型输出的物体数超过上限：明确拒绝，不做静默截断（V1.2.1 P1-8）。"""

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(f"objects 超量：{count} > {limit}")
        self.count = count
        self.limit = limit

SYSTEM_PROMPT = (
    "你是儿童绘本的画面理解助手。只输出 JSON，不要任何解释或 Markdown 代码块。"
)

USER_PROMPT = """请阅读这页绘本（文字见下），**只输出一个 JSON 对象**，不要解释、不要 Markdown。

格式：
{"description": "一句话中文描述画面，30 字内",
 "objects": [{"label": "名词占位", "bbox": [x1,y1,x2,y2]}],
 "scene_tags": ["中文关键词，最多 4 个"],
 "safety": {"pass": true, "flags": []}}

要求：
1. bbox 用归一化整数坐标，范围 0-1000，左上角为原点；
2. objects 最多 10 个，列**画面里所有孩子可能用手指出来的东西**：
   人物、动物、植物、建筑、天空、食物、玩具、家具都要列，不要只列主角；
3. 只有纯背景色块、光影、花纹、文字本身不算物体；
4. label 用 2-4 个字的中文**具体名词**，必须写**这一页画面里真实存在**的东西；
   上面格式里的「名词占位」只是占位符，禁止原样输出，也不要输出「物体」「对象」「物品」这类泛称；
   不要英文、不要别名；
5. 不要输出 confidence 等格式外的字段；
6. 画面若含暴力、恐怖、成人内容，safety.pass 置 false 并在 flags 写原因。

绘本文字：
%s
"""


MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB：防止不受信任服务回超大响应


def _encode_jpeg(image: Image.Image, max_side: int = 1280, quality: int = 88) -> str:
    work = image.convert("RGB")
    if max(work.size) > max_side:
        scale = max_side / max(work.size)
        work = work.resize((max(1, int(work.width * scale)), max(1, int(work.height * scale))))
    buffer = io.BytesIO()
    work.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


_TRUE_WORDS = {"true", "1", "yes", "y", "t", "on", "是", "真"}
_FALSE_WORDS = {"false", "0", "no", "n", "f", "off", "", "否", "假"}

# 模型会照抄提示词里的占位词。这些词不是画面内容，落进契约会变成假物体。
_PLACEHOLDER_LABELS = {
    "名词占位", "具体名词", "画面中的具体名词", "物体名称", "物品名称",
    "物体", "对象", "物品", "名词", "标签", "中文通用名词",
}


def _is_placeholder_label(label: str) -> bool:
    """判断 label 是不是提示词占位符（而不是画面里的真实名词）。"""
    text = label.strip().strip("<>《》「」\"'")
    return label.startswith("<") or text in _PLACEHOLDER_LABELS


MAX_OBJECTS = 12        # 单页最多保留的物体数；再多对"指一指"没有意义
_MIN_SIDE_PX = 3.0      # 宽或高小于 3px 的框是退化框（模型常成串吐 11×1 的条）
_DUP_IOU = 0.80         # 与已有框重叠到这个比例就视为重复


def _iou(a, b) -> float:
    """两个 [x1,y1,x2,y2] 框的交并比。"""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def parse_bool(value, default: bool = False) -> bool:
    """安全布尔解析：模型常返回字符串 "false"，不能直接 bool()。

    默认值取 False（保守）：无法识别时宁可判不安全。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
    return default


def parse_flags(value) -> list[str]:
    """flags 可能是数组、字符串、或 None，统一成字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def parse_safety(payload) -> tuple[bool, list[str]]:
    """安全字段解析：**严格拒绝类型宽恕**（V1.2.1 P0-1）。

    只认 ``{"pass": true, "flags": []}``；``"true"``、``1``、``"1"`` 等
    一律判不安全，原因列表里写明具体哪条不合格。
    """
    return strict_safety(payload)


def _parse_confidence(value) -> float | None:
    """解析单个物体的置信度；非法返回 None（不伪造 0.75）。

    拒绝：bool、NaN、Inf、字符串、越界值、非数字。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    if not 0.0 <= number <= 1.0:
        return None
    return number


def _loads_json(content: str) -> dict:
    start = content.find("{")
    if start < 0:
        raise ValueError("输出里没有 JSON 对象")
    payload = content[start:]
    end = payload.rfind("}")
    if end > 0:
        payload = payload[: end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass

    for cut in range(len(payload) - 1, max(len(payload) - 800, 0), -1):
        if payload[cut] not in "}]":
            continue
        candidate = payload[: cut + 1]
        candidate += "]" * max(0, candidate.count("[") - candidate.count("]"))
        candidate += "}" * max(0, candidate.count("{") - candidate.count("}"))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(payload[:200])


class QwenVlBackend:
    name = "qwen2.5-vl-http"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("QWEN_VL_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("QWEN_VL_API_KEY") or ""
        self.model = model or os.getenv("QWEN_VL_MODEL") or "qwen2.5-vl-7b-instruct"
        self.timeout = timeout or int(os.getenv("QWEN_VL_TIMEOUT", "60"))
        self.max_tokens = int(os.getenv("QWEN_VL_MAX_TOKENS", "2000"))

    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "未配置 QWEN_VL_BASE_URL"
        return True, ""

    def understand(self, image: Image.Image, ocr_text: str) -> VlmResult:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)

        prompt = USER_PROMPT % (ocr_text.strip() or "（无文字）")
        return self._parse(self._post(self._payload(image, prompt)), image.size)

    def chat_raw(self, image: Image.Image, prompt: str, max_tokens: int | None = None) -> str:
        """自定义 prompt 的底层调用（讲解生成等场景用）。"""
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        return self._post(self._payload(image, prompt, max_tokens))

    def _payload(
        self, image: Image.Image, prompt: str, max_tokens: int | None = None
    ) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0.0,
            # 思考版模型（如 qwen3-vl）会先输出思维链，预算给小了正文会被挤空
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + _encode_jpeg(image)},
                        },
                    ],
                },
            ],
        }
        if os.getenv("QWEN_VL_DISABLE_THINKING") == "1":
            # vLLM 会把 chat_template_kwargs 透传给 HF 模板，Qwen3 系可借此关掉思考
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _post(self, payload: dict) -> str:
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}" if self.api_key else "Bearer EMPTY",
            },
            method="POST",
        )
        verbose = os.getenv("VISION_LOG_VERBOSE") == "1"
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("VLM 响应超过大小上限，已丢弃")
                body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 响应体可能回显请求内容，默认不落日志；排障时用 VISION_LOG_VERBOSE=1
            if verbose:
                detail = exc.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"VLM HTTP {exc.code}: {detail}") from exc
            raise RuntimeError(f"VLM HTTP {exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise VlmTimeout("VLM 请求超时") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise VlmTimeout("VLM 连接超时") from exc
            raise RuntimeError(f"VLM 请求失败: {type(exc.reason).__name__}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"VLM 请求失败: {type(exc).__name__}") from exc

        message = body["choices"][0]["message"]
        content = message.get("content") or ""
        if not content.strip():
            raise RuntimeError(
                "VLM 只输出了思考内容、正文为空（请调大 QWEN_VL_MAX_TOKENS "
                "或改用非思考模型）"
            )
        return content

    @staticmethod
    def _parse(content: str, size: tuple[int, int]) -> VlmResult:
        try:
            data = _loads_json(content)
        except ValueError as exc:
            # 正文可能含用户内容，默认不带原文
            if os.getenv("VISION_LOG_VERBOSE") == "1":
                raise RuntimeError(f"VLM 返回非 JSON: {content[:200]}") from exc
            raise RuntimeError("VLM 返回非 JSON") from exc
        width, height = size
        objects: list[VlmObject] = []
        confidence_missing = 0
        raw_objects = data.get("objects") or []
        if not isinstance(raw_objects, list):
            raise ValueError("objects 不是数组")
        for item in raw_objects:
            if not isinstance(item, dict):
                continue
            try:
                box = [float(v) for v in item["bbox"]]
                if len(box) != 4 or any(math.isnan(v) or math.isinf(v) for v in box):
                    continue
                bbox = [
                    box[0] * width / 1000.0,
                    box[1] * height / 1000.0,
                    box[2] * width / 1000.0,
                    box[3] * height / 1000.0,
                ]
                label = str(item.get("label", "")).strip()
                if not label or _is_placeholder_label(label):
                    continue
                # 退化框（模型在暗部/纹理上刷出的条状框）和重复框都不是真物体
                if min(bbox[2] - bbox[0], bbox[3] - bbox[1]) < _MIN_SIDE_PX:
                    continue
                if any(_iou(bbox, obj.bbox) >= _DUP_IOU for obj in objects):
                    continue
                # 超量直接拒绝；不在解析层悄悄截断
                if len(objects) >= MAX_OBJECTS:
                    raise VlmOutputOverflow(len(raw_objects), MAX_OBJECTS)
                # 缺失/非法置信度如实记 0，并计数上报，绝不伪造成 0.75
                confidence = _parse_confidence(item.get("confidence"))
                if confidence is None:
                    confidence_missing += 1
                    confidence = 0.0
                objects.append(VlmObject(label=label, bbox=bbox, confidence=confidence))
            except VlmOutputOverflow:
                raise
            except Exception:  # noqa: BLE001 - 单个物体解析失败不影响整页
                continue
        safety_ok, safety_reasons = strict_safety(data.get("safety"))
        return VlmResult(
            description=str(data.get("description", "")).strip(),
            objects=objects,
            scene_tags=[str(t) for t in (data.get("scene_tags") or [])],
            safety_pass=safety_ok,
            safety_flags=safety_reasons,
            safety_source="model" if safety_ok else "unavailable",
            confidence_missing=confidence_missing,
        )
