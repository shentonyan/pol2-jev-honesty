"""按 OpenJEV 文档校验请求。先在本地拦住无效请求，避免浪费公共推理预算。"""
from __future__ import annotations

from typing import Any

MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10
TYPES = {"choice", "score", "noul"}
ALLOWED_QUESTION_KEYS = {"type", "instructions", "criteria"}


class SchemaError(ValueError):
    pass


def validate_question(qid: str, q: Any) -> None:
    if not isinstance(q, dict):
        raise SchemaError(f"{qid}: 问题必须是对象")
    extra = set(q) - ALLOWED_QUESTION_KEYS
    if extra:
        raise SchemaError(f"{qid}: 含有不应发送给模型的本地字段 {sorted(extra)}")
    t = q.get("type")
    if t not in TYPES:
        raise SchemaError(f"{qid}: type 必须是 {sorted(TYPES)} 之一")
    instr = q.get("instructions")
    if instr in (None, "", [], {}):
        raise SchemaError(f"{qid}: 必须提供 instructions（问题 ID 不会发给模型）")
    crit = q.get("criteria")
    if t == "choice":
        if not isinstance(crit, dict) or len(crit) < 2:
            raise SchemaError(f"{qid}: choice 的 criteria 必须是至少 2 个选项的对象")
        if len(crit) > MAX_CHOICE_OPTIONS:
            raise SchemaError(f"{qid}: choice 最多 {MAX_CHOICE_OPTIONS} 个选项")
    elif t == "score":
        if not isinstance(crit, list) or len(crit) < 2:
            raise SchemaError(f"{qid}: score 的 criteria 必须是至少 2 级的有序数组")
        if len(crit) > MAX_SCORE_LEVELS:
            raise SchemaError(f"{qid}: score 最多 {MAX_SCORE_LEVELS} 级")
        if len({repr(c) for c in crit}) != len(crit):
            raise SchemaError(f"{qid}: score 各级描述必须互不相同")
    elif t == "noul":
        if crit is not None:
            if not isinstance(crit, dict) or not set(crit) <= {"true", "false"}:
                raise SchemaError(f"{qid}: noul 的 criteria 只能包含 true / false")


def validate_request(payload: dict) -> None:
    if "state" not in payload or payload["state"] in (None, ""):
        raise SchemaError("缺少 state")
    qs = payload.get("questions")
    if not isinstance(qs, dict) or not qs:
        raise SchemaError("questions 必须是非空对象")
    for qid, q in qs.items():
        validate_question(qid, q)
