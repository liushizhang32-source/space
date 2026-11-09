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
from datetime import datetime, timezone

from .config import Settings
from .errors import AppError, ErrorCode, VideoPublishError
from .ids import page_no_of, ulid
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
        }
        if self.video_error:
            payload["video_error"] = self.video_error
        return payload


def run_page(
    page_id: str,
    age_level: str,
    settings: Settings,
    *,
    make_video: bool = True,
    tts_client: TTSClient | None = None,
    ocr: dict | None = None,
    vlm: dict | None = None,
) -> PageRunResult:
    started = time.perf_counter()
    files = PageFiles(settings, page_id)
    page_no = page_no_of(page_id)

    try:
        story = build_page_story(
            page_id,
            age_level,
            settings,
            tts_client=tts_client,
            ocr=ocr,
            vlm=vlm,
        )
    except AppError as exc:
        status = "blocked" if exc.code == ErrorCode.SAFETY_BLOCKED else "failed"
        return PageRunResult(
            page_id=page_id,
            page_no=page_no,
            status=status,
            error={"code": int(exc.code), "msg": exc.msg},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
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
    )


def load_story(page_id: str, settings: Settings) -> dict:
    """给 video 子命令用：直接读已落盘的 story.json 并校验。"""
    data = read_json(PageFiles(settings, page_id).story)
    if data is None:
        raise AppError(ErrorCode.NOT_FOUND, f"找不到 story.json：{page_id}")
    return StoryDoc.model_validate(data).model_dump()
