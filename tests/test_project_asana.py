"""Substep 10.3b: the project domain and the Asana connector (read-only, one configured workspace)."""
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.connectors import registry as creg
from app.connectors.base import ConnectorConfig
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorConfigError,
                                   ConnectorNotFoundError)
from app.connectors.kit import KitConnector, build_config
from app.connectors.project.asana import AsanaConnector, check_asana_config
from app.connectors.project.base import (GetTaskInput, ListProjectsInput, ListTasksInput, ProjectConnector,
                                         project_tool_definitions)
from app.kernel.errors import PolicyDeniedError, ToolInputError
from app.kernel.permissions import Principal
from app.models import ExecutionStatus, SystemEvent, ToolExecution
from app.models.enums import RiskLevel
from tests.domain_helpers import add_cred, make_rig
from tests.test_workspace_connectors import principal, public_dns, team  # noqa: F401
from tests.test_workspaces_api import mkws

TOKEN = "2/SECRET-ASANA-PAT-9917"
CANARY = "CANARY-asana-7742"
WS = "555"
URL = "https://asana.test/api/1.0"


def task(i, ws=WS, **kw):
    return {"gid": str(i), "name": f"Task {i}", "completed": False, "due_on": "2026-12-01", "modified_at": "2026-11-01T10:00:00Z",
            "assignee": {"gid": "9", "name": "Ada"}, "workspace": {"gid": ws}, "notes": f"notes {i}", "followers": [{"gid": "7"}],
            "custom_fields": [{"gid": "1"}], "permalink_url": "https://x", **kw}


class Fake:
    def __init__(self, key=TOKEN, tasks=None):
        self.key, self.log = key, []
        self.projects = {"101": {"ws": WS, "name": "Alpha"}, "102": {"ws": WS, "name": "Beta"}, "201": {"ws": "999", "name": "Other"},
                         "103": {"ws": WS, "name": "Old", "archived": True}}
        self.tasks = tasks if tasks is not None else [task(i) for i in range(1, 8)]
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, req):
        self.log.append(req)
        if req.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401)
        p, q = req.url.path.removeprefix("/api/1.0"), req.url.params
        if p == "/users/me":
            return httpx.Response(200, json={"data": {"gid": "1"}})
        if p == "/projects":
            rows = [{"gid": g, "name": v["name"]} for g, v in self.projects.items() if v["ws"] == q.get("workspace") and not v.get("archived")]
            return httpx.Response(200, json={"data": rows, "next_page": None})
        if p.startswith("/projects/"):
            v = self.projects.get(p.rsplit("/", 1)[1])
            return httpx.Response(200, json={"data": {"gid": p.rsplit("/", 1)[1], "workspace": {"gid": v["ws"]}, "archived": v.get("archived", False)}}) if v else httpx.Response(404)
        if p == "/tasks":
            limit, start = int(q.get("limit", "50")), int(q["offset"].removeprefix("off")) if q.get("offset") else 0
            rows = [t for t in self.tasks if not (t["completed"] and q.get("completed_since") == "now")][start:start + limit]
            more = start + limit < len(self.tasks)
            return httpx.Response(200, json={"data": rows, "next_page": {"offset": f"off{start + limit}", "uri": "x"} if more else None})
        if p.startswith("/tasks/"):
            t = next((t for t in self.tasks if t["gid"] == p.rsplit("/", 1)[1]), None)
            return httpx.Response(200, json={"data": t}) if t else httpx.Response(404)
        return httpx.Response(404)


def make(fake=None, token=TOKEN, ws=WS):
    fake = fake or Fake()
    return AsanaConnector(ConnectorConfig(base_url=URL, auth_token=SecretStr(token)), workspace_gid=ws,
                          transport=fake.transport, sleep=lambda s: None), fake


def with_body(body):
    return AsanaConnector(ConnectorConfig(base_url=URL, auth_token=SecretStr("t")), workspace_gid=WS,
                          transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), sleep=lambda s: None)


# ------------------------------------------------------------------ connector
def test_identity_capabilities_and_config_rules():
    c, _ = make()
    assert isinstance(c, KitConnector) and isinstance(c, ProjectConnector) and TOKEN not in repr(c)
    assert [x.name for x in c.capabilities()] == ["project.list", "task.list", "task.get"] and not any(x.write for x in c.capabilities())
    assert check_asana_config({"workspace_gid": "555"}) == "555"
    for bad in (None, {}, {"workspace_gid": 555}, {"workspace_gid": ""}, {"workspace_gid": "5/../6"}, {"workspace_gid": "12ab"}):
        with pytest.raises(ConnectorConfigError):
            check_asana_config(bad)
    for gid in ("", "x", "1/2"):
        with pytest.raises(ConnectorConfigError):
            AsanaConnector(ConnectorConfig(base_url=URL, auth_token=SecretStr("t")), workspace_gid=gid)


def test_list_projects_is_scoped_to_the_configured_workspace_and_skips_archived():
    c, fake = make()
    out = c.list_projects(ListProjectsInput())
    assert [(p.id, p.name) for p in out.projects] == [("101", "Alpha"), ("102", "Beta")] and out.next_cursor is None
    q = fake.log[-1].url.params
    assert q["workspace"] == WS and q["archived"] == "false"
    assert make(ws="999")[0].list_projects(ListProjectsInput()).projects[0].id == "201"


def test_list_tasks_checks_the_project_first_pages_and_allow_lists():
    c, fake = make()
    out = c.list_tasks(ListTasksInput(project_id="101", limit=3))
    assert [r.url.path.removeprefix("/api/1.0") for r in fake.log] == ["/projects/101", "/tasks"]
    assert [t.id for t in out.tasks] == ["1", "2", "3"] and out.next_cursor == "off3"
    assert set(out.tasks[0].model_dump()) == {"id", "name", "completed", "due_on", "assignee_name", "modified_at"}
    blob = json.dumps(out.model_dump())
    assert "followers" not in blob and "permalink" not in blob and "notes" not in blob and out.tasks[0].assignee_name == "Ada"
    rest = c.list_tasks(ListTasksInput(project_id="101", limit=3, cursor="off6"))
    assert [t.id for t in rest.tasks] == ["7"] and rest.next_cursor is None
    assert fake.log[-1].url.params["completed_since"] == "now" and fake.log[-1].url.params["project"] == "101"


def test_include_completed_drops_the_open_only_filter():
    done = Fake(tasks=[task(1), task(2, completed=True)])
    c, _ = make(done)
    assert [t.id for t in c.list_tasks(ListTasksInput(project_id="101")).tasks] == ["1"]
    assert [t.id for t in c.list_tasks(ListTasksInput(project_id="101", include_completed=True)).tasks] == ["1", "2"]


@pytest.mark.parametrize("project", ["201", "103", "999"])
def test_projects_outside_the_workspace_archived_or_missing_look_like_not_found_and_tasks_are_never_read(project):
    c, fake = make()
    with pytest.raises(ConnectorNotFoundError):
        c.list_tasks(ListTasksInput(project_id=project))
    assert all(not r.url.path.endswith("/tasks") for r in fake.log)


def test_get_task_returns_notes_and_enforces_workspace_and_id():
    c, _ = make(Fake(tasks=[task(1), task(2, ws="999")]))
    t = c.get_task(GetTaskInput(task_id="1")).task
    assert t.id == "1" and t.notes == "notes 1" and t.name == "Task 1"
    with pytest.raises(ConnectorNotFoundError):
        c.get_task(GetTaskInput(task_id="2"))                       # a task of another Asana workspace
    with pytest.raises(ConnectorNotFoundError):
        c.get_task(GetTaskInput(task_id="42"))
    with pytest.raises(ConnectorBadResponseError):
        with_body({"data": task(77)}).get_task(GetTaskInput(task_id="5"))


def test_free_text_is_cleaned_and_capped():
    t = make(Fake(tasks=[task(1, name="Fix\u202e\x00 it " + "n" * 900, notes="a\u200bb" + "z" * 5000)]))[0].get_task(GetTaskInput(task_id="1")).task
    assert t.name.startswith("Fix it ") and len(t.name) == 300 and t.notes.startswith("ab") and len(t.notes) == 2000


def test_missing_optional_fields_are_none():
    t = make(Fake(tasks=[{"gid": "5", "name": "n", "workspace": {"gid": WS}}]))[0].get_task(GetTaskInput(task_id="5")).task
    assert t.assignee_name is None and t.due_on is None and t.completed is None


@pytest.mark.parametrize("body", [[], "x", {}, {"data": "x"}, {"data": [5]}, {"data": [{"gid": "abc", "name": "n"}]},
                                  {"data": [{"gid": "1", "name": 5}]}, {"data": [], "next_page": {"offset": "bad offset!"}},
                                  {"data": [], "next_page": {"offset": 5}}])
def test_malformed_responses_are_bad_responses(body):
    with pytest.raises(ConnectorBadResponseError):
        with_body(body).list_projects(ListProjectsInput())


@pytest.mark.parametrize("bad", [{"assignee": "x"}, {"name": 5}, {"gid": "abc"}, {"completed": "yes"}])
def test_malformed_task_records_are_bad_responses(bad):
    c, _ = make(Fake(tasks=[{**task(1), **bad}]))
    with pytest.raises(ConnectorBadResponseError):
        c.list_tasks(ListTasksInput(project_id="101", include_completed=True))     # (the fake filters "open only" itself)


def test_only_get_requests_and_auth_failures_report_a_code_only():
    c, fake = make()
    c.list_projects(ListProjectsInput()); c.list_tasks(ListTasksInput(project_id="101")); c.get_task(GetTaskInput(task_id="1")); c.validate_connection()
    assert {r.method for r in fake.log} == {"GET"}
    bad, _ = make(Fake(key="other"))
    st = bad.validate_connection()
    assert st.ok is False and st.message == "connector_auth_failed" and TOKEN not in st.message
    with pytest.raises(ConnectorAuthError):
        bad.list_projects(ListProjectsInput())
    assert make()[0].validate_connection().ok is True


# ------------------------------------------------------------------ schemas and tools
@pytest.mark.parametrize("kw", [{"project_id": ""}, {"project_id": "1/../2"}, {"project_id": "abc"}, {"project_id": "1?x=y"},
                                {"project_id": "1", "limit": 0}, {"project_id": "1", "limit": 101}, {"project_id": "1", "cursor": "a b"},
                                {"project_id": "1", "cursor": "a/b"}, {"project_id": "1", "x": 1}, {"project_id": "١٢"}])
def test_invalid_task_list_inputs_are_rejected(kw):
    with pytest.raises(ValidationError):
        ListTasksInput(**kw)


@pytest.mark.parametrize("tid", ["", "abc", "1/../2", "-1", "1 2", "9" * 21, "1\n"])
def test_task_ids_cannot_alter_the_request_path(tid):
    with pytest.raises(ValidationError):
        GetTaskInput(task_id=tid)


def test_tools_are_low_risk_project_reads_and_the_spec_declares_the_domain():
    tools = project_tool_definitions(lambda ws: None)
    assert [t.id for t in tools] == ["project.project.list", "project.task.list", "project.task.get"]
    assert all(t.required_permission == "project:read" and t.risk_level == RiskLevel.LOW and not t.approval_required for t in tools)
    spec = creg.get_spec("asana")
    assert spec.domains == frozenset({"project"})
    with pytest.raises(ConnectorConfigError):
        creg.validate_config("asana", {"base_url": "https://app.asana.com/api/1.0"}, __import__("app.config", fromlist=["x"]).get_settings())


# ------------------------------------------------------------------ through the kernel
@pytest.fixture
def rig(db_session, monkeypatch):
    def build_for(r, config, secret, settings):
        fake = r.fakes.setdefault(secret, Fake(key=secret))
        return AsanaConnector(build_config(config, secret, settings), workspace_gid=check_asana_config(config),
                              transport=fake.transport, sleep=lambda s: None)
    r = make_rig(db_session, monkeypatch, "asana", {"project"}, build_for, check_asana_config)
    yield r
    r.wc.close()


def conn(client, h, ws, key=TOKEN, gid=WS, url=URL, name="pm"):
    return add_cred(client, h, ws, "asana", key, {"base_url": url, "workspace_gid": gid}, name)


def test_admin_reads_projects_and_tasks_through_the_kernel(client, team, rig):
    hs, ws = team
    conn(client, hs["admin"], ws)
    pr = rig.run("admin@x.com", ws, "project.project.list")
    assert pr.status == ExecutionStatus.SUCCEEDED and [p["id"] for p in pr.output["projects"]] == ["101", "102"]
    tl = rig.run("owner@x.com", ws, "project.task.list", {"project_id": "101", "limit": 2})
    assert tl.status == ExecutionStatus.SUCCEEDED and [t["id"] for t in tl.output["tasks"]] == ["1", "2"] and tl.output["next_cursor"] == "off2"
    tg = rig.run("admin@x.com", ws, "project.task.get", {"task_id": "3"})
    assert tg.status == ExecutionStatus.SUCCEEDED and tg.output["task"]["notes"] == "notes 3"
    assert TOKEN not in json.dumps([pr.output, tl.output, tg.output])


def test_other_workspace_projects_and_tasks_are_refused_through_the_kernel(client, team, rig):
    hs, ws = team
    conn(client, hs["admin"], ws)
    ex = rig.run("admin@x.com", ws, "project.task.list", {"project_id": "201"})
    assert ex.status == ExecutionStatus.FAILED and "ConnectorNotFoundError" in ex.error


def test_members_and_unscoped_agents_cannot_read_projects(client, team, rig):
    hs, ws = team
    conn(client, hs["admin"], ws)
    with pytest.raises(PolicyDeniedError):
        rig.run("member@x.com", ws, "project.project.list")
    p = principal(rig.db, "admin@x.com", ws["id"])
    narrow = Principal(user_id=p.user_id, workspace_id=p.workspace_id, permissions=p.permissions, agent="a", agent_scope=frozenset({"crm:read"}))
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(narrow, "project.task.get", {"task_id": "1"})
    broad = Principal(user_id=p.user_id, workspace_id=p.workspace_id, permissions=p.permissions, agent="a", agent_scope=frozenset({"project:read"}))
    assert rig.svc.submit(broad, "project.project.list", {}).status == ExecutionStatus.SUCCEEDED


def test_invalid_inputs_never_reach_asana(client, team, rig):
    hs, ws = team
    conn(client, hs["admin"], ws)
    for tool, data in (("project.task.get", {"task_id": "1/../2"}), ("project.task.list", {"project_id": "x"}),
                       ("project.task.list", {"project_id": "1", "limit": 500}), ("project.project.list", {"cursor": "a b"})):
        with pytest.raises(ToolInputError):
            rig.run("admin@x.com", ws, tool, data)
    assert not rig.fakes


def test_no_connection_revocation_and_two_providers_fail_safely(client, team, rig, monkeypatch):
    hs, ws = team
    assert rig.run("admin@x.com", ws, "project.project.list").status == ExecutionStatus.FAILED
    cid = conn(client, hs["admin"], ws)
    assert rig.run("admin@x.com", ws, "project.project.list").status == ExecutionStatus.SUCCEEDED
    monkeypatch.setitem(creg.SPECS, "otherpm", creg.ConnectorSpec("otherpm", creg.SPECS["asana"].build, frozenset({"project"})))
    add_cred(client, hs["admin"], ws, "otherpm", "tok-other-1", {"base_url": "https://o.test", "workspace_gid": "1"}, "second")
    two = rig.run("admin@x.com", ws, "project.project.list")
    assert two.status == ExecutionStatus.FAILED and "ConnectorConfigError" in two.error
    client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"])


def test_two_workspaces_use_their_own_tokens_and_workspace_gids(client, team, rig):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other Co")
    conn(client, hs["admin"], ws, key="tok-A-11111")
    conn(client, hs["outsider"], other, key="tok-B-22222", gid="999", url="https://other.test/api/1.0")
    a = rig.run("admin@x.com", ws, "project.project.list")
    b = rig.run("outsider@x.com", other, "project.project.list")
    assert [p["id"] for p in a.output["projects"]] == ["101", "102"] and [p["id"] for p in b.output["projects"]] == ["201"]


def test_credential_creation_requires_a_valid_workspace_gid_and_the_connection_test_works(client, team, rig):
    hs, ws = team
    for config in ({"base_url": URL}, {"base_url": URL, "workspace_gid": "abc"}, {"workspace_gid": "555"},
                   {"base_url": "http://127.0.0.1:9", "workspace_gid": "555"}):
        r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["admin"],
                        json={"provider": "asana", "name": "bad", "secret": "tok-123456", "config": config})
        assert r.status_code == 422, config
    cid = conn(client, hs["admin"], ws)
    t = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["admin"])
    assert t.status_code == 200 and t.json()["ok"] is True and t.json()["capabilities"] == ["project.list", "task.list", "task.get"]


def test_audit_never_holds_the_token_or_task_text(client, team, rig, db_session):
    hs, ws = team
    conn(client, hs["admin"], ws)
    rig.fakes[TOKEN] = Fake(tasks=[task(1, name=CANARY, notes=CANARY)])
    rig.run("admin@x.com", ws, "project.task.get", {"task_id": "1"})
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    assert TOKEN not in blob and CANARY not in blob
