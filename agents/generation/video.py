"""video.json 生成（C4）：一页图 + 分段配音 + 字幕 -> ffmpeg -> mp4。

v1 按“图文 + 配音”简化合成（§A.2 #9：image_prompt 不消费）：
  - 每个 story segment 一张静帧，时长等于该段 TTS 实测时长；
  - 字幕用 Pillow 预渲染成透明 PNG 再 overlay（比 drawtext 稳，中文/换行都可控）；
  - TTS 失败（audio_url 缺失）时用等长静音补齐，字幕照常出现；
  - 任一步失败 -> VideoError(3007)，页面 partial + [no_video]，不写 video.json。
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from .config import Settings
from .errors import ContractError, VideoError
from .ids import book_id_of, page_no_of
from .media import probe_duration_ms
from .proc import run, tail
from .schemas import VideoDoc
from .storage import PageFiles, asset_url, write_json

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
    return candidate if candidate.is_file() else None


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


def _render_once(page_id: str, story: dict, image: Path, settings: Settings) -> tuple[dict, Path, bool]:
    ffmpeg = settings.ffmpeg
    if not ffmpeg:
        raise VideoError("ffmpeg 不可用", detail="请设置 FFMPEG_PATH")

    segments = story.get("segments") or []
    if not segments:
        raise VideoError("story.json 没有 segments")

    files = PageFiles(settings, page_id)
    started = time.perf_counter()

    tmp_dir = (settings.tmp_dir / f"{page_id}_video_{os.getpid()}_{int(time.time() * 1000)}").resolve()
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

        files.video.parent.mkdir(parents=True, exist_ok=True)
        staged = files.video.with_name(files.video.name + ".part")
        shutil.move(str(merged), str(staged))
        os.replace(staged, files.video)

        planned = [float(seg["duration_sec"]) for seg in segments]
        total_planned = round(sum(planned), 3)
        actual_ms = probe_duration_ms(files.video, settings)
        actual = round(actual_ms / 1000.0, 3) if actual_ms else total_planned
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
        return validated.model_dump(), files.video, subtitles_used
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def compose_video(page_id: str, story: dict, settings: Settings) -> VideoResult:
    """带重试的合成入口（§1.13：Video 超时 180s、重试 1 次、退避 5s）。"""
    files = PageFiles(settings, page_id)
    image = files.source_image()
    if image is None:
        raise VideoError("找不到页面原图", detail=f"期望 {settings.uploads_dir}/{page_id}_orig.*")
    image = image.resolve()

    attempts = 1 + max(0, settings.max_retry)
    last: VideoError | None = None
    for attempt in range(1, attempts + 1):
        try:
            doc, path, subtitles = _render_once(page_id, story, image, settings)
            write_json(files.video_json, doc)
            return VideoResult(
                page_id=page_id,
                doc=doc,
                path=path,
                subtitles_burned=subtitles,
                elapsed_ms=int(doc.get("elapsed_ms") or 0),
            )
        except VideoError as exc:
            last = exc
            if attempt == attempts:
                break
            time.sleep(max(0.0, settings.retry_backoff_sec))
    raise last or VideoError("视频生成失败")
