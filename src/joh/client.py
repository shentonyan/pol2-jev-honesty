"""OpenJEV 客户端（仅用标准库）与确定性的离线 MockClient。

真实端点：POST {base}/systemone，Authorization: Bearer <key>。
- 429 / 503 / 5xx / 网络错误：有界退避重试，遵守 Retry-After（秒）。
- 401 / 422：不重试（重试一个不变的无效请求没有意义）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from .schema import validate_request

DEFAULT_BASE_URL = "https://api.openjev.sh/v1"
RETRYABLE = {429, 500, 502, 503, 504}


class JevError(RuntimeError):
    def __init__(self, status: int | None, body: Any, message: str = ""):
        self.status = status
        self.body = body
        super().__init__(message or f"OpenJEV error (status={status}): {body!r}")


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """极简 .env 读取：只设置尚未存在的环境变量；不打印任何值。"""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


class JevClient:
    backend = "live"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "openjev",
        timeout: float = 60.0,
        max_retries: int = 5,
        min_interval: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key or os.environ.get("OPENJEV_API_KEY")
        if not self.api_key:
            raise JevError(None, None, "缺少 OPENJEV_API_KEY：请在环境变量或 .env 中设置，或使用 --mock 离线运行。")
        self.base_url = (base_url or os.environ.get("OPENJEV_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._sleep = sleep
        self._last_call = 0.0

    # -- HTTP ---------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        while True:
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as e:
                        raise JevError(resp.status, raw, "响应不是 JSON") from e
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    pass
                if e.code in RETRYABLE and attempt < self.max_retries:
                    self._sleep(self._backoff(attempt, e.headers.get("Retry-After")))
                    attempt += 1
                    continue
                raise JevError(e.code, body) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < self.max_retries:
                    self._sleep(self._backoff(attempt, None))
                    attempt += 1
                    continue
                raise JevError(None, str(e), f"网络错误：{e}") from None

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return min(30.0, (2 ** attempt) * 0.5 + random.random() * 0.25)

    # -- API ----------------------------------------------------------------
    def models(self) -> dict:
        return self._request("GET", "/models")

    def systemone(self, state: Any, questions: dict) -> dict:
        payload = {"model": self.model, "state": state, "questions": questions}
        validate_request(payload)
        resp = self._request("POST", "/systemone", payload)
        if "answers" not in resp:
            raise JevError(200, resp, "响应中没有 answers 字段")
        return resp


# ---------------------------------------------------------------------------
# MockClient：确定性、离线、可注入偏差。
# 目的不是模仿 Jev 的判断质量，而是让测试框架本身可验证：
#   - 无偏 mock 在所有结构性蜕变下严格不变 → 蜕变测试应「通过」；
#   - 注入位置偏差 / 键名偏差 / 归属偏差 → 对应测试应「失败」。
# ---------------------------------------------------------------------------
def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _h(*parts: Any) -> float:
    """把任意内容哈希到 [-1, 1)。"""
    d = hashlib.sha256("\x1f".join(_canon(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(d[:8], "big") / 2**63 - 1.0


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    es = [math.exp(x - m) for x in xs]
    s = sum(es)
    return [e / s for e in es]


def _concentration(ps: Iterable[float]) -> float:
    ps = [p for p in ps]
    n = len(ps)
    if n <= 1:
        return 1.0
    ent = -sum(p * math.log(p) for p in ps if p > 0)
    return 1.0 - ent / math.log(n)


def _norm_state(state: Any) -> Any:
    """state 的规范形式：对象键排序（所以字段顺序置换不改变 mock 的输出）。"""
    return json.loads(_canon(state))


class MockClient:
    backend = "mock"
    model = "mock-jev"

    def __init__(
        self,
        position_bias: float = 0.0,
        label_bias: float = 0.0,
        sycophancy_bias: float = 0.0,
        self_markers: tuple[str, ...] = ("我自己写的", "I wrote this myself"),
        temperature: float = 1.5,
        seed: str = "pol2",
        blind_keys: tuple[str, ...] = ("author_note",),
    ):
        self.position_bias = position_bias
        self.label_bias = label_bias
        self.sycophancy_bias = sycophancy_bias
        self.self_markers = self_markers
        self.temperature = temperature
        self.seed = seed
        # 理想裁判对作者归属「失明」：哈希前剔除这些顶层字段。归属偏差只能经 sycophancy_bias 显式注入。
        self.blind_keys = blind_keys
        self.calls: list[dict] = []

    def models(self) -> dict:
        return {"object": "list", "data": [{"id": self.model, "description": "offline mock"}]}

    def _is_self(self, state: Any) -> bool:
        s = _canon(state)
        return any(m in s for m in self.self_markers)

    def _desc(self, d: Any) -> Any:
        return d if d is not None else ""

    def systemone(self, state: Any, questions: dict) -> dict:
        payload = {"model": self.model, "state": state, "questions": questions}
        validate_request(payload)
        self.calls.append(payload)
        st = _norm_state(state)
        if isinstance(st, dict):
            st = {k: v for k, v in st.items() if k not in self.blind_keys}
        flatter = self.sycophancy_bias if self._is_self(state) else 0.0
        answers: dict[str, dict] = {}
        for qid, q in questions.items():
            t = q["type"]
            instr = q.get("instructions")
            crit = q.get("criteria")
            if t == "choice":
                keys = list(crit.keys())
                logits = []
                for i, k in enumerate(keys):
                    x = self.temperature * _h(self.seed, st, instr, self._desc(crit[k]))
                    if i == 0:
                        x += self.position_bias
                    x += self.label_bias * _h("label", k)
                    logits.append(x)
                ps = _softmax(logits)
                probs = {k: p for k, p in zip(keys, ps)}
                answers[qid] = {
                    "type": "choice",
                    "choice": max(probs, key=probs.get),
                    "probabilities": probs,
                    "confidence": _concentration(ps),
                }
            elif t == "score":
                levels = list(crit)
                logits = []
                for i, lv in enumerate(levels):
                    x = self.temperature * _h(self.seed, st, instr, lv)
                    if i == 0:
                        x += self.position_bias
                    if i == len(levels) - 1:
                        x += flatter * 3  # 归属偏差：对「作者本人」的作品给更高一级
                    logits.append(x)
                ps = _softmax(logits)
                answers[qid] = {
                    "type": "score",
                    "score": sum(i * p for i, p in enumerate(ps)),
                    "legend": {str(i): lv for i, lv in enumerate(levels)},
                    "probabilities": {str(i): p for i, p in enumerate(ps)},
                    "confidence": _concentration(ps),
                }
            elif t == "noul":
                crit = crit or {}
                x = self.temperature * _h(self.seed, st, instr, self._desc(crit.get("true")), self._desc(crit.get("false")))
                x -= flatter * 3  # 归属偏差：对「作者本人」更宽容（更少判定为有问题）
                answers[qid] = {"type": "noul", "noul": 1.0 / (1.0 + math.exp(-x))}
            else:  # pragma: no cover - validate_request 已拦截
                raise JevError(422, {"error": f"unknown type {t}"})
        return {
            "model": self.model,
            "answers": answers,
            "usage": {"input_tokens": len(_canon(payload)) // 4, "output_tokens": 8 * len(questions)},
        }


def make_client(mock: bool = False, **kw) -> JevClient | MockClient:
    if mock:
        return MockClient(**{k: v for k, v in kw.items() if k in {"position_bias", "label_bias", "sycophancy_bias", "seed"}})
    return JevClient(**{k: v for k, v in kw.items() if k in {"api_key", "base_url", "model", "timeout", "max_retries", "min_interval"}})
