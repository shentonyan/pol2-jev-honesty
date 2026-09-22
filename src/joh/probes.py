"""探针文件：一个 JSON 描述一组「类型化问题」+ 只在本地使用的元数据。

发给模型的只有 type / instructions / criteria。
dimension、pol_ref、polarity、weight、option_values、negated 等本地字段绝不外发，
这一点由 schema.validate_question 强制检查（多出的键会直接报错）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import SchemaError, validate_question

POLARITIES = {"honest_high", "honest_low", "raw"}


@dataclass
class Probe:
    id: str
    version: str
    source: str
    questions: dict[str, dict]
    thresholds: dict = field(default_factory=dict)
    languages: tuple[str, ...] = ("zh", "en")
    raw: dict = field(default_factory=dict)

    @property
    def noul_band(self) -> tuple[float, float]:
        lo, hi = self.thresholds.get("noul_contested", [0.35, 0.65])
        return float(lo), float(hi)

    @property
    def min_confidence(self) -> float:
        return float(self.thresholds.get("min_confidence", 0.5))

    def build(self, lang: str = "zh", variant: str | None = None) -> dict[str, dict]:
        """构建 API 的 questions 对象。variant='negated' 时使用人工撰写的否定版本（仅 noul）。"""
        out: dict[str, dict] = {}
        for qid, q in self.questions.items():
            body = q.get(lang)
            if body is None:
                raise SchemaError(f"{self.id}.{qid}: 没有 {lang} 版本")
            if variant == "negated":
                neg = q.get("negated", {}).get(lang)
                if neg is None:
                    continue
                body = neg
            api_q = {"type": q["type"], "instructions": body["instructions"]}
            if body.get("criteria") is not None:
                api_q["criteria"] = body["criteria"]
            validate_question(qid, api_q)
            out[qid] = api_q
        return out


def _check(probe: Probe) -> None:
    for qid, q in probe.questions.items():
        pol = q.get("polarity", "raw")
        if pol not in POLARITIES:
            raise SchemaError(f"{probe.id}.{qid}: polarity 必须是 {sorted(POLARITIES)}")
        shapes = []
        for lang in probe.languages:
            if lang not in q:
                continue
            crit = q[lang].get("criteria")
            if q["type"] == "choice":
                shapes.append(tuple(crit.keys()))
            elif q["type"] == "score":
                shapes.append(len(crit))
        if len(set(shapes)) > 1:
            raise SchemaError(f"{probe.id}.{qid}: 不同语言版本的选项键/级数必须一致")
        if q["type"] == "choice":
            ov = q.get("option_values")
            keys = set(q[probe.languages[0]]["criteria"].keys())
            if ov is not None and set(ov) != keys:
                raise SchemaError(f"{probe.id}.{qid}: option_values 的键必须与 criteria 一致")
        g = q.get("gate")
        if g is not None:
            gq = probe.questions.get(g)
            if gq is None or gq["type"] != "noul":
                raise SchemaError(f"{probe.id}.{qid}: gate 必须指向同一探针里的 noul 题")
    for lang in probe.languages:
        probe.build(lang)  # 触发逐题校验


def load_probe(path: str | Path) -> Probe:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    p = Probe(
        id=d["id"],
        version=d["version"],
        source=d.get("source", ""),
        questions=d["questions"],
        thresholds=d.get("thresholds", {}),
        languages=tuple(d.get("languages", ["zh", "en"])),
        raw=d,
    )
    _check(p)
    return p


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
