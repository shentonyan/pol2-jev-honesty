"""裁判自身的诚实：蜕变测试（metamorphic testing）。

「内在一致性」首先要求在裁判身上成立。对同一 state 与同一判断，做只改变形式、
不改变语义的变换，再把答案映射回原始标签空间，比较差异。

结构性变换（无偏裁判应严格不变）：
  repeat         原样重跑：测量运行间噪声底线（noise floor）
  shuffle        choice 选项顺序置换
  relabel        choice 选项键名改为 A/B/C…（键名本身就是返回值，可能带语义偏置）
  reverse        score 量表方向反转（映射回：score' → (L-1) - score）
  permute_state  state 对象字段顺序反转（递归）
语义性变换（需要人工撰写的对应版本；离线 mock 不理解语言，按设计无法通过）：
  lang           换用另一种语言的 instructions/criteria
  negate         noul 使用人工撰写的否定问句，期望 noul' ≈ 1 - noul
"""
from __future__ import annotations

import random
from typing import Any, Callable

from .probes import Probe

STRUCTURAL = ("repeat", "shuffle", "relabel", "reverse", "permute_state")
SEMANTIC = ("lang", "negate")


def _perm(n: int, seed: str) -> list[int]:
    idx = list(range(n))
    rng = random.Random(seed)
    for _ in range(10):
        rng.shuffle(idx)
        if n < 2 or idx != list(range(n)):
            break
    return idx


def _reverse_state(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _reverse_state(x[k]) for k in reversed(list(x.keys()))}
    if isinstance(x, list):
        return [_reverse_state(v) for v in x]
    return x


# 规范形式：choice/score → 原始顺序下的概率列表；noul → 标量
def canonical(q: dict, a: dict) -> dict:
    t = q["type"]
    if t == "noul":
        return {"type": t, "noul": float(a["noul"])}
    if t == "choice":
        keys = list(q["criteria"].keys())
        return {"type": t, "probs": [float(a["probabilities"].get(k, 0.0)) for k in keys]}
    n = len(q["criteria"])
    return {
        "type": t,
        "probs": [float(a["probabilities"].get(str(i), 0.0)) for i in range(n)],
        "score": float(a["score"]),
        "levels": n,
    }


def delta(c0: dict, c1: dict) -> dict:
    if c0["type"] == "noul":
        return {"delta": abs(c0["noul"] - c1["noul"])}
    tvd = 0.5 * sum(abs(p - q) for p, q in zip(c0["probs"], c1["probs"]))
    out = {"delta": tvd}
    if c0["type"] == "score":
        out["score_delta_norm"] = abs(c0["score"] - c1["score"]) / (c0["levels"] - 1)
    return out


def brief(c: dict) -> Any:
    """便于人读的值：noul → 概率；score → 分数；choice → 概率列表（原始顺序）。"""
    if c["type"] == "noul":
        return round(c["noul"], 4)
    if c["type"] == "score":
        return round(c["score"], 4)
    return [round(p, 4) for p in c["probs"]]


Mapper = Callable[[dict], dict]


def transform(
    name: str, questions: dict, state: Any, probe: Probe, lang: str, seed: str = "mm"
) -> tuple[dict, Any, dict[str, Mapper]]:
    """返回 (变换后的 questions, 变换后的 state, {qid: 把变换空间答案映射为原始规范形式的函数})。
    某题不适用该变换时不出现在返回的 questions 中。"""
    qs: dict[str, dict] = {}
    mappers: dict[str, Mapper] = {}

    if name == "repeat":
        for qid, q in questions.items():
            qs[qid] = q
            mappers[qid] = lambda a, q=q: canonical(q, a)
        return qs, state, mappers

    if name == "permute_state":
        for qid, q in questions.items():
            qs[qid] = q
            mappers[qid] = lambda a, q=q: canonical(q, a)
        return qs, _reverse_state(state), mappers

    if name == "shuffle":
        for qid, q in questions.items():
            if q["type"] != "choice":
                continue
            keys = list(q["criteria"].keys())
            order = _perm(len(keys), f"{seed}:{qid}")
            q2 = dict(q, criteria={keys[i]: q["criteria"][keys[i]] for i in order})
            qs[qid] = q2
            mappers[qid] = lambda a, q=q: canonical(q, a)  # 键名未变，按原顺序读取即可
        return qs, state, mappers

    if name == "relabel":
        for qid, q in questions.items():
            if q["type"] != "choice":
                continue
            keys = list(q["criteria"].keys())
            labels = [chr(ord("A") + i) if i < 26 else f"O{i}" for i in range(len(keys))]
            fwd = dict(zip(keys, labels))
            q2 = dict(q, criteria={fwd[k]: q["criteria"][k] for k in keys})

            def m(a, q=q, fwd=fwd):
                probs = {k: a["probabilities"].get(lbl, 0.0) for k, lbl in fwd.items()}
                return canonical(q, {"probabilities": probs})

            qs[qid] = q2
            mappers[qid] = m
        return qs, state, mappers

    if name == "reverse":
        for qid, q in questions.items():
            if q["type"] != "score":
                continue
            n = len(q["criteria"])
            q2 = dict(q, criteria=list(reversed(q["criteria"])))

            def m(a, q=q, n=n):
                probs = {str(i): a["probabilities"].get(str(n - 1 - i), 0.0) for i in range(n)}
                return canonical(q, {"probabilities": probs, "score": (n - 1) - float(a["score"])})

            qs[qid] = q2
            mappers[qid] = m
        return qs, state, mappers

    if name == "lang":
        other = next((l for l in probe.languages if l != lang), None)
        if other is None:
            return {}, state, {}
        alt = probe.build(other)
        for qid, q in questions.items():
            if qid in alt:
                qs[qid] = alt[qid]
                mappers[qid] = lambda a, q=q: canonical(q, a)  # 键名/级数跨语言一致（load 时已校验）
        return qs, state, mappers

    if name == "negate":
        neg = probe.build(lang, variant="negated")
        for qid, q in neg.items():
            if questions.get(qid, {}).get("type") != "noul":
                continue
            qs[qid] = q
            mappers[qid] = lambda a: {"type": "noul", "noul": 1.0 - float(a["noul"])}
        return qs, state, mappers

    raise ValueError(f"未知变换 {name}")


def run_metamorphic(
    client,
    probe: Probe,
    state: Any,
    lang: str = "zh",
    transforms: tuple[str, ...] = STRUCTURAL,
    tolerance: float = 0.10,
    seed: str = "mm",
) -> dict:
    base_qs = probe.build(lang)
    base = client.systemone(state, base_qs)["answers"]
    base_c = {qid: canonical(q, base[qid]) for qid, q in base_qs.items()}

    results: dict[str, dict] = {}
    for name in transforms:
        qs, st, mappers = transform(name, base_qs, state, probe, lang, seed)
        if not qs:
            results[name] = {"applicable": False}
            continue
        ans = client.systemone(st, qs)["answers"]
        per_q = {}
        for qid in qs:
            mapped = mappers[qid](ans[qid])
            d = delta(base_c[qid], mapped)
            d["pass"] = d["delta"] <= tolerance
            d["base"] = brief(base_c[qid])
            d["variant"] = brief(mapped)  # 已映射回原始标签空间
            per_q[qid] = d
        results[name] = {
            "applicable": True,
            "max_delta": max(v["delta"] for v in per_q.values()),
            "pass": all(v["pass"] for v in per_q.values()),
            "questions": per_q,
        }

    # mock 不理解语言：语义变换在 mock 下只检查流程，不计入总体结论
    understands_language = getattr(client, "backend", "live") != "mock"
    for name, r in results.items():
        r["counts_toward_verdict"] = bool(r.get("applicable")) and (name not in SEMANTIC or understands_language)

    noise = results.get("repeat", {}).get("max_delta")
    for name, r in results.items():
        if r.get("applicable") and name != "repeat" and noise is not None:
            r["excess_over_noise"] = r["max_delta"] - noise
    return {
        "probe": f"{probe.id}@{probe.version}",
        "lang": lang,
        "tolerance": tolerance,
        "noise_floor": noise,
        "transforms": results,
        "all_pass": all(r["pass"] for r in results.values() if r["counts_toward_verdict"]),
    }


def run_metamorphic_many(
    client,
    probe: Probe,
    items: list[dict],
    lang: str = "zh",
    transforms: tuple[str, ...] = STRUCTURAL,
    tolerance: float = 0.10,
    seed: str = "mm",
) -> dict:
    """对多个 state 运行蜕变测试并聚合：每个 (变换, 问题) 的失败率、平均/最大 Δ、超出各自噪声底线的平均量。"""
    per_state = {}
    for it in items:
        per_state[it["id"]] = run_metamorphic(client, probe, it["state"], lang, transforms, tolerance, seed)

    agg: dict[str, dict] = {}
    for name in transforms:
        rows: dict[str, list[tuple[float, float | None]]] = {}
        counts = True
        for rep in per_state.values():
            r = rep["transforms"].get(name, {})
            if not r.get("applicable"):
                continue
            counts = counts and r["counts_toward_verdict"]
            for qid, d in r["questions"].items():
                rows.setdefault(qid, []).append((d["delta"], rep["noise_floor"]))
        if not rows:
            agg[name] = {"applicable": False}
            continue
        qstats = {}
        for qid, xs in rows.items():
            ds = [x for x, _ in xs]
            ex = [x - (n or 0.0) for x, n in xs]
            qstats[qid] = {
                "n": len(ds),
                "fail_rate": sum(x > tolerance for x in ds) / len(ds),
                "mean_delta": sum(ds) / len(ds),
                "max_delta": max(ds),
                "mean_excess_over_noise": sum(ex) / len(ex),
            }
        all_d = [x for xs in rows.values() for x, _ in xs]
        agg[name] = {
            "applicable": True,
            "counts_toward_verdict": counts,
            "fail_rate": sum(x > tolerance for x in all_d) / len(all_d),
            "mean_delta": sum(all_d) / len(all_d),
            "worst_question": max(qstats, key=lambda q: qstats[q]["mean_delta"]),
            "questions": qstats,
        }
    noises = [r["noise_floor"] for r in per_state.values() if r["noise_floor"] is not None]
    return {
        "probe": f"{probe.id}@{probe.version}",
        "lang": lang,
        "tolerance": tolerance,
        "n_states": len(items),
        "noise_floor_mean": sum(noises) / len(noises) if noises else None,
        "noise_floor_max": max(noises) if noises else None,
        "aggregate": agg,
        "per_state": per_state,
    }
