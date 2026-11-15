"""Substep 10.1: connector kit, business domains and domain-level provider resolution."""
import base64
import json
from typing import List, Optional

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings, get_settings
from app.connectors import registry as creg
from app.connectors.base import Capability, ConnectorConfig, ConnectionStatus
from app.connectors.domains import DOMAINS, business_tool, domain_permissions, verb_kind
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError
from app.connectors.kit import ExternalText, KitConnector, build_config, clean_text, paginate
from app.connectors.registry import ConnectorSpec
from app.connectors.workspace import WorkspaceConnectors
from app.identity.roles import permissions_for
from app.kernel.errors import InvalidToolDefinitionError
from app.kernel.permissions import Principal
from app.models.enums import RiskLevel, Role
from tests.test_workspace_connectors import add_cred, public_dns, team  # noqa: F401


# ------------------------------------------------------------------ auth schemes
def conn(cls, secret="tok-123", **kw):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json={"ok": True})
    c = cls(ConnectorConfig(base_url="https://x.test", auth_token=SecretStr(secret)),
            transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)
    return c, seen


class Bearer(KitConnector):
    name = "b"
    def capabilities(self): return [Capability("x.read", "x")]
    def tools(self): return []


class Keyed(Bearer):
    auth_kind, auth_header = "header", "X-Api-Key"


class Basic(Bearer):
    auth_kind = "basic"


def test_bearer_header_and_scheme_variants():
    c, seen = conn(Bearer)
    c._request("GET", "/ping")
    assert seen[0].headers["authorization"] == "Bearer tok-123"
    c, seen = conn(Keyed)
    c._request("GET", "/ping")
    assert seen[0].headers["x-api-key"] == "tok-123" and "authorization" not in seen[0].headers
    c, seen = conn(Basic, secret="user:p@ss")
    c._request("GET", "/ping")
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(b"user:p@ss").decode()


@pytest.mark.parametrize("cls,secret", [(Bearer, ""), (Bearer, "   "), (Bearer, "a b"), (Bearer, "tok\r\nX-Evil: 1"),
                                        (Bearer, "tok\x00"), (Bearer, "x" * 4097), (Basic, "nocolon"), (Keyed, "a\nb")])
def test_invalid_secrets_are_refused_before_any_request(cls, secret):
    with pytest.raises(ConnectorConfigError):
        conn(cls, secret=secret)


def test_missing_credential_is_refused():
    with pytest.raises(ConnectorConfigError):
        Bearer(ConnectorConfig(base_url="https://x.test"))


@pytest.mark.parametrize("header", ["Authorization", "Host", "Content-Length", "Cookie", "bad header", "X\r\nY", "1Key", ""])
def test_unsafe_auth_header_names_fail_at_class_creation(header):
    with pytest.raises(ConnectorConfigError):
        type("Bad", (KitConnector,), {"auth_kind": "header", "auth_header": header, "name": "bad"})


def test_unknown_auth_kind_fails_at_class_creation():
    with pytest.raises(ConnectorConfigError):
        type("Bad", (KitConnector,), {"auth_kind": "magic", "name": "bad"})


def test_the_secret_never_appears_in_repr_or_error_codes():
    c, _ = conn(Bearer, secret="SECRET-VALUE-9")
    assert "SECRET-VALUE-9" not in repr(c) and "SECRET-VALUE-9" not in str(c.config)


def test_build_config_applies_https_ssrf_and_timeout_rules(monkeypatch):
    from app.connectors import netguard
    monkeypatch.setattr(netguard, "assert_public_host", lambda *a, **k: None)
    s = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)
    cfg = build_config({"base_url": "https://crm.test", "timeout_seconds": 5}, "k", s)
    assert cfg.timeout_seconds == 5 and cfg.auth_token.get_secret_value() == "k"
    for bad in ({}, {"base_url": ""}, {"base_url": 5}, {"base_url": "https://crm.test", "timeout_seconds": "x"},
                {"base_url": "ftp://crm.test"}, {"base_url": "https://u:p@crm.test"}):
        with pytest.raises(ConnectorConfigError):
            build_config(bad, "k", s)
    with pytest.raises(ConnectorConfigError):
        build_config(None, "k", s)


def test_build_config_blocks_private_hosts():
    s = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)
    with pytest.raises(Exception):
        build_config({"base_url": "http://127.0.0.1:9"}, "k", s)


# ------------------------------------------------------------------ untrusted text
def test_clean_text_strips_hidden_characters_keeps_normal_text_and_caps_length():
    assert clean_text("Hello\u200b World\u202e!\x00\x07") == "Hello World!"
    assert clean_text("a\tb\nc") == "a\tb\nc"
    assert clean_text("\ufeffstart\u2028end\u00ad") == "startend"
    assert clean_text("x" * 50, 10) == "x" * 10 and clean_text(None) is None and clean_text("") == ""
    assert clean_text("héllo wörld ✓ 日本") == "héllo wörld ✓ 日本"
    for bad in (5, b"x", ["a"], {"a": 1}, 1.5, True):
        with pytest.raises(ValueError):
            clean_text(bad)


def test_external_text_field_cleans_and_bounds_outputs():
    class Mail(BaseModel):
        subject: ExternalText(20)
        note: Optional[ExternalText(5)] = None
    m = Mail(subject="Hi\u202e there\x00 " + "z" * 100, note=None)
    assert m.subject == ("Hi there " + "z" * 100)[:20] and m.note is None
    assert Mail(subject="s", note="abcdefgh").note == "abcde"
    with pytest.raises(ValueError):
        Mail(subject=123)


# ------------------------------------------------------------------ pagination
def pages(*chunks):
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        i = len(calls) - 1
        return list(chunks[i]), (f"c{i + 1}" if i + 1 < len(chunks) else None)
    return fetch, calls


def test_paginate_reads_all_pages_when_within_bounds():
    fetch, calls = pages([1, 2], [3, 4], [5])
    p = paginate(fetch, max_pages=5, max_items=100)
    assert p.items == [1, 2, 3, 4, 5] and p.truncated is False and calls == [None, "c1", "c2"]


def test_paginate_item_ceiling_truncates_and_reports_it():
    fetch, calls = pages([1, 2, 3], [4, 5, 6], [7])
    p = paginate(fetch, max_pages=5, max_items=4)
    assert p.items == [1, 2, 3, 4] and p.truncated is True and len(calls) == 2


def test_paginate_exactly_at_the_ceiling_with_no_more_is_not_truncated():
    fetch, _ = pages([1, 2, 3, 4])
    assert paginate(fetch, max_items=4).truncated is False


def test_paginate_exactly_at_the_ceiling_with_more_available_is_truncated():
    fetch, _ = pages([1, 2], [3])
    p = paginate(fetch, max_items=2)
    assert p.items == [1, 2] and p.truncated is True


def test_paginate_page_ceiling_truncates():
    fetch, calls = pages(*([i] for i in range(10)))
    p = paginate(fetch, max_pages=3, max_items=100)
    assert p.items == [0, 1, 2] and p.truncated is True and len(calls) == 3


def test_paginate_detects_a_repeating_cursor():
    with pytest.raises(ConnectorBadResponseError):
        paginate(lambda cursor: ([1], "same"), max_pages=10, max_items=100)


def test_paginate_empty_and_invalid_bounds():
    assert paginate(lambda c: ([], None)).items == []
    for kw in ({"max_pages": 0}, {"max_pages": 21}, {"max_items": 0}, {"max_items": 1001}):
        with pytest.raises(ConnectorConfigError):
            paginate(lambda c: ([], None), **kw)


# ------------------------------------------------------------------ business tools
class In(BaseModel):
    x: int = 1


class Out(BaseModel):
    ok: bool = True


def mk(domain, verb, **kw):
    return business_tool(domain, verb, action=kw.pop("action", "go"), description="d", input_schema=In,
                         output_schema=Out, handler=lambda ctx, data: {"ok": True}, **kw)


def test_read_tools_are_low_risk_without_approval_and_may_retry():
    t = mk("crm", "read", resource="lead", action="list", max_retries=2)
    assert t.id == "crm.lead.list" and t.required_permission == "crm:read"
    assert t.risk_level == RiskLevel.LOW and t.approval_required is False and t.max_retries == 2


def test_write_tools_need_approval_and_never_retry():
    t = mk("crm", "write", resource="lead", action="create", max_retries=3)
    assert t.id == "crm.lead.create" and t.required_permission == "crm:write"
    assert t.risk_level == RiskLevel.MEDIUM and t.approval_required is True and t.max_retries == 0
    assert mk("email", "draft", action="draft", risk=RiskLevel.HIGH).risk_level == RiskLevel.HIGH


def test_send_tools_are_high_risk_with_mandatory_approval():
    for domain, verb in (("email", "send"), ("chat", "post")):
        t = mk(domain, verb, action="send")
        assert t.risk_level == RiskLevel.HIGH and t.approval_required is True and t.max_retries == 0


@pytest.mark.parametrize("domain,verb,risk", [
    ("crm", "read", RiskLevel.MEDIUM), ("crm", "read", RiskLevel.HIGH), ("crm", "write", RiskLevel.LOW),
    ("email", "send", RiskLevel.MEDIUM), ("email", "send", RiskLevel.LOW), ("chat", "post", RiskLevel.LOW),
])
def test_risk_cannot_be_lowered_or_misdeclared(domain, verb, risk):
    with pytest.raises(InvalidToolDefinitionError):
        mk(domain, verb, risk=risk)


@pytest.mark.parametrize("domain,verb", [("ghost", "read"), ("crm", "delete"), ("email", "write"), ("calendar", "send"), ("", ""), ("CRM", "read")])
def test_unknown_domains_and_verbs_are_rejected(domain, verb):
    with pytest.raises(InvalidToolDefinitionError):
        mk(domain, verb)


def test_malformed_ids_are_rejected_by_the_kernel_rules():
    with pytest.raises(InvalidToolDefinitionError):
        mk("crm", "read", resource="Bad Name", action="list")


def test_every_domain_verb_builds_a_valid_tool_and_the_catalog_is_small():
    assert set(DOMAINS) == {"email", "calendar", "crm", "chat", "project"}
    for d, verbs in DOMAINS.items():
        for v, kind in verbs.items():
            t = mk(d, v)
            assert t.required_permission == f"{d}:{v}" and verb_kind(d, v) == kind
            assert (t.risk_level == RiskLevel.LOW) == (kind == "read")


# ------------------------------------------------------------------ roles
def test_business_domain_permissions_are_admin_only_by_default():
    perms = domain_permissions()
    assert len(perms) == sum(len(v) for v in DOMAINS.values())
    for role in (Role.VIEWER, Role.MEMBER):
        p = Principal(user_id="u", workspace_id="w", permissions=permissions_for(role))
        assert not any(p.can(x) for x in perms), role
    for role in (Role.ADMIN, Role.OWNER):
        p = Principal(user_id="u", workspace_id="w", permissions=permissions_for(role))
        assert all(p.can(x) for x in perms), role


def test_an_agent_scope_without_the_permission_cannot_use_a_domain_tool():
    admin = permissions_for(Role.ADMIN)
    p = Principal(user_id="u", workspace_id="w", permissions=admin, agent="a", agent_scope=frozenset({"task:read"}))
    assert not p.can("crm:read") and not p.can("email:send")


# ------------------------------------------------------------------ domain-level provider resolution
class FakeCrm(KitConnector):
    name = "fake"

    def capabilities(self): return [Capability("lead.list", "x")]
    def tools(self): return []


def fake_spec(provider, domains):
    return ConnectorSpec(provider, lambda config, secret, settings, **kw: FakeCrm(
        ConnectorConfig(base_url=config["base_url"], auth_token=SecretStr(secret)),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))), frozenset(domains))


def cred(client, h, ws, provider, name="c", secret="k1"):
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=h,
                    json={"provider": provider, "name": name, "secret": secret, "config": {"base_url": "https://crm.test"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def wc(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setitem(creg.SPECS, "crmone", fake_spec("crmone", {"crm"}))
    monkeypatch.setitem(creg.SPECS, "crmtwo", fake_spec("crmtwo", {"crm"}))
    monkeypatch.setitem(creg.SPECS, "mailone", fake_spec("mailone", {"email"}))
    w = WorkspaceConnectors(sessionmaker(bind=db_session.get_bind(), expire_on_commit=False), get_settings())
    yield w
    w.close()


def test_providers_for_lists_only_declaring_providers(wc):
    assert creg.providers_for("crm") == ["crmone", "crmtwo", "hubspot"] and creg.providers_for("email") == ["gmail", "mailone"]
    assert creg.providers_for("calendar") == ["google_calendar"] and creg.providers_for("nope") == []
    assert creg.get_spec("aceden").domains == frozenset()


def test_domain_resolves_to_the_single_connected_provider(client, team, wc):
    hs, ws = team
    cred(client, hs["admin"], ws, "crmtwo")
    cred(client, hs["admin"], ws, "mailone", name="mail")
    assert wc.domain_provider(ws["id"], "crm") == "crmtwo" and wc.domain_provider(ws["id"], "email") == "mailone"
    assert isinstance(wc.for_domain("crm")(ws["id"]), FakeCrm)


def test_no_connection_for_the_domain_is_refused(client, team, wc):
    hs, ws = team
    cred(client, hs["admin"], ws, "mailone")
    with pytest.raises(ConnectorConfigError, match="No crm connection"):
        wc.for_domain("crm")(ws["id"])
    with pytest.raises(ConnectorConfigError, match="No calendar connection"):
        wc.domain_provider(ws["id"], "calendar")


def test_two_providers_for_one_domain_are_refused_not_guessed(client, team, wc):
    hs, ws = team
    cred(client, hs["admin"], ws, "crmone", name="a")
    cred(client, hs["admin"], ws, "crmtwo", name="b")
    with pytest.raises(ConnectorConfigError, match="Multiple active crm"):
        wc.for_domain("crm")(ws["id"])


def test_revoking_a_credential_ends_domain_access_and_other_workspaces_never_resolve(client, team, wc):
    hs, ws = team
    cid = cred(client, hs["admin"], ws, "crmone")
    other = client.post("/workspaces", json={"name": "Other Co"}, headers=hs["outsider"]).json()
    with pytest.raises(ConnectorConfigError):
        wc.for_domain("crm")(other["id"])
    assert wc.for_domain("crm")(ws["id"])
    assert client.delete(f"/workspaces/{ws['id']}/credentials/{cid}", headers=hs["admin"]).status_code in (200, 204)
    with pytest.raises(ConnectorConfigError):
        wc.for_domain("crm")(ws["id"])


def test_a_rotated_secret_is_used_by_the_domain_resolver(client, team, wc):
    hs, ws = team
    cid = cred(client, hs["admin"], ws, "crmone")
    first = wc.for_domain("crm")(ws["id"])
    r = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/rotate", json={"secret": "k2"}, headers=hs["admin"])
    assert r.status_code == 200
    assert wc.for_domain("crm")(ws["id"]) is not first
