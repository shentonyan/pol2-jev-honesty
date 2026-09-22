"""漂移哨兵：`openjev` 是浮动别名，会静默跟随最新 Jev。
用固定金标集（canary set）建立基线，之后定期重跑，按 JS 散度公开报告分布漂移。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compose import dimension_value
from .metamorphic import canonical
from .probes import Probe


def load_canary(path: str | Path) -> list[dict]:
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    items: list[dict] = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        items.extend(d if isinstance(d, list) else [d])
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("canary 条目 id 重复")
    return items


def js_divergence(p: list[float], q: list[float]) -> float:
    """Jensen–Shannon 散度，以 2 为底，取值 [0, 1]。"""
    def kl(a, b):
        return sum(x * math.log2(x / y) for x, y in zip(a, b) if x > 0)
    sp, sq = sum(p) or 1.0, sum(q) or 1.0
    p = [x / sp for x in p]
    q = [x / sq for x in q]
    m = [(x + y) / 2 for x, y in zip(p, q)]
    return max(0.0, 0.5 * kl(p, m) + 0.5 * kl(q, m))


def as_dist(c: dict) -> list[float]:
    if c["type"] == "noul":
        return [1.0 - c["noul"], c["noul"]]
    return c["probs"]


def snapshot(client, probe: Probe, items: list[dict], lang: str = "zh") -> dict:
    qs = probe.build(lang)
    out = {}
    for it in items:
        ans = client.systemone(it["state"], qs)["answers"]
        out[it["id"]] = {qid: canonical(q, ans[qid]) for qid, q in qs.items()}
    return {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": getattr(client, "backend", "unknown"),
        "model_alias": getattr(client, "model", "unknown"),
        "probe": f"{probe.id}@{probe.version}",
        "lang": lang,
        "items": out,
    }


def compare(baseline: dict, current: dict, threshold: float = 0.05) -> dict:
    rows = []
    for iid, qs in baseline["items"].items():
        cur = current["items"].get(iid)
        if cur is None:
            continue
        for qid, c0 in qs.items():
            if qid not in cur:
                continue
            rows.append({"item": iid, "question": qid, "js": js_divergence(as_dist(c0), as_dist(cur[qid]))})
    js = [r["js"] for r in rows]
    return {
        "baseline_created": baseline["created"],
        "current_created": current["created"],
        "probe_match": baseline["probe"] == current["probe"],
        "threshold": threshold,
        "n": len(rows),
        "mean_js": sum(js) / len(js) if js else 0.0,
        "max_js": max(js) if js else 0.0,
        "drifted": sorted([r for r in rows if r["js"] > threshold], key=lambda r: -r["js"]),
        "drift_detected": any(x > threshold for x in js),
    }


def gold_agreement(probe: Probe, snap: dict, items: list[dict], lang: str = "zh") -> dict:
    """金标（合成样本上的人工预期：诚实朝向的 0/1）与读数的一致率。仅用于校准阈值，不是准确率声明。"""
    hits, total, per_q = 0, 0, {}
    for it in items:
        for qid, g in (it.get("gold") or {}).items():
            c = snap["items"].get(it["id"], {}).get(qid)
            if c is None or qid not in probe.questions:
                continue
            q = probe.questions[qid]
            ans = _answer_from_canonical(q, c)
            v = dimension_value(q, ans, q[lang].get("criteria"))["value"]
            if v is None:
                continue
            ok = abs(v - g) < 0.5
            hits += ok
            total += 1
            s = per_q.setdefault(qid, [0, 0])
            s[0] += ok
            s[1] += 1
    return {"agreement": hits / total if total else None, "n": total, "per_question": {k: v[0] / v[1] for k, v in per_q.items()}}


def _answer_from_canonical(q: dict, c: dict) -> dict[str, Any]:
    if c["type"] == "noul":
        return {"noul": c["noul"]}
    if c["type"] == "score":
        return {"score": c["score"]}
    keys = list(q["zh"]["criteria"].keys()) if "zh" in q else list(q["en"]["criteria"].keys())
    return {"probabilities": dict(zip(keys, c["probs"]))}
