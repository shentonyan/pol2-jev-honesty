import pytest

from joh.probes import load_probe
from joh.schema import ALLOWED_QUESTION_KEYS


@pytest.mark.parametrize("name", ["honesty_v1", "honesty_v1_1", "pai_boundary_v1", "work_quality_v1"])
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_probe_files_build_clean_payloads(root, name, lang):
    p = load_probe(root / f"probes/{name}.json")
    qs = p.build(lang)
    assert qs, "探针不能为空"
    for q in qs.values():
        assert set(q) <= ALLOWED_QUESTION_KEYS


def test_honesty_covers_six_forms(honesty):
    refs = {q["pol_ref"] for q in honesty.questions.values()}
    assert {f"2.1 表现形式{i}" for i in range(1, 7)} <= refs


def test_negated_variant_only_for_noul(honesty):
    neg = honesty.build("zh", variant="negated")
    assert neg and all(q["type"] == "noul" for q in neg.values())


def test_mismatched_language_shapes_rejected(tmp_path, root):
    import json
    d = json.loads((root / "probes/honesty_v1.json").read_text(encoding="utf-8"))
    d["questions"]["consistency"]["en"]["criteria"].pop()
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(Exception, match="一致"):
        load_probe(f)


def test_v1_1_fixes(root):
    import json
    p = load_probe(root / "probes/honesty_v1_1.json")
    zh = p.build("zh")
    fe = zh["fabricated_experience"]["instructions"]
    assert "`speaker`" in fe and "无法确认" not in fe  # 不再与回应文本字面重合
    neg = p.build("zh", variant="negated")["fabricated_experience"]["instructions"]
    assert "是否没有" in neg and "包括" not in neg  # 字面否定，无空真从句
    assert p.questions["false_image"]["option_values"]["no_pressure"] is None
    assert p.questions["pleasing_pressure"]["polarity"] == "raw"
    items = json.loads((root / "data/canary_v1_1/honesty_canary_v1_1.json").read_text(encoding="utf-8"))
    assert all(it["state"]["speaker"] for it in items)
