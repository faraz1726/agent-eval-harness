import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from agent_harness.server import create_app  # noqa: E402


def test_server_endpoints():
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(tmp))
        assert client.get("/health").json()["status"] == "ok"
        assert len(client.get("/scenarios").json()) >= 12
        run = client.post("/runs", json={"agent": "mock:v2"}).json()
        assert run["summary"]["pass_rate"] == 1.0
        assert client.get(f"/runs/{run['run_id']}").status_code == 200
        assert "Agent Evaluation Report" in client.get(f"/runs/{run['run_id']}/report").text
        assert client.get("/runs/nope").status_code == 404
        assert client.post("/runs", json={"agent": "bogus:x"}).status_code == 400
        chat = client.post("/agent/chat", json={"session_id": "s1", "message": "How much is the Growth plan?"}).json()
        assert "$199" in chat["reply"] and chat["tool_calls"][0]["name"] == "lookup_product"
