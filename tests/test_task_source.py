"""
Task.source ("slack" | "gmail" | "whatsapp" | None) — the value behind the
source badge. Rules are pure; the API tests need a migrated Postgres (skipped
otherwise), like the other DB tests.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Priority, Task, TaskStatus
from app.schemas import TaskResponse


# ── the rules ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fields,expected", [
    ({"whatsapp_message_id": "wamid.1"}, "whatsapp"),
    ({"gmail_message_id": "18c2f"}, "gmail"),
    ({"slack_message_ts": "1700000000.000100"}, "slack"),
    ({"slack_channel_id": "C123"}, "slack"),
    ({"slack_channel_id": "C123", "slack_message_ts": "1.1"}, "slack"),
    ({}, None),                                           # manual / forwarded email / Teams / API
    ({"source_message": "[API] zapier"}, None),
    ({"whatsapp_message_id": "", "gmail_message_id": None}, None),   # empty values don't count
    ({"whatsapp_message_id": "w", "gmail_message_id": "g"}, "whatsapp"),   # defined precedence
    ({"gmail_message_id": "g", "slack_channel_id": "C1"}, "gmail"),
])
def test_source_rules(fields, expected):
    assert Task(**fields).source == expected


def _task(**fields):
    now = datetime.now(timezone.utc)
    return Task(id=1, title="t", priority=Priority.medium, status=TaskStatus.to_do,
                created_at=now, updated_at=now, **fields)


def test_schema_includes_source_and_does_not_leak_message_ids():
    out = TaskResponse.model_validate(_task(whatsapp_message_id="wamid.secret")).model_dump(mode="json")
    assert out["source"] == "whatsapp"
    assert "whatsapp_message_id" not in out and "gmail_message_id" not in out
    assert TaskResponse.model_validate(_task()).model_dump(mode="json")["source"] is None


# ── through the real API ─────────────────────────────────────────────────────
@pytest.fixture
def api():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal()
        s.execute(text("select whatsapp_message_id from tasks limit 1"))
        s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")

    from fastapi import Depends
    from app.auth import get_current_user
    from app.database import SessionLocal, get_db
    from app.models import User, UserRole, Workspace
    from app.routers import tasks as tasks_router

    s = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    ws = Workspace(name=f"ws-{tag}"); s.add(ws); s.commit(); s.refresh(ws)
    user = User(email=f"src-{tag}@example.com", name="Mgr", workspace_id=ws.id, role=UserRole.architect)
    s.add(user); s.commit(); s.refresh(user)

    def mk(title, **kw):
        t = Task(title=title, task_description=title, priority=Priority.medium, status=TaskStatus.to_do,
                 workspace_id=ws.id, owner_id=user.id, share_token=uuid.uuid4().hex[:20], **kw)
        s.add(t); s.commit(); s.refresh(t)
        return t

    made = {
        "whatsapp": mk("from whatsapp", whatsapp_message_id=f"wamid.{tag}"),
        "gmail":    mk("from gmail", gmail_message_id=f"g{tag}"),
        "slack":    mk("from slack", slack_channel_id="C1", slack_message_ts=f"{tag}.1"),
        "manual":   mk("typed in by hand"),
    }

    app = FastAPI(); app.include_router(tasks_router.router)
    app.dependency_overrides[get_current_user] = lambda db=Depends(get_db): db.get(User, user.id)
    client = TestClient(app)
    yield client, made

    for t in made.values():
        s.delete(s.get(Task, t.id))
    s.commit(); s.delete(s.get(User, user.id)); s.commit(); s.delete(s.get(Workspace, ws.id)); s.commit(); s.close()


def test_list_endpoints_return_source(api):
    client, made = api
    for path in ("/tasks/", "/tasks/team"):
        r = client.get(path, params={"limit": 200})
        assert r.status_code == 200, (path, r.text)
        by_title = {t["title"]: t for t in r.json()["tasks"]}
        assert by_title["from whatsapp"]["source"] == "whatsapp"
        assert by_title["from gmail"]["source"] == "gmail"
        assert by_title["from slack"]["source"] == "slack"
        assert by_title["typed in by hand"]["source"] is None
        assert all("whatsapp_message_id" not in t and "gmail_message_id" not in t for t in by_title.values())


def test_single_task_endpoint_returns_source(api):
    client, made = api
    r = client.get(f"/tasks/{made['whatsapp'].id}")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "whatsapp"


def test_ownership_graph_tasks_carry_source(api):
    """The 'All Tasks' panel on the graph view is fed by /tasks/graph, which builds its own task dicts."""
    client, made = api
    r = client.get("/tasks/graph")
    assert r.status_code == 200, r.text
    tasks = {t["title"]: t for node in r.json()["nodes"] for t in node["tasks"]}
    assert tasks["from whatsapp"]["source"] == "whatsapp"
    assert tasks["from gmail"]["source"] == "gmail"
    assert tasks["from slack"]["source"] == "slack"
    assert tasks["typed in by hand"]["source"] is None
