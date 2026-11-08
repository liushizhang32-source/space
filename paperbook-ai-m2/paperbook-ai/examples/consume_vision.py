"""M3 视角：读 ocr.json + vlm.json，产出一份 story 草稿。

    python examples/consume_vision.py --page book01_p01

这是给成员3 的**起步模板**：结构已经按 C3（story.json）搭好，
你只需要把 `narration` 换成 LLM 生成的故事文本，其余字段保持不变。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.config import load_env  # noqa: E402

WORDS_PER_MINUTE = 220  # C1/§1.14 给的估算口径


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_story(ocr: dict, vlm: dict, *, age_level: str = "3-6") -> dict:
    page_id = ocr["page_id"]
    texts = [b["text"] for b in sorted(ocr["text_blocks"], key=lambda b: b["order"])]
    objects = [
        o for o in (vlm.get("objects") or [])
        if isinstance(o, dict) and o.get("object_id")
    ]
    tags = [t.strip() for t in (vlm.get("scene_tags") or []) if isinstance(t, str) and t.strip()]
    # StorySegment.scene 要求非空；VLM 缺失/无标签时给显式兜底，不能留空串
    scene = "、".join(tags) if tags else "绘本画面（自动兜底）"

    # 有文字就逐句成段；无字绘本用画面描述兜底
    narrations = texts or ([vlm.get("description")] if vlm.get("description") else [])
    if not narrations:
        narrations = ["这一页没有文字，也没有描述。"]

    segments = []
    for index, narration in enumerate(narrations, start=1):
        seconds = max(1.0, round(len(narration) / WORDS_PER_MINUTE * 60, 1))
        segments.append(
            {
                "segment_id": f"{page_id}_s{index:02d}",
                "order": index,
                "narration": narration,
                "scene": scene,
                "duration_sec": seconds,
                "duration_source": "estimate",  # 接上 TTS 后换成 tts
                "audio_url": None,
                "highlight_object_ids": [o["object_id"] for o in objects],
            }
        )

    title = texts[0] if texts else (vlm.get("description") or page_id)
    # 没有安全结论时按“未验证”处理，不默认通过
    safety = vlm.get("safety")
    if not isinstance(safety, dict) or "pass" not in safety:
        safety = {"pass": False, "flags": ["vlm_missing"]}
    return {
        "schema_version": "1.0",
        "book_id": ocr["book_id"],
        "page_id": page_id,
        "page_no": ocr["page_no"],
        "title": title[:20],
        "age_level": age_level,
        "status": "ok",
        "segments": segments,
        "total_duration_sec": round(sum(s["duration_sec"] for s in segments), 1),
        # 只接受真正的布尔 true；字符串 "false" 不能当通过
        "safety_pass": safety.get("pass") is True,
        "safety_flags": [str(f) for f in (safety.get("flags") or [])],
        "elapsed_ms": ocr.get("elapsed_ms", 0) + vlm.get("elapsed_ms", 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读视觉产物，生成 story 草稿")
    parser.add_argument("--page", required=True, help="如 book01_p01")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--age-level", default="3-6", choices=["3-6", "6-9"])
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    ocr_path = data_dir / "json" / f"{args.page}_ocr.json"
    vlm_path = data_dir / "json" / f"{args.page}_vlm.json"

    if not ocr_path.is_file():
        print(f"缺少 {ocr_path}，先跑 python run.py ...")
        return 1

    ocr = read_json(ocr_path)
    # VLM 阶段失败时不会产出 vlm.json（公共 VLMData 无 failed 枚举），
    # 这里按"只剩文字"降级，不直接退出。
    if vlm_path.is_file():
        vlm = read_json(vlm_path)
    else:
        vlm = {"status": "missing", "description": "", "objects": [], "scene_tags": []}
        log = data_dir / "logs" / f"{args.page}_vlm.error.json"
        reason = ""
        if log.is_file():
            reason = read_json(log).get("message", "")
        print(f"[WARN] 没有 {vlm_path.name}（VLM 阶段失败：{reason or '未知'}）")
        print("       改为只用 OCR 文本生成故事草稿。")

    print(f"页面 {args.page}  {ocr['image_width']}x{ocr['image_height']}")
    print(f"  ocr : {ocr['status']}  文本块 {len(ocr['text_blocks'])}")
    print(f"  vlm : {vlm['status']}  物体 {len(vlm.get('objects') or [])}")
    for block in ocr["text_blocks"]:
        print(f"    [{block['order']}] {block['text']}")
    if vlm.get("description"):
        print(f"  画面：{vlm['description']}")

    story = build_story(ocr, vlm, age_level=args.age_level)
    out_path = Path(args.out) if args.out else data_dir / "draft" / f"{args.page}_story.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nstory 草稿 → {out_path}")
    print(f"  segments={len(story['segments'])}  "
          f"total={story['total_duration_sec']}s  title={story['title']}")
    print("\n下一步（M3）：把 narration 换成 LLM 生成的故事，接 TTS 后改 duration_source=tts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
