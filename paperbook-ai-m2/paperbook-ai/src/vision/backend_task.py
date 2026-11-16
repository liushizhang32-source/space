"""后端任务登记与取消证据（V1.2.2 P1）。

为什么需要这一层：VLM 走常驻 HTTP 服务（Ollama / vLLM / OpenAI 兼容端点）时，
“Worker 进程退出”只能证明客户端不再等待，**不能**证明服务端已经停止计算。
本模块做三件事：

1. 给每次模型调用发一个 ``backend_task_id``，并把它与
   job / generation / attempt / fencing_token 绑定（写进 attempt 目录）；
2. 尝试向服务端发起单任务取消，并如实记录返回码、是否得到终止确认；
3. 拿不到终止确认时，明确给出 ``may_retry=False`` / ``may_publish=False``，
   把“能不能继续”变成可判定的数据，而不是靠口头假设。

诚实边界：Ollama 目前没有“取消某个请求”的公开接口，断开流式连接只能
让服务端在下一次写 token 时发现对端消失。因此本模块把这种情况记为
``cancel_mode="connection_close"`` + ``terminal_confirmed=False``，
并建议 M1 用“一次 attempt 一个专用服务进程/容器”做真正的资源隔离
（见 docs/VLM_EXECUTION_BOUNDARY.md）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .strictjson import StrictJsonError, loads_object as strict_loads_object

PROTOCOL = "m2-backend-task/0.1"

STATE_RUNNING = "running"
STATE_FINISHED = "finished"
STATE_CANCELLED = "cancelled"
STATE_ABANDONED = "abandoned"

CONFIRM_NONE = "none"
CONFIRM_RESPONSE = "response"
CONFIRM_CONNECTION = "connection"


@dataclass
class BackendTask:
    """一次模型调用的可核验记录。字段全部是“事实”，不做推断。"""

    task_id: str
    backend: str
    model: str
    endpoint: str
    job_id: str
    page_id: str
    generation_id: str
    attempt_id: str
    fencing_token: str
    started_at: float
    state: str = STATE_RUNNING
    cancel_requested_at: float | None = None
    cancel_mode: str = "unsupported"
    cancel_endpoint: str = ""
    cancel_status: int | None = None
    cancel_body: str = ""
    terminal_confirmed: bool = False
    terminal_confirmed_at: float | None = None
    confirmation: str = CONFIRM_NONE
    finished_at: float | None = None
    detail: str = ""

    def elapsed_ms(self) -> int:
        end = self.finished_at or time.monotonic()
        return int((end - self.started_at) * 1000)

    def may_retry(self) -> bool:
        """终止未确认时禁止重试（审查要求）。"""
        if self.state in (STATE_FINISHED, STATE_CANCELLED):
            return True
        return self.terminal_confirmed

    def may_publish(self) -> bool:
        """终止未确认的旧任务不得发布结果。"""
        return self.state == STATE_FINISHED and self.terminal_confirmed

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["protocol"] = PROTOCOL
        data["elapsed_ms"] = self.elapsed_ms()
        data["may_retry"] = self.may_retry()
        data["may_publish"] = self.may_publish()
        return data


def new_task(
    *,
    backend: str,
    model: str,
    endpoint: str,
    job_id: str,
    page_id: str,
    generation_id: str,
    attempt_id: str,
    fencing_token: str,
) -> BackendTask:
    return BackendTask(
        task_id=f"bt_{uuid.uuid4().hex}",
        backend=backend,
        model=model,
        endpoint=endpoint,
        job_id=job_id,
        page_id=page_id,
        generation_id=generation_id,
        attempt_id=attempt_id,
        fencing_token=fencing_token,
        started_at=time.monotonic(),
    )


def write_record(path: Path, task: BackendTask) -> None:
    """把任务记录写进 attempt 私有目录（覆盖写：同一 attempt 只有一条）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _default_open(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


def _confirmation_from_body(task: BackendTask, body: str) -> tuple[bool, str]:
    """严格判定取消响应；任何"看起来像确认"但不匹配的内容都退回未确认。

    审查要求（V1.2.2 P1）：必须校验 backend_task_id、generation_id、attempt_id，
    拒绝矛盾响应与非 JSON 内容；未确认时不得释放租约、重试或发布。
    """
    try:
        payload = strict_loads_object(body)
    except StrictJsonError as exc:
        return False, f"取消响应不是合法 JSON（{exc.kind}），终止未确认"
    if payload.get("cancelled") is not True:
        return False, "取消响应未给出 cancelled=true，终止未确认"
    # 服务端若回显标识，必须与本次任务逐项一致；不一致说明取消的不是这个任务
    for field in ("task_id", "backend_task_id"):
        if field in payload and str(payload[field]) != task.task_id:
            return False, f"取消响应 {field} 不匹配，终止未确认"
    for field in ("generation_id", "attempt_id"):
        if field in payload and str(payload[field]) != getattr(task, field):
            return False, f"取消响应 {field} 不匹配，终止未确认"
    # 矛盾响应：一边说取消了，一边又说还在跑/没终止
    if payload.get("terminal") is False or payload.get("state") in (
        "running",
        "queued",
        "pending",
    ):
        return False, "取消响应自相矛盾（cancelled=true 但任务仍在运行），终止未确认"
    return True, ""


def cancel(
    task: BackendTask,
    *,
    url_template: str = "",
    timeout: float = 2.0,
    opener: Callable[..., Any] | None = None,
) -> BackendTask:
    """尝试取消服务端任务；结果如实写回 task，不做乐观推测。

    ``url_template`` 形如 ``http://127.0.0.1:11434/api/cancel/{task_id}``；
    留空表示服务端没有单任务取消接口，只能退化为断开连接。
    """
    task.cancel_requested_at = time.monotonic()
    if not url_template:
        task.cancel_mode = "connection_close"
        task.detail = "服务端未提供单任务取消接口；仅关闭客户端连接，终止未确认"
        task.state = STATE_ABANDONED
        return task

    task.cancel_mode = "http"
    task.cancel_endpoint = url_template.format(task_id=task.task_id)
    open_fn = opener or _default_open
    req = urllib.request.Request(task.cancel_endpoint, method="DELETE")
    try:
        with open_fn(req, timeout) as resp:  # type: ignore[union-attr]
            body = resp.read(2048).decode("utf-8", "replace")
            task.cancel_status = int(getattr(resp, "status", 200))
            task.cancel_body = body[:500]
            # 只有服务端明确回 cancelled=true 且标识/状态自洽，才算“可信终止确认”
            ok, why = _confirmation_from_body(task, body)
            if task.cancel_status < 300 and ok:
                task.terminal_confirmed = True
                task.terminal_confirmed_at = time.monotonic()
                task.confirmation = CONFIRM_RESPONSE
                task.state = STATE_CANCELLED
            else:
                task.state = STATE_ABANDONED
                task.detail = why or "取消请求已被接收，但响应未给出终止确认"
    except urllib.error.HTTPError as exc:
        task.cancel_status = int(exc.code)
        task.state = STATE_ABANDONED
        task.detail = f"取消请求被拒绝：HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - 连不上也是事实，必须记录
        task.state = STATE_ABANDONED
        task.detail = f"取消请求失败：{type(exc).__name__}"
    return task


def finish(task: BackendTask) -> BackendTask:
    """正常结束（模型已返回），此时客户端侧确认可终止。

    已被取消/放弃的任务如果又迟到返回，**不得**改判成功——
    否则迟到结果会被当成新结果发布（审查明确禁止）。
    """
    if task.state != STATE_RUNNING:
        task.detail = (task.detail + "；" if task.detail else "") + "迟到结果被忽略"
        return task
    task.state = STATE_FINISHED
    task.finished_at = time.monotonic()
    if task.confirmation == CONFIRM_NONE:
        # 请求已完成：连接关闭后服务端不再有该任务的计算，这一条属于
        # “响应已返回”的强证据，与“中途取消”不同，单独标记。
        task.terminal_confirmed = True
        task.terminal_confirmed_at = task.finished_at
        task.confirmation = CONFIRM_CONNECTION
    return task


def abandon(task: BackendTask, detail: str) -> BackendTask:
    task.state = STATE_ABANDONED
    task.finished_at = time.monotonic()
    task.detail = detail
    return task
