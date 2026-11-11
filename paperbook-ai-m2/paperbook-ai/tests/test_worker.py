"""V1.2.1 单次 Worker 协议回归测试（不联网、不依赖 pytest 之外的库）。

覆盖：
- identity 七项逐项回显；OCR 成功返回合法 C1；OCR 无字返回 empty 而不是失败；
- VLM 必须消费 M1 传入的 C1（含 SHA256），成功时恰好产出 C2 + sidecar；
- safety 未通过时 3004、不落任何产物（fail-closed）；
- 路径穿越/绝对路径/产物重名/已存在文件被拒；坏请求也写 result.json；
- 超时映射 2002 + transient；契约错误 9001 + 非重试。
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from urllib.error import URLError

from PIL import Image

from vision import worker
from vision.backends.base import OcrLine, VlmObject, VlmResult

from _helpers import temp_dir

IDENTITY = {
    "job_id": "job_01",
    "page_id": "book01_p01",
    "generation_id": "gen_01",
    "input_revision": 1,
    "epoch": 2,
    "attempt_id": "att_01",
    "fencing_token": "tok_0123456789abcdef",
}


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, lines=None, exc: BaseException | None = None):
        self.lines = lines
        self.exc = exc

    def available(self):
        return True, ""

    def recognize(self, image):
        if self.exc is not None:
            raise self.exc
        if self.lines is not None:
            return self.lines
        return [OcrLine("Hello page", (12.0, 20.0, 180.0, 48.0), 0.93)]


class FakeVlm:
    name = "fake-vlm"

    def __init__(self, result: VlmResult | None = None, exc: BaseException | None = None):
        self.result = result
        self.exc = exc
        self.last_text = None

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        self.last_text = ocr_text
        if self.exc is not None:
            raise self.exc
        if self.result is None:
            return None
        return self.result


def _make_image(tmp: Path, name: str = "page.png") -> Path:
    path = tmp / name
    Image.new("RGB", (240, 320), "white").save(path)
    return path


def _request(tmp: Path, stage: str, outputs: dict, **extra) -> dict:
    image = _make_image(tmp)
    request = {
        "protocol": worker.PROTOCOL,
        "stage": stage,
        "image_path": str(image),
        "outputs": outputs,
        **IDENTITY,
    }
    request.update(extra)
    return request


def _vlm_result(**overrides) -> VlmResult:
    payload = dict(
        description="一个孩子在草地上",
        safety_pass=True,
        objects=[VlmObject("孩子", (10.0, 10.0, 100.0, 200.0), 0.8)],
        scene_tags=["草地"],
        safety_flags=[],
        safety_source="model",
        confidence_missing=0,
    )
    payload.update(overrides)
    return VlmResult(**payload)


def _run_ocr(tmp: Path) -> dict:
    request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
    envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=FakeOcr())
    assert code == 0, envelope
    return request


def _vlm_inputs(tmp: Path, ocr_request: dict) -> dict:
    c1_path = tmp / "json/book01_p01_ocr.json"
    image_path = Path(ocr_request["image_path"])
    return {
        "c1": "json/book01_p01_ocr.json",
        "c1_sha256": hashlib.sha256(c1_path.read_bytes()).hexdigest(),
        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
    }


def _vlm_outputs() -> dict:
    return {
        "c2": "json/book01_p01_vlm.json",
        "sidecar": "json/book01_p01_vlm.vision_refs.json",
    }


def test_ocr_success_writes_c1_and_result():
    with temp_dir() as tmp:
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=FakeOcr())

        assert code == 0, code
        assert envelope["code"] == 0
        assert envelope["protocol"] == worker.PROTOCOL
        assert envelope["identity"] == IDENTITY
        assert envelope["artifacts"] == {"c1": "json/book01_p01_ocr.json"}

        doc = json.loads((tmp / "json/book01_p01_ocr.json").read_text("utf-8"))
        assert doc["page_id"] == "book01_p01"
        assert doc["status"] == "ok"
        assert doc["text_blocks"][0]["text"] == "Hello page"

        result = json.loads((tmp / "result.json").read_text("utf-8"))
        assert result == envelope


def test_ocr_empty_is_success_not_failure():
    with temp_dir() as tmp:
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=FakeOcr(lines=[]))

        assert code == 0
        assert envelope["code"] == 0
        doc = json.loads((tmp / "json/book01_p01_ocr.json").read_text("utf-8"))
        assert doc["status"] == "empty"
        assert doc["text_blocks"] == []


def test_vlm_success_requires_c2_and_sidecar_with_sha_binding():
    with temp_dir() as tmp:
        ocr_request = _run_ocr(tmp)
        request = _request(
            tmp, "vlm", _vlm_outputs(), inputs=_vlm_inputs(tmp, ocr_request)
        )
        envelope, code = worker.process_request(
            request, cwd=tmp, vlm_backend=FakeVlm(_vlm_result())
        )

        assert code == 0, envelope
        assert set(envelope["artifacts"]) == {"c2", "sidecar"}

        c2_bytes = (tmp / "json/book01_p01_vlm.json").read_bytes()
        sidecar = json.loads(
            (tmp / "json/book01_p01_vlm.vision_refs.json").read_text("utf-8")
        )
        assert sidecar["schema_version"] == "vision_refs/0.1"
        assert sidecar["contract_status"] == "candidate"
        assert sidecar["identity"] == IDENTITY
        assert sidecar["identity"]["attempt_id"] == "att_01"
        assert sidecar["job_id"] == "job_01"  # 扁平镜像
        assert sidecar["c2"]["sha256"] == hashlib.sha256(c2_bytes).hexdigest()
        assert sidecar["c2"]["relative_path"] == "json/book01_p01_vlm.json"

        c2_doc = json.loads(c2_bytes)
        assert [o["object_id"] for o in sidecar["observations"]] == [
            o["object_id"] for o in c2_doc["objects"]
        ]
        assert sidecar["observations"][0]["confidence"]["kind"] == "model_estimate"
        assert sidecar["observations"][0]["confidence"]["calibrated"] is False


def test_vlm_safety_block_writes_no_artifacts():
    with temp_dir() as tmp:
        ocr_request = _run_ocr(tmp)
        request = _request(
            tmp, "vlm", _vlm_outputs(), inputs=_vlm_inputs(tmp, ocr_request)
        )
        envelope, code = worker.process_request(
            request,
            cwd=tmp,
            vlm_backend=FakeVlm(
                _vlm_result(safety_pass=False, safety_flags=["violence"], safety_source="model")
            ),
        )

        assert code == 1
        assert envelope["code"] == worker.ERROR_SAFETY_BLOCKED == 3004
        assert envelope["transient"] is False
        assert envelope["artifacts"] == {}
        assert envelope["detail"]["verdict"]["pass"] is False
        assert not (tmp / "json/book01_p01_vlm.json").exists()
        assert not (tmp / "json/book01_p01_vlm.vision_refs.json").exists()


def test_vlm_uses_inputs_c1_text():
    with temp_dir() as tmp:
        ocr_request = _run_ocr(tmp)
        vlm = FakeVlm(_vlm_result())
        request = _request(
            tmp, "vlm", _vlm_outputs(), inputs=_vlm_inputs(tmp, ocr_request)
        )
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=vlm)

        assert code == 0
        assert vlm.last_text == "Hello page"
        assert envelope["artifacts"]["c2"].endswith("_vlm.json")


def test_path_traversal_is_rejected():
    with temp_dir() as tmp:
        request = _request(
            tmp,
            "vlm",
            {"c2": "../evil.json", "sidecar": "json/s.vision_refs.json"},
        )
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=FakeVlm(_vlm_result()))

        assert code == 2
        assert envelope["code"] == 9001
        assert "bad_request" in envelope["msg"]
        assert not (tmp.parent / "evil.json").exists()
        assert json.loads((tmp / "result.json").read_text("utf-8"))["code"] == 9001


def test_missing_identity_is_bad_request():
    with temp_dir() as tmp:
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        del request["fencing_token"]
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=FakeOcr())

        assert code == 2
        assert envelope["code"] == 9001
        assert "fencing_token" in envelope["msg"]
        assert "fencing_token" not in envelope["identity"]


def test_timeout_maps_to_2002_transient():
    with temp_dir() as tmp:
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        envelope, code = worker.process_request(
            request, cwd=tmp, ocr_backend=FakeOcr(exc=URLError(socket.timeout("timed out")))
        )

        assert code == 1
        assert envelope["code"] == 2002
        assert envelope["transient"] is True
        assert not (tmp / "json").exists()


def test_backend_none_is_contract_error():
    with temp_dir() as tmp:
        ocr_request = _run_ocr(tmp)
        request = _request(
            tmp, "vlm", _vlm_outputs(), inputs=_vlm_inputs(tmp, ocr_request)
        )
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=FakeVlm(None))

        assert code == 1
        assert envelope["code"] == 9001
        assert envelope["transient"] is False


def test_absolute_image_path_is_rejected():
    with temp_dir() as tmp:
        image = _make_image(tmp)
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        request["image_path"] = "page.png"  # 相对路径
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=FakeOcr())

        assert code == 2
        assert envelope["code"] == 9001
        assert image.exists()


def test_unsupported_image_bytes_rejected_before_backend():
    with temp_dir() as tmp:
        bogus = tmp / "page.pdf"
        bogus.write_bytes(b"%PDF-1.7\n%fake\n")
        request = _request(tmp, "ocr", {"c1": "json/book01_p01_ocr.json"})
        request["image_path"] = str(bogus)
        ocr = FakeOcr()
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=ocr)

        assert code == 1
        assert envelope["code"] in (1006, 1004)
        assert not (tmp / "json").exists()
