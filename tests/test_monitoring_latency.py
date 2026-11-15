"""Step 13.5: latency percentiles and approval-decision delay in the monitoring summary."""
from datetime import timedelta

import pytest

from app.kernel.service import _now
from app.models.enums import ApprovalStatus, ExecutionStatus
from app.models.kernel import Approval
from app.monitoring.service import percentile
from tests.test_monitoring import add, u
from tests.test_policy_execution_limit import kernel_for
from tests.test_policy_store import put
from tests.test_workspace_connectors import principal, mkws, team  # noqa: F401


@pytest.mark.parametrize("vals,q,want", [
    ([], 95, None), ([7], 50, 7), ([7], 95, 7),
    ([1, 2, 3, 4], 50, 2), ([4, 3, 2, 1], 95, 4),
    (list(range(1, 101)), 50, 50), (list(range(1, 101)), 95, 95), (list(range(1, 101)), 100, 100),
    (list(range(1, 21)), 95, 19),
])
def test_percentile_is_nearest_rank_and_an_observed_value(vals, q, want):
    assert percentile(vals, q) == want


def test_execution_percentiles_in_the_summary(client, team, db_session):
    hs, ws = team
    for ms in (100, 200, 300, 400, 5000):
        add(db_session, ws["id"], ExecutionStatus.SUCCEEDED, ms=ms)
    e = client.get(u(ws), headers=hs["admin"]).json()["executions"]
    assert e["p50_duration_ms"] == 300 and e["p95_duration_ms"] == 5000 and e["max_duration_ms"] == 5000


def test_percentiles_are_null_when_nothing_ran(client, team):
    hs, ws = team
    e = client.get(u(ws), headers=hs["admin"]).json()["executions"]
    assert e["p50_duration_ms"] is None and e["p95_duration_ms"] is None


def _approval(db, ws_id, status, created_ago, decided_ago):
    ex = add(db, ws_id, ExecutionStatus.AWAITING_APPROVAL, ran=False)
    now = _now()
    a = Approval(workspace_id=ws_id, execution_id=ex.id, status=status, requested_by="u", created_at=now - timedelta(seconds=created_ago),
                 decided_by="boss" if decided_ago is not None else None,
                 decided_at=None if decided_ago is None else now - timedelta(seconds=decided_ago))
    db.add(a)
    db.commit()


def test_decision_delay_counts_only_human_decisions_in_the_window(client, team, db_session):
    hs, ws = team
    w = ws["id"]
    _approval(db_session, w, ApprovalStatus.APPROVED, 700, 100)      # 600s
    _approval(db_session, w, ApprovalStatus.REJECTED, 1000, 800)     # 200s
    _approval(db_session, w, ApprovalStatus.EXECUTED, 400, 100)      # 300s
    _approval(db_session, w, ApprovalStatus.EXPIRED, 90000, 10)      # not a decision
    _approval(db_session, w, ApprovalStatus.PENDING, 50, None)       # not decided
    _approval(db_session, w, ApprovalStatus.APPROVED, 200000, 190000)   # decided outside a one-day window
    a = client.get(u(ws, 86400), headers=hs["admin"]).json()["approvals"]
    assert a["decided_in_window"] == 3 and a["avg_decision_seconds"] == 366 and a["p95_decision_seconds"] == 600
    assert a["decision_sample_capped"] is False and a["pending"] == 1


def test_other_workspaces_do_not_leak_into_latency_or_decision_delay(client, team, db_session):
    hs, ws = team
    other = mkws(client, hs["outsider"])
    add(db_session, other["id"], ExecutionStatus.SUCCEEDED, ms=9999)
    _approval(db_session, other["id"], ApprovalStatus.APPROVED, 5000, 10)
    j = client.get(u(ws), headers=hs["admin"]).json()
    assert j["executions"]["p95_duration_ms"] is None and j["approvals"]["decided_in_window"] == 0
    assert client.get(u(other), headers=hs["outsider"]).json()["approvals"]["decided_in_window"] == 1


def test_decision_stats_carry_no_identities(client, team, db_session):
    hs, ws = team
    _approval(db_session, ws["id"], ApprovalStatus.APPROVED, 100, 10)
    assert "boss" not in client.get(u(ws), headers=hs["admin"]).text
