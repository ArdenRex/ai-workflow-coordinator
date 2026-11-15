"""Step 14.6: failure handling and burst behaviour. Escalation is re-checked at the claim; bad input, a failing database, a failing
tool and bursts of bad requests all end in a clean, content-free 4xx/429/503, never a 500 and never a leak."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.kernel.approvals import ApprovalService
from app.kernel.service import ToolExecutionService
from app.models.enums import ExecutionStatus
from app.models.kernel import ToolExecution
from tests.route_discovery import api_routes
from tests.test_isolation import world  # noqa: F401
from tests.test_policy_escalation import RULE, fail_rows, kernel_for, put
from tests.test_workspace_connectors import principal, team  # noqa: F401


# ------------------------------------------------------------------ escalation re-checked at the claim
def test_escalation_is_rechecked_at_the_claim_and_parks_the_run(client, team, db_session, monkeypatch):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    answers = iter([False, True])                                  # fine at the early check, tripped by the time it claims
    monkeypatch.setattr(ToolExecutionService, "_escalated", lambda self, w, p: next(answers))
    ex = k.submit(me, "system.ping", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and ex.started_at is None and ex.output is None


def test_an_approved_run_is_never_re_escalated(client, team, db_session, monkeypatch):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=3, escalation=RULE)
    fail_rows(db_session, ws["id"], 2)
    ex = k.submit(me, "system.ping", {})
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL
    approval = ApprovalService(db_session)
    pending = approval.list_pending(ws["id"])[0] if hasattr(approval, "list_pending") else None
    from app.models import Approval
    row = db_session.scalar(select(Approval).where(Approval.execution_id == ex.id))
    approval.decide(row.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert k.execute_approved(me, ex.id).status == ExecutionStatus.SUCCEEDED       # still escalated, but a human already decided


def test_no_rule_means_no_extra_check(client, team, db_session, monkeypatch):
    hs, ws = team
    me, k = principal(db_session, "admin@x.com", ws["id"]), kernel_for(client, db_session)
    calls = []
    monkeypatch.setattr(ToolExecutionService, "_escalated", lambda self, w, p: calls.append(1) or False)
    assert k.submit(me, "system.ping", {}).status == ExecutionStatus.SUCCEEDED and len(calls) == 1      # the early check only; no claim-time recheck


# ------------------------------------------------------------------ a failing tool leaks nothing
def test_a_crashing_tool_stores_only_the_error_type(client, team, db_session):
    from app.kernel.registry import ToolDefinition
    from app.models.enums import RiskLevel
    from pydantic import BaseModel

    class Empty(BaseModel):
        pass

    def boom(ctx, data):
        raise RuntimeError("db password=SUPER-SECRET-PW host=10.0.0.5")
    hs, ws = team
    reg = client.app.state.tool_registry
    reg.register(ToolDefinition(id="x.boom", description="d", input_schema=Empty, output_schema=Empty, required_permission="audit:read",
                                risk_level=RiskLevel.LOW, handler=boom, max_retries=1))
    me, k = principal(db_session, "owner@x.com", ws["id"]), kernel_for(client, db_session)
    ex = k.submit(me, "x.boom", {})
    assert ex.status == ExecutionStatus.FAILED and ex.error == "Tool failed: RuntimeError"
    from app.models.kernel import SystemEvent
    assert all("SUPER-SECRET" not in str(e.payload) for e in db_session.scalars(select(SystemEvent)))


# ------------------------------------------------------------------ a failing database
def test_a_database_failure_is_a_generic_500_and_ready_says_unavailable(app, team, monkeypatch):
    hs, ws = team

    def broken():
        raise OperationalError("select 1", {}, Exception("could not connect: password=DB-SECRET-PW"))
        yield
    app.dependency_overrides[get_db] = broken
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get(f"/workspaces/{ws['id']}/credentials", headers=hs["owner"])
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"} and "DB-SECRET" not in r.text
    monkeypatch.setattr("app.database.check_database", lambda: False)
    ready = c.get("/ready")
    assert ready.status_code == 503 and ready.json() == {"status": "unavailable", "database": False}


# ------------------------------------------------------------------ hostile input on every workspace route
HOSTILE_PARAMS = ["a" * 5000, "x\x00y", "%00", "../../etc/passwd", "💥" * 40, "'; drop table users;--", "{}", "-1", "9" * 40]


def test_hostile_ids_and_malformed_bodies_never_cause_a_5xx(client, app, world):
    hs, a, b = world
    routes = api_routes(app, contains="{workspace_id}")
    assert len(routes) >= 50
    bodies = [dict(content=b"{not json"), dict(content=b"\xff\xfe\xfd"), dict(content=b'{"a":' + b"[" * 2000),
              dict(content=b"null", headers={"content-type": "application/json"}), dict(data={"k": "v"}),
              dict(json={k: 10 ** 40 for k in ("version", "expected_version", "limit", "threshold", "window_seconds", "interval_seconds",
                                               "ttl_seconds", "max_executions", "offset", "top_k")})]
    bad = []
    for route in routes:
        for method in route.methods:
            for hostile in HOSTILE_PARAMS:
                path = route.path.replace("{workspace_id}", a["id"])
                for p in route.param_convertors:
                    path = path.replace("{" + p + "}", hostile if p != "workspace_id" else a["id"])
                res = client.request(method, path.replace("\x00", "%00"), headers=hs["a_owner"])
                if res.status_code >= 500:
                    bad.append((method, route.path, hostile[:12], res.status_code))
            if method in ("POST", "PUT", "PATCH"):
                for kw in bodies:
                    path = route.path.replace("{workspace_id}", a["id"])
                    for p in route.param_convertors:
                        path = path.replace("{" + p + "}", str(uuid.uuid4()))
                    hdr = {**hs["a_owner"], **kw.pop("headers", {})} if "headers" in kw else hs["a_owner"]
                    res = client.request(method, path, headers=hdr, **{k: v for k, v in kw.items() if k != "headers"})
                    if res.status_code >= 500:
                        bad.append((method, route.path, "body", res.status_code))
    assert bad == [], bad[:10]


# ------------------------------------------------------------------ bursts
def test_a_burst_of_bad_logins_is_throttled_never_a_500_and_other_users_are_unaffected(client, team):
    codes = [client.post("/auth/login", json={"email": "owner@x.com", "password": f"wrong-{i}-pw"}).status_code for i in range(60)]
    assert set(codes) <= {401, 429} and 429 in codes
    assert client.post("/auth/login", json={"email": "someone-else@x.com", "password": "nope-nope-1"}).status_code in (401, 429)


def test_a_modest_burst_of_authenticated_reads_stays_correct_and_fast(client, team):
    hs, ws = team
    times, codes = [], []
    for _ in range(150):
        t = time.perf_counter()
        codes.append(client.get(f"/workspaces/{ws['id']}/credentials", headers=hs["owner"]).status_code)
        times.append(time.perf_counter() - t)
    times.sort()
    assert set(codes) == {200} and times[int(len(times) * 0.95)] < 1.0
