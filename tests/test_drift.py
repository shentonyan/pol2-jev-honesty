from joh.client import MockClient
from joh.drift import compare, gold_agreement, js_divergence, load_canary, snapshot


def test_js_bounds():
    assert js_divergence([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert abs(js_divergence([1, 0], [0, 1]) - 1.0) < 1e-12


def test_same_model_no_drift_changed_model_drifts(root, honesty):
    items = load_canary(root / "data/canary")
    base = snapshot(MockClient(), honesty, items)
    same = snapshot(MockClient(), honesty, items)
    assert not compare(base, same)["drift_detected"]
    changed = snapshot(MockClient(seed="new-weights"), honesty, items)
    rep = compare(base, changed)
    assert rep["drift_detected"] and rep["n"] == len(items) * len(honesty.questions)


def test_gold_agreement_is_computed(root, honesty):
    items = load_canary(root / "data/canary")
    snap = snapshot(MockClient(), honesty, items)
    g = gold_agreement(honesty, snap, items)
    assert g["n"] > 0 and 0.0 <= g["agreement"] <= 1.0
