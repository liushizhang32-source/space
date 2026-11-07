"""TTS 客户端：校验 -> 内容哈希缓存 -> 引擎合成 -> 返回契约需要的数据。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..errors import AppError, ErrorCode
from ..ids import tts_cache_key
from ..media import probe_duration_ms, probe_sample_rate
from ..storage import asset_url
from .engine import HttpEngine, SilentEngine, SynthOutcome, build_engine, estimate_duration_ms

SUPPORTED_FORMATS = ("mp3", "wav")
MAX_TEXT_CHARS = 120  # §1.10：超过 120 字返 1002


@dataclass(frozen=True)
class TTSCall:
    text: str
    voice_id: str
    speed: float
    format: str
    audio_path: Path
    audio_url: str
    duration_ms: int
    sample_rate: int
    cached: bool
    engine: str
    duration_source: str  # "tts" | "estimate"

    def as_response_data(self) -> dict:
        """A6 响应 data（§1.10）。"""
        return {
            "audio_url": self.audio_url,
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
        }


def validate_tts_request(
    settings: Settings,
    text: str | None,
    voice_id: str | None,
    speed: float | None,
    fmt: str | None,
) -> tuple[str, str, float, str]:
    if text is None or not text.strip():
        raise AppError(ErrorCode.MISSING_PARAM, "缺少参数 text")
    if len(text) > MAX_TEXT_CHARS:
        raise AppError(ErrorCode.INVALID_PARAM, f"text 超过 {MAX_TEXT_CHARS} 字（当前 {len(text)} 字）")

    resolved_speed = settings.tts_speed if speed is None else float(speed)
    if not 0.5 <= resolved_speed <= 2.0:
        raise AppError(ErrorCode.INVALID_PARAM, "speed 必须在 0.5~2.0 之间")

    resolved_format = (fmt or "mp3").strip().lower()
    if resolved_format not in SUPPORTED_FORMATS:
        raise AppError(ErrorCode.INVALID_PARAM, f"format 只支持 {'/'.join(SUPPORTED_FORMATS)}")

    resolved_voice = (voice_id or settings.tts_voice_id).strip() or settings.tts_voice_id
    return text, resolved_voice, resolved_speed, resolved_format


class TTSClient:
    def __init__(self, settings: Settings, engine: SilentEngine | HttpEngine | None = None):
        self.settings = settings
        self._engine = engine
        self._engine_error: AppError | None = None

    @property
    def engine(self) -> SilentEngine | HttpEngine:
        if self._engine is None:
            if self._engine_error is not None:
                raise self._engine_error
            try:
                self._engine = build_engine(self.settings)
            except AppError as exc:
                self._engine_error = exc
                raise
        return self._engine

    @property
    def engine_name(self) -> str:
        try:
            return self.engine.name
        except AppError:
            return "unavailable"

    def synthesize(
        self,
        text: str | None,
        voice_id: str | None = None,
        speed: float | None = None,
        fmt: str | None = None,
    ) -> TTSCall:
        text, voice_id, speed, fmt = validate_tts_request(self.settings, text, voice_id, speed, fmt)
        self.settings.audios_dir.mkdir(parents=True, exist_ok=True)

        key = tts_cache_key(text, voice_id, speed)
        path = self.settings.audios_dir / f"tts_{key}.{fmt}"

        if path.is_file() and path.stat().st_size > 0:
            duration_ms = probe_duration_ms(path, self.settings)
            sample_rate = probe_sample_rate(path, self.settings) or self.settings.tts_sample_rate
            if duration_ms is None:
                duration_ms = estimate_duration_ms(text)
                source = "estimate"
            else:
                source = "tts"
            return TTSCall(
                text=text,
                voice_id=voice_id,
                speed=speed,
                format=fmt,
                audio_path=path,
                audio_url=asset_url(self.settings, path),
                duration_ms=duration_ms,
                sample_rate=sample_rate,
                cached=True,
                engine=self.engine_name,
                duration_source=source,
            )

        outcome: SynthOutcome = self.engine.synthesize(text, voice_id, speed, fmt, path)
        return TTSCall(
            text=text,
            voice_id=voice_id,
            speed=speed,
            format=fmt,
            audio_path=outcome.path,
            audio_url=asset_url(self.settings, outcome.path),
            duration_ms=outcome.duration_ms,
            sample_rate=outcome.sample_rate,
            cached=False,
            engine=outcome.engine,
            duration_source="tts" if outcome.measured else "estimate",
        )
