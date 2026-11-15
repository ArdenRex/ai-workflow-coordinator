"""Step 15.3: the launch-gate script runs against an in-process app, passes on a production-shaped app and fails on a development one."""
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import create_app
from tests.test_production_config import prod

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class Adapter:
    """Same request() as preflight.Http, but calls the app in-process."""

    def __init__(self, client):
        self.c = client

    def request(self, method, path, headers=None, body=None):
        r = self.c.request(method, path, headers=headers, json=body)
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content


@pytest.fixture
def prod_http(db_session, monkeypatch):
    s = prod()
    monkeypatch.setattr("app.api.health.get_settings", lambda: s)
    monkeypatch.setattr("app.database.check_database", lambda engine=None: True)
    app = create_app(s)
    app.dependency_overrides[get_db] = lambda: db_session
    return Adapter(TestClient(app))


def run(http, *flags):
    g = preflight.Gates()
    preflight.read_only_gates(http, g)
    if "smoke" in flags:
        preflight.smoke_journey(http, g)
    return g


def test_a_production_shaped_instance_passes_every_gate(prod_http):
    g = run(prod_http, "smoke")
    assert g.failed == [], g.failed
    assert len(g.results) == 8 + 6


def test_a_development_instance_fails_the_schema_and_health_gates(client):
    g = run(Adapter(client))
    failed = {n.split()[0] for n, _, _ in g.failed}
    assert {"G2", "G3"} <= failed and "G1" not in failed


def test_a_missing_security_header_is_caught(prod_http):
    real = prod_http.request

    def stripped(method, path, headers=None, body=None):
        s, h, b = real(method, path, headers, body)
        h.pop("x-frame-options", None)
        return s, h, b
    prod_http.request = stripped
    assert any(n.startswith("G4") for n, _, _ in run(prod_http).failed)


def test_an_unreachable_database_fails_ready(prod_http, monkeypatch):
    monkeypatch.setattr("app.database.check_database", lambda engine=None: False)
    assert any(n.startswith("G1") for n, _, _ in run(prod_http).failed)


def test_a_permissive_cors_instance_is_caught():
    class Open:
        def request(self, method, path, headers=None, body=None):
            return 200, {"access-control-allow-origin": "*"}, b"{}"
    assert any(n.startswith("G6") for n, _, _ in run(Open()).failed)


def test_a_check_that_crashes_fails_without_printing_its_error():
    class Boom:
        def request(self, *a, **k):
            raise RuntimeError("secret-token-123 at https://internal.host")
    g = run(Boom())
    out = preflight.render(g)
    assert len(g.failed) == 8 and "secret-token-123" not in out and "internal.host" not in out and "NOT READY" in out


def test_the_report_and_exit_code(prod_http, capsys):
    assert preflight.main(["x://bad"]) == 2
    assert preflight.main(["http://ignored", "--smoke"], http=prod_http) == 0
    out = capsys.readouterr().out
    assert "RESULT: READY" in out and "Not covered here" in out


def test_the_report_never_contains_tokens_or_passwords(prod_http, capsys):
    preflight.main(["http://ignored", "--smoke"], http=prod_http)
    out = capsys.readouterr().out
    assert "Bearer" not in out and "access_token" not in out and "Pf-" not in out


def test_the_script_uses_only_the_standard_library_at_import_time():
    src = (ROOT / "scripts" / "preflight.py").read_text()
    top = [l for l in src.splitlines() if l.startswith(("import ", "from "))]
    assert not [l for l in top if any(x in l for x in ("requests", "httpx", "fastapi", "sqlalchemy", "app."))]


def test_the_docs_describe_the_preflight_script():
    prod_doc = (ROOT / "docs" / "PRODUCTION.md").read_text()
    assert "scripts/preflight.py" in prod_doc and "scripts/preflight.py" in (ROOT / "docs" / "RUNBOOK.md").read_text()
