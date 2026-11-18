"""离线 M1 装配：真实 Gate + Authority + Fences + C1/C2/Sidecar/原图 fixture。

只用于测试。全部身份、密钥、Token、资产均在临时目录内生成，测试结束即删除；
不连接网络、不调用真实模型、不产生真实费用。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

from orchestrator.services.integration_reference import Authority, OfflineKMS  # noqa: E402
from orchestrator.services.vision_supervisor.gate import Gate  # noqa: E402
from orchestrator.services.vision_supervisor.shared import SharedFences  # noqa: E402
from orchestrator.services.vision_supervisor.supervisor import Snapshot  # noqa: E402

from orchestrator.vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer  # noqa: E402

BOOK = "book01"
IMAGE = b"\x89PNG\r\n\x1a\n" + bytes(range(64)) * 4
SIZE = (96, 128)


def page_id(page_no: int) -> str:
    return f"{BOOK}_p{page_no:02d}"


def _c1_document(page: str, page_no: int, *, text: str = "小熊在森林里慢慢散步。") -> dict:
    return {
        "schema_version": "1.0",
        "book_id": BOOK,
        "page_id": page,
        "page_no": page_no,
        "status": "ok",
        "image_width": SIZE[0],
        "image_height": SIZE[1],
        "text_blocks": [
            {
                "block_id": f"{page}_t01",
                "order": 1,
                "text": text,
                "bbox": [4, 8, 80, 40],
                "confidence": 0.93,
            }
        ],
        "page_confidence": 0.93,
        "elapsed_ms": 7,
    }


def _c2_document(page: str, page_no: int, *, description: str = "一只棕色小熊站在树边。") -> dict:
    return {
        "schema_version": "1.0",
        "book_id": BOOK,
        "page_id": page,
        "page_no": page_no,
        "status": "ok",
        "image_width": SIZE[0],
        "image_height": SIZE[1],
        "description": description,
        "objects": [
            {
                "object_id": f"{page}_o01",
                "label": "小熊",
                "bbox": [10, 12, 60, 90],
                "confidence": 0.88,
            }
        ],
        "scene_tags": ["森林"],
        "safety": {"pass": True, "flags": []},
        "elapsed_ms": 9,
    }


def _snapshots(identity, page_no: int) -> tuple[Snapshot, Snapshot]:
    page = identity.page_id
    c1raw = json.dumps(_c1_document(page, page_no), ensure_ascii=False, separators=(",", ":")).encode()
    c2doc = _c2_document(page, page_no)
    c2raw = json.dumps(c2doc, ensure_ascii=False, separators=(",", ":")).encode()
    refs = dict(asdict(identity))
    refs.update(
        {
            "schema_version": "vision_refs/0.1",
            "c2": {
                "asset_id": "fixture-c2",
                "schema_version": "1.0",
                "relative_path": f"json/{page}_vlm.json",
                "sha256": hashlib.sha256(c2raw).hexdigest(),
            },
            "source": {
                "component_mode": "fixture",
                "model_ref": "fixture-vlm",
                "prompt_sha256": "a" * 64,
                "evidence_ref": "offline",
            },
            "observations": [],
        }
    )
    sidecar = json.dumps(refs, ensure_ascii=False, separators=(",", ":")).encode()
    image_sha = hashlib.sha256(IMAGE).hexdigest()
    c1 = Snapshot(
        replace(identity, attempt_id="ocr", fencing_token="ocr-token"),
        "fixture",
        {"c1": c1raw},
        image_sha256=image_sha,
        c1_sha256=hashlib.sha256(c1raw).hexdigest(),
    )
    c2 = Snapshot(identity, "fixture", {"c2": c2raw, "sidecar": sidecar}, image_sha256=image_sha)
    return c1, c2


@dataclass
class PageFixture:
    page_no: int
    page_id: str
    record: object
    identity: object
    c1: Snapshot
    c2: Snapshot


@dataclass
class Rig:
    authority: Authority
    keys: OfflineKMS
    clock: list
    fences: Fences
    gate: Gate
    service_token: str
    db_path: Path
    anchor_path: Path
    pages: dict = field(default_factory=dict)

    @property
    def image(self) -> bytes:
        return IMAGE

    def page(self, page_no: int = 3) -> PageFixture:
        """在同一 Authority 上为另一页建立 SharedFences 生命周期与输入快照。"""
        if page_no in self.pages:
            return self.pages[page_no]
        page = page_id(page_no)
        record, _ = self.fences.begin(f"job-offline-{page_no}", page)
        if record.identity is None:
            identity = self.fences.attempt(record)
            # reserve_stage 是 M1 侧把 identity 持久化为 Current 的唯一入口
            self.authority.reserve_stage(identity, "vlm", "m3-offline-fixture")
        else:
            # 重启/恢复：直接使用 SQLite 中已持久化的 Current identity，不重新签发
            identity = record.identity
        c1, c2 = _snapshots(identity, page_no)
        node = PageFixture(page_no, page, record, identity, c1, c2)
        self.pages[page_no] = node
        return node

    def consumer_for(self, page_no: int = 3, *, service_token: str | None = None) -> M1GenerationConsumer:
        node = self.page(page_no)
        return M1GenerationConsumer(
            self.authority,
            self.gate,
            self.fences,
            node.record,
            service_token=service_token or self.service_token,
        )

    # 兼容默认页的旧用法
    def consumer(self, *, service_token: str | None = None) -> M1GenerationConsumer:
        return self.consumer_for(3, service_token=service_token)

    def reopen(self) -> "Rig":
        """模拟 M1 服务重启：同一 SQLite + 同一 anchor + 同一离线密钥根。"""
        authority = Authority(
            self.db_path, self.anchor_path, self.keys, lambda: self.clock[0], offline_test=True
        )
        return replace(
            self, authority=authority, gate=Gate({"fixture"}), fences=SharedFences(authority), pages={}
        )


def make_rig(root: Path, *, clock_start: int = 1000, service_ttl: int = 300, page_no: int = 3) -> Rig:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    clock = [clock_start]
    keys = OfflineKMS(seed=b"m3-m1-offline-integration-fixture-seed")
    authority = Authority.provision(
        root / "authority.sqlite", root / "retained.anchor", keys, lambda: clock[0], offline_test=True
    )
    authority.provision_project("M1")
    authority.grant("M3", "M1", "generate")
    authority.grant("M3", "M1", "assets.read")

    fences = SharedFences(authority)
    gate = Gate({"fixture"})
    service_token = authority.service_token("M3", ttl=service_ttl)
    rig = Rig(
        authority=authority,
        keys=keys,
        clock=clock,
        fences=fences,
        gate=gate,
        service_token=service_token,
        db_path=root / "authority.sqlite",
        anchor_path=root / "retained.anchor",
    )
    rig.page(page_no)
    return rig


def begin(
    rig: Rig,
    *,
    page_no: int = 3,
    request: str = "req-1",
    amount: int = 1000,
    consumer: M1GenerationConsumer | None = None,
):
    """走一次 Gate → Generation Attempt 分配。"""
    node = rig.page(page_no)
    consumer = consumer or rig.consumer_for(page_no)
    return consumer.begin(
        page_id=node.page_id,
        request_id=request,
        amount=amount,
        c1=node.c1,
        c2=node.c2,
        size=SIZE,
        image=IMAGE,
        final_messages=[{"role": "user", "content": "为这一页生成儿童故事"}],
    )


def result_payload(inputs: dict, *, text: str | None = None) -> bytes:
    """确定性的“生成结果”：消费已授权输入后产出的候选故事 JSON。"""
    c1 = json.loads(inputs["c1.json"])
    body = text or (c1["text_blocks"][0]["text"] if c1["text_blocks"] else "")
    doc = {
        "schema": "m3-generation-candidate/0.1",
        "page_id": c1["page_id"],
        "narration": body,
        "source_mode": "fixture",
    }
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
