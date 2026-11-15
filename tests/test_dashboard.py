"""Step 13.8: combined overview endpoint and the static dashboard page."""
import re
import shutil
import subprocess

import pytest

from app.api.dashboard import ASSET_DIR, ASSETS
from app.models.enums import ExecutionStatus
from tests.test_monitoring import add
from tests.test_monitoring_alerts import get as get_alerts
from tests.test_monitoring_health import get as get_health
from tests.test_workspace_connectors import SECRET, mkws, team  # noqa: F401


def ov(ws, window=None):
    return f"/workspaces/{ws['id']}/monitoring/overview" + (f"?window_seconds={window}" if window is not None else "")


def test_overview_permissions_and_window(client, team):
    hs, ws = team
    assert client.get(ov(ws), headers=hs["member"]).status_code == 403
    assert client.get(ov(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert client.get(ov(ws)).status_code == 401
    for w in (0, 61, 999999):
        r = client.get(ov(ws, w), headers=hs["admin"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_window"
    assert client.get(ov(ws), headers=hs["owner"]).json()["window_seconds"] == 86400


def test_overview_matches_the_three_separate_reports(client, team, db_session):
    hs, ws = team
    for _ in range(5):
        add(db_session, ws["id"], ExecutionStatus.FAILED, tool="a.tool")
    o = client.get(ov(ws), headers=hs["admin"]).json()
    assert set(o) == {"window_seconds", "generated_at", "summary", "health", "alerts"}
    s = client.get(f"/workspaces/{ws['id']}/monitoring/summary", headers=hs["admin"]).json()
    h, a = get_health(client, hs["admin"], ws), get_alerts(client, hs["admin"], ws)
    for part, other in ((o["summary"], s), (o["health"], h), (o["alerts"], a)):
        part, other = dict(part), dict(other)
        part.pop("generated_at"), other.pop("generated_at")
        assert part == other
    assert o["alerts"]["firing_count"] >= 1


def test_overview_is_workspace_scoped_and_read_only(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    add(db_session, other["id"], ExecutionStatus.FAILED, tool="theirs.tool", error="boom")
    r = client.get(ov(ws), headers=hs["admin"])
    assert r.json()["summary"]["executions"]["total"] == 0 and "theirs" not in r.text and SECRET not in r.text
    assert client.post(ov(ws), headers=hs["admin"]).status_code == 405


def test_dashboard_page_and_assets_are_served_with_strict_headers(client):
    for path, ctype in (("/dashboard", "text/html"), ("/dashboard/dashboard.css", "text/css"), ("/dashboard/dashboard.js", "text/javascript")):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)
        csp = r.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert client.get("/dashboard/index.html").status_code == 404 and client.get("/dashboard/other.js").status_code == 404


def test_page_has_no_inline_script_no_external_origin_and_no_data(client):
    html = client.get("/dashboard").text
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []
    assert not re.search(r"\son[a-z]+\s*=", html) and "http://" not in html and "https://" not in html
    assert SECRET not in html


def test_script_never_uses_dangerous_sinks_or_persistent_storage():
    js = (ASSET_DIR / "dashboard.js").read_text()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage",
                "document.cookie", "http://", "https://"):
        assert bad not in js, bad
    assert 'credentials: "omit"' in js and "textContent" in js


def test_asset_allowlist_exists_on_disk():
    for name in ASSETS:
        assert (ASSET_DIR / name).is_file()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_parses():
    assert subprocess.run(["node", "--check", str(ASSET_DIR / "dashboard.js")], capture_output=True).returncode == 0
