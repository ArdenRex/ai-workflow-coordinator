"""Substep 10.2: the CRM domain interface and the HubSpot connector (read-only)."""
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.connectors import registry as creg
from app.connectors.base import ConnectorConfig
from app.connectors.crm.base import (CrmConnector, GetLeadInput, ListLeadsInput, crm_tool_definitions)
from app.connectors.crm.hubspot import HubSpotConnector
from app.connectors.errors import (ConnectorAuthError, ConnectorBadResponseError, ConnectorNotFoundError,
                                   ConnectorRateLimitedError)
from app.connectors.kit import KitConnector, build_config
from app.connectors.registry import ConnectorSpec
from app.connectors.workspace import WorkspaceConnectors, register_workspace_tools
from app.kernel.errors import PolicyDeniedError
from app.kernel.permissions import Principal
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from app.models import ExecutionStatus, SystemEvent
from app.models.enums import RiskLevel, Role
from app.identity.roles import permissions_for
from tests.test_workspace_connectors import principal, public_dns, team  # noqa: F401
from tests.test_workspaces_api import mkws

TOKEN = "pat-na1-SECRET-TOKEN-7731"
CANARY = "CANARY-crm-5521"


def contact(i, first="Ada", last="Lovelace", email=None, company="Analytical", stage="lead", archived=False, **extra):
    props = {"firstname": first, "lastname": last, "email": email or f"ada{i}@example.com", "company": company,
             "lifecyclestage": stage, "phone": "+1-555-0100", "address": "1 Secret St", "notes": CANARY, **extra}
    return {"id": str(i), "properties": props, "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-02-01T00:00:00Z",
            "archived": archived, "owner": "someone"}


class Fake:
    """In-memory HubSpot: bearer auth, paging via `after`, one record GET, and a request log."""
    def __init__(self, key=TOKEN, total=7):
        self.key, self.log, self.total = key, [], total
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request):
        self.log.append(req)
        if req.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401)
        path = req.url.path
        if path == "/crm/v3/objects/contacts":
            limit = int(req.url.params.get("limit", "10"))
            start = int(req.url.params.get("after", "0"))
            rows = [contact(i) for i in range(start + 1, min(start + limit, self.total) + 1)]
            body = {"results": rows}
            if start + limit < self.total:
                body["paging"] = {"next": {"after": str(start + limit)}}
            return httpx.Response(200, json=body)
        if path.startswith("/crm/v3/objects/contacts/"):
            i = path.rsplit("/", 1)[1]
            if i.isdigit() and 1 <= int(i) <= self.total:
                return httpx.Response(200, json=contact(int(i)))
            return httpx.Response(404)
        return httpx.Response(404)


def make(fake=None, token=TOKEN):
    fake = fake or Fake()
    c = HubSpotConnector(ConnectorConfig(base_url="https://api.hubspot.test", auth_token=SecretStr(token)),
                         transport=fake.transport, sleep=lambda s: None)
    return c, fake


# ------------------------------------------------------------------ connector
def test_connector_is_a_kit_connector_and_a_crm_connector_with_two_capabilities():
    c, _ = make()
    assert isinstance(c, KitConnector) and isinstance(c, CrmConnector)
    assert [x.name for x in c.capabilities()] == ["lead.list", "lead.get"] and not any(x.write for x in c.capabilities())
    assert TOKEN not in repr(c)


def test_list_leads_returns_the_allow_listed_shape_and_a_cursor():
    c, fake = make()
    out = c.list_leads(ListLeadsInput(limit=3))
    assert [l.id for l in out.leads] == ["1", "2", "3"] and out.next_cursor == "3"
    d = out.leads[0].model_dump()
    assert set(d) == {"id", "first_name", "last_name", "email", "company", "stage", "created_at", "updated_at"}
    assert d["first_name"] == "Ada" and d["stage"] == "lead" and d["created_at"] == "2026-01-01T00:00:00Z"
    blob = json.dumps(out.model_dump())
    assert "555-0100" not in blob and "Secret St" not in blob and CANARY not in blob and "someone" not in blob
    req = fake.log[-1]
    assert req.method == "GET" and req.url.params["limit"] == "3" and req.url.params["archived"] == "false"
    assert "firstname" in req.url.params["properties"] and "phone" not in req.url.params["properties"]


def test_paging_walks_to_the_end_with_no_cursor():
    c, _ = make()
    seen, cursor = [], None
    for _ in range(5):
        out = c.list_leads(ListLeadsInput(limit=3, cursor=cursor))
        seen += [l.id for l in out.leads]
        cursor = out.next_cursor
        if cursor is None:
            break
    assert seen == [str(i) for i in range(1, 8)] and cursor is None


def test_get_lead_and_missing_lead():
    c, _ = make()
    assert c.get_lead(GetLeadInput(lead_id="4")).lead.id == "4"
    with pytest.raises(ConnectorNotFoundError):
        c.get_lead(GetLeadInput(lead_id="99"))


def test_only_get_requests_are_ever_sent():
    c, fake = make()
    c.list_leads(ListLeadsInput())
    c.get_lead(GetLeadInput(lead_id="1"))
    c.validate_connection()
    assert {r.method for r in fake.log} == {"GET"}


def test_wrong_token_is_an_auth_error_and_the_connection_check_reports_a_code_only():
    c, _ = make(Fake(key="other"))
    with pytest.raises(ConnectorAuthError):
        c.list_leads(ListLeadsInput())
    st = c.validate_connection()
    assert st.ok is False and st.message == "connector_auth_failed" and TOKEN not in st.message
    assert make()[0].validate_connection().ok is True


def test_archived_records_are_skipped_and_the_page_never_exceeds_the_limit():
    def handler(req):
        return httpx.Response(200, json={"results": [contact(1), contact(2, archived=True)] + [contact(i) for i in range(3, 12)]})
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t")),
                         transport=httpx.MockTransport(handler), sleep=lambda s: None)
    out = c.list_leads(ListLeadsInput(limit=4))
    assert [l.id for l in out.leads] == ["1", "3", "4", "5"] and out.next_cursor is None


def test_free_text_is_cleaned_and_capped():
    def handler(req):
        return httpx.Response(200, json={"results": [contact(1, first="Ada\u202e\x00!", company="C" * 500,
                                                             email="a@b.co\u200b")]})
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t")),
                         transport=httpx.MockTransport(handler), sleep=lambda s: None)
    lead = c.list_leads(ListLeadsInput()).leads[0]
    assert lead.first_name == "Ada!" and len(lead.company) == 200 and lead.email == "a@b.co"


def test_missing_properties_become_none():
    def handler(req):
        return httpx.Response(200, json={"results": [{"id": "9"}, {"id": "10", "properties": None}]})
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t")),
                         transport=httpx.MockTransport(handler), sleep=lambda s: None)
    leads = c.list_leads(ListLeadsInput()).leads
    assert [l.id for l in leads] == ["9", "10"] and leads[0].email is None and leads[1].first_name is None


@pytest.mark.parametrize("body", [
    [], "text", {"results": "x"}, {"results": [5]}, {"results": [{"id": "abc"}]}, {"results": [{"id": "1", "properties": []}]},
    {"results": [{"id": "1", "properties": {"email": 5}}]}, {"results": [{"id": "1", "properties": {"company": {"a": 1}}}]},
    {"results": [], "paging": {"next": {"after": "bad cursor!"}}}, {"results": [], "paging": {"next": {"after": 5}}},
    {"results": [], "paging": {"next": []}},
])
def test_malformed_responses_are_bad_responses_not_crashes(body):
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t")),
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), sleep=lambda s: None)
    with pytest.raises(ConnectorBadResponseError):
        c.list_leads(ListLeadsInput())


def test_get_lead_must_answer_for_the_requested_id():
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t")),
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, json=contact(77))), sleep=lambda s: None)
    with pytest.raises(ConnectorBadResponseError):
        c.get_lead(GetLeadInput(lead_id="5"))


def test_rate_limits_surface_as_retryable_after_bounded_get_retries():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"})
    c = HubSpotConnector(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr("t"), max_retries=1),
                         transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ConnectorRateLimitedError):
        c.list_leads(ListLeadsInput())
    assert len(calls) == 2


# ------------------------------------------------------------------ input schemas
@pytest.mark.parametrize("kw", [{"limit": 0}, {"limit": 101}, {"cursor": "bad cursor"}, {"cursor": "a/b"}, {"cursor": ""},
                                {"cursor": "x" * 65}, {"extra": 1}, {"limit": "ten"}])
def test_invalid_list_inputs_are_rejected(kw):
    with pytest.raises(ValidationError):
        ListLeadsInput(**kw)


@pytest.mark.parametrize("lead_id", ["", "abc", "1/../2", "1?x=y", "-1", "1 2", "9" * 21, "١٢٣", "1\n"])
def test_lead_ids_cannot_alter_the_request_path(lead_id):
    with pytest.raises(ValidationError):
        GetLeadInput(lead_id=lead_id)
    with pytest.raises(ValidationError):
        GetLeadInput(lead_id="1", extra=2)


# ------------------------------------------------------------------ tools and registry
def test_tool_definitions_are_low_risk_reads_with_crm_read_and_no_approval():
    tools = crm_tool_definitions(lambda ws: None)
    assert [t.id for t in tools] == ["crm.lead.list", "crm.lead.get"]
    assert all(t.required_permission == "crm:read" and t.risk_level == RiskLevel.LOW and not t.approval_required for t in tools)


def test_registry_registers_crm_tools_next_to_aceden_tools(db_session):
    wc = WorkspaceConnectors(sessionmaker(bind=db_session.get_bind()), get_settings())
    reg = register_workspace_tools(ToolRegistry(), wc)
    ids = {t.id for t in reg.list()} if hasattr(reg, "list") else set()
    assert {"crm.lead.list", "crm.lead.get", "aceden.task.list"} <= ids


def test_spec_declares_the_crm_domain_and_builds_through_the_ssrf_guard(monkeypatch):
    spec = creg.get_spec("hubspot")
    assert spec.domains == frozenset({"crm"})
    with pytest.raises(Exception):
        spec.build({"base_url": "http://127.0.0.1:9"}, "tok", get_settings())
    with pytest.raises(Exception):
        creg.validate_config("hubspot", {}, get_settings())


# ------------------------------------------------------------------ end to end through the kernel
def add_hubspot(client, h, ws, key=TOKEN, name="crm", url="https://api.hubspot.test"):
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=h,
                    json={"provider": "hubspot", "name": name, "secret": key, "config": {"base_url": url}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def rig(db_session, monkeypatch):
    class Rig:
        fakes = {}

    def build(config, secret, settings, **kw):
        fake = Rig.fakes.setdefault(secret, Fake(key=secret))
        return HubSpotConnector(build_config(config, secret, settings), transport=fake.transport, sleep=lambda s: None)
    monkeypatch.setitem(creg.SPECS, "hubspot", ConnectorSpec("hubspot", build, frozenset({"crm"})))
    wc = WorkspaceConnectors(sessionmaker(bind=db_session.get_bind(), expire_on_commit=False), get_settings())
    Rig.wc, Rig.db = wc, db_session
    Rig.svc = ToolExecutionService(db_session, register_workspace_tools(ToolRegistry(), wc))
    yield Rig
    wc.close()


def run(rig, email, ws, tool="crm.lead.list", data=None):
    return rig.svc.submit(principal(rig.db, email, ws["id"]), tool, data or {"limit": 3})


def test_admin_runs_crm_tools_with_the_workspace_credential(client, team, rig):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    ex = run(rig, "admin@x.com", ws)
    assert ex.status == ExecutionStatus.SUCCEEDED and [l["id"] for l in ex.output["leads"]] == ["1", "2", "3"]
    assert ex.output["next_cursor"] == "3" and CANARY not in json.dumps(ex.output) and "phone" not in json.dumps(ex.output)
    one = run(rig, "owner@x.com", ws, "crm.lead.get", {"lead_id": "2"})
    assert one.status == ExecutionStatus.SUCCEEDED and one.output["lead"]["id"] == "2"
    assert TOKEN not in json.dumps(ex.output) and TOKEN not in (ex.error or "")


def test_members_cannot_use_crm_tools(client, team, rig):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    with pytest.raises(PolicyDeniedError):
        run(rig, "member@x.com", ws)
    assert not rig.fakes                                              # the CRM was never contacted


def test_an_agent_without_crm_read_in_its_scope_is_denied(client, team, rig):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    p = principal(rig.db, "admin@x.com", ws["id"])
    narrow = Principal(user_id=p.user_id, workspace_id=p.workspace_id, permissions=p.permissions, agent="a",
                       agent_scope=frozenset({"task:read"}))
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(narrow, "crm.lead.list", {})
    broad = Principal(user_id=p.user_id, workspace_id=p.workspace_id, permissions=p.permissions, agent="a",
                      agent_scope=frozenset({"crm:read"}))
    assert rig.svc.submit(broad, "crm.lead.list", {"limit": 1}).status == ExecutionStatus.SUCCEEDED


def test_invalid_tool_input_never_reaches_the_crm(client, team, rig):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    from app.kernel.errors import ToolInputError
    for tool, data in (("crm.lead.get", {"lead_id": "1/../2"}), ("crm.lead.list", {"limit": 500}),
                       ("crm.lead.list", {"cursor": "a b"}), ("crm.lead.list", {"x": 1})):
        with pytest.raises(ToolInputError):
            run(rig, "admin@x.com", ws, tool, data)
    assert not rig.fakes.get(TOKEN) or not rig.fakes[TOKEN].log


def test_no_crm_connection_fails_safely(client, team, rig):
    hs, ws = team
    ex = run(rig, "admin@x.com", ws)
    assert ex.status == ExecutionStatus.FAILED and "ConnectorConfigError" in ex.error


def test_two_workspaces_use_their_own_tokens_and_never_each_others_data(client, team, rig):
    hs, ws = team
    other = mkws(client, hs["outsider"], "Other Co")
    add_hubspot(client, hs["admin"], ws, key="tok-A-11111")
    add_hubspot(client, hs["outsider"], other, key="tok-B-22222", url="https://other.hubspot.test")
    a = run(rig, "admin@x.com", ws)
    b = run(rig, "outsider@x.com", other)
    assert a.status == b.status == ExecutionStatus.SUCCEEDED
    assert len(rig.fakes["tok-A-11111"].log) == 1 and len(rig.fakes["tok-B-22222"].log) == 1
    assert rig.fakes["tok-A-11111"].log[0].headers["authorization"] == "Bearer tok-A-11111"


def test_revoked_credential_stops_crm_access_immediately(client, team, rig):
    hs, ws = team
    cid = add_hubspot(client, hs["admin"], ws)
    assert run(rig, "admin@x.com", ws).status == ExecutionStatus.SUCCEEDED
    client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"])
    assert run(rig, "admin@x.com", ws).status == ExecutionStatus.FAILED


def test_two_crm_providers_connected_is_refused_not_guessed(client, team, rig, monkeypatch):
    hs, ws = team
    monkeypatch.setitem(creg.SPECS, "othercrm", ConnectorSpec("othercrm", creg.SPECS["hubspot"].build, frozenset({"crm"})))
    add_hubspot(client, hs["admin"], ws)
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["admin"],
                    json={"provider": "othercrm", "name": "second", "secret": "tok-other-1",
                          "config": {"base_url": "https://other.test"}})
    assert r.status_code == 201
    ex = run(rig, "admin@x.com", ws)
    assert ex.status == ExecutionStatus.FAILED and "ConnectorConfigError" in ex.error
    assert not rig.fakes.get(TOKEN) or not rig.fakes[TOKEN].log


def test_a_connected_system_that_is_not_a_crm_is_refused(client, team, rig, monkeypatch):
    hs, ws = team

    class NotCrm(KitConnector):
        name = "x"
        def capabilities(self): return []
        def tools(self): return []
    monkeypatch.setitem(creg.SPECS, "hubspot", ConnectorSpec("hubspot", lambda config, secret, settings, **kw: NotCrm(
        ConnectorConfig(base_url="https://x.test", auth_token=SecretStr(secret))), frozenset({"crm"})))
    add_hubspot(client, hs["admin"], ws)
    ex = run(rig, "admin@x.com", ws)
    assert ex.status == ExecutionStatus.FAILED and "ConnectorConfigError" in ex.error


def test_remote_failures_fail_the_execution_with_codes_only(client, team, rig):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    rig.fakes[TOKEN] = Fake(key="a-different-server-key")
    ex = run(rig, "admin@x.com", ws)
    assert ex.status == ExecutionStatus.FAILED and TOKEN not in (ex.error or "") and "Bearer" not in (ex.error or "")


def test_connection_test_endpoint_works_for_hubspot_and_lists_capabilities(client, team, db_session, monkeypatch):
    hs, ws = team
    monkeypatch.setattr(get_settings(), "connection_test_cooldown_seconds", 0)
    fake = Fake()
    monkeypatch.setitem(creg.SPECS, "hubspot", ConnectorSpec("hubspot", lambda config, secret, settings, **kw: HubSpotConnector(
        build_config(config, secret, settings), transport=fake.transport, sleep=lambda s: None), frozenset({"crm"})))
    cid = add_hubspot(client, hs["admin"], ws)
    t = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["admin"])
    assert t.status_code == 200 and t.json()["ok"] is True and t.json()["capabilities"] == ["lead.list", "lead.get"]
    assert client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["member"]).status_code == 403


def test_creating_a_hubspot_credential_validates_its_config(client, team):
    hs, ws = team
    base = {"provider": "hubspot", "name": "crm", "secret": "tok-123456"}
    for config in ({}, {"base_url": "ftp://x"}, {"base_url": "http://127.0.0.1:9"}, {"base_url": "https://u:p@x.test"}):
        r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["admin"], json={**base, "config": config})
        assert r.status_code == 422, config


def test_credential_secret_never_reaches_audit_events(client, team, rig, db_session):
    hs, ws = team
    add_hubspot(client, hs["admin"], ws)
    run(rig, "admin@x.com", ws)
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    assert TOKEN not in blob and CANARY not in blob
