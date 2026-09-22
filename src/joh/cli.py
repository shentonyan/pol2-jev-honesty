"""命令行入口：python -m joh <命令>。所有结果写入 runs/，每次 API 调用写入账本。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import HONESTY_CLAUSE, __version__
from .client import JevError, MockClient, load_dotenv, make_client
from .compose import readout
from .drift import compare, gold_agreement, load_canary, snapshot
from .ledger import Ledger, LedgeredClient
from .metamorphic import SEMANTIC, STRUCTURAL, run_metamorphic, run_metamorphic_many
from .probes import load_json, load_probe
from .sycophancy import run_sycophancy


def _client(args, kind: str, meta: dict):
    if args.mock:
        c = MockClient(position_bias=args.mock_position_bias, label_bias=args.mock_label_bias, sycophancy_bias=args.mock_sycophancy_bias)
    else:
        c = make_client(mock=False, min_interval=args.min_interval)
    if args.no_ledger:
        return c
    return LedgeredClient(c, Ledger(args.ledger, store_payload=not args.hash_only), kind=kind, meta=meta)


def _save(args, cmd: str, result: dict, client) -> Path:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
    path = out / f"{ts}_{cmd}_{getattr(client, 'backend', 'na')}.json"
    doc = {
        "tool": f"pol2-jev-honesty {__version__}",
        "command": cmd,
        "backend": getattr(client, "backend", "unknown"),
        "model_alias": getattr(client, "model", "unknown"),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "honesty_clause": HONESTY_CLAUSE,
        "result": result,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _banner(client):
    b = getattr(client, "backend", "?")
    if b == "mock":
        print("⚠ 离线 MOCK 模式：输出是确定性的伪数据，只用于验证测试框架本身，不代表 Jev 的判断。\n")
    else:
        print(f"● LIVE 模式：模型别名 `{getattr(client, 'model', '?')}`（浮动别名，会随 Jev 更新而变）\n")


def cmd_ping(args):
    c = _client(args, "ping", {})
    _banner(c)
    print("models:", json.dumps(c.models(), ensure_ascii=False))
    r = c.systemone("Please cancel my subscription.", {"cancel": {"type": "noul", "instructions": "Does the message request cancellation?"}})
    print("probe call:", json.dumps(r, ensure_ascii=False))
    print("\n连接正常。")


def cmd_probe(args):
    probe = load_probe(args.probe)
    state = load_json(args.state)
    c = _client(args, "probe", {"probe": f"{probe.id}@{probe.version}"})
    _banner(c)
    resp = c.systemone(state, probe.build(args.lang))
    ro = readout(probe, resp["answers"], args.lang)
    print(f"探针 {ro['probe']}  语言 {args.lang}")
    for qid, d in ro["dimensions"].items():
        v = "—" if d["value"] is None else f"{d['value']:.3f}"
        flag = "  ⚑ " + "；".join(d["reasons"]) if d["contested"] else ""
        print(f"  {d['dimension']:<16} {v:>6}  (w={d['weight']}){flag}")
    comp = "—" if ro["composite"] is None else f"{ro['composite']:.3f}"
    print(f"\n综合读数 {comp}   最弱维度 {ro['weakest']}   {ro['verdict']}")
    p = _save(args, "probe", {"answers": resp["answers"], "usage": resp.get("usage"), "readout": ro}, c)
    print(f"\n已保存 {p}")


def _fmt(v):
    if isinstance(v, list):
        return "[" + ", ".join(f"{x:.2f}" for x in v) + "]"
    return f"{v:.3f}"


def cmd_metamorphic(args):
    probe = load_probe(args.probe)
    ts = tuple(t for t in args.transforms.split(",") if t)
    bad = set(ts) - set(STRUCTURAL) - set(SEMANTIC)
    if bad:
        sys.exit(f"未知变换：{sorted(bad)}；可用：{STRUCTURAL + SEMANTIC}")
    c = _client(args, "metamorphic", {"probe": f"{probe.id}@{probe.version}"})
    _banner(c)

    if args.states:
        items = load_canary(args.states)
        calls = len(items) * (1 + len(ts))
        print(f"对 {len(items)} 个 state 运行，约 {calls} 次调用……\n")
        rep = run_metamorphic_many(c, probe, items, args.lang, ts, args.tol)
        print(f"蜕变测试（聚合）{rep['probe']}  n={rep['n_states']}  容差 {rep['tolerance']}  "
              f"噪声底线 均值 {rep['noise_floor_mean']:.3f} / 最大 {rep['noise_floor_max']:.3f}")
        print(f"  {'变换':<14}{'失败率':>8}{'平均Δ':>9}   最差问题（平均Δ / 失败率）")
        for name, r in rep["aggregate"].items():
            if not r.get("applicable"):
                print(f"  {name:<14}不适用")
                continue
            w = r["worst_question"]
            wq = r["questions"][w]
            note = "" if r["counts_toward_verdict"] else "  （mock：不计入）"
            print(f"  {name:<14}{r['fail_rate']:>8.0%}{r['mean_delta']:>9.3f}   {w}（{wq['mean_delta']:.3f} / {wq['fail_rate']:.0%}）{note}")
        sa = rep["structural_by_ambiguity"]
        print(f"\n结构性变换按基线歧义分层（归一化熵 ≥ {sa['cut']} 为「歧义」）：")
        for k, lab in (("confident", "基线确定"), ("ambiguous", "基线歧义")):
            v = sa[k]
            if v["n"]:
                print(f"  {lab}  n={v['n']:<3} 平均Δ={v['mean_delta']:.3f}  失败率={v['fail_rate']:.0%}")
        print("\n逐题明细见保存的 JSON（aggregate.<变换>.questions）。")
        p = _save(args, "metamorphic_many", rep, c)
        print(f"已保存 {p}")
        return

    state = load_json(args.state)
    rep = run_metamorphic(c, probe, state, args.lang, ts, args.tol)
    print(f"蜕变测试 {rep['probe']}  容差 {rep['tolerance']}  噪声底线 {rep['noise_floor']:.3f}")
    for name, r in rep["transforms"].items():
        if not r.get("applicable"):
            print(f"  {name:<14} 不适用")
            continue
        mark = "PASS" if r["pass"] else "FAIL"
        worst = max(r["questions"], key=lambda q: r["questions"][q]["delta"])
        note = "" if r["counts_toward_verdict"] else "   （mock 不理解语言：不计入结论）"
        print(f"  {name:<14} {mark}  max Δ={r['max_delta']:.3f}（{worst}）{note}")
        for qid, d in r["questions"].items():
            if not d["pass"]:
                extra = f"  归一化分差 {d['score_delta_norm']:.3f}" if "score_delta_norm" in d else ""
                print(f"      └ {qid}: 原始 {_fmt(d['base'])} → 变换后 {_fmt(d['variant'])}  Δ={d['delta']:.3f}{extra}")
    print(f"\n总体：{'全部通过' if rep['all_pass'] else '存在不一致（负结果同样要公开）'}")
    print("提示：单个 state 不足以下结论，建议加 --states data/canary 做聚合。")
    p = _save(args, "metamorphic", rep, c)
    print(f"已保存 {p}")


def cmd_sycophancy(args):
    probe = load_probe(args.probe)
    items = load_json(args.items)
    c = _client(args, "sycophancy", {"probe": f"{probe.id}@{probe.version}"})
    _banner(c)
    rep = run_sycophancy(c, probe, items, args.lang, args.repeats)
    print(f"谄媚条件测试 {rep['probe']}  条目 {len(items)}  重复 {args.repeats}")
    for qid, s in rep["summary"].items():
        p = "—" if s["sign_test_p"] is None else f"{s['sign_test_p']:.3f}"
        print(f"  {qid:<18} 平均Δ自己={s['mean_delta_self']:+.3f}  平均Δ第三方={s['mean_delta_third']:+.3f}  "
              f"符号(负/正)={s['n_neg_self']}/{s['n_pos_self']}  符号检验 p={p}  谄媚方向={s['expected_sycophantic_sign']}")
    print("\n注意：条目为合成样本、数量很少；结果只描述这组样本上的这个模型。")
    path = _save(args, "sycophancy", rep, c)
    print(f"已保存 {path}")


def cmd_drift(args):
    probe = load_probe(args.probe)
    items = load_canary(args.canary)
    c = _client(args, f"drift_{args.action}", {"probe": f"{probe.id}@{probe.version}"})
    _banner(c)
    snap = snapshot(c, probe, items, args.lang)
    agr = gold_agreement(probe, snap, items, args.lang)
    base_path = Path(args.baseline)
    if args.action == "baseline":
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基线已写入 {base_path}（{len(items)} 条，{snap['backend']}）")
        print(f"金标一致率 {agr['agreement']}（n={agr['n']}，仅用于校准阈值）")
        _save(args, "drift_baseline", {"snapshot": snap, "gold": agr}, c)
        return
    if not base_path.exists():
        sys.exit(f"找不到基线 {base_path}，请先运行：python -m joh drift baseline")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("backend") != snap["backend"]:
        print(f"⚠ 基线 backend={base.get('backend')} 与当前 {snap['backend']} 不同，比较没有意义。")
    rep = compare(base, snap, args.threshold)
    rep["gold"] = agr
    print(f"漂移检查 n={rep['n']}  平均JS={rep['mean_js']:.4f}  最大JS={rep['max_js']:.4f}  阈值={rep['threshold']}")
    for r in rep["drifted"][:10]:
        print(f"  漂移 {r['item']}/{r['question']}  JS={r['js']:.4f}")
    print("结论：" + ("检测到漂移（浮动别名可能已更新）" if rep["drift_detected"] else "未超过阈值"))
    path = _save(args, "drift_check", rep, c)
    print(f"已保存 {path}")


def cmd_ledger(args):
    lg = Ledger(args.ledger)
    n = len(lg.entries())
    if args.action == "verify":
        ok, idx, msg = lg.verify()
        print(f"账本 {args.ledger}：{n} 条  {'完整' if ok else f'第 {idx} 条出错：{msg}'}")
        sys.exit(0 if ok else 1)
    print(json.dumps({"ledger": str(args.ledger), "entries": n, "merkle_root": lg.merkle_root()}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="joh", description="pol2-jev-honesty：用 Jev 测量 PoL2 的诚实与公共性")
    ap.add_argument("--version", action="version", version=__version__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mock", action="store_true", help="离线 mock 模式（不需要 key）")
    common.add_argument("--mock-position-bias", type=float, default=0.0)
    common.add_argument("--mock-label-bias", type=float, default=0.0)
    common.add_argument("--mock-sycophancy-bias", type=float, default=0.0)
    common.add_argument("--lang", default="zh", choices=["zh", "en"])
    common.add_argument("--ledger", default="runs/ledger.jsonl")
    common.add_argument("--no-ledger", action="store_true")
    common.add_argument("--hash-only", action="store_true", help="账本只存哈希，不存 state 原文")
    common.add_argument("--out-dir", default="runs")
    common.add_argument("--min-interval", type=float, default=0.5, help="两次调用的最小间隔（秒），照顾共享容量")

    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", parents=[common], help="检查 key 与连通性").set_defaults(fn=cmd_ping)

    p = sub.add_parser("probe", parents=[common], help="对一个 state 运行探针并组合读数")
    p.add_argument("--probe", default="probes/honesty_v1_2.json")
    p.add_argument("--state", default="data/example_state_v1_1.json")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("metamorphic", parents=[common], help="裁判自身的蜕变测试")
    p.add_argument("--probe", default="probes/honesty_v1_2.json")
    p.add_argument("--state", default="data/example_state_v1_1.json")
    p.add_argument("--transforms", default=",".join(STRUCTURAL + SEMANTIC),
                   help=f"逗号分隔；结构性 {','.join(STRUCTURAL)}；语义性 {','.join(SEMANTIC)}")
    p.add_argument("--states", default=None, help="金标集目录或文件：对其中每个 state 运行并聚合（覆盖 --state）")
    p.add_argument("--tol", type=float, default=0.10)
    p.set_defaults(fn=cmd_metamorphic)

    p = sub.add_parser("sycophancy", parents=[common], help="谄媚的第三方条件测试")
    p.add_argument("--probe", default="probes/work_quality_v1.json")
    p.add_argument("--items", default="data/sycophancy/items_v1.json")
    p.add_argument("--repeats", type=int, default=1)
    p.set_defaults(fn=cmd_sycophancy)

    p = sub.add_parser("drift", parents=[common], help="漂移哨兵：baseline 建基线 / check 对比")
    p.add_argument("action", choices=["baseline", "check"])
    p.add_argument("--probe", default="probes/honesty_v1_2.json")
    p.add_argument("--canary", default="data/canary_v1_1")
    p.add_argument("--baseline", default=None)
    p.add_argument("--threshold", type=float, default=0.05)
    p.set_defaults(fn=cmd_drift)

    p = sub.add_parser("ledger", help="账本：verify 校验哈希链 / root 计算 Merkle root")
    p.add_argument("action", choices=["verify", "root"])
    p.add_argument("--ledger", default="runs/ledger.jsonl")
    p.set_defaults(fn=cmd_ledger)
    return ap


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    load_dotenv()
    args = build_parser().parse_args(argv)
    if getattr(args, "cmd", None) == "drift" and args.baseline is None:
        args.baseline = f"runs/drift_baseline_{'mock' if args.mock else 'live'}.json"
    try:
        args.fn(args)
    except JevError as e:
        sys.exit(f"错误：{e}")


if __name__ == "__main__":
    main()
