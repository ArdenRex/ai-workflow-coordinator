"""Substep 10.6: Step 10 hardening: outbound call limit, cross-connector invariants, end-to-end audited journey."""
import json
import re

import httpx
import pytest
from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.connectors import registry as creg
from app.connectors.base import ConnectorConfig
from app.connectors.crm.hubspot import HubSpotConnector
from app.connectors.domains import DOMAINS, domain_permissions
from app.connectors.email.base import ListMessagesInput
from app.connectors.email.gmail import GmailConnector
from app.connectors.errors import ConnectorConfigError, ConnectorRateLimitedError
from app.connectors.kit import build_config
from app.connectors.ratelimit import CallLimiter
from app.connectors.workspace import register_workspace_tools
from app.kernel.registry import ToolRegistry
from app.models import ExecutionStatus, SystemEvent
from app.models.enums import RiskLevel
from tests.domain_helpers import add_cred, make_rig
from tests.test_connector_writes import CASES, MAIL, Slack, _builders, decide_and_run, WGoogle, MAIL_WRITE_SCOPE
from tests.test_oauth_google import CANARY, CSEC, GMAIL_URL, RTOK, SECRET, TOKEN_URL, Clock, Google, mail
from tests.test_workspace_connectors import public_dns, team  # noqa: F401


class Ticker:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ the limiter
def test_limiter_allows_the_limit_then_refuses_until_the_window_slides():
    t = Ticker()
    lim = CallLimiter(3, clock=t)
    for _ in range(3):
        lim.acquire()
    with pytest.raises(ConnectorRateLimitedError) as e:
        lim.acquire()
    assert e.value.retry_after == 60
    t.t += 59
    with pytest.raises(ConnectorRateLimitedError) as e:
        lim.acquire()
    assert e.value.retry_after == 1
    t.t += 1
    lim.acquire()                                        # the oldest call left the window
    for _ in range(100):
        CallLimiter(0).acquire()                         # 0 = unlimited


def hub(limit, handler):
    return HubSpotConnector(ConnectorConfig(base_url="https://hub.test", auth_token=SecretStr("tok-123456"), max_calls_per_minute=limit),
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)


def test_a_connection_over_its_limit_makes_no_request_and_a_retry_is_not_counted_twice():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"results": []})
    c = hub(2, handler)
    t = Ticker()
    c._limiter = CallLimiter(2, clock=t)
    c._request("GET", "/crm/v3/objects/contacts")        # 503 then a retry: one logical call, two HTTP requests
    c._request("GET", "/crm/v3/objects/contacts")
    n = len(calls)
    with pytest.raises(ConnectorRateLimitedError):
        c._request("GET", "/crm/v3/objects/contacts")
    with pytest.raises(ConnectorRateLimitedError):
        c._request("POST", "/crm/v3/objects/contacts", json_body={})   # writes are limited too
    assert len(calls) == n


def test_limit_is_per_connection_and_the_google_limit_blocks_before_any_token_call():
    fake = Google()
    fake.msgs = dict(mail(i) for i in range(1, 3))
    c = GmailConnector(ConnectorConfig(base_url=GMAIL_URL, auth_token=SecretStr(SECRET), max_calls_per_minute=1), token_url=TOKEN_URL,
                       transport=fake.transport, sleep=lambda s: None, clock=Clock())
    c.validate_connection()
    before = (fake.token_calls, len(fake.log))
    with pytest.raises(ConnectorRateLimitedError):
        c.list_messages(ListMessagesInput())
    assert (fake.token_calls, len(fake.log)) == before
    other = hub(1, lambda r: httpx.Response(200, json={"results": []}))
    other._request("GET", "/crm/v3/objects/contacts")    # a different connection has its own window


def test_the_limit_comes_from_settings_and_is_validated():
    s = get_settings().model_copy(update={"connector_max_calls_per_minute": 7, "allow_private_connector_hosts": True})
    assert build_config({"base_url": "https://hub.test"}, "tok-123456", s).max_calls_per_minute == 7
    assert get_settings().connector_max_calls_per_minute == 120
    with pytest.raises(ConnectorConfigError):
        ConnectorConfig(base_url="https://hub.test", max_calls_per_minute=-1)


def test_rate_limited_failures_are_fixed_text():
    c = hub(1, lambda r: httpx.Response(200, json={}))
    c._request("GET", "/crm/v3/objects/contacts")
    with pytest.raises(ConnectorRateLimitedError) as e:
        c._request("GET", "/crm/v3/objects/contacts")
    assert "tok-123456" not in str(e.value) and e.value.code == "connector_rate_limited"


# ------------------------------------------------------------------ invariants over every registered tool
class _Stub:
    def provider(self, name):
        return lambda ws: None

    def for_domain(self, domain):
        return lambda ws: None


@pytest.fixture(scope="module")
def tools():
    return register_workspace_tools(ToolRegistry(), _Stub()).list()


def test_every_domain_has_a_connector_and_every_business_tool_follows_the_rules(tools):
    for domain in DOMAINS:
        assert creg.providers_for(domain), domain
    business = [t for t in tools if t.id.split(".")[0] in DOMAINS]
    assert len(business) == 17 and len({t.id for t in tools}) == len(tools)
    for t in business:
        domain = t.id.split(".")[0]
        assert re.match(r"^[a-z]+(\.[a-z]+){1,2}$", t.id) and t.required_permission in domain_permissions()
        assert t.required_permission.startswith(domain + ":")
        kind = DOMAINS[domain][t.required_permission.split(":")[1]]
        if kind == "read":
            assert t.risk_level == RiskLevel.LOW and not t.approval_required
        else:
            assert t.approval_required and t.max_retries == 0 and t.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
            assert kind != "send" or t.risk_level == RiskLevel.HIGH


def test_schemas_are_strict_and_never_carry_secret_looking_fields(tools):
    secretish = re.compile(r"secret|token|password|credential|api_?key|authorization", re.I)

    def names(model, seen=()):
        for fname, f in model.model_fields.items():
            yield fname
            sub = f.annotation
            for cand in getattr(sub, "__args__", (sub,)):
                for inner in getattr(cand, "__args__", (cand,)):
                    if isinstance(inner, type) and issubclass(inner, BaseModel) and inner not in seen:
                        yield from names(inner, seen + (model,))
    for t in tools:
        if t.id.split(".")[0] not in DOMAINS:
            continue
        assert t.input_schema.model_config.get("extra") == "forbid", t.id
        assert not [n for n in names(t.output_schema) if secretish.search(n)], t.id
        assert not [n for n in names(t.input_schema) if secretish.search(n)], t.id


def test_only_read_tools_exist_for_asana_and_project_writes_are_not_registered(tools):
    ids = {t.id for t in tools}
    assert not any(i.startswith("project.") and not i.endswith((".list", ".get")) for i in ids)


def test_provider_specs_declare_domains_and_validate_write_flag_at_creation():
    for name in ("hubspot", "slack", "gmail", "google_calendar"):
        spec = creg.get_spec(name)
        assert spec.domains and spec.check_config is not None
        with pytest.raises(ConnectorConfigError):
            spec.check_config({"base_url": "https://x.test", "allow_write": "yes"})


# ------------------------------------------------------------------ the whole journey, audited
def test_journey_connect_ask_approve_execute_audit(client, team, db_session, monkeypatch):
    provider, domain, secret, config, data, key = CASES["email.send"]
    rig = make_rig(db_session, monkeypatch, provider, {domain}, _builders()[provider], creg.SPECS[provider].check_config)
    hs, ws = team
    cid = add_cred(client, hs["admin"], ws, provider, secret, {**config, "allow_write": True})          # 1 connect
    t = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["admin"]).json()        # 2 understand
    assert t["ok"] and "send" in t["capabilities"]
    ex = rig.run("admin@x.com", ws, "email.send", data)                                                  # 3 request
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and not rig.fakes[secret].posts               # 4 stops for a human
    done = decide_and_run(rig, ws, ex)                                                                   # 5 approve + execute
    assert done.status == ExecutionStatus.SUCCEEDED and len(rig.fakes[secret].posts) == 1
    events = db_session.scalars(select(SystemEvent).where(SystemEvent.execution_id == ex.id).order_by(SystemEvent.created_at)).all()
    kinds = [e.event_type for e in events]
    for needed in ("execution.created", "approval.requested", "approval.approved", "execution.started", "approval.executed"):
        assert needed in kinds, kinds
    assert kinds.index("approval.requested") < kinds.index("approval.approved") < kinds.index("approval.executed")
    blob = json.dumps([e.payload for e in events])                                                       # 6 audited, content-free
    assert CANARY not in blob and RTOK not in blob and CSEC not in blob and "Line one" not in blob
    rig.wc.close()
