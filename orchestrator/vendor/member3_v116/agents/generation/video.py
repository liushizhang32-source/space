"""video.json 生成（C4）：一页图 + 分段配音 + 字幕 -> ffmpeg -> mp4。

v1 按“图文 + 配音”简化合成（§A.2 #9：image_prompt 不消费）：
  - 每个 story segment 一张静帧，时长等于该段 TTS 实测时长；
  - 字幕用 Pillow 预渲染成透明 PNG 再 overlay（比 drawtext 稳，中文/换行都可控）；
  - TTS 失败（audio_url 缺失）时用等长静音补齐，字幕照常出现；
  - 任一步失败 -> VideoError(3007)，页面 partial + [no_video]，不写 video.json。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from .config import Settings
from .errors import AppError, ContractError, ErrorCode, VideoError, VideoPublishError
from .ids import book_id_of, page_no_of
from .media import MediaStatus, VideoProbe, validate_video
from .proc import run, tail
from .safety import ensure_story_safe
from .schemas import StoryDoc, VideoDoc
from .storage import PageFiles, asset_url

try:  # Pillow 只用于字幕渲染，缺了也能出无字幕视频
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - 取决于环境
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)

SUBTITLE_MAX_CHARS = 18
SUBTITLE_BOTTOM_MARGIN = 40

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    page_id: str
    doc: dict
    path: Path
    subtitles_burned: bool
    elapsed_ms: int


def find_font(settings: Settings) -> str | None:
    if settings.video_font:
        candidate = Path(settings.video_font)
        if candidate.is_file():
            return str(candidate)
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _audio_path(segment: dict, settings: Settings) -> Path | None:
    url = segment.get("audio_url")
    if not url:
        return None
    name = Path(urlparse(str(url)).path).name
    candidate = settings.audios_dir / name
    if not candidate.is_file():
        # 声明了音频却找不到文件：这是资源故障，不能静默降级成静音
        raise VideoError(f"segment {segment.get('segment_id')} 声明了 audio_url 但音频文件缺失: {name}")
    return candidate


def wrap_subtitle(narration: str, max_chars: int = SUBTITLE_MAX_CHARS) -> list[str]:
    """标点优先断行，单行不超过 max_chars，最多 4 行（超出截断，避免挡住画面）。"""
    text = (narration or "").strip()
    if not text:
        return []
    lines: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in "。！？!?；;，,、：:" and len(buffer) >= 8:
            lines.append(buffer)
            buffer = ""
        elif len(buffer) >= max_chars:
            lines.append(buffer)
            buffer = ""
    if buffer:
        lines.append(buffer)
    return lines[:4]


def _subtitle_png(narration: str, settings: Settings, tmp_dir: Path, stem: str) -> Path | None:
    """把旁白渲染成底部半透明字幕条（PNG，宽 = 视频宽）。"""
    if Image is None or ImageDraw is None or ImageFont is None:
        return None
    font_path = find_font(settings)
    if not font_path:
        return None
    lines = wrap_subtitle(narration, max(12, min(SUBTITLE_MAX_CHARS, settings.video_width // 40)))
    if not lines:
        return None

    font_size = max(24, settings.video_width // 21)
    try:
        font = ImageFont.truetype(font_path, font_size)
    except OSError:
        return None

    measurer = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    line_height = int(font_size * 1.5)
    text_width = max(measurer.textlength(line, font=font) for line in lines)
    padding = max(12, font_size // 2)
    box_width = min(settings.video_width - 2 * padding, int(text_width) + 2 * padding)
    box_height = line_height * len(lines) + padding

    canvas = Image.new("RGBA", (settings.video_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    left = (settings.video_width - box_width) // 2
    draw.rounded_rectangle(
        [left, 0, left + box_width, box_height - 1],
        radius=16,
        fill=(0, 0, 0, 155),
    )
    for index, line in enumerate(lines):
        width = measurer.textlength(line, font=font)
        draw.text(
            ((settings.video_width - width) / 2, padding // 2 + index * line_height),
            line,
            font=font,
            fill=(255, 255, 255, 255),
        )

    path = tmp_dir / f"{stem}_sub.png"
    canvas.save(path)
    return path


def _base_vf(settings: Settings) -> str:
    width, height = settings.video_width, settings.video_height
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={settings.video_fps}"
    )


def _render_clip(
    settings: Settings,
    ffmpeg: str,
    image: Path,
    audio: Path | None,
    duration: float,
    out: Path,
    narration: str,
    tmp_dir: Path,
    with_subtitles: bool = True,
) -> bool:
    """渲染一个片段，返回是否真的烧了字幕。"""
    ffmpeg_inputs: list[str] = [
        "-loop",
        "1",
        "-framerate",
        str(settings.video_fps),
        "-i",
        str(image),
    ]
    if audio is not None:
        ffmpeg_inputs += ["-i", str(audio)]
    else:
        ffmpeg_inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100"]

    subtitle = _subtitle_png(narration, settings, tmp_dir, out.stem) if with_subtitles else None

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *ffmpeg_inputs]
    if subtitle is not None:
        cmd += ["-loop", "1", "-i", str(subtitle)]
        filter_complex = (
            f"[0:v]{_base_vf(settings)}[bg];"
            f"[bg][2:v]overlay=(W-w)/2:H-h-{SUBTITLE_BOTTOM_MARGIN}:format=auto[v]"
        )
        cmd += ["-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a"]
    else:
        cmd += ["-vf", _base_vf(settings)]

    cmd += ["-t", f"{duration:.3f}"]
    if audio is not None:
        cmd += ["-af", "apad"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = run(cmd, timeout=settings.video_timeout_sec)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        if subtitle is not None:
            # 字幕出问题时退回无字幕重试一次，别让整页视频挂掉
            return _render_clip(
                settings, ffmpeg, image, audio, duration, out, "", tmp_dir, with_subtitles=False
            )
        raise VideoError(f"片段合成失败（{out.stem}）", detail=tail(proc))
    return subtitle is not None


def _concat(ffmpeg: str, clips: list[Path], out: Path, timeout: int, tmp_dir: Path) -> None:
    list_file = tmp_dir / "concat.txt"
    lines = []
    for clip in clips:
        # concat 里的相对路径是相对 list 文件解析的，统一写绝对路径，避免双重拼接
        posix = Path(clip).resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{posix}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = run(cmd, timeout=timeout)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise VideoError("视频拼接失败", detail=tail(proc))


_PUBLISH_LOCKS: dict[str, threading.Lock] = {}
_PUBLISH_LOCKS_GUARD = threading.Lock()


def _page_lock(page_id: str) -> threading.Lock:
    """同一页的 mp4/JSON 发布串行化，避免同页并发互踩。"""
    with _PUBLISH_LOCKS_GUARD:
        return _PUBLISH_LOCKS.setdefault(page_id, threading.Lock())


def _best_effort_unlink(path: Path, *, note: str) -> None:
    """提交后的垃圾清理：失败只记录，绝不触发回滚。"""
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:  # pragma: no cover - 取决于文件系统状态
        logger.warning("%s 清理失败（产物已提交，不影响一致性）：%s (%s)", note, path, exc)


def _publish_pair(merged: Path, doc: dict, files: PageFiles) -> None:
    """MP4 + JSON 成对发布。

    锁内完成：备份旧版本 → 提交新版本 → 失败则回滚（同一把锁，不同线程无法插入）。
    提交成功后，备份清理失败只记录、不回滚。
    回滚失败时保留备份作为恢复材料，并抛 VideoPublishError 指明路径。

    说明：锁只覆盖同进程同页的写者；跨进程写者未串行化。读者可能看到
    “旧 MP4 + 新 JSON”或“新 MP4 + 旧 JSON”的短暂窗口，读取方应按 video.json
    的 mtime/内容做一致性判断。
    """
    suffix = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    staged = files.video.with_name(f"{files.video.name}.staged.{suffix}")
    json_tmp = files.video_json.with_name(f"{files.video_json.name}.tmp.{suffix}")
    mp4_backup = files.video.with_name(f"{files.video.name}.bak.{suffix}")
    json_backup = files.video_json.with_name(f"{files.video_json.name}.bak.{suffix}")

    files.video.parent.mkdir(parents=True, exist_ok=True)
    files.video_json.parent.mkdir(parents=True, exist_ok=True)

    video_committed = False
    json_committed = False
    original_error: Exception | None = None
    rollback_errors: list[str] = []

    with _page_lock(files.page_id):
        try:
            shutil.move(str(merged), str(staged))
            json_tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            if files.video.exists():
                os.replace(files.video, mp4_backup)
            if files.video_json.exists():
                os.replace(files.video_json, json_backup)

            os.replace(staged, files.video)
            video_committed = True
            os.replace(json_tmp, files.video_json)
            json_committed = True
        except Exception as exc:
            original_error = exc

        if original_error is not None:
            # 回滚仍在同一把锁内：其他线程无法在“失败”和“恢复”之间发布新版本
            if video_committed:
                try:
                    files.video.unlink(missing_ok=True)
                except OSError as exc:
                    rollback_errors.append(f"删除新 MP4 失败: {exc}")
            if mp4_backup.exists():
                try:
                    os.replace(mp4_backup, files.video)
                except OSError as exc:
                    rollback_errors.append(f"恢复旧 MP4 失败: {exc}")
            if json_committed:
                try:
                    files.video_json.unlink(missing_ok=True)
                except OSError as exc:
                    rollback_errors.append(f"删除新 JSON 失败: {exc}")
            if json_backup.exists():
                try:
                    os.replace(json_backup, files.video_json)
                except OSError as exc:
                    rollback_errors.append(f"恢复旧 JSON 失败: {exc}")

    if original_error is None:
        # 提交成功：备份清理是提交后动作，失败只记录
        _best_effort_unlink(mp4_backup, note="MP4 备份")
        _best_effort_unlink(json_backup, note="JSON 备份")
        _best_effort_unlink(staged, note="staged MP4")
        _best_effort_unlink(json_tmp, note="JSON 临时文件")
        return

    # 失败：staged/json_tmp 是本轮可丢弃的临时文件
    _best_effort_unlink(staged, note="staged MP4")
    _best_effort_unlink(json_tmp, note="JSON 临时文件")

    if rollback_errors:
        kept = [str(p) for p in (mp4_backup, json_backup) if p.exists()]
        raise VideoPublishError(
            "视频发布失败且回滚未完成：旧产物已保留为备份，需要人工恢复",
            detail=f"original={original_error!r}; backups={kept}; errors={rollback_errors}",
        ) from original_error

    raise original_error


def _render_once(page_id: str, story: dict, image: Path, settings: Settings) -> tuple[dict, Path, bool]:
    ffmpeg = settings.ffmpeg
    if not ffmpeg:
        raise VideoError("ffmpeg 不可用", detail="请设置 FFMPEG_PATH")

    segments = story.get("segments") or []
    if not segments:
        raise VideoError("story.json 没有 segments")

    files = PageFiles(settings, page_id)
    started = time.perf_counter()

    # 进程 + 线程 + 随机后缀：同一页并发生成时不会共用临时目录
    suffix = f"{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
    tmp_dir = (settings.tmp_dir / f"{page_id}_video_{suffix}").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    subtitles_used = False
    try:
        for index, segment in enumerate(segments, 1):
            duration = float(segment.get("duration_sec") or 0)
            if duration <= 0:
                raise VideoError(f"segment {segment.get('segment_id')} 时长为 0")
            audio = _audio_path(segment, settings)
            out = tmp_dir / f"clip_{index:02d}.mp4"
            narration = str(segment.get("narration") or "")
            burned = _render_clip(settings, ffmpeg, image, audio, duration, out, narration, tmp_dir)
            subtitles_used = subtitles_used or burned
            clip_paths.append(out)

        merged = tmp_dir / "merged.mp4"
        _concat(ffmpeg, clip_paths, merged, settings.video_timeout_sec, tmp_dir)

        # 先对临时产物做深检，通过后才发布到正式路径；失败不产生正式文件
        check = validate_video(merged, settings, deep=True)
        if check.status is MediaStatus.UNAVAILABLE:
            raise AppError(ErrorCode.UNAVAILABLE, "视频无法验证（ffprobe 不可用）", detail=check.reason)
        if check.status is MediaStatus.INVALID:
            raise VideoError(f"视频文件校验失败：{check.reason}")
        video_probe = check.probe
        assert isinstance(video_probe, VideoProbe)

        files.video.parent.mkdir(parents=True, exist_ok=True)

        planned = [float(seg["duration_sec"]) for seg in segments]
        total_planned = round(sum(planned), 3)
        actual = round(video_probe.duration_ms / 1000.0, 3)
        if abs(actual - total_planned) > 0.2 and total_planned > 0:
            scale = actual / total_planned
            durations = [round(d * scale, 3) for d in planned]
            total = round(sum(durations), 3)
        else:
            durations = planned
            total = total_planned

        timeline: list[dict] = []
        cursor = 0.0
        for segment, duration in zip(segments, durations):
            timeline.append(
                {
                    "segment_id": segment["segment_id"],
                    "start_sec": round(cursor, 3),
                    "end_sec": round(cursor + duration, 3),
                }
            )
            cursor += duration

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        doc = {
            "schema_version": "1.0",
            "book_id": book_id_of(page_id),
            "page_id": page_id,
            "page_no": page_no_of(page_id),
            "status": "ok",
            "video_url": asset_url(settings, files.video),
            "duration_sec": total,
            "resolution": f"{settings.video_width}x{settings.video_height}",
            "fps": settings.video_fps,
            "segments": timeline,
            "elapsed_ms": elapsed_ms,
        }
        try:
            validated = VideoDoc.model_validate(doc)
        except ValidationError as exc:
            raise ContractError("video.json 不满足 C4 契约", detail=str(exc)[:800]) from exc

        # MP4 + JSON 事务化发布：先写唯一临时文件，再在页级锁内成对替换；
        # 任一步失败都回滚到旧版本，并清掉本轮 staged/backup。
        _publish_pair(merged, validated.model_dump(), files)
        return validated.model_dump(), files.video, subtitles_used
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def compose_video(page_id: str, story: dict, settings: Settings) -> VideoResult:
    """带重试的合成入口（§1.13：Video 超时 180s、重试 1 次、退避 5s）。

    独立调用（不经 Story/中枢）时也必须先过契约与安全检查，不能绕过。
    """
    try:
        story_doc = StoryDoc.model_validate(story)
    except ValidationError as exc:
        raise ContractError("story.json 不满足 C3 契约，拒绝合成视频", detail=str(exc)[:800]) from exc
    if story_doc.page_id != page_id:
        raise VideoError(f"story.json 的 page_id({story_doc.page_id}) 与请求({page_id}) 不一致")
    if story_doc.safety_pass is False:
        raise AppError(
            ErrorCode.SAFETY_BLOCKED,
            "story.json safety_pass=false，拒绝合成视频",
            detail="上游已判定内容不安全",
        )
    ensure_story_safe(story_doc.model_dump(), settings, stage="视频输入")

    files = PageFiles(settings, page_id)
    image = files.source_image()
    if image is None:
        raise VideoError("找不到页面原图", detail=f"期望 {settings.uploads_dir}/{page_id}_orig.*")
    image = image.resolve()

    attempts = 1 + max(0, settings.max_retry)
    last: AppError | None = None
    for attempt in range(1, attempts + 1):
        try:
            doc, path, subtitles = _render_once(page_id, story_doc.model_dump(), image, settings)
            return VideoResult(
                page_id=page_id,
                doc=doc,
                path=path,
                subtitles_burned=subtitles,
                elapsed_ms=int(doc.get("elapsed_ms") or 0),
            )
        except AppError as exc:
            last = exc
            # 需要人工恢复的发布错误绝不自动重试（即使未来错误码变化）
            if isinstance(exc, VideoPublishError) or not exc.retryable or attempt == attempts:
                break
            time.sleep(max(0.0, settings.retry_backoff_sec))
    raise last or VideoError("视频生成失败")
