"""Step 14.5: production configuration review and the end-to-end journey from the blueprint."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.kernel.approvals import ApprovalService
from app.main import create_app
from app.models import Approval, SystemEvent
from tests.test_agent_context import CALLS
from tests.test_agent_runs_api import base, intent_json, plan_json, rig, writer  # noqa: F401
from tests.test_workspace_connectors import principal

PROD = dict(app_env="production", app_secret_key="k" * 40, database_url="postgresql://u:p@h/db", llm_provider="openai_compatible",
            llm_base_url="https://llm.example/v1", llm_api_key="z", _env_file=None)


def prod(**over):
    return Settings(**{**PROD, **over})


def test_the_reference_production_settings_are_valid():
    assert prod().is_production


@pytest.mark.parametrize("over", [
    {"app_secret_key": "short"}, {"database_url": "sqlite:///./x.db"}, {"llm_provider": "fake", "llm_base_url": None, "llm_api_key": None},
    {"allowed_origins": "*"}, {"auth_max_failed_logins": 0}, {"auth_max_requests_per_minute": 0},
    {"allow_private_connector_hosts": True}, {"connector_max_calls_per_minute": 0},
    {"llm_base_url": "http://llm.example/v1"}, {"aceden_base_url": "http://a.example", "aceden_api_key": "k"},
    {"app_secret_key_previous": "tooshort"},
])
def test_production_refuses_every_unsafe_setting(over):
    with pytest.raises(ValidationError):
        prod(**over)


def test_development_keeps_its_conveniences():
    s = Settings(app_env="development", allow_private_connector_hosts=True, connector_max_calls_per_minute=0, _env_file=None)
    assert s.allow_private_connector_hosts and not s.is_production


def test_production_app_exposes_no_schema_or_docs_and_a_minimal_health(monkeypatch):
    s = prod()
    monkeypatch.setattr("app.api.health.get_settings", lambda: s)
    c = TestClient(create_app(s))
    assert c.get("/openapi.json").status_code == 404 and c.get("/docs").status_code == 404 and c.get("/redoc").status_code == 404
    assert c.get("/health").json() == {"status": "ok", "service": s.app_name}
    assert c.get("/health").headers["x-content-type-options"] == "nosniff"


def test_development_app_keeps_docs_and_a_full_health(client):
    assert client.get("/openapi.json").status_code == 200 and client.get("/health").json()["version"]


def test_the_example_env_file_matches_the_real_settings():
    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    keys = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, re.M))
    fields = {f.upper() for f in Settings.model_fields}
    assert keys <= fields, f"in .env.example but not a setting: {sorted(keys - fields)}"
    assert "ALLOW_PRIVATE_CONNECTOR_HOSTS" in keys and "APP_SECRET_KEY" in keys


def test_the_container_runs_as_a_non_root_user_and_migrates_before_serving():
    d = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text()
    assert re.search(r"^USER app$", d, re.M) and d.index("USER app") < d.index("CMD")
    assert d.index("alembic upgrade head") < d.index("uvicorn")


# ---------------------------------------------------------------- the blueprint's journey, end to end over HTTP
def test_the_whole_journey_plan_approve_execute_verify_audit(writer, db_session):
    client, hs, ws, other, script = writer
    script.extend([intent_json("notes.task.update"), plan_json("notes.task.update", {"task_id": 5})])
    # goal -> controlled plan -> permissions and policy -> approval required, nothing executed yet
    run = client.post(f"{base(ws)}/runs", json={"agent_id": "task_writer", "goal": "update task five"}, headers=hs["member"]).json()
    assert run["status"] == "waiting_approval" and CALLS == []
    # an outsider and an agent cannot decide; a human owner does; deciding alone executes nothing
    approval = db_session.scalar(select(Approval).where(Approval.execution_id == run["pending_execution_id"]))
    with pytest.raises(Exception):
        ApprovalService(db_session).decide(approval.id, principal(db_session, "outsider@x.com", other["id"]), approve=True)
    ApprovalService(db_session).decide(approval.id, principal(db_session, "owner@x.com", ws["id"]), approve=True)
    assert CALLS == []
    # the run's owner resumes -> exactly one execution, result reported
    done = client.post(f"{base(ws)}/runs/{run['id']}/resume", headers=hs["member"])
    assert done.status_code == 200 and done.json()["status"] == "succeeded" and len(CALLS) == 1
    # everything is audited, only in this workspace, and the other workspace sees none of it
    types = {e.event_type for e in db_session.scalars(select(SystemEvent).where(SystemEvent.workspace_id == ws["id"]))}
    assert {"plan.proposed", "approval.requested", "approval.approved", "execution.created", "execution.succeeded", "agent_run.succeeded"} <= types, types
    assert db_session.scalar(select(SystemEvent).where(SystemEvent.workspace_id == other["id"],
                                                       SystemEvent.event_type.like("approval%"))) is None
    # the business can see it: the monitoring overview (admin) reports the run, and a member cannot read it
    ov = client.get(f"/workspaces/{ws['id']}/monitoring/overview", headers=hs["admin"])
    assert ov.status_code == 200 and set(ov.json()) >= {"summary", "health", "alerts"}
    assert client.get(f"/workspaces/{ws['id']}/monitoring/overview", headers=hs["member"]).status_code == 403
