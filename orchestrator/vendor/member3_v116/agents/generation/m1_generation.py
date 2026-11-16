"""M3 侧消费 M1 离线 Generation Attempt 的接入层。

契约状态：Generation Contract V1.0 仍是 **DRAFT，未激活**。本模块只接入 M1 的
离线参考实现（`orchestrator.services.integration_reference`）中的
`bridge.begin_from_gate()`，不声明任何正式 Generation HTTP 接口。

职责边界（与 M1 文档一致）：

* M3 只拿到 M1 配置的 service token、以及 M1 分配的 attempt token / identity；
* M3 不签发、不改写任何 token，不调用 provision / grant / put_asset / settle；
* M3 不结算预算：submit 只是“候选结果接收”，真正扣费由 M1 可信账单适配器
  `Authority.settle()` 完成，本模块**没有**、也不应出现 settle 方法；
* 上游身份与 lineage（job_id / page_id / generation_id / input_revision /
  epoch）原样保留在 attempt 上，M3 不重造上游 Identity。

状态语义（来自 M1 参考库）：RESERVED 可读/可提交；submit 后预留转入 UNKNOWN
并继续占用预算；服务重启后 recover 把 SUBMITTED 标为 UNKNOWN，禁止自动重发；
只有 M1 可信结算后才 DONE。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .errors import AppError, ErrorCode

__all__ = [
    "GenerationAttempt",
    "GenerationDenied",
    "M1KitUnavailable",
    "M1GenerationConsumer",
    "TERMINAL_DENIALS",
]

#: 这些拒绝说明当前 attempt/token 已经不能继续工作，调用方必须停止并去
#: 查询 / 恢复 / 对账，而不是换一个幂等键重试制造新账户。
TERMINAL_DENIALS = frozenset(
    {
        "TOKEN_EXPIRED",
        "TOKEN_REVOKED",
        "TOKEN_KIND",
        "TOKEN_KEY_MISMATCH",
        "FORBIDDEN",
        "SERVICE_MISMATCH",
        "STALE_ATTEMPT",
        "FENCING_MISMATCH",
        "ATTEMPT_UNRESOLVED",
        "ATTEMPT_SUBMITTED",
        "ATTEMPT_UNKNOWN",
        "ATTEMPT_DONE",
        "UNKNOWN_RETAINS_BUDGET",
        "UNKNOWN_ATTEMPT",
        "BUDGET_EXHAUSTED",
        "IDEMPOTENCY_CONFLICT",
        "ASSET_FORBIDDEN",
        "ASSET_VERSION",
        "UNKNOWN_ASSET",
        "UNPROVISIONED",
        "PRODUCTION_BLOCKED",
        "PROVIDER_BLOCKED",
        "CLOCK_ROLLBACK",
        "ROLLBACK_DETECTED",
        "MAINTENANCE",
        "CORRUPT",
    }
)

_INVALID = frozenset(
    {
        "INVALID_AMOUNT",
        "INVALID_REQUEST",
        "INVALID_PROMPT",
        "INVALID_LINEAGE",
        "INVALID_RESULT",
        "INVALID_ASSET",
        "INVALID_PATH",
        "INVALID_SUBJECT",
        "INVALID_PROJECT",
        "INVALID_GRANT",
        "INVALID_SETTLEMENT",
        "MALFORMED",
        "MALFORMED_PROVENANCE",
    }
)


class M1KitUnavailable(RuntimeError):
    """离线接入包不在当前解释器路径里。"""


class GenerationDenied(AppError):
    """M1 拒绝了一次 Generation 操作。

    保留 M1 的原始拒绝码（``m1_code``），同时给出 M3 契约错误码：
    参数/路径类映射为 ``1002``，其余鉴权/预算/幂等类映射为 ``1005``。
    所有 M1 拒绝都是终止性的：M3 不得换键重试。
    """

    def __init__(self, m1_code: str, detail: str | None = None):
        self.m1_code = m1_code
        self.terminal = True
        code = ErrorCode.INVALID_PARAM if m1_code in _INVALID else ErrorCode.UNAUTHORIZED
        super().__init__(code, f"生成授权被拒绝：{m1_code}", detail=detail)

    def __str__(self) -> str:  # pragma: no cover - 便于日志
        return self.m1_code


@dataclass(frozen=True)
class GenerationAttempt:
    """M1 分配的一次独立 Generation attempt（M3 只读视图）。"""

    request_id: str
    page_id: str
    amount: int
    attempt_id: str
    token: str
    identity: Mapping[str, Any]
    assets: tuple[str, ...]
    result_sha256: str | None = None

    # ---- lineage（上游身份原样保留，M3 不重造） ----
    @property
    def job_id(self) -> str:
        return str(self.identity["job_id"])

    @property
    def generation_id(self) -> str:
        return str(self.identity["generation_id"])

    @property
    def input_revision(self) -> int:
        return int(self.identity["input_revision"])

    @property
    def epoch(self) -> int:
        return int(self.identity["epoch"])

    @property
    def lineage(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "page_id": self.page_id,
            "generation_id": self.generation_id,
            "input_revision": self.input_revision,
            "epoch": self.epoch,
        }

    @property
    def submitted(self) -> bool:
        return self.result_sha256 is not None


def _require_amount(amount: object) -> int:
    if type(amount) is not int or not 1 <= amount <= 15000:
        raise GenerationDenied("INVALID_AMOUNT", "amount 必须是 1..15000 的整数 minor units")
    return amount


def _load_kit():
    try:
        from orchestrator.services.integration_reference import Denied
        from orchestrator.services.integration_reference.bridge import begin_from_gate
        from orchestrator.services.vision_supervisor.supervisor import Cancelled
    except Exception as exc:  # noqa: BLE001 - 报告为环境缺失而不是业务拒绝
        raise M1KitUnavailable(
            "M1 offline integration kit is not importable; add m1_kit_extract to sys.path"
        ) from exc
    return Denied, Cancelled, begin_from_gate


class M1GenerationConsumer:
    """把 M1 Gate 之后的 Generation 分配、读资产、提交结果封装成 M3 可用接口。"""

    def __init__(self, authority, gate, fences, record, *, service_token: str, project: str = "M1"):
        if not isinstance(service_token, str) or not service_token:
            raise GenerationDenied("SERVICE_MISMATCH", "service token 缺失")
        self.authority = authority
        self.gate = gate
        self.fences = fences
        self.record = record
        self.service_token = service_token
        self.project = project

    # ------------------------------------------------------------------ begin
    def _asset_prefix(self) -> str:
        """Gate 桥接按**上游** identity 的 generation/attempt 写入资产。"""
        upstream = getattr(self.record, "identity", None)
        generation_id = getattr(upstream, "generation_id", None)
        attempt_id = getattr(upstream, "attempt_id", None)
        if not generation_id or not attempt_id:
            raise GenerationDenied("UPSTREAM_LINEAGE", "缺少上游 Gate identity")
        return f"upstream/{generation_id}/{attempt_id}"

    def begin(
        self,
        *,
        page_id: str,
        request_id: str,
        amount: int,
        c1,
        c2,
        size: tuple[int, int],
        image: bytes,
        final_messages: Sequence[Mapping[str, str]],
    ) -> GenerationAttempt:
        """走 M1 Gate 后分配一个独立 attempt；同一 request_id + 同参数幂等。"""
        _require_amount(amount)
        if not isinstance(request_id, str) or not request_id:
            raise GenerationDenied("INVALID_REQUEST", "request_id 不能为空")
        if type(image) is not bytes or not image:
            raise GenerationDenied("IMAGE_BINDING", "必须提供不可变原图 bytes")
        if not final_messages:
            raise GenerationDenied("INVALID_PROMPT", "final_messages 不能为空")

        Denied, Cancelled, begin_from_gate = _load_kit()
        try:
            response = begin_from_gate(
                self.authority,
                self.gate,
                self.record,
                self.fences,
                c1,
                c2,
                size,
                project=self.project,
                request_id=request_id,
                amount=amount,
                image=image,
                final_messages=list(final_messages),
                service=self.service_token,
            )
        except Cancelled:
            raise GenerationDenied('STALE_ATTEMPT', '上游 Generation 已被取消或换代') from None
        except Denied as exc:
            raise GenerationDenied(str(exc)) from None

        identity = response.get("identity")
        token = response.get("token")
        if type(identity) is not dict or type(token) is not str:
            raise GenerationDenied("MALFORMED", "M1 返回的分配缺 identity/token")
        if identity.get("page_id") != page_id:
            raise GenerationDenied("UPSTREAM_LINEAGE", "M1 身份 page_id 与请求不一致")
        for key in ("job_id", "page_id", "generation_id", "input_revision", "epoch",
                    "attempt_id", "fencing_token"):
            if key not in identity:
                raise GenerationDenied("UPSTREAM_LINEAGE", f"M1 身份缺字段 {key}")

        prefix = self._asset_prefix()
        assets = (
            f"{prefix}/c1.json",
            f"{prefix}/c2.json",
            f"{prefix}/sidecar.json",
            f"{prefix}/image.bin",
        )
        return GenerationAttempt(
            request_id=request_id,
            page_id=page_id,
            amount=amount,
            attempt_id=str(identity["attempt_id"]),
            token=token,
            identity=dict(identity),
            assets=assets,
        )

    # ------------------------------------------------------------------- read
    def read_asset(self, attempt: GenerationAttempt, name: str) -> bytes:
        """按授权读取一个精确版本资产；名字必须是 attempt 绑定的四个输入之一。"""
        Denied, Cancelled, _ = _load_kit()
        try:
            return self.authority.read(
                self.service_token, attempt.token, dict(attempt.identity), name
            )
        except Cancelled:
            raise GenerationDenied('STALE_ATTEMPT', '上游 Generation 已被取消或换代') from None
        except Denied as exc:
            raise GenerationDenied(str(exc)) from None

    def read_inputs(self, attempt: GenerationAttempt) -> dict[str, bytes]:
        """读取 Gate 桥接写入的 c1 / c2 / sidecar / image（全部离线 BLOB）。"""
        return {name.rsplit("/", 1)[-1]: self.read_asset(attempt, name) for name in attempt.assets}

    # ----------------------------------------------------------------- submit
    def submit(self, attempt: GenerationAttempt, payload: bytes) -> GenerationAttempt:
        """提交候选结果摘要；重复提交同内容幂等，内容变化被拒绝。"""
        if type(payload) is not bytes:
            raise GenerationDenied("INVALID_RESULT", "结果必须是 bytes")
        Denied, Cancelled, _ = _load_kit()
        try:
            digest = self.authority.submit(
                self.service_token, attempt.token, dict(attempt.identity), payload
            )
        except Cancelled:
            raise GenerationDenied('STALE_ATTEMPT', '上游 Generation 已被取消或换代') from None
        except Denied as exc:
            raise GenerationDenied(str(exc)) from None
        return dataclasses.replace(attempt, result_sha256=digest)

    def run(self, attempt: GenerationAttempt, producer: Callable[[dict[str, bytes]], bytes]) -> GenerationAttempt:
        """读授权输入 → 生成候选结果 → 提交。M3 的生成入口只看到已授权输入。"""
        inputs = self.read_inputs(attempt)
        payload = producer(inputs)
        if type(payload) is not bytes:
            raise GenerationDenied("INVALID_RESULT", "producer 必须返回 bytes")
        return self.submit(attempt, payload)

    # ----------------------------------------------------------------- cancel
    def cancel(self, attempt: GenerationAttempt) -> None:
        """仅释放尚未 submit 的 RESERVED；已提交的预留只能由 M1 账单对账。"""
        Denied, Cancelled, _ = _load_kit()
        try:
            self.authority.cancel(attempt.attempt_id)
        except Cancelled:
            raise GenerationDenied('STALE_ATTEMPT', '上游 Generation 已被取消或换代') from None
        except Denied as exc:
            raise GenerationDenied(str(exc)) from None

    # ----------------------------------------------------------------- totals
    def totals(self) -> dict[str, int]:
        """只读查看项目账本（spent / held / available），不触发任何预留。"""
        return dict(self.authority.totals())
