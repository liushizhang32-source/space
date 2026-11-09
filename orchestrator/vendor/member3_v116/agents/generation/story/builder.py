"""story.json 生成（C3）：读 ocr/vlm -> 生成故事 -> 调 TTS -> 落盘。

契约要点：
  - 一页一故事，故事键就是 page_id；
  - segment_id = {page_id}_s{2位}，order 从 1 连续；
  - 每段 narration ≤120 字（TTS 单次上限），duration_sec 用 TTS 实测；
  - TTS 失败 → duration_source=estimate，音频缺失，页面 partial + [no_audio]；
  - 安全拦截 → 3004，该页 blocked，不产出文件。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pydantic import ValidationError

from ..config import Settings
from ..errors import AppError, ContractError, ErrorCode, StoryError, StoryInputError
from ..ids import book_id_of, page_no_of, segment_id
from ..safety import ensure_safe, story_texts
from ..schemas import StoryDoc
from ..storage import PageFiles, read_json, write_json
from ..tts.client import TTSClient
from ..tts.engine import estimate_duration_sec
from .draft import DraftSegment, StoryDraft
from .llm import LLMClient
from .template import build_template_draft, page_objects, page_text
from .text import normalize, split_long

MAX_SEGMENTS = 20
LLM_SOFT_LIMIT = 110

SYSTEM_PROMPT = """你是儿童绘本故事作者。根据一页绘本的 OCR 文字和画面描述，写出适合朗读的中文旁白。
只输出一个 JSON 对象，结构为：
{"title": "不超过16个汉字", "segments": [{"narration": "旁白", "scene": "这一段的画面描述", "highlight_object_ids": ["object_id"]}]}
硬性要求：
1. 2~5 段，每段 narration 不超过 60 个汉字，口语化、句子短、适合 3~9 岁儿童听；
2. 只能使用给定文字和画面里出现的人/物/场景，不新增角色，不改变画面主体；
3. 不写暴力、恐怖、危险行为；
4. highlight_object_ids 只能从给定列表里选，没有就输出 []；
5. 不输出 JSON 以外的任何内容。"""


@dataclass(frozen=True)
class InputState:
    text: str
    description: str
    objects: list[dict]
    tags: list[str]
    has_text: bool
    has_scene: bool
    wordless: bool
    ocr_failed: bool
    vlm_failed: bool

    @property
    def degraded(self) -> list[str]:
        flags: list[str] = []
        if self.ocr_failed:
            flags.append("no_ocr")
        if self.vlm_failed:
            flags.append("no_scene")
        return flags


@dataclass
class StoryResult:
    page_id: str
    doc: dict
    degraded: list[str]
    tts_failures: list[str]
    model_name: str
    elapsed_ms: int


KNOWN_STAGE_STATUS = frozenset({"ok", "empty", "failed"})


def normalize_status(raw: object) -> str:
    """§1.2.6：消费方对未知枚举走 default 分支。未知状态按 failed 处理，宁可降级也不误判成功。"""
    value = str(raw or "").strip().lower()
    return value if value in KNOWN_STAGE_STATUS else "failed"


def validate_input_doc(doc: dict | None, page_id: str, kind: str) -> dict | None:
    """上游产物必须是“这一页”的：schema_version / page_id / page_no / book_id 全部对齐。"""
    if doc is None:
        return None
    if not isinstance(doc, dict):
        raise AppError(ErrorCode.INVALID_PARAM, f"{kind}.json 不是 JSON 对象")
    if str(doc.get("schema_version")) != "1.0":
        raise AppError(
            ErrorCode.INVALID_PARAM,
            f"{kind}.json 的 schema_version 不是 1.0",
            detail=str(doc.get("schema_version")),
        )
    if doc.get("page_id") != page_id:
        raise AppError(
            ErrorCode.INVALID_PARAM,
            f"{kind}.json 的 page_id({doc.get('page_id')}) 与请求({page_id}) 不一致",
        )
    if doc.get("page_no") != page_no_of(page_id):
        raise AppError(
            ErrorCode.INVALID_PARAM,
            f"{kind}.json 的 page_no({doc.get('page_no')}) 与 page_id 不一致",
        )
    if doc.get("book_id") != book_id_of(page_id):
        raise AppError(
            ErrorCode.INVALID_PARAM,
            f"{kind}.json 的 book_id({doc.get('book_id')}) 与 page_id 不一致",
        )
    return doc


def analyze_inputs(ocr: dict | None, vlm: dict | None) -> InputState:
    ocr_status = normalize_status((ocr or {}).get("status"))
    vlm_status = normalize_status((vlm or {}).get("status"))

    text = page_text(ocr)
    objects = page_objects(vlm)
    description = normalize(str((vlm or {}).get("description") or ""))
    tags = [str(t) for t in ((vlm or {}).get("scene_tags") or []) if str(t).strip()]

    has_text = ocr is not None and ocr_status == "ok" and bool(text)
    # OCR empty = 无字绘本，不是失败（§1.12 / §1.14）
    wordless = ocr is not None and (ocr_status == "empty" or (ocr_status == "ok" and not text))
    ocr_failed = ocr is None or ocr_status == "failed"

    vlm_ok = vlm is not None and vlm_status in ("ok", "empty")
    has_scene = vlm_ok and bool(description or objects or tags)
    vlm_failed = not vlm_ok

    return InputState(
        text=text,
        description=description,
        objects=objects,
        tags=tags,
        has_text=has_text,
        has_scene=has_scene,
        wordless=wordless,
        ocr_failed=ocr_failed,
        vlm_failed=vlm_failed,
    )


def fallback_scene(state: InputState, narration: str) -> str:
    """降级路径下的画面描述兜底：保证 scene 非空（C3 要求每段有 scene）。

    优先级：VLM 描述 → 物体标签 → 场景标签 → 旁白摘录 → 通用文案。
    """
    description = (state.description or "").strip()
    if description:
        return description[:400]

    labels = [str(obj.get("label")).strip() for obj in state.objects if str(obj.get("label") or "").strip()]
    if labels:
        return ("画面中出现了" + "、".join(labels[:3]) + "。")[:400]

    tags = [str(tag).strip() for tag in state.tags if str(tag).strip()]
    if tags:
        return ("、".join(tags[:3]) + "的画面。")[:400]

    snippet = (narration or "").strip()[:20]
    if snippet:
        return f"书页画面：{snippet}"
    return "书页画面。"


def _llm_prompt(state: InputState, age_level: str) -> str:
    objects = "\n".join(
        f"- object_id={o.get('object_id')} label={o.get('label')} " for o in state.objects
    ) or "（无）"
    return (
        f"年龄档：{age_level} 岁\n"
        f"页面文字：{state.text or '（这一页没有文字）'}\n"
        f"画面描述：{state.description or '（无）'}\n"
        f"画面物体：\n{objects}\n"
        f"场景标签：{'、'.join(state.tags) or '（无）'}"
    )


def _draft_from_llm(state: InputState, age_level: str, settings: Settings) -> StoryDraft:
    client = LLMClient(settings)
    payload = client.chat_json(SYSTEM_PROMPT, _llm_prompt(state, age_level), timeout=settings.story_timeout_sec)
    raw_segments = payload.get("segments") or []
    segments: list[DraftSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        narration = normalize(str(item.get("narration") or ""))
        if not narration:
            continue
        ids = [str(i) for i in (item.get("highlight_object_ids") or []) if isinstance(i, str)]
        segments.append(
            DraftSegment(
                narration=narration,
                scene=normalize(str(item.get("scene") or "")) or state.description,
                highlight_object_ids=ids or None,
            )
        )
    if not segments:
        raise StoryError("LLM 没有产出可用分段", detail=str(payload)[:400])
    return StoryDraft(
        title=normalize(str(payload.get("title") or "")) or "书页上的故事",
        segments=segments,
        model_name=settings.llm_model or "llm",
        model_version="1.0",
    )


def _sanitize(draft: StoryDraft, state: InputState) -> list[DraftSegment]:
    """保证：段数 1~20、每段 ≤120 字、highlight 只引用真实 object_id。"""
    valid_ids = {str(o["object_id"]) for o in state.objects}
    segments: list[DraftSegment] = []
    for segment in draft.segments:
        for chunk in split_long(segment.narration, LLM_SOFT_LIMIT):
            chunk = normalize(chunk)
            if not chunk:
                continue
            ids = [i for i in (segment.highlight_object_ids or []) if i in valid_ids] or None
            segments.append(DraftSegment(narration=chunk, scene=segment.scene, highlight_object_ids=ids))
            if len(segments) >= MAX_SEGMENTS:
                break
        if len(segments) >= MAX_SEGMENTS:
            break
    if not segments:
        raise StoryInputError("没有可用的故事内容")
    return segments


def generate_draft(state: InputState, age_level: str, settings: Settings) -> StoryDraft:
    if not (state.has_text or state.has_scene):
        raise StoryInputError("这一页既没有文字也没有画面描述，无法生成故事")

    if LLMClient(settings).configured:
        try:
            draft = _draft_from_llm(state, age_level, settings)
        except AppError:
            if not settings.story_fallback_on_error:
                raise
            draft = _template_from_state(state, age_level)
    else:
        draft = _template_from_state(state, age_level)
    return draft


def _template_from_state(state: InputState, age_level: str) -> StoryDraft:
    return build_template_draft(
        _ocr_like(state) if state.has_text else None,
        _vlm_like(state) if state.has_scene else None,
        age_level,
    )


def _ocr_like(state: InputState) -> dict:
    return {
        "status": "ok",
        "text_blocks": [{"order": 1, "text": state.text}],
    }


def _vlm_like(state: InputState) -> dict:
    return {
        "status": "ok" if (state.description or state.objects) else "empty",
        "description": state.description,
        "objects": state.objects,
        "scene_tags": state.tags,
    }


def build_page_story(
    page_id: str,
    age_level: str,
    settings: Settings,
    tts_client: TTSClient | None = None,
    *,
    ocr: dict | None = None,
    vlm: dict | None = None,
    persist: bool = True,
) -> StoryResult:
    started = time.perf_counter()
    if age_level not in ("3-6", "6-9"):
        raise AppError(ErrorCode.INVALID_PARAM, f"age_level 只支持 3-6 / 6-9，收到 {age_level!r}")

    files = PageFiles(settings, page_id)
    ocr_doc = ocr if ocr is not None else read_json(files.ocr)
    vlm_doc = vlm if vlm is not None else read_json(files.vlm)
    # 输入页身份校验：防止拿错页的 ocr/vlm 生成故事
    ocr_doc = validate_input_doc(ocr_doc, page_id, "ocr")
    vlm_doc = validate_input_doc(vlm_doc, page_id, "vlm")

    state = analyze_inputs(ocr_doc, vlm_doc)
    if not (state.has_text or state.has_scene):
        raise StoryInputError(
            "OCR 与 VLM 都没有可用内容",
            detail=f"ocr={None if ocr_doc is None else ocr_doc.get('status')}, vlm={None if vlm_doc is None else vlm_doc.get('status')}",
        )

    # 上游（成员 2）已经判过安全：vlm.json 的 safety.pass=false 就是最终结论，不再生成故事
    vlm_safety = (vlm_doc or {}).get("safety") or {}
    if isinstance(vlm_safety, dict) and vlm_safety.get("pass") is False:
        raise AppError(
            ErrorCode.SAFETY_BLOCKED,
            "画面命中内容安全拦截",
            detail=",".join(str(flag) for flag in (vlm_safety.get("flags") or [])),
        )

    if settings.safety_enabled:
        ensure_safe([state.text, state.description], settings, stage="上游输入")

    draft = generate_draft(state, age_level, settings)
    draft_segments = _sanitize(draft, state)

    # 先把最终文本（title + narration + 最终 scene）全部算出来，再统一过安全闸。
    # fallback_scene 在这里就补齐，保证“兜底 scene 新引入的词”也在 TTS 之前被检查。
    final_segments: list[dict] = []
    for order, segment in enumerate(draft_segments, 1):
        final_segments.append(
            {
                "segment_id": segment_id(page_id, order),
                "order": order,
                "narration": segment.narration,
                "scene": (segment.scene or "").strip() or fallback_scene(state, segment.narration),
                "highlight_object_ids": list(segment.highlight_object_ids or []),
            }
        )

    ensure_safe(
        [draft.title]
        + [item["narration"] for item in final_segments]
        + [item["scene"] for item in final_segments],
        settings,
        stage="生成草稿",
    )

    client = tts_client or TTSClient(settings)
    segments: list[dict] = []
    tts_failures: list[str] = []

    for item in final_segments:
        sid = item["segment_id"]
        try:
            call = client.synthesize(item["narration"])
            duration = round(call.duration_ms / 1000.0, 3)
            audio_url = call.audio_url
            source = call.duration_source
            if source != "tts":
                tts_failures.append(sid)
        except AppError as exc:
            if exc.code == ErrorCode.SAFETY_BLOCKED:
                # 安全拒绝必须向上传播为 blocked，不能被降级成“没音频”
                raise
            duration = round(estimate_duration_sec(item["narration"]), 3)
            audio_url = None
            source = "estimate"
            tts_failures.append(sid)
            settings.logs_dir.mkdir(parents=True, exist_ok=True)
            with (settings.logs_dir / f"{page_id}_generation.log").open("a", encoding="utf-8") as log:
                log.write(f"[tts-failed] {sid} code={int(exc.code)} msg={exc.msg}\n")

        entry = {
            "segment_id": sid,
            "order": item["order"],
            "narration": item["narration"],
            "scene": item["scene"],
            "duration_sec": duration,
            "duration_source": source,
            "highlight_object_ids": item["highlight_object_ids"],
        }
        if audio_url:
            entry["audio_url"] = audio_url
        segments.append(entry)

    total = round(sum(s["duration_sec"] for s in segments), 3)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    doc = {
        "schema_version": "1.0",
        "book_id": book_id_of(page_id),
        "page_id": page_id,
        "page_no": page_no_of(page_id),
        "title": (draft.title or "书页上的故事")[:80],
        "age_level": age_level,
        "status": "ok",
        "segments": segments,
        "total_duration_sec": total,
        "safety_pass": True,
        "safety_flags": [],
        "model": {"name": draft.model_name, "version": draft.model_version},
        "elapsed_ms": elapsed_ms,
    }

    try:
        validated = StoryDoc.model_validate(doc)
    except ValidationError as exc:
        raise ContractError("story.json 不满足 C3 契约", detail=str(exc)[:800]) from exc

    doc = _strip_none(validated.model_dump())

    # 落盘前最后一道闸：任何不合格文本都不允许进入最终产物
    ensure_safe(story_texts(doc), settings, stage="产物落盘前")

    if persist:
        write_json(files.story, doc)

    degraded = list(state.degraded)
    if tts_failures:
        degraded.append("no_audio")
    return StoryResult(
        page_id=page_id,
        doc=doc,
        degraded=degraded,
        tts_failures=tts_failures,
        model_name=draft.model_name,
        elapsed_ms=elapsed_ms,
    )


def _strip_none(value):
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value
