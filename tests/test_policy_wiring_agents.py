"""Substep 12.2b: a stored workspace policy takes effect on agent runs (and every executor built by plans and workflows)."""
import pathlib

from sqlalchemy import select

from app.models import ToolExecution
from app.models.enums import ExecutionStatus
from tests.test_agent_runs_api import rig, start  # noqa: F401  (rig is a fixture)
from tests.test_policy_store import put


def succeeded_pings(db):
    return [e for e in db.scalars(select(ToolExecution)) if e.tool_id == "system.ping" and e.status == ExecutionStatus.SUCCEEDED]


def test_agent_run_baseline_then_stored_approval_rule_parks_it(rig, db_session):
    client, hs, ws, _, script = rig
    assert start(client, hs["member"], ws, script).json()["status"] == "succeeded"          # no row = today's behaviour
    n = len(succeeded_pings(db_session))
    assert put(client, hs["owner"], ws, expected_version=0, autonomy_level=3,
               approval_required_tools=["system.ping"]).status_code == 200
    r = start(client, hs["member"], ws, script)
    assert r.status_code == 201 and r.json()["status"] == "waiting_approval", r.text       # the stored rule now binds the agent
    assert len(succeeded_pings(db_session)) == n                                           # nothing ran unattended


def test_agent_run_with_a_stored_disable_never_executes_the_tool(rig, db_session):
    client, hs, ws, _, script = rig
    assert put(client, hs["owner"], ws, expected_version=0, autonomy_level=3,
               disabled_tools=["system.ping"]).status_code == 200
    r = start(client, hs["member"], ws, script)
    assert r.json().get("status") != "succeeded" or r.json()["result"]["outcome"] != "executed"
    assert succeeded_pings(db_session) == []


def test_a_stored_policy_in_one_workspace_does_not_bind_another(rig, db_session):
    client, hs, ws, other, script = rig
    assert put(client, hs["owner"], ws, expected_version=0, autonomy_level=3,
               approval_required_tools=["system.ping"]).status_code == 200
    r = start(client, hs["outsider"], other, script)
    assert r.json()["status"] == "succeeded"


def test_every_executor_in_the_api_layer_is_built_with_the_stored_policy():
    for name, expected in (("agent_runs", 2), ("plans", 1), ("workflows", 1)):
        text = pathlib.Path(f"app/api/{name}.py").read_text()
        assert text.count("AgentExecutor(") == expected, name
        assert text.count("base_policy_provider=session_policy_provider(db)") == expected, name
