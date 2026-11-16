"""M3 业务入口的 M1 授权会话：一次页面生成对应一个 Generation Attempt。

`pipeline.run_page(..., m1=session)` 只通过本会话读取由 M1 授权、Gate 桥接写入的
c1/c2/sidecar/image；故事生成完成后把**已落盘的 story.json 原始字节**提交给 M1。
本模块不读本地 ocr/vlm 文件，也不自行签发 Token。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .errors import AppError, ErrorCode
from .m1_generation import GenerationAttempt, GenerationDenied, M1GenerationConsumer

__all__ = ["M1PageSession", "M1ReleaseError", "open_session"]

#: 上游已撤销 / 已换代时，M1 已经释放（或无需再释放）预留，属于可幂等处理的终态。
_IDEMPOTENT_RELEASE = frozenset({"TOKEN_REVOKED", "STALE_ATTEMPT"})


class M1ReleaseError(AppError):
    """释放未提交预留失败：预算可能仍被占用，调用方必须显式对账。

    只用于无法确认“已释放”的拒绝（例如 MAINTENANCE / CORRUPT / CLOCK_ROLLBACK）；
    TOKEN_REVOKED、STALE_ATTEMPT 视为已完成的幂等终态，不会抛出本异常。
    """

    def __init__(self, m1_code: str):
        self.m1_code = m1_code
        super().__init__(
            ErrorCode.UNAUTHORIZED, f"释放预算失败：{m1_code}", detail=m1_code
        )


@dataclass
class M1PageSession:
    """绑定一个 M1 Generation Attempt 的页面会话。"""

    consumer: M1GenerationConsumer
    attempt: GenerationAttempt
    _inputs: dict[str, bytes] | None = field(default=None, repr=False)
    submitted: bool = False
    released: bool = False
    release_error: str | None = None

    @property
    def page_id(self) -> str:
        return self.attempt.page_id

    @property
    def attempt_id(self) -> str:
        return self.attempt.attempt_id

    def inputs(self) -> dict[str, bytes]:
        """按授权读取四个输入（c1/c2/sidecar/image），只读一次。"""
        if self._inputs is None:
            try:
                self._inputs = self.consumer.read_inputs(self.attempt)
            except GenerationDenied as exc:
                raise AppError(
                    ErrorCode.UNAUTHORIZED, f"M1 授权读取失败：{exc.m1_code}", detail=exc.m1_code
                ) from None
        return self._inputs

    def inputs_json(self) -> tuple[dict, dict]:
        data = self.inputs()
        ocr = json.loads(data["c1.json"])
        vlm = json.loads(data["c2.json"])
        return ocr, vlm

    def ensure_page(self, page_id: str) -> None:
        for doc in self.inputs_json():
            if doc.get("page_id") != page_id:
                raise AppError(
                    ErrorCode.INVALID_PARAM,
                    f"授权输入页身份不一致：期望 {page_id}，收到 {doc.get('page_id')!r}",
                )

    def submit_story_bytes(self, payload: bytes) -> str:
        if self.submitted:
            raise AppError(ErrorCode.INVALID_PARAM, "该 Generation Attempt 已提交")
        try:
            updated = self.consumer.submit(self.attempt, payload)
        except GenerationDenied as exc:
            raise AppError(
                ErrorCode.UNAUTHORIZED, f"提交生成结果被拒绝：{exc.m1_code}", detail=exc.m1_code
            ) from None
        self.attempt = updated
        self.submitted = True
        return updated.result_sha256 or ""

    def release(self) -> None:
        """仅在尚未提交时释放预留；已提交的必须由 M1 账单对账。

        - 成功取消：置 `released=True`，重复调用安全（M1 cancel 对 CANCELLED 幂等）。
        - 上游已撤销/已换代（TOKEN_REVOKED / STALE_ATTEMPT）：视为已释放终态。
        - 其他拒绝（MAINTENANCE / CORRUPT / CLOCK_ROLLBACK / UNKNOWN_ATTEMPT ...）：
          抛出 `M1ReleaseError` 并记录 `release_error`，**不得**伪装成释放成功。
        """
        if self.submitted:
            return
        if self.released:
            return
        try:
            self.consumer.cancel(self.attempt)
        except GenerationDenied as exc:
            if exc.m1_code in _IDEMPOTENT_RELEASE:
                self.released = True
                return
            self.release_error = exc.m1_code
            raise M1ReleaseError(exc.m1_code) from None
        self.released = True


def open_session(
    consumer: M1GenerationConsumer,
    *,
    page_id: str,
    request_id: str,
    amount: int,
    c1,
    c2,
    size: tuple[int, int],
    image: bytes,
    final_messages,
) -> M1PageSession:
    """Gate → 独立 attempt；同一 request_id 的重试会拿回同一分配。"""
    attempt = consumer.begin(
        page_id=page_id,
        request_id=request_id,
        amount=amount,
        c1=c1,
        c2=c2,
        size=size,
        image=image,
        final_messages=final_messages,
    )
    return M1PageSession(consumer=consumer, attempt=attempt)
