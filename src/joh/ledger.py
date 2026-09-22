"""公共判决账本：每次调用追加一条 JSONL 记录，哈希链串联，可计算 Merkle root 以便定期上链锚定。

对应 PoL2 第 7 章第五条「可验证决策链路（数据源、推理步骤、伦理依据）」：
  数据源   = state（或其哈希）
  伦理依据 = criteria 文本（探针文件中注明 pol_ref）
  推理步骤 = Jev 不提供 → reasoning_steps 如实记为 "not_available"
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(obj: Any) -> str:
    s = obj if isinstance(obj, str) else canon(obj)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: str | Path, store_payload: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store_payload = store_payload

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _last_hash(self) -> str:
        es = self.entries()
        return es[-1]["entry_hash"] if es else GENESIS

    def append(self, kind: str, request: dict, response: dict, meta: dict | None = None) -> dict:
        qs = request.get("questions", {})
        entry = {
            "seq": len(self.entries()),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "meta": meta or {},
            "model_alias": request.get("model"),
            "request_sha256": sha256(request),
            "state_sha256": sha256(request.get("state")),
            "criteria_sha256": {qid: sha256({k: q.get(k) for k in ("type", "instructions", "criteria")}) for qid, q in qs.items()},
            "request": request if self.store_payload else None,
            "response": response,
            "reasoning_steps": "not_available",
            "prev_hash": self._last_hash(),
        }
        entry["entry_hash"] = sha256({k: v for k, v in entry.items() if k != "entry_hash"})
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def verify(self) -> tuple[bool, int | None, str]:
        prev = GENESIS
        for i, e in enumerate(self.entries()):
            if e.get("prev_hash") != prev:
                return False, i, "prev_hash 断链"
            recomputed = sha256({k: v for k, v in e.items() if k != "entry_hash"})
            if recomputed != e.get("entry_hash"):
                return False, i, "entry_hash 与内容不符（记录被改动）"
            if e.get("request") is not None and sha256(e["request"]) != e["request_sha256"]:
                return False, i, "request 与 request_sha256 不符"
            prev = e["entry_hash"]
        return True, None, "ok"

    def merkle_root(self) -> str:
        level = [e["entry_hash"] for e in self.entries()]
        if not level:
            return GENESIS
        while len(level) > 1:
            if len(level) % 2:
                level.append(level[-1])
            level = [hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).hexdigest() for a, b in zip(level[::2], level[1::2])]
        return level[0]


class LedgeredClient:
    """包装任意 client：每次 systemone 调用都写入账本。"""

    def __init__(self, client, ledger: Ledger, kind: str = "call", meta: dict | None = None):
        self.client = client
        self.ledger = ledger
        self.kind = kind
        self.meta = meta or {}
        self.backend = getattr(client, "backend", "unknown")
        self.model = getattr(client, "model", "unknown")

    def models(self):
        return self.client.models()

    def systemone(self, state, questions):
        resp = self.client.systemone(state, questions)
        request = {"model": self.model, "state": state, "questions": questions}
        self.ledger.append(self.kind, request, resp, dict(self.meta, backend=self.backend))
        return resp
