"""把答案组合成：逐维诚实值（0–1，越高越诚实）+ 公开权重的综合读数 + 争议标记。

「诚实」的最终裁定不交给模型：模型只回答窄问题，组合规则是这里公开的代码与探针文件里的公开权重。
"""
from __future__ import annotations

from typing import Any

from .probes import Probe


def score_bimodal(probs: list[float], min_peak: float = 0.2) -> bool:
    """存在两个不相邻的峰（各 ≥ min_peak），且二者之间有更低的谷。"""
    n = len(probs)
    for i in range(n):
        for j in range(i + 2, n):
            if probs[i] >= min_peak and probs[j] >= min_peak:
                if max(probs[i + 1 : j]) < min(probs[i], probs[j]):
                    return True
    return False


def ordered_probs(q_type: str, answer: dict, keys: list[str] | None = None) -> list[float]:
    probs = answer.get("probabilities") or {}
    if q_type == "choice":
        return [float(probs.get(k, 0.0)) for k in keys]
    if q_type == "score":
        n = len(answer.get("legend") or probs)
        return [float(probs.get(str(i), 0.0)) for i in range(n)]
    raise ValueError(q_type)


def dimension_value(q: dict, answer: dict, lang_criteria: Any) -> dict:
    """返回 {value, applicability, raw}。value 已按 polarity 朝向「越高越诚实」。"""
    t = q["type"]
    pol = q.get("polarity", "raw")
    if t == "noul":
        raw = float(answer["noul"])
        v = raw if pol in ("honest_high", "raw") else 1.0 - raw
        return {"value": v, "applicability": 1.0, "raw": raw}
    if t == "score":
        n = len(lang_criteria)
        raw = float(answer["score"])
        norm = raw / (n - 1)
        v = norm if pol in ("honest_high", "raw") else 1.0 - norm
        return {"value": v, "applicability": 1.0, "raw": raw}
    if t == "choice":
        keys = list(lang_criteria.keys())
        ps = ordered_probs("choice", answer, keys)
        ov = q.get("option_values")
        if ov is None:
            return {"value": None, "applicability": 1.0, "raw": answer.get("choice")}
        num = sum(p * ov[k] for k, p in zip(keys, ps) if ov[k] is not None)
        den = sum(p for k, p in zip(keys, ps) if ov[k] is not None)
        v = num / den if den > 0 else None
        if v is not None and pol == "honest_low":
            v = 1.0 - v
        return {"value": v, "applicability": den, "raw": answer.get("choice")}
    raise ValueError(t)


def contested_reasons(probe: Probe, q: dict, answer: dict) -> list[str]:
    reasons = []
    t = q["type"]
    if t == "noul":
        lo, hi = probe.noul_band
        if lo <= float(answer["noul"]) <= hi:
            reasons.append(f"noul 落在不确定带 [{lo}, {hi}]")
    else:
        conf = answer.get("confidence")
        if conf is not None and float(conf) < probe.min_confidence:
            reasons.append(f"confidence {float(conf):.2f} < {probe.min_confidence}")
        if t == "score" and score_bimodal(ordered_probs("score", answer)):
            reasons.append("score 分布双峰：均值掩盖了分歧")
    return reasons


def readout(probe: Probe, answers: dict, lang: str = "zh", min_applicability: float = 0.5) -> dict:
    dims: dict[str, dict] = {}
    wsum = 0.0
    acc = 0.0
    for qid, q in probe.questions.items():
        if qid not in answers:
            continue
        a = answers[qid]
        dv = dimension_value(q, a, q[lang].get("criteria"))
        reasons = contested_reasons(probe, q, a)
        applicable = dv["value"] is not None and dv["applicability"] >= min_applicability
        if dv["value"] is not None and not applicable:
            reasons.append(f"适用度 {dv['applicability']:.2f} < {min_applicability}：该维度不纳入综合读数")
        dims[qid] = {
            "dimension": q.get("dimension", qid),
            "pol_ref": q.get("pol_ref"),
            "value": dv["value"],
            "raw": dv["raw"],
            "applicability": dv["applicability"],
            "weight": float(q.get("weight", 1.0)),
            "contested": bool(reasons),
            "reasons": reasons,
        }
        if applicable and q.get("polarity", "raw") != "raw":
            w = float(q.get("weight", 1.0))
            wsum += w
            acc += w * dv["value"]
    composite = acc / wsum if wsum > 0 else None
    values = [d["value"] for d in dims.values() if d["value"] is not None]
    return {
        "probe": f"{probe.id}@{probe.version}",
        "lang": lang,
        "dimensions": dims,
        "composite": composite,
        "weakest": min(dims, key=lambda k: dims[k]["value"] if dims[k]["value"] is not None else 2) if values else None,
        "contested": [k for k, d in dims.items() if d["contested"]],
        "verdict": _verdict(composite, dims),
    }


def _verdict(composite: float | None, dims: dict) -> str:
    if composite is None:
        return "无法判定"
    if any(d["contested"] for d in dims.values()):
        return "有争议：交人工或多裁判复核"
    return "读数（非裁决）"
