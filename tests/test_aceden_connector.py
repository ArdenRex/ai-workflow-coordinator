import pathlib

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.aceden import AcedenConnector, aceden_tool_definitions
from app.connectors.aceden.schemas import GetTaskInput, ListTasksInput
from app.connectors.base import ConnectorConfig
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError, ConnectorNotFoundError
from app.kernel.errors import PolicyDeniedError, ToolInputError
from app.kernel.permissions import Principal
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from app.models import ExecutionStatus

pytestmark = pytest.mark.usefixtures("seed_workspaces")

TASK = {"id": 5, "title": "Fix bug", "description": "d", "assignee": "Ali", "deadline": None,
        "priority": "high", "status": "to_do", "workspace_id": 99, "source_message": "PRIVATE TEXT",
        "created_at": "2026-01-01T00:00:00", "updated_at": None, "unknown_field": 1}


def fake_aceden(log=None, key="key-A"):
    def handler(req: httpx.Request):
        if log is not None:
            log.append((req.url.path, dict(req.url.params), req.headers.get("x-api-key")))
        if req.headers.get("x-api-key") != key:
            return httpx.Response(401, json={"detail": "bad key"})
        if req.url.path == "/api/v1/tasks":
            return httpx.Response(200, json={"total": 1, "skip": 0, "limit": int(req.url.params.get("limit", 50)),
                                             "tasks": [TASK]})
        if req.url.path == "/api/v1/tasks/5":
            return httpx.Response(200, json=TASK)
        return httpx.Response(404, json={"detail": "Task not found."})
    return httpx.MockTransport(handler)


def conn(key="key-A", log=None, **kw):
    return AcedenConnector(ConnectorConfig(base_url="https://aceden.test", auth_token=SecretStr(key)),
                           transport=fake_aceden(log, key=kw.get("server_key", key)), sleep=lambda s: None)


# ---- connector -----------------------------------------------------------------
def test_requires_api_key():
    for tok in (None, SecretStr(""), SecretStr("   ")):
        with pytest.raises(ConnectorConfigError):
            AcedenConnector(ConnectorConfig(base_url="https://a.test", auth_token=tok))


def test_list_tasks_sends_only_set_filters_and_drops_extra_fields():
    log = []
    out = conn(log=log).list_tasks(ListTasksInput(status="to_do", limit=10))
    assert log[0] == ("/api/v1/tasks", {"status": "to_do", "skip": "0", "limit": "10"}, "key-A")
    dumped = out.model_dump()
    assert dumped["tasks"][0]["title"] == "Fix bug"
    flat = str(dumped)
    assert "PRIVATE TEXT" not in flat and "unknown_field" not in flat and "workspace_id" not in flat


def test_get_task_and_not_found():
    assert conn().get_task(GetTaskInput(task_id=5)).task.id == 5
    with pytest.raises(ConnectorNotFoundError):
        conn().get_task(GetTaskInput(task_id=404))


def test_unexpected_remote_shape_rejected():
    c = AcedenConnector(ConnectorConfig(base_url="https://a.test", auth_token=SecretStr("k")),
                        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"nope": 1})))
    with pytest.raises(ConnectorBadResponseError):
        c.list_tasks(ListTasksInput())


def test_connection_validation():
    assert conn().validate_connection().ok is True
    bad = conn(server_key="other").validate_connection()
    assert bad.ok is False and bad.message == "connector_auth_failed"


def test_capabilities_are_read_only_and_key_not_in_repr():
    c = conn()
    assert all(not cap.write for cap in c.capabilities()) and "key-A" not in repr(c)


def test_connector_does_not_import_aceden_app_code():
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "connectors" / "aceden"
    for f in root.rglob("*.py"):
        text = f.read_text()
        assert "ai-workflow-coordinator" not in text and "from app.routers" not in text


# ---- through the kernel ------------------------------------------------------
@pytest.fixture
def kernel(db_session):
    logs = {"w1": [], "w2": []}
    conns = {"w1": conn("key-A", logs["w1"]), "w2": conn("key-B", logs["w2"])}
    registry = ToolRegistry()
    for t in aceden_tool_definitions(lambda ws: conns[ws]):
        registry.register(t)
    return ToolExecutionService(db_session, registry), logs


def P(ws="w1", perms=("task:read",)):
    return Principal(user_id="u1", workspace_id=ws, permissions=frozenset(perms))


def test_tools_run_through_kernel_and_are_audited(kernel):
    svc, logs = kernel
    ex = svc.submit(P(), "aceden.task.list", {"status": "to_do"})
    assert ex.status == ExecutionStatus.SUCCEEDED and ex.output["tasks"][0]["id"] == 5
    ex2 = svc.submit(P(), "aceden.task.get", {"task_id": 5})
    assert ex2.output["task"]["title"] == "Fix bug"
    assert [e.event_type for e in svc.audit_trail(ex.id, "w1")] == [
        "execution.created", "execution.started", "execution.succeeded"]


def test_each_workspace_uses_its_own_credentials(kernel):
    svc, logs = kernel
    svc.submit(P("w1"), "aceden.task.list", {})
    svc.submit(P("w2"), "aceden.task.list", {})
    assert logs["w1"][0][2] == "key-A" and logs["w2"][0][2] == "key-B"


def test_kernel_blocks_without_permission(kernel):
    svc, logs = kernel
    with pytest.raises(PolicyDeniedError):
        svc.submit(P(perms=("other:read",)), "aceden.task.list", {})
    assert logs["w1"] == []


def test_kernel_rejects_bad_input_before_any_network_call(kernel):
    svc, logs = kernel
    for bad in ({"limit": 5000}, {"status": "weird"}, {"extra": 1}, {"assignee": ""}):
        with pytest.raises(ToolInputError):
            svc.submit(P(), "aceden.task.list", bad)
    with pytest.raises(ToolInputError):
        svc.submit(P(), "aceden.task.get", {"task_id": "5/../../admin"})
    assert logs["w1"] == []


def test_remote_not_found_becomes_failed_execution_with_safe_error(kernel):
    svc, _ = kernel
    ex = svc.submit(P(), "aceden.task.get", {"task_id": 404})
    assert ex.status == ExecutionStatus.FAILED and ex.error == "Tool failed: ConnectorNotFoundError"


def test_planner_description_has_no_credentials_or_handlers(kernel):
    svc, _ = kernel
    for t in svc.registry.list():
        d = str(t.describe())
        assert "key-A" not in d and "handler" not in d


def test_connector_tools_helper_registers_cleanly():
    reg = ToolRegistry()
    for t in conn().tools():
        reg.register(t)
    assert [t.id for t in reg.list()] == ["aceden.task.get", "aceden.task.list"]
