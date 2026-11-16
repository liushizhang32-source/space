"""backend_task 的绑定 / 取消 / 迟到结果语义（V1.2.2 P1）。

这些测试全部使用内存里的假 opener，不连真实模型服务：
它们证明的是**记录与判定逻辑**，不能证明真实服务端已停止计算。
真实服务端的终止证据见 docs/VLM_EXECUTION_BOUNDARY.md 的探针结果。
"""

import io
import urllib.error

from _helpers import c1_binding, temp_dir

from vision import backend_task as bt

BIND = dict(
    backend="http",
    model="qwen2.5vl:3b",
    endpoint="http://127.0.0.1:11434/v1",
    job_id="job_01",
    page_id="book01_p01",
    generation_id="gen_01",
    attempt_id="att_01",
    fencing_token="tok_0123456789abcdef",
)


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_new_task_binds_identity():
    task = bt.new_task(**BIND)
    assert task.task_id.startswith("bt_")
    data = task.to_dict()
    assert data["protocol"] == bt.PROTOCOL
    for key, value in BIND.items():
        assert data[key] == value, key
    assert data["state"] == "running"
    assert data["may_retry"] is False
    assert data["may_publish"] is False


def test_cancel_without_endpoint_is_unconfirmed():
    task = bt.new_task(**BIND)
    bt.cancel(task)
    assert task.cancel_mode == "connection_close"
    assert task.terminal_confirmed is False
    assert task.may_retry() is False
    assert task.may_publish() is False


def test_cancel_with_confirmed_response():
    task = bt.new_task(**BIND)
    seen = {}

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return _Resp(b'{"cancelled": true, "task_id": "%s"}' % task.task_id.encode())

    bt.cancel(task, url_template="http://x/api/cancel/{task_id}", opener=opener)
    assert seen["method"] == "DELETE"
    assert task.task_id in seen["url"]
    assert task.cancel_status == 200
    assert task.terminal_confirmed is True
    assert task.state == bt.STATE_CANCELLED
    assert task.may_retry() is True


def test_cancel_http_error_is_recorded():
    task = bt.new_task(**BIND)

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)

    bt.cancel(task, url_template="http://x/api/cancel/{task_id}", opener=opener)
    assert task.cancel_status == 404
    assert task.terminal_confirmed is False
    assert task.state == bt.STATE_ABANDONED
    assert "HTTP 404" in task.detail


def test_cancel_connection_error_is_recorded():
    task = bt.new_task(**BIND)

    def opener(req, timeout):
        raise urllib.error.URLError("boom")

    bt.cancel(task, url_template="http://x/api/cancel/{task_id}", opener=opener)
    assert task.terminal_confirmed is False
    assert "URLError" in task.detail


def test_response_without_explicit_confirmation_is_not_trusted():
    task = bt.new_task(**BIND)

    def opener(req, timeout):
        return _Resp(b'{"ok": true}')

    bt.cancel(task, url_template="http://x/api/cancel/{task_id}", opener=opener)
    assert task.terminal_confirmed is False
    assert task.state == bt.STATE_ABANDONED


def test_finish_confirms_completed_call():
    task = bt.new_task(**BIND)
    bt.finish(task)
    assert task.state == bt.STATE_FINISHED
    assert task.terminal_confirmed is True
    assert task.may_publish() is True


def test_late_result_after_cancel_is_ignored():
    task = bt.new_task(**BIND)
    bt.cancel(task)  # 未确认
    bt.finish(task)  # 旧任务迟到返回
    assert task.state == bt.STATE_ABANDONED
    assert task.may_publish() is False
    assert "迟到结果被忽略" in task.detail


def test_record_roundtrip():
    task = bt.new_task(**BIND)
    bt.finish(task)
    with temp_dir() as tmp:
        path = tmp / "backend_task.json"
        bt.write_record(path, task)
        text = path.read_text(encoding="utf-8")
    assert task.task_id in text
    assert '"may_publish": true' in text


def test_worker_writes_backend_task_record():
    """Worker 侧：一次成功 VLM 调用必须在 attempt 目录留下绑定记录。"""
    import hashlib
    import json
    from pathlib import Path

    from PIL import Image

    from vision import worker
    from vision.backends.base import VlmObject, VlmResult

    class _Ocr:
        name = "fake-ocr"

        def available(self):
            return True, ""

        def recognize(self, image, **_kw):
            from vision.backends.base import OcrLine

            return [OcrLine("hello", (0.0, 0.0, 40.0, 10.0), 0.9)]

    class _Vlm:
        name = "fake-vlm"

        def available(self):
            return True, ""

        def understand(self, image, ocr_text):
            return VlmResult(
                description="画面",
                objects=[VlmObject("孩子", (5.0, 5.0, 50.0, 60.0), 0.7)],
                scene_tags=[],
                safety_pass=True,
                safety_flags=[],
                safety_raw={"pass": True, "flags": []},
                safety_source="model",
            )

    identity = dict(
        job_id="job_09", page_id="book01_p01", generation_id="gen_09",
        input_revision=1, epoch=1, attempt_id="att_09",
        fencing_token="tok_0123456789abcdef",
    )
    with temp_dir() as tmp:
        image = tmp / "page.png"
        Image.new("RGB", (200, 260), "white").save(image)
        ocr_req = {"protocol": worker.PROTOCOL, "stage": "ocr",
                   "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(), "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
                   **identity}
        env, code = worker.process_request(ocr_req, cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        vlm_req = {
            "protocol": worker.PROTOCOL, "stage": "vlm", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
            "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
            "inputs": {"c1": str(c1)},
            "c1_binding": c1_binding(identity, c1.read_bytes(), Path(image).read_bytes()),
            **identity,
        }
        env, code = worker.process_request(vlm_req, cwd=tmp, vlm_backend=_Vlm())
        assert code == 0, env
        record = json.loads((tmp / "backend_task.json").read_text(encoding="utf-8"))
    assert record["attempt_id"] == "att_09"
    assert record["generation_id"] == "gen_09"
    assert record["fencing_token"] == "tok_0123456789abcdef"
    assert record["state"] == "finished"
    assert record["terminal_confirmed"] is True


def _cancel_with(body: bytes):
    task = bt.new_task(**BIND)
    bt.cancel(
        task,
        url_template="http://x/api/cancel/{task_id}",
        opener=lambda req, timeout: _Resp(body),
    )
    return task


def test_cancel_with_wrong_task_id_is_not_trusted():
    task = _cancel_with(b'{"cancelled": true, "task_id": "bt_someone_else"}')
    assert task.terminal_confirmed is False
    assert task.state == bt.STATE_ABANDONED
    assert "task_id" in task.detail


def test_cancel_with_wrong_generation_is_not_trusted():
    task = _cancel_with(b'{"cancelled": true, "generation_id": "gen_99"}')
    assert task.terminal_confirmed is False
    assert "generation_id" in task.detail


def test_cancel_with_non_json_body_is_not_trusted():
    task = _cancel_with(b"OK")
    assert task.terminal_confirmed is False
    assert "JSON" in task.detail


def test_cancel_with_contradictory_body_is_not_trusted():
    task = _cancel_with(b'{"cancelled": true, "terminal": false}')
    assert task.terminal_confirmed is False
    assert "矛盾" in task.detail


def test_cancel_with_full_identity_echo_is_confirmed():
    task = bt.new_task(**BIND)
    body = (
        '{"cancelled": true, "task_id": "%s", "generation_id": "%s",'
        ' "attempt_id": "%s", "terminal": true}'
        % (task.task_id, BIND["generation_id"], BIND["attempt_id"])
    ).encode()
    bt.cancel(
        task,
        url_template="http://x/api/cancel/{task_id}",
        opener=lambda req, timeout: _Resp(body),
    )
    assert task.terminal_confirmed is True
    assert task.state == bt.STATE_CANCELLED
    assert task.may_publish() is False  # 已取消的任务不发布结果
