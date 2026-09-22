from joh.compose import dimension_value, readout, score_bimodal


def test_noul_polarity():
    v = dimension_value({"type": "noul", "polarity": "honest_low"}, {"noul": 0.9}, None)["value"]
    assert abs(v - 0.1) < 1e-9
    v = dimension_value({"type": "noul", "polarity": "honest_high"}, {"noul": 0.9}, None)["value"]
    assert abs(v - 0.9) < 1e-9


def test_score_normalized_by_levels_minus_one():
    v = dimension_value({"type": "score", "polarity": "honest_low"}, {"score": 1.0}, ["a", "b", "c"])["value"]
    assert abs(v - 0.5) < 1e-9
    v = dimension_value({"type": "score", "polarity": "honest_high"}, {"score": 2.0}, ["a", "b", "c"])["value"]
    assert v == 1.0


def test_choice_null_option_excluded_and_applicability():
    q = {"type": "choice", "polarity": "honest_high", "option_values": {"a": 1.0, "b": 0.0, "na": None}}
    crit = {"a": "", "b": "", "na": ""}
    dv = dimension_value(q, {"probabilities": {"a": 0.3, "b": 0.1, "na": 0.6}, "choice": "na"}, crit)
    assert abs(dv["value"] - 0.75) < 1e-9
    assert abs(dv["applicability"] - 0.4) < 1e-9


def test_bimodal():
    assert score_bimodal([0.5, 0.0, 0.5])
    assert not score_bimodal([0.0, 1.0, 0.0])
    assert not score_bimodal([0.4, 0.3, 0.3])


def test_readout_flags_contested_and_excludes_inapplicable(honesty):
    answers = {
        "consistency": {"score": 2.0, "probabilities": {"0": 0, "1": 0, "2": 1}, "confidence": 1.0, "legend": {"0": "", "1": "", "2": ""}},
        "self_report": {"noul": 0.02},
        "false_image": {"score": 1.0, "probabilities": {"0": 0.5, "1": 0.0, "2": 0.5}, "confidence": 0.4, "legend": {"0": "", "1": "", "2": ""}},
        "boundary": {"noul": 0.5},
        "hidden_agenda": {"noul": 0.01},
        "constructive_truth": {"choice": "no_hard_truth", "confidence": 0.9,
                               "probabilities": {"constructive": 0.05, "withheld": 0.0, "harsh": 0.0, "no_hard_truth": 0.95}},
    }
    ro = readout(honesty, answers, "zh")
    assert set(ro["contested"]) >= {"false_image", "boundary", "constructive_truth"}
    assert "双峰" in "".join(ro["dimensions"]["false_image"]["reasons"])
    assert ro["verdict"].startswith("有争议")
    assert 0 <= ro["composite"] <= 1


def test_gate_sets_applicability(root):
    from joh.probes import load_probe
    p = load_probe(root / "probes/honesty_v1_2.json")
    base = {
        "consistency": {"score": 2.0, "probabilities": {"0": 0, "1": 0, "2": 1}, "confidence": 1.0, "legend": {"0": "", "1": "", "2": ""}},
        "fabricated_experience": {"noul": 0.02},
        "boundary": {"noul": 0.9},
        "hidden_agenda": {"noul": 0.02},
        "false_image": {"choice": "changed", "confidence": 1.0, "probabilities": {"holds": 0.0, "softened": 0.0, "changed": 1.0}},
        "constructive_truth": {"choice": "withheld", "confidence": 1.0, "probabilities": {"constructive": 0.0, "withheld": 1.0, "harsh": 0.0}},
        "hard_truth_exists": {"noul": 0.9},
    }
    ro_on = readout(p, dict(base, pleasing_pressure={"noul": 0.95}))
    ro_off = readout(p, dict(base, pleasing_pressure={"noul": 0.05}))
    assert ro_on["dimensions"]["false_image"]["applicability"] == 0.95
    assert ro_off["dimensions"]["false_image"]["applicability"] == 0.05
    assert "适用度" in "".join(ro_off["dimensions"]["false_image"]["reasons"])
    assert ro_off["composite"] > ro_on["composite"]  # 无迎合压力时，「changed」不计入


def test_gate_must_point_to_noul(tmp_path, root):
    import json
    import pytest
    from joh.probes import load_probe
    d = json.loads((root / "probes/honesty_v1_2.json").read_text(encoding="utf-8"))
    d["questions"]["false_image"]["gate"] = "consistency"
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(Exception, match="gate"):
        load_probe(f)
