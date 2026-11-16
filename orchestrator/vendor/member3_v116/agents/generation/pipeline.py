"""单页流水线：story -> tts -> video，并给出契约里的页面状态与 degraded 标记。

这一层是给编排中枢（成员 1）用的集成面：
    run_page() 返回 dict，字段与 /jobs 的 pages[] 对齐（page_id/page_no/status/degraded/
    story_url/video_url/error），中枢只需把它塞进 job 状态机。

页面状态判定（§1.7 / §1.14）：
    done     故事与视频都成功
    partial  有降级（no_ocr / no_scene / no_audio / no_video）
    blocked  安全拦截
    failed   故事层失败（该页无产物）
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from datetime import datetime, timezone

from .config import Settings
from .errors import AppError, ErrorCode, VideoPublishError
from .ids import page_no_of, ulid

if TYPE_CHECKING:  # pragma: no cover
    from .m1_pipeline import M1PageSession
from .schemas import StoryDoc
from .story.builder import StoryResult, build_page_story
from .storage import PageFiles, asset_url, read_json
from .tts.client import TTSClient
from .video import compose_video

logger = logging.getLogger(__name__)


def record_publish_recovery(settings: Settings, page_id: str, exc: VideoPublishError) -> str:
    """把“需要人工恢复”的发布错误写进内部日志，返回可追踪的 recovery_id。

    诊断写入是“尽力而为”：主日志不可写时退到备用日志；都失败时只记录到
    logging，绝不因日志 I/O 失败而遮蔽原本的 3007 恢复语义。
    公共响应只带 recovery_id，不泄漏本机备份路径。
    """
    recovery_id = "rec_" + ulid()
    record = {
        "event": "video_publish_recovery_required",
        "recovery_id": recovery_id,
        "page_id": page_id,
        "code": int(exc.code),
        "msg": exc.msg,
        "detail": exc.detail,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # 先告警：即使后面的文件写入全部失败，恢复信息也已通过 logging 输出
    logger.warning(
        "视频发布需要人工恢复：recovery_id=%s page_id=%s detail=%s",
        recovery_id,
        page_id,
        exc.detail,
    )

    primary = settings.logs_dir / f"{page_id}_publish_errors.jsonl"
    fallback = settings.logs_dir / "publish_errors_fallback.jsonl"

    for label, path in (("primary", primary), ("fallback", fallback)):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as write_error:
            logger.error("恢复日志写入失败（%s）：%s (%s)", label, path, write_error)
            continue
        if label == "fallback":
            logger.warning("主恢复日志不可写，已写入备用日志：%s", path)
        return recovery_id

    # 主日志和备用日志都写不进去：保留可追踪 id，rest 交给 logging
    logger.error(
        "恢复信息未能持久化（recovery_id=%s page_id=%s detail=%s）",
        recovery_id,
        page_id,
        exc.detail,
    )
    return recovery_id


@dataclass
class PageRunResult:
    page_id: str
    page_no: int
    status: str
    degraded: list[str] = field(default_factory=list)
    story_url: str | None = None
    video_url: str | None = None
    error: dict | None = None
    video_error: dict | None = None
    elapsed_ms: int = 0
    story: StoryResult | None = None
    generation_mode: str = "mock_static"
    m1_attempt_id: str | None = None
    m1_result_sha256: str | None = None
    #: 失败路径上释放 M1 预留失败时记录；None 表示无需释放或释放成功。
    budget_release_error: dict | None = None

    def to_dict(self) -> dict:
        """与 /jobs 的 pages[] 结构对齐（video_error 是本地调试附加字段）。"""
        payload = {
            "page_id": self.page_id,
            "page_no": self.page_no,
            "status": self.status,
            "degraded": self.degraded,
            "story_url": self.story_url,
            "video_url": self.video_url,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "generation_mode": self.generation_mode,
            "m1_attempt_id": self.m1_attempt_id,
            "m1_result_sha256": self.m1_result_sha256,
            "budget_release_error": self.budget_release_error,
        }
        if self.video_error:
            payload["video_error"] = self.video_error
        return payload


def _release_on_failure(m1: "M1PageSession | None") -> dict | None:
    """失败路径的统一释放：只释放未提交的预留，释放失败必须显式上报。"""
    if m1 is None:
        return None
    try:
        m1.release()
        return None
    except AppError as exc:
        m1_code = getattr(exc, "m1_code", None)
        logger.error(
            "M1 预算释放失败：%s（attempt=%s, m1_code=%s）；预算可能仍被占用，需 M1 对账",
            exc.msg,
            m1.attempt_id,
            m1_code,
        )
        return {"code": int(exc.code), "msg": exc.msg, "m1_code": m1_code}
    except Exception:
        # A lost cancel response does not prove the reservation was released.
        logger.exception("M1 预算释放结果不确定；需 M1 对账")
        return {"code": int(ErrorCode.UNAVAILABLE), "msg": "预算释放结果不确定",
                "m1_code": "RELEASE_UNCERTAIN"}


def run_page(
    page_id: str,
    age_level: str,
    settings: Settings,
    *,
    make_video: bool = True,
    tts_client: TTSClient | None = None,
    ocr: dict | None = None,
    vlm: dict | None = None,
    m1: "M1PageSession | None" = None,
    cancelled=None,
) -> PageRunResult:
    started = time.perf_counter()
    files = PageFiles(settings, page_id)
    page_no = page_no_of(page_id)

    try:
        if cancelled is not None and cancelled():
            raise AppError(ErrorCode.UNAVAILABLE, "页面生成已取消")
        if m1 is not None:
            # 授权模式下输入只来自 M1 Gate 桥接的不可变 bytes，不读本地 ocr/vlm
            m1.ensure_page(page_id)
            ocr, vlm = m1.inputs_json()

        story = build_page_story(
            page_id,
            age_level,
            settings,
            tts_client=tts_client,
            ocr=ocr,
            vlm=vlm,
        )
    except AppError as exc:
        # 授权读取失败 / 页身份不一致 / 故事生成失败走同一释放路径
        release_error = _release_on_failure(m1)
        status = "blocked" if exc.code == ErrorCode.SAFETY_BLOCKED else "failed"
        return PageRunResult(
            page_id=page_id,
            page_no=page_no,
            status=status,
            error={"code": int(exc.code), "msg": exc.msg},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            generation_mode="m1_authorized" if m1 is not None else "mock_static",
            m1_attempt_id=m1.attempt_id if m1 is not None else None,
            budget_release_error=release_error,
        )

    if cancelled is not None and cancelled():
        release_error = _release_on_failure(m1)
        return PageRunResult(page_id, page_no, "failed",
            error={"code": int(ErrorCode.UNAVAILABLE), "msg": "页面生成已取消"},
            generation_mode="m1_authorized" if m1 else "mock_static",
            m1_attempt_id=m1.attempt_id if m1 else None, budget_release_error=release_error)

    submitted_sha: str | None = None
    if m1 is not None:
        # 提交前：读 story.json 原始字节。读取失败仍属"未提交"，必须释放预留。
        try:
            payload = files.story.read_bytes()
        except OSError as exc:
            release_error = _release_on_failure(m1)
            code = ErrorCode.NOT_FOUND if isinstance(exc, FileNotFoundError) else ErrorCode.UNAVAILABLE
            logger.error("读取 story.json 失败（%s），已尝试释放 M1 预留：%s", files.story, exc)
            return PageRunResult(
                page_id=page_id,
                page_no=page_no,
                status="failed",
                error={"code": int(code), "msg": "读取故事结果失败"},
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                story=story,
                generation_mode="m1_authorized",
                m1_attempt_id=m1.attempt_id,
                budget_release_error=release_error,
            )

        # 提交后：submit 失败可能意味着 M1 已进入 UNKNOWN，不得假定未提交，
        # 也不得自行释放；由调用方按错误码查询/对账。
        try:
            submitted_sha = m1.submit_story_bytes(payload)
        except AppError as exc:
            return PageRunResult(
                page_id=page_id,
                page_no=page_no,
                status="failed",
                error={"code": int(exc.code), "msg": exc.msg},
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                story=story,
                generation_mode="m1_authorized",
                m1_attempt_id=m1.attempt_id,
            )

    degraded = list(story.degraded)
    story_url = asset_url(settings, files.story)
    video_url: str | None = None
    video_error: dict | None = None

    if make_video:
        try:
            video = compose_video(page_id, story.doc, settings)
            video_url = video.doc["video_url"]
        except AppError as exc:
            if exc.code == ErrorCode.SAFETY_BLOCKED:
                # 视频阶段的安全拒绝保持 blocked 语义，不能降级成 no_video
                return PageRunResult(
                    page_id=page_id,
                    page_no=page_no,
                    status="blocked",
                    degraded=degraded,
                    story_url=None,
                    generation_mode="m1_authorized" if m1 else "mock_static",
                    m1_attempt_id=m1.attempt_id if m1 else None,
                    m1_result_sha256=submitted_sha,
                    error={"code": int(exc.code), "msg": exc.msg},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            degraded.append("no_video")
            if isinstance(exc, VideoPublishError):
                # 需要人工恢复：内部日志保留备份路径，公共响应只给 recovery_id
                recovery_id = record_publish_recovery(settings, page_id, exc)
                video_error = {"code": int(exc.code), "msg": exc.msg, "recovery_id": recovery_id}
            else:
                video_error = {"code": int(exc.code), "msg": exc.msg}

    status = "partial" if degraded else "done"
    return PageRunResult(
        page_id=page_id,
        page_no=page_no,
        status=status,
        degraded=degraded,
        story_url=story_url,
        video_url=video_url,
        video_error=video_error,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        story=story,
        generation_mode="m1_authorized" if m1 is not None else "mock_static",
        m1_attempt_id=m1.attempt_id if m1 is not None else None,
        m1_result_sha256=submitted_sha,
    )


def load_story(page_id: str, settings: Settings) -> dict:
    """给 video 子命令用：直接读已落盘的 story.json 并校验。"""
    data = read_json(PageFiles(settings, page_id).story)
    if data is None:
        raise AppError(ErrorCode.NOT_FOUND, f"找不到 story.json：{page_id}")
    return StoryDoc.model_validate(data).model_dump()
