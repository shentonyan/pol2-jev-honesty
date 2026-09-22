"""用本地假服务器测试真实客户端的 HTTP 行为（重试、Retry-After、不重试 4xx、鉴权头）。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from joh.client import JevClient, JevError

Q = {"q": {"type": "noul", "instructions": "x?"}}


@pytest.fixture
def server():
    state = {"script": [], "seen": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _serve(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"null") if n else None
            state["seen"].append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            status, headers, payload = state["script"].pop(0) if state["script"] else (500, {}, {"error": "no script"})
            data = json.dumps(payload).encode()
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _serve

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    yield state
    srv.shutdown()


def client(server, **kw):
    slept = []
    c = JevClient(api_key="test-key", base_url=server["url"], sleep=slept.append, **kw)
    return c, slept


OK = (200, {}, {"model": "openjev", "answers": {"q": {"type": "noul", "noul": 0.9}}})


def test_success_and_auth_header(server):
    server["script"] = [OK]
    c, _ = client(server)
    r = c.systemone("s", Q)
    assert r["answers"]["q"]["noul"] == 0.9
    seen = server["seen"][0]
    assert seen["path"] == "/v1/systemone" and seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "openjev"


def test_429_honors_retry_after_then_succeeds(server):
    server["script"] = [(429, {"Retry-After": "7"}, {"error": "rate limited"}), OK]
    c, slept = client(server)
    c.systemone("s", Q)
    assert 7.0 in slept and len(server["seen"]) == 2


def test_422_is_not_retried(server):
    server["script"] = [(422, {}, {"error": "Missing field: state"}), OK]
    c, _ = client(server)
    with pytest.raises(JevError) as e:
        c.systemone("s", Q)
    assert e.value.status == 422 and len(server["seen"]) == 1


def test_503_bounded_retries(server):
    server["script"] = [(503, {}, {"error": "down"})] * 10
    c, slept = client(server, max_retries=2)
    with pytest.raises(JevError) as e:
        c.systemone("s", Q)
    assert e.value.status == 503 and len(server["seen"]) == 3 and len(slept) == 2


def test_missing_answers_is_an_error(server):
    server["script"] = [(200, {}, {"model": "openjev"})]
    c, _ = client(server)
    with pytest.raises(JevError, match="answers"):
        c.systemone("s", Q)


def test_invalid_request_blocked_locally_before_network(server):
    c, _ = client(server)
    with pytest.raises(Exception):
        c.systemone("s", {"q": {"type": "noul", "instructions": "x", "weight": 1}})
    assert server["seen"] == []


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENJEV_API_KEY", raising=False)
    with pytest.raises(JevError, match="OPENJEV_API_KEY"):
        JevClient()


def test_models_endpoint(server):
    server["script"] = [(200, {}, {"object": "list", "data": [{"id": "openjev"}]})]
    c, _ = client(server)
    assert c.models()["data"][0]["id"] == "openjev"
    assert server["seen"][0]["path"] == "/v1/models"
