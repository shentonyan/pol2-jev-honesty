import pytest

from joh.client import MockClient
from joh.metamorphic import STRUCTURAL, canonical, run_metamorphic, transform


def test_unbiased_judge_passes_all_structural_transforms(honesty, example_state):
    rep = run_metamorphic(MockClient(), honesty, example_state, "zh", STRUCTURAL, tolerance=1e-9)
    assert rep["all_pass"], rep
    assert rep["noise_floor"] == 0.0


def test_position_bias_is_detected(honesty, example_state):
    rep = run_metamorphic(MockClient(position_bias=2.0), honesty, example_state, "zh", STRUCTURAL)
    t = rep["transforms"]
    assert t["repeat"]["pass"] and t["permute_state"]["pass"]
    assert not t["shuffle"]["pass"]
    assert not t["reverse"]["pass"]
    assert not rep["all_pass"]


def test_label_bias_is_detected_only_by_relabel(honesty, example_state):
    rep = run_metamorphic(MockClient(label_bias=3.0), honesty, example_state, "zh", STRUCTURAL)
    t = rep["transforms"]
    assert not t["relabel"]["pass"]
    assert t["shuffle"]["pass"] and t["reverse"]["pass"]


def test_reverse_mapping_is_exact():
    q = {"type": "score", "instructions": "x", "criteria": ["a", "b", "c", "d"]}
    qs, _, m = transform("reverse", {"q": q}, "s", None, "zh")
    assert qs["q"]["criteria"] == ["d", "c", "b", "a"]
    a = {"score": 0.5, "probabilities": {"0": 0.5, "1": 0.5, "2": 0.0, "3": 0.0}}
    c = m["q"](a)
    assert c["probs"] == [0.0, 0.0, 0.5, 0.5]
    assert c["score"] == 2.5


def test_relabel_mapping_is_exact():
    q = {"type": "choice", "instructions": "x", "criteria": {"yes": "", "no": ""}}
    qs, _, m = transform("relabel", {"q": q}, "s", None, "zh")
    assert list(qs["q"]["criteria"]) == ["A", "B"]
    assert m["q"]({"probabilities": {"A": 0.8, "B": 0.2}})["probs"] == [0.8, 0.2]


def test_permute_state_reverses_keys_recursively():
    _, st, _ = transform("permute_state", {}, {"a": 1, "b": {"x": 1, "y": 2}}, None, "zh")
    assert list(st) == ["b", "a"] and list(st["b"]) == ["y", "x"]


def test_semantic_transforms_run_and_are_reported(honesty, example_state):
    # mock 不理解语言，语义变换按设计不应被当作通过/失败的证据；这里只检查流程与映射
    rep = run_metamorphic(MockClient(), honesty, example_state, "zh", ("lang", "negate"))
    assert rep["transforms"]["lang"]["applicable"]
    assert set(rep["transforms"]["negate"]["questions"]) == {"self_report"}


def test_canonical_rejects_nothing_silently():
    q = {"type": "choice", "instructions": "x", "criteria": {"a": "", "b": ""}}
    assert canonical(q, {"probabilities": {"a": 1.0}})["probs"] == [1.0, 0.0]


def test_semantic_transforms_do_not_count_under_mock(honesty, example_state):
    rep = run_metamorphic(MockClient(), honesty, example_state, "zh", STRUCTURAL + ("lang", "negate"))
    assert rep["transforms"]["lang"]["counts_toward_verdict"] is False
    assert rep["all_pass"]


def test_many_states_aggregate(root, honesty):
    from joh.drift import load_canary
    from joh.metamorphic import run_metamorphic_many
    items = load_canary(root / "data/canary")
    rep = run_metamorphic_many(MockClient(position_bias=2.0), honesty, items, "zh", ("repeat", "shuffle", "permute_state"))
    a = rep["aggregate"]
    assert rep["n_states"] == len(items)
    assert a["repeat"]["fail_rate"] == 0 and a["permute_state"]["fail_rate"] == 0
    assert a["shuffle"]["fail_rate"] > 0 and a["shuffle"]["worst_question"] == "constructive_truth"


def test_failure_details_recorded(honesty, example_state):
    rep = run_metamorphic(MockClient(position_bias=2.0), honesty, example_state, "zh", ("reverse",))
    d = rep["transforms"]["reverse"]["questions"]["false_image"]
    assert "base" in d and "variant" in d and "score_delta_norm" in d
