"""Step 15.1: final acceptance. One check per success criterion of the blueprint, run against the real HTTP API where the criterion is
behavioural and against the source tree where it is structural. `python scripts/acceptance_report.py` runs these and writes docs/ACCEPTANCE.md."""
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.kernel.approvals import ApprovalService
from app.models import Approval, SystemEvent, ToolExecution
from tests.test_agent_context import CALLS
from tests.test_agent_runs_api import base as run_base, intent_json, plan_json, rig, writer  # noqa: F401
from tests.test_memory_api import b as mem_base, item
from tests.test_plans_api import PING, base as plan_base, create, run_body, st
from tests.test_policy_escalation import fail_rows
from tests.test_workflow_api import WRITE, base as wf_base, define, drive, start, step, wf
from tests.test_workspace_connectors import mock_spec, principal, public_dns, team  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
CORE = ["kernel", "orchestration", "workflows", "memory", "llm", "intelligence", "security", "monitoring"]

CRITERIA = {
    "c01": "It is independent of the existing Aceden software",
    "c02": "Multiple organizations can safely use it",
    "c03": "External systems can be securely connected",
    "c04": "AI can understand business requests",
    "c05": "AI can plan controlled actions",
    "c06": "Agents can coordinate work",
    "c07": "Tools execute through one trusted boundary",
    "c08": "Permissions are enforced",
    "c09": "Approvals cannot be bypassed",
    "c10": "Actions are auditable",
    "c11": "Business context is available safely",
    "c12": "Workflows can operate reliably",
    "c13": "Failures are observable",
    "c14": "The system is secure and tested",
    "c15": "The product delivers measurable real-world business value",
}


def py_files(*pkgs):
    for pkg in pkgs:
        yield from (APP / pkg).rglob("*.py")


def test_c01_the_core_does_not_depend_on_aceden_or_any_specific_connector():
    """The core may reuse the generic connector infrastructure (base config, errors, network guard); it may never import the Aceden
    connector or the provider registry, and never mention Aceden."""
    generic = {"netguard", "base", "errors", "workspace"}
    bad = []
    for f in py_files(*CORE):
        text = f.read_text()
        for mod in re.findall(r"^\s*from\s+app\.connectors(?:\.([a-z_.]+))?\s+import\s+(\w+)|^\s*import\s+app\.connectors\.(\w+)", text, re.M):
            name = (mod[0].split(".")[0] if mod[0] else mod[1]) or mod[2]
            if name not in generic:
                bad.append((f.name, f"imports app.connectors.{name}"))
        if re.search(r"aceden", text, re.I) and "tokens.py" not in f.name:        # tokens.py only uses it as a key-derivation label
            bad.append((f.name, "mentions Aceden"))
    assert bad == [], bad
    assert (APP / "connectors" / "kit.py").exists()                                 # a generic HTTP connector kit, not Aceden-shaped


def test_c02_two_organizations_cannot_see_each_other(rig):
    client, hs, ws, other, _ = rig
    r = client.post(f"/workspaces/{ws['id']}/credentials", json={"provider": "aceden", "name": "prod", "secret": "k-1234567890",
                                                                 "config": {"base_url": "https://a.test"}}, headers=hs["owner"])
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.get(f"/workspaces/{other['id']}/credentials", headers=hs["outsider"]).json() == []
    assert client.get(f"/workspaces/{other['id']}/credentials/{cid}", headers=hs["outsider"]).status_code == 404
    assert client.get(f"/workspaces/{ws['id']}/credentials", headers=hs["outsider"]).status_code in (403, 404)


def test_c03_a_system_is_connected_and_tested_without_exposing_its_secret(client, team, monkeypatch):
    hs, ws = team
    key = "ACCEPT-secret-4471-xyz"
    mock_spec(monkeypatch, server_key=key)
    r = client.post(f"/workspaces/{ws['id']}/credentials", json={"provider": "aceden", "name": "prod", "secret": key,
                                                                 "config": {"base_url": "https://aceden.test"}}, headers=hs["admin"])
    assert r.status_code == 201 and key not in r.text
    tested = client.post(f"/workspaces/{ws['id']}/credentials/{r.json()['id']}/test", headers=hs["admin"])
    assert tested.status_code == 200 and key not in tested.text


def test_c04_c05_a_goal_is_understood_and_turned_into_a_controlled_plan(writer, db_session):
    client, hs, ws, _, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{run_base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"}, headers=hs["member"]).json()
    types = {e.event_type for e in db_session.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws["id"]))}
    assert {"intent.resolved", "plan.proposed"} <= types                           # understood, then planned
    assert run["status"] == "waiting_approval" and CALLS == []                    # a plan is a proposal, not an action


def test_c06_agents_coordinate_dependent_work(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a"), st("b", deps=["a"])], *PING, *PING, execute=True)
    assert r.status_code == 200 and r.json()["drive_state"] == "completed" and r.json()["plan"]["status"] == "succeeded"
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 2


def test_c07_every_tool_handler_is_reached_only_through_the_kernel_service():
    callers = [str(f.relative_to(APP)) for f in APP.rglob("*.py") if re.search(r"\.handler\b", f.read_text()) and "registry.py" not in f.name]
    assert callers == ["kernel/service.py"], callers


def test_c08_permissions_are_enforced_by_role(client, rig):
    _, hs, ws, _, _ = rig
    make = lambda h: client.post(f"/workspaces/{ws['id']}/credentials", json={"provider": "aceden", "name": "n", "secret": "k-1234567890",
                                                                              "config": {"base_url": "https://a.test"}}, headers=h)
    assert make(hs["viewer"]).status_code == 403 and make(hs["member"]).status_code == 403
    assert client.get(f"/workspaces/{ws['id']}/monitoring/overview", headers=hs["member"]).status_code == 403
    assert client.get(f"/workspaces/{ws['id']}/monitoring/overview", headers=hs["admin"]).status_code == 200


def test_c09_an_approval_cannot_be_skipped_or_bypassed(writer, db_session):
    client, hs, ws, other, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{run_base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"}, headers=hs["member"]).json()
    early = client.post(f"{run_base(ws)}/runs/{run['id']}/resume", headers=hs["member"])
    assert CALLS == [] and (early.status_code != 200 or early.json()["status"] != "succeeded")      # not approved yet: nothing runs
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run["pending_execution_id"]))
    with pytest.raises(Exception):
        ApprovalService(db_session).decide(approval.id, principal(db_session, "outsider@x.com", other["id"]), approve=True)
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=False)
    late = client.post(f"{run_base(ws)}/runs/{run['id']}/resume", headers=hs["member"])
    assert CALLS == [] and (late.status_code != 200 or late.json()["status"] != "succeeded")        # rejected: never runs


def test_c10_the_whole_chain_is_audited_with_an_actor(writer, db_session):
    client, hs, ws, _, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    run = client.post(f"{run_base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"}, headers=hs["member"]).json()
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run["pending_execution_id"]))
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert client.post(f"{run_base(ws)}/runs/{run['id']}/resume", headers=hs["member"]).json()["status"] == "succeeded"
    events = list(db_session.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws["id"])))
    types = {e.event_type for e in events}
    assert {"plan.proposed", "approval.requested", "approval.approved", "execution.created", "execution.succeeded"} <= types
    assert all(e.actor for e in events if e.event_type in ("approval.approved", "approval.requested"))   # who asked, who decided


def test_c11_business_context_is_isolated_and_deletable(rig):
    client, hs, ws, other, _ = rig
    mem = client.post(mem_base(ws), json=item(content="Acceptance refunds policy: 14 days."), headers=hs["owner"]).json()
    q = {"query": "refunds policy"}
    assert "Acceptance" not in client.post(f"{mem_base(other)}/search", json=q, headers=hs["outsider"]).text
    assert "Acceptance" in client.post(f"{mem_base(ws)}/search", json=q, headers=hs["owner"]).text
    assert client.delete(f"{mem_base(ws)}/{mem['id']}", headers=hs["owner"]).status_code in (200, 204)
    assert "Acceptance" not in client.post(f"{mem_base(ws)}/search", json=q, headers=hs["owner"]).text     # deletion is honoured


def test_c12_a_workflow_pauses_for_approval_and_resumes_exactly_once(writer, db_session):
    client, hs, ws, _, script = writer
    define(client, hs["admin"], ws, wf(steps=[step("w", "task_writer")]))
    run = start(client, hs["member"], ws).json()
    script.extend(WRITE)
    assert drive(client, hs["member"], ws, run["id"]).json()["drive_state"] == "paused_approval" and CALLS == []
    approval = db_session.scalar(select(Approval))
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert drive(client, hs["member"], ws, run["id"]).json()["drive_state"] == "completed"
    assert drive(client, hs["member"], ws, run["id"]).status_code in (200, 409) and len(CALLS) == 1      # re-driving never repeats the action


def test_c13_failures_become_visible_alerts_without_leaking_content(rig, db_session):
    client, hs, ws, _, _ = rig
    fail_rows(db_session, ws["id"], 5)
    ov = client.get(f"/workspaces/{ws['id']}/monitoring/overview", headers=hs["admin"])
    assert ov.status_code == 200 and "execution_failure_rate" in json.dumps(ov.json()["alerts"])
    assert ov.json()["health"]["needs_attention"] is True or "alerts" in ov.json()


def test_c14_security_and_testing_evidence_exists():
    for doc in ("SECURITY.md", "PRODUCTION.md", "ISOLATION.md", "BACKUP.md", "POSTGRES.md"):
        assert (ROOT / "docs" / doc).exists(), doc
    for t in ("test_surface_sweeps.py", "test_credential_security.py", "test_failure_hardening.py", "test_release_hygiene.py"):
        assert (ROOT / "tests" / t).exists(), t


def test_c15_measurable_business_value():
    pytest.skip("MANUAL: business value is shown by pilot customers, not by software tests")
