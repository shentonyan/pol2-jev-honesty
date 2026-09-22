"""端到端：mock 模式下跑通所有命令。"""
import json

import pytest

from joh.cli import main


@pytest.fixture
def run(tmp_path, root, monkeypatch):
    monkeypatch.chdir(root)
    monkeypatch.delenv("OPENJEV_API_KEY", raising=False)
    common = ["--mock", "--out-dir", str(tmp_path / "runs"), "--ledger", str(tmp_path / "ledger.jsonl")]

    def _run(*args, extra=()):
        main([*args, *common, *extra])
    _run.tmp = tmp_path
    return _run


def outputs(tmp, cmd):
    return [json.loads(p.read_text(encoding="utf-8")) for p in (tmp / "runs").glob(f"*_{cmd}_mock.json")]


def test_probe(run, capsys):
    run("probe")
    out = capsys.readouterr().out
    assert "MOCK" in out and "综合读数" in out
    doc = outputs(run.tmp, "probe")[0]
    assert doc["backend"] == "mock" and "诚实条款" in doc["honesty_clause"]


def test_metamorphic_structural(run, capsys):
    run("metamorphic", "--transforms", "repeat,shuffle,relabel,reverse,permute_state")
    assert "全部通过" in capsys.readouterr().out


def test_metamorphic_detects_bias(run, capsys):
    run("metamorphic", "--transforms", "repeat,shuffle", extra=["--mock-position-bias", "2"])
    assert "FAIL" in capsys.readouterr().out


def test_sycophancy(run, capsys):
    run("sycophancy", extra=["--mock-sycophancy-bias", "1"])
    assert "flaw_present" in capsys.readouterr().out


def test_drift_baseline_then_check(run, capsys):
    b = str(run.tmp / "base.json")
    run("drift", "baseline", "--baseline", b)
    run("drift", "check", "--baseline", b)
    assert "未超过阈值" in capsys.readouterr().out


def test_ledger_verify_after_runs(run, capsys):
    run("probe")
    with pytest.raises(SystemExit) as e:
        main(["ledger", "verify", "--ledger", str(run.tmp / "ledger.jsonl")])
    assert e.value.code == 0
    main(["ledger", "root", "--ledger", str(run.tmp / "ledger.jsonl")])
    assert "merkle_root" in capsys.readouterr().out


def test_live_without_key_fails_clearly(root, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # 没有 .env
    monkeypatch.delenv("OPENJEV_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        main(["probe", "--probe", str(root / "probes/honesty_v1.json"), "--state", str(root / "data/example_state.json"), "--no-ledger"])
    assert "OPENJEV_API_KEY" in str(e.value.code)


def test_metamorphic_many_states(run, capsys):
    run("metamorphic", "--states", "data/canary", "--transforms", "repeat,shuffle,reverse")
    out = capsys.readouterr().out
    assert "聚合" in out and "失败率" in out


def test_metamorphic_prints_failure_details(run, capsys):
    run("metamorphic", "--transforms", "repeat,reverse", extra=["--mock-position-bias", "2"])
    assert "└ false_image" in capsys.readouterr().out
