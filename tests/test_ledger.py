import json

from joh.client import MockClient
from joh.ledger import GENESIS, Ledger, LedgeredClient


def fill(path, n=3, **kw):
    lg = Ledger(path, **kw)
    c = LedgeredClient(MockClient(), lg, kind="t")
    for i in range(n):
        c.systemone(f"state {i}", {"q": {"type": "noul", "instructions": "x?"}})
    return lg


def test_chain_verifies_and_records_missing_reasoning(tmp_path):
    lg = fill(tmp_path / "l.jsonl")
    ok, idx, _ = lg.verify()
    assert ok and idx is None
    es = lg.entries()
    assert es[0]["prev_hash"] == GENESIS
    assert all(e["reasoning_steps"] == "not_available" for e in es)
    assert es[1]["prev_hash"] == es[0]["entry_hash"]


def test_tampering_is_detected(tmp_path):
    p = tmp_path / "l.jsonl"
    lg = fill(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["response"]["answers"]["q"]["noul"] = 0.999
    lines[1] = json.dumps(e, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, idx, msg = lg.verify()
    assert not ok and idx == 1 and "改动" in msg


def test_deletion_breaks_chain(tmp_path):
    p = tmp_path / "l.jsonl"
    lg = fill(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    ok, idx, msg = lg.verify()
    assert not ok and idx == 1 and "断链" in msg


def test_merkle_root_changes_with_content(tmp_path):
    a = fill(tmp_path / "a.jsonl", 3)
    r1 = a.merkle_root()
    assert len(r1) == 64 and r1 == a.merkle_root()
    LedgeredClient(MockClient(), a).systemone("more", {"q": {"type": "noul", "instructions": "x?"}})
    assert a.merkle_root() != r1


def test_hash_only_mode_stores_no_state(tmp_path):
    lg = fill(tmp_path / "h.jsonl", 1, store_payload=False)
    e = lg.entries()[0]
    assert e["request"] is None and len(e["state_sha256"]) == 64
    assert lg.verify()[0]
