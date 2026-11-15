from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_request_id_generated_and_echoed(client):
    assert client.get("/health").headers["x-request-id"]
    r = client.get("/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_unhandled_error_is_sanitized():
    app = create_app(Settings(app_env="test"))

    @app.get("/boom")
    def boom():
        raise RuntimeError("db password=hunter2")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert "hunter2" not in r.text
