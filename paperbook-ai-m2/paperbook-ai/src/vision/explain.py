"""为索引里的物体生成儿童化讲解（离线跑一次，点读时直接读）。

一页只调一次 VLM：把该页所有 label 一起给模型，让它输出 {label: 一句话}，
比"一个物体调一次"省 3–5 倍时间。
"""

from __future__ import annotations

from PIL import Image

EXPLAIN_PROMPT = """你是儿童绘本讲解员。看这页绘本，为下面每个物体写一句给 3-6 岁孩子听的话。

要求：
1. 20 字以内，口语化，像大人蹲下来跟孩子说话；
2. 说它是什么、在做什么、或有什么特点（颜色/动作/位置）；
3. 不要用"这是"开头，不要编号，不要英文，不要感叹号连用。

物体：{labels}

只输出 JSON，形如 {{"兔子": "……", "树": "……"}}，键必须与上面完全一致。"""


def build_prompt(labels: list[str]) -> str:
    return EXPLAIN_PROMPT.format(labels="、".join(labels))


def explain_objects(
    backend, image: Image.Image, labels: list[str], *, max_tokens: int | None = None
) -> dict[str, str]:
    """调一次 VLM，返回 {label: 讲解}。

    max_tokens 传 None 时用后端自己的预算（思考版模型需要足够大）。
    """
    if not labels:
        return {}
    if not hasattr(backend, "chat_raw"):
        raise RuntimeError(f"后端 {getattr(backend, 'name', '?')} 不支持 chat_raw，无法生成讲解")

    from .backends.qwen_vl import _loads_json

    content = backend.chat_raw(image, build_prompt(labels), max_tokens)
    try:
        data = _loads_json(content)
    except ValueError as exc:
        raise RuntimeError(f"讲解输出不是 JSON: {content[:160]}") from exc

    result: dict[str, str] = {}
    wanted = set(labels)
    for key, value in data.items():
        label = str(key).strip()
        if label not in wanted:  # 模型可能多给，只收我们问的
            continue
        text = str(value).strip()
        if text:
            result[label] = text
    return result
