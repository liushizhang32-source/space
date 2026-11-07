"""成员 3 的命令行入口。

  python -m agents.generation run    --page-id book01_p03 --age-level 3-6
  python -m agents.generation story  --page-id book01_p03 --age-level 3-6
  python -m agents.generation video  --page-id book01_p03
  python -m agents.generation tts    --text "从前有只小兔子。"
  python -m agents.generation serve  --port 8001
  python -m agents.generation check
  python -m agents.generation schema --out schemas
  python -m agents.generation demo   [--variant wordless]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .envelope import fail, ok
from .errors import AppError
from .pipeline import load_story, run_page
from .schemas import export_json_schemas
from .story.builder import build_page_story
from .tts.client import TTSClient
from .video import compose_video, find_font


def _print(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.write(text + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agents.generation", description="纸书智伴 · 成员 3（Story/TTS/Video）")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑单页全链路（story -> tts -> video）")
    run.add_argument("--page-id", required=True)
    run.add_argument("--age-level", default="3-6", choices=["3-6", "6-9"])
    run.add_argument("--no-video", action="store_true", help="只生成 story.json")

    story = sub.add_parser("story", help="只生成 story.json")
    story.add_argument("--page-id", required=True)
    story.add_argument("--age-level", default="3-6", choices=["3-6", "6-9"])

    video = sub.add_parser("video", help="用已有 story.json 合成视频")
    video.add_argument("--page-id", required=True)

    tts = sub.add_parser("tts", help="调用本模块 TTS（等价 A6）")
    tts.add_argument("--text", required=True)
    tts.add_argument("--voice-id", default=None)
    tts.add_argument("--speed", type=float, default=None)
    tts.add_argument("--format", default="mp3", choices=["mp3", "wav"])

    serve = sub.add_parser("serve", help="启动 TTS HTTP 服务（A6）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)

    sub.add_parser("check", help="自检：ffmpeg / 引擎 / LLM / 目录")

    schema = sub.add_parser("schema", help="导出 story/video 的 JSON Schema")
    schema.add_argument("--out", default="schemas")

    demo = sub.add_parser("demo", help="用内置 mock 页跑通全链路")
    demo.add_argument("--page-id", default="book01_p03")
    demo.add_argument("--age-level", default="3-6", choices=["3-6", "6-9"])
    demo.add_argument("--variant", default="text", choices=["text", "wordless"])
    demo.add_argument("--no-video", action="store_true")
    demo.add_argument("--overwrite", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings.from_env()
    settings.ensure_dirs()

    try:
        if args.command == "run":
            result = run_page(args.page_id, args.age_level, settings, make_video=not args.no_video)
            _print(result.to_dict())
            return 0 if result.status in ("done", "partial") else 1

        if args.command == "story":
            result = build_page_story(args.page_id, args.age_level, settings)
            _print(result.doc)
            return 0

        if args.command == "video":
            story = load_story(args.page_id, settings)
            result = compose_video(args.page_id, story, settings)
            _print(result.doc)
            return 0

        if args.command == "tts":
            call = TTSClient(settings).synthesize(args.text, args.voice_id, args.speed, args.format)
            payload = ok(call.as_response_data())
            payload["data"]["cached"] = call.cached
            payload["data"]["engine"] = call.engine
            _print(payload)
            return 0

        if args.command == "serve":
            import uvicorn

            from .tts.service import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")
            return 0

        if args.command == "check":
            client = TTSClient(settings)
            _print(
                {
                    "data_dir": str(settings.data_dir.resolve()),
                    "asset_base_url": settings.asset_base_url,
                    "ffmpeg": settings.ffmpeg,
                    "ffprobe": settings.ffprobe,
                    "tts_engine": client.engine_name,
                    "tts_http_url": settings.tts_http_url or None,
                    "tts_voice_id": settings.tts_voice_id,
                    "llm_configured": bool(settings.llm_base_url and settings.llm_model),
                    "story_model": settings.llm_model or "mock-template",
                    "video_resolution": f"{settings.video_width}x{settings.video_height}@{settings.video_fps}",
                    "subtitle_font": find_font(settings),
                    "safety_enabled": settings.safety_enabled,
                }
            )
            return 0

        if args.command == "schema":
            written = export_json_schemas(Path(args.out))
            _print({"written": [str(p) for p in written]})
            return 0

        if args.command == "demo":
            from .demo import ensure_sample_page

            ensure_sample_page(
                settings,
                args.page_id,
                wordless=args.variant == "wordless",
                overwrite=args.overwrite,
            )
            result = run_page(args.page_id, args.age_level, settings, make_video=not args.no_video)
            payload = {"mock": True, "note": "内置样例页与 silent TTS，产物不代表真实模型效果", **result.to_dict()}
            _print(payload)
            return 0 if result.status in ("done", "partial") else 1

    except AppError as exc:
        _print(fail(exc.code, exc.msg))
        if exc.detail:
            sys.stderr.write(f"detail: {exc.detail}\n")
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
