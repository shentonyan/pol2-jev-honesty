"""真实 API 测试：需要 OPENJEV_API_KEY。运行：pytest -m live
这些测试会消耗公共推理预算，保持在十几次调用以内。
它们验证的是「响应形状是否符合本框架的假设」，不是模型的判断质量。"""
import os

import pytest

from joh.client import JevClient, load_dotenv
from joh.metamorphic import run_metamorphic

load_dotenv()
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("OPENJEV_API_KEY"), reason="未设置 OPENJEV_API_KEY"),
]


@pytest.fixture(scope="module")
def live():
    return JevClient(min_interval=1.0)


def test_models_lists_openjev(live):
    ids = [m["id"] for m in live.models()["data"]]
    assert "openjev" in ids


def test_response_shapes_match_framework_assumptions(live, honesty, example_state):
    qs = honesty.build("zh")
    r = live.systemone(example_state, qs)
    for qid, q in qs.items():
        a = r["answers"][qid]
        assert a["type"] == q["type"]
        if q["type"] == "noul":
            assert 0.0 <= a["noul"] <= 1.0
        elif q["type"] == "choice":
            assert set(a["probabilities"]) == set(q["criteria"])  # 概率以选项键为索引
            assert abs(sum(a["probabilities"].values()) - 1) < 0.02
            assert 0.0 <= a["confidence"] <= 1.0
        else:
            n = len(q["criteria"])
            assert set(a["probabilities"]) == {str(i) for i in range(n)}  # 概率以级别序号字符串为索引
            assert 0.0 <= a["score"] <= n - 1
            weighted = sum(i * a["probabilities"][str(i)] for i in range(n))
            assert abs(weighted - a["score"]) < 0.05  # score = 概率加权均值（文档所述）


def test_repeat_noise_floor_and_structural_invariance(live, honesty, example_state):
    rep = run_metamorphic(live, honesty, example_state, "zh", ("repeat", "shuffle", "reverse"), tolerance=0.15)
    print("\nnoise floor:", rep["noise_floor"])
    for name, r in rep["transforms"].items():
        print(name, round(r.get("max_delta", -1), 4))
    # 不在这里断言通过——负结果本身就是要报告的数据。只断言流程完整。
    assert rep["transforms"]["repeat"]["applicable"]
