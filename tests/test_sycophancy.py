from joh.client import MockClient
from joh.probes import load_json
from joh.sycophancy import _sign_test, build_state, run_sycophancy


def test_state_structure_identical_across_conditions():
    keys = {tuple(build_state("t", c)) for c in ("anonymous", "self", "third_party")}
    assert keys == {("author_note", "text")}


def test_attribution_blind_judge_has_zero_delta(root, work_quality):
    items = load_json(root / "data/sycophancy/items_v1.json")
    rep = run_sycophancy(MockClient(), work_quality, items, "zh")
    for s in rep["summary"].values():
        assert s["mean_delta_self"] == 0.0 and s["mean_delta_third"] == 0.0


def test_injected_sycophancy_is_detected_in_expected_direction(root, work_quality):
    items = load_json(root / "data/sycophancy/items_v1.json")
    rep = run_sycophancy(MockClient(sycophancy_bias=1.0), work_quality, items, "zh")
    s = rep["summary"]
    assert s["flaw_present"]["mean_delta_self"] < -0.05  # 对作者本人：更少判定有缺陷
    assert s["flaw_present"]["n_neg_self"] == len(items)
    assert s["quality"]["mean_delta_self"] > 0.05  # 对作者本人：质量更高
    assert s["flaw_present"]["mean_delta_third"] == 0.0  # 第三方条件不受影响
    assert s["flaw_present"]["sign_test_p"] < 0.05


def test_sign_test():
    assert _sign_test(0, 0) is None
    assert abs(_sign_test(6, 0) - 2 / 64) < 1e-12
    assert _sign_test(3, 3) == 1.0
