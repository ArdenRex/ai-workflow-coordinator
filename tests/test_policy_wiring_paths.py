"""Substep 12.2c: a stored policy holds through plans and workflows, and no kernel in the app is built without a provider."""
import pathlib
import re

from sqlalchemy import select

from app.models import ToolExecution
from app.models.enums import ExecutionStatus
from tests.test_plans_api import PING, base as plan_base, create, run_body, st  # noqa: F401
from tests.test_workflow_api import base as wf_base, define, drive, start, step, wf  # noqa: F401
from tests.test_agent_runs_api import rig  # noqa: F401  (fixture)
from tests.test_policy_store import put


def pings_run(db):
    return [e for e in db.scalars(select(ToolExecution)) if e.tool_id == "system.ping" and e.status == ExecutionStatus.SUCCEEDED]


def test_a_stored_approval_rule_stops_a_plan_step_from_running_unattended(rig, db_session):
    client, hs, ws, _, script = rig
    assert put(client, hs["owner"], ws, expected_version=0, autonomy_level=3,
               approval_required_tools=["system.ping"]).status_code == 200
    r = create(client, hs["member"], ws, script, [st("a")])
    pid = r.json()["plan"]["id"]
    script.extend(PING)
    out = client.post(f"{plan_base(ws)}/{pid}/run", json=run_body(r), headers=hs["member"])
    assert out.status_code == 200, out.text
    assert out.json()["drive_state"] != "completed" and out.json()["plan"]["status"] != "succeeded"
    assert pings_run(db_session) == []


def test_a_stored_approval_rule_pauses_a_workflow_run_and_nothing_executes(rig, db_session):
    client, hs, ws, _, script = rig
    assert define(client, hs["admin"], ws, wf(steps=[step("a")])).status_code == 200
    assert put(client, hs["owner"], ws, expected_version=0, autonomy_level=3,
               approval_required_tools=["system.ping"]).status_code == 200
    run = start(client, hs["member"], ws).json()
    script.extend(PING)
    out = drive(client, hs["member"], ws, run["id"])
    assert out.status_code == 200, out.text
    assert out.json()["drive_state"] == "paused_approval" and out.json()["run"]["steps"][0]["status"] == "waiting_approval"
    assert pings_run(db_session) == []


def test_plan_and_workflow_baseline_is_unchanged_without_a_stored_policy(rig, db_session):
    client, hs, ws, _, script = rig
    r = create(client, hs["member"], ws, script, [st("a")])
    script.extend(PING)
    out = client.post(f"{plan_base(ws)}/{r.json()['plan']['id']}/run", json=run_body(r), headers=hs["member"])
    assert out.json()["drive_state"] == "completed" and len(pings_run(db_session)) == 1


def _calls(text, name):
    """Yield the full argument text of every `name(...)` call (balanced parentheses), skipping class definitions."""
    for m in re.finditer(r"(?<![\w.])" + name + r"\(", text):
        if text[max(0, m.start() - 6):m.start()] == "class ":
            continue
        depth, j = 1, m.end()
        while depth and j < len(text):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        yield text[m.end():j - 1]


def test_no_kernel_or_executor_in_the_app_is_built_without_a_policy_provider():
    """Closing guard: every construction site names its provider. A new bare site fails here, not in production."""
    seen = {"ToolExecutionService": 0, "AgentExecutor": 0}
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        text = path.read_text()
        for name, kw in (("ToolExecutionService", "policy_provider="), ("AgentExecutor", "base_policy_provider=")):
            for args in _calls(text, name):
                seen[name] += 1
                assert kw in args, (str(path), name, args[:80])
    assert seen["ToolExecutionService"] >= 5 and seen["AgentExecutor"] >= 4          # the scan really found the sites
