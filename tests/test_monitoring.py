"""Step 13.1: workspace monitoring summary. Read-only, workspace-scoped, content-free."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.kernel.errors import ToolNotFoundError
from app.kernel.service import _now
from app.models.enums import ApprovalStatus, ExecutionStatus, RiskLevel
from app.models.kernel import Approval, SystemEvent, ToolExecution
from app.monitoring.service import MonitoringService
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_store import put
from tests.test_workspace_connectors import principal, mkws, team  # noqa: F401


def u(ws, window=None):
    return f"/workspaces/{ws['id']}/monitoring/summary" + (f"?window_seconds={window}" if window is not None else "")


def add(db, ws, status, *, tool="system.ping", age=0, ms=100, error=None, inp=None, ran=True):
    t = _now() - timedelta(seconds=age)
    row = ToolExecution(workspace_id=ws, tool_id=tool, requested_by="u", risk_level=RiskLevel.LOW, status=status, input=inp or {},
                        started_at=t if ran else None, finished_at=t + timedelta(milliseconds=ms) if ran else None, error=error, created_at=t)
    db.add(row)
    db.commit()
    return row


def test_permissions_only_admins_and_owners_read_it(client, team):
    hs, ws = team
    for who in ("admin", "owner"):
        assert client.get(u(ws), headers=hs[who]).status_code == 200
    assert client.get(u(ws), headers=hs["member"]).status_code == 403
    assert client.get(u(ws), headers=hs["outsider"]).status_code in (403, 404)
    assert client.get(u(ws)).status_code == 401


def test_an_empty_workspace_is_all_zeroes(client, team):
    hs, ws = team
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["executions"]["total"] == 0 and j["executions"]["failure_rate"] is None and j["executions"]["avg_duration_ms"] is None
    assert j["approvals"] == {"pending": 0, "oldest_pending_age_seconds": None, "rejected_in_window": 0, "expired_in_window": 0,
                              "decided_in_window": 0, "avg_decision_seconds": None, "p95_decision_seconds": None, "decision_sample_capped": False}
    assert (j["denials_in_window"], j["top_failing_tools"], j["recent_failures"], j["needs_attention"]) == (0, [], [], False)
    assert j["window_seconds"] == 86400


@pytest.mark.parametrize("w", [0, 1, 60, 3601, -5, 999999])
def test_invalid_windows_are_refused(client, team, w):
    hs, ws = team
    r = client.get(u(ws, w), headers=hs["admin"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_window"


def test_counts_rates_durations_and_failures(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    for _ in range(3):
        add(db_session, w, ExecutionStatus.SUCCEEDED, ms=100)
    add(db_session, w, ExecutionStatus.FAILED, tool="a.tool", ms=500, error="Tool failed: ValueError", inp={"secret": "SHHH"})
    add(db_session, w, ExecutionStatus.FAILED, tool="a.tool", ms=300, error="Tool timed out")
    add(db_session, w, ExecutionStatus.FAILED, tool="b.tool", ms=100, error="x")
    add(db_session, w, ExecutionStatus.AWAITING_APPROVAL, ran=False)
    j = client.get(u(ws), headers=hs["admin"]).json()
    e = j["executions"]
    assert e["total"] == 7 and e["by_status"] == {"awaiting_approval": 1, "failed": 3, "succeeded": 3}
    assert e["failure_rate"] == 0.5 and e["max_duration_ms"] == 500 and e["avg_duration_ms"] == 200
    assert j["top_failing_tools"] == [{"name": "a.tool", "count": 2}, {"name": "b.tool", "count": 1}]
    assert len(j["recent_failures"]) == 3 and j["needs_attention"] is True
    assert "SHHH" not in client.get(u(ws), headers=hs["admin"]).text            # never any tool input or output


def test_the_window_excludes_old_rows(client, team, db_session):
    hs, ws = team
    add(db_session, ws["id"], ExecutionStatus.FAILED, age=7200, error="x")
    assert client.get(u(ws, 3600), headers=hs["admin"]).json()["executions"]["total"] == 0
    assert client.get(u(ws, 86400), headers=hs["admin"]).json()["executions"]["by_status"] == {"failed": 1}


def test_denials_are_counted_with_reasons(client, team, db_session):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    for _ in range(2):
        with pytest.raises(ToolNotFoundError):
            k.submit(me, "no.such", {})
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["denials_in_window"] == 2 and j["denial_reasons"] == [{"name": "tool_not_found", "count": 2}]


def test_pending_approvals_and_staleness(client, team, db_session):
    hs, ws = team
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, risk_overrides={"system.ping": "high"})
    ex = kernel_for(client, db_session).submit(principal(db_session, "member@x.com", ws["id"]), "system.ping", {})
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["approvals"]["pending"] == 1 and j["approvals"]["oldest_pending_age_seconds"] < 60 and j["needs_attention"] is False
    ex.approvals[0].created_at = _now() - timedelta(hours=30)
    db_session.commit()
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["approvals"]["oldest_pending_age_seconds"] >= 30 * 3600 - 5 and j["needs_attention"] is True


def test_another_workspaces_data_never_appears(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    add(db_session, other["id"], ExecutionStatus.FAILED, tool="theirs.tool", error="boom")
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["executions"]["total"] == 0 and "theirs.tool" not in client.get(u(ws), headers=hs["admin"]).text
    assert client.get(u(other), headers=hs["outsider"]).json()["executions"]["total"] == 1


def test_reading_changes_nothing(client, team, db_session):
    hs, ws = team
    add(db_session, ws["id"], ExecutionStatus.FAILED, error="x")
    counts = lambda: (db_session.scalar(select(func.count()).select_from(ToolExecution)), db_session.scalar(select(func.count()).select_from(SystemEvent)),   # noqa: E731
                      db_session.scalar(select(func.count()).select_from(Approval)))
    before = counts()
    client.get(u(ws), headers=hs["admin"])
    assert counts() == before
    assert client.post(u(ws), headers=hs["admin"]).status_code == 405 and client.put(u(ws), headers=hs["admin"], json={}).status_code == 405


def test_service_rejects_a_window_it_does_not_know(db_session):
    with pytest.raises(ValueError):
        MonitoringService(db_session).summary("w", 5)
