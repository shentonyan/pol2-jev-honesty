from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def honesty(root):
    from joh.probes import load_probe
    return load_probe(root / "probes/honesty_v1.json")


@pytest.fixture
def work_quality(root):
    from joh.probes import load_probe
    return load_probe(root / "probes/work_quality_v1.json")


@pytest.fixture
def example_state(root):
    from joh.probes import load_json
    return load_json(root / "data/example_state.json")
