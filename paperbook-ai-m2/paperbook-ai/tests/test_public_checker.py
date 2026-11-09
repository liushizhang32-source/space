"""公共 Schema 检查器的回归测试。

`SCHEMA_REPO_ROOT` 必须指向**当前联合仓库**，检查器会用它的真实
`orchestrator/schemas/ocr.py` / `vlm.py` 做校验；没有设置就直接 fail，
因为“未验证”不能当成“通过”。
"""
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location(
        "public_checker_under_test", ROOT / "scripts/validate_with_orchestrator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source_root():
    value = os.environ.get("SCHEMA_REPO_ROOT")
    if not value:
        pytest.fail("Set SCHEMA_REPO_ROOT to the target repository; unverified is not pass")
    return value


@pytest.fixture
def docs(tmp_path):
    for kind in ("ocr", "vlm"):
        shutil.copyfile(
            ROOT / f"samples/example/book01_p01_{kind}.json",
            tmp_path / f"book01_p01_{kind}.json",
        )
    return tmp_path


def run_page(checker, source_root, path, page="book01_p01"):
    return checker.main(
        ["--repo-root", source_root, "--from", str(path), "--page", page]
    )


def run_dir(checker, source_root, path):
    """不指定 --page：走目录自动枚举（F02 盲区就发生在这条路径）。"""
    return checker.main(["--repo-root", source_root, "--from", str(path)])


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def clone_page(docs, kind, new_page, **overrides):
    """把 book01_p01 的某类产物复制成另一页，用于构造混合目录。"""
    doc = load(docs / f"book01_p01_{kind}.json")
    doc["page_id"] = new_page
    doc["book_id"] = new_page.rsplit("_p", 1)[0]
    doc["page_no"] = int(new_page.rsplit("_p", 1)[1])
    doc.update(overrides)
    save(docs / f"{new_page}_{kind}.json", doc)


# ---------------------------------------------------------------- 基本完备性


def test_missing_both_is_failure(checker, source_root, tmp_path):
    assert run_page(checker, source_root, tmp_path) == 1


def test_missing_vlm_is_failure(checker, source_root, docs):
    (docs / "book01_p01_vlm.json").unlink()
    assert run_page(checker, source_root, docs) == 1


def test_missing_ocr_is_failure(checker, source_root, docs):
    (docs / "book01_p01_ocr.json").unlink()
    assert run_page(checker, source_root, docs) == 1


def test_complete_pair_passes(checker, source_root, docs):
    assert run_page(checker, source_root, docs) == 0


def test_unknown_optional_field_is_accepted(checker, source_root, docs):
    path = docs / "book01_p01_vlm.json"
    doc = load(path)
    doc["future_field"] = True
    save(path, doc)
    assert run_page(checker, source_root, docs) == 0


# ------------------------------------------------- 严格整数：1.0 必须被拒绝
# 公共模型是 StrictInt：整数值浮点、布尔、数字字符串都要拒绝。
# 1.0 这条尤其关键——宽松的 int 模型会把它收成 1，从而“假通过”；
# 只测 1.5 无法区分 strict 与 lax，等于把这条防线让掉了。


@pytest.mark.parametrize("kind", ["ocr", "vlm"])
@pytest.mark.parametrize("value", [1.0, 1.5, True, "1"])
def test_non_strict_integer_bbox_is_failure(checker, source_root, docs, kind, value):
    path = docs / f"book01_p01_{kind}.json"
    doc = load(path)
    target = doc["text_blocks"][0] if kind == "ocr" else doc["objects"][0]
    target["bbox"][0] = value
    save(path, doc)
    assert run_page(checker, source_root, docs) == 1


def test_invalid_json_is_failure(checker, source_root, docs):
    (docs / "book01_p01_vlm.json").write_text("{", encoding="utf-8")
    assert run_page(checker, source_root, docs) == 1


def test_missing_public_models_is_unverified(checker, tmp_path):
    assert checker.main(["--repo-root", str(tmp_path), "--from", str(tmp_path)]) == 2


# ------------------------------------------- 目录自动枚举：不能只看 OCR 文件


def test_orphan_vlm_in_mixed_dir_is_detected(checker, source_root, docs):
    """一个完整页 + 一个只有 VLM 的页：缺 OCR 的页必须被枚举出来。"""
    clone_page(docs, "vlm", "book02_p01")
    assert run_dir(checker, source_root, docs) == 1


def test_orphan_ocr_in_mixed_dir_is_detected(checker, source_root, docs):
    clone_page(docs, "ocr", "book02_p01")
    assert run_dir(checker, source_root, docs) == 1


# --------------------------------------------- 文件名 / 配对身份 / 尺寸一致


def test_page_id_mismatch_is_failure(checker, source_root, docs):
    path = docs / "book01_p01_vlm.json"
    doc = load(path)
    doc["page_id"] = "book02_p01"
    save(path, doc)
    assert run_page(checker, source_root, docs) == 1


@pytest.mark.parametrize("field", ["book_id", "page_no", "image_width", "image_height"])
def test_pair_identity_mismatch_is_failure(checker, source_root, docs, field):
    path = docs / "book01_p01_vlm.json"
    doc = load(path)
    doc[field] = doc[field] + 1 if isinstance(doc[field], int) else "book99"
    save(path, doc)
    assert run_page(checker, source_root, docs) == 1
