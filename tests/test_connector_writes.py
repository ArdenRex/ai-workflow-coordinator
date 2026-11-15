"""Substep 10.5: approval-gated write tools: crm.lead.create, email.draft, email.send, calendar.meeting.create, chat.message.post."""
import base64
import json
from email import message_from_bytes

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.connectors import registry as creg
from app.connectors.base import ConnectorConfig
from app.connectors.calendar.base import CreateMeetingInput, calendar_write_tool_definitions
from app.connectors.calendar.google_calendar import GoogleCalendarConnector
from app.connectors.chat.base import PostMessageInput, chat_write_tool_definitions
from app.connectors.chat.slack import SlackConnector
from app.connectors.crm.base import CreateLeadInput, crm_write_tool_definitions
from app.connectors.crm.hubspot import HubSpotConnector
from app.connectors.email.base import ComposeEmailInput, ListMessagesInput, email_write_tool_definitions
from app.connectors.email.gmail import GmailConnector
from app.connectors.errors import ConnectorBadResponseError, ConnectorConfigError, ConnectorNotFoundError, ConnectorUnavailableError
from app.connectors.kit import build_config
from app.connectors.writes import write_enabled
from app.kernel.errors import PolicyDeniedError, ToolInputError
from app.kernel.permissions import Principal
from app.models import ExecutionStatus, SystemEvent
from app.models.enums import RiskLevel
from app.models.kernel import Approval
from tests.domain_helpers import add_cred, make_rig
from tests.test_chat_slack import Fake as SlackFake, TOKEN as SLACK_TOKEN, URL as SLACK_URL
from tests.test_oauth_google import (CAL_SCOPE, CAL_URL, CANARY, CSEC, GM_SCOPE, GMAIL_URL, RTOK, SECRET, TOKEN_URL, Clock, Google)
from tests.test_workspace_connectors import principal, public_dns, team  # noqa: F401

COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
SEND = "https://www.googleapis.com/auth/gmail.send"
EVENTS = "https://www.googleapis.com/auth/calendar.events"
MAIL_WRITE_SCOPE = f"{GM_SCOPE} {COMPOSE} {SEND}"
CAL_WRITE_SCOPE = f"{CAL_SCOPE} {EVENTS}"
HUB_URL, HUB_TOKEN = "https://hub.test", "pat-hub-SECRET-123456"
MAIL = {"to": ["a@x.com"], "cc": ["c@x.com"], "subject": "Hello", "body": f"Line one\nLine two {CANARY}"}
MEETING = {"summary": "Kickoff", "start": "2026-03-02T10:00:00+00:00", "end": "2026-03-02T11:00:00+00:00",
           "attendees": ["a@x.com"], "location": "Room 1", "description": "Agenda"}
LEAD = {"email": "New@Lead.com", "first_name": "Ann", "company": "Acme"}


class WGoogle(Google):
    """Google fake that also accepts the POST calls the write tools make."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.posts = []

    def handle(self, req):
        if req.method != "POST" or req.url.host == "oauth.test":
            return super().handle(req)
        self.log.append(req)
        if req.headers.get("authorization") != f"Bearer {self.valid}":
            return httpx.Response(401)
        self.posts.append(req)
        body, p = json.loads(req.content), req.url.path
        if p == "/gmail/v1/users/me/drafts":
            return httpx.Response(200, json={"id": "r-123", "message": {"id": f"{10:016x}", "threadId": f"{10:016x}"}})
        if p == "/gmail/v1/users/me/messages/send":
            return httpx.Response(200, json={"id": f"{11:016x}", "threadId": f"{11:016x}", "labelIds": ["SENT"]})
        if p == "/calendar/v3/calendars/primary/events":
            return httpx.Response(200, json={"id": "evt00042", "status": "confirmed", "summary": body["summary"],
                                             "start": body["start"], "end": body["end"], "attendees": body["attendees"]})
        return httpx.Response(404)


def raw_of(req):
    body = json.loads(req.content)
    raw = body["raw"] if "raw" in body else body["message"]["raw"]
    return message_from_bytes(base64.urlsafe_b64decode(raw + "=="))


def gmail(scope=MAIL_WRITE_SCOPE, allow=True, fake=None, clock=None):
    fake = fake or WGoogle(scope=scope)
    c = GmailConnector(ConnectorConfig(base_url=GMAIL_URL, auth_token=SecretStr(SECRET)), allow_write=allow, token_url=TOKEN_URL,
                       transport=fake.transport, sleep=lambda s: None, clock=clock or Clock())
    return c, fake


def cal(scope=CAL_WRITE_SCOPE, allow=True, fake=None):
    fake = fake or WGoogle(scope=scope)
    c = GoogleCalendarConnector(ConnectorConfig(base_url=CAL_URL, auth_token=SecretStr(SECRET)), allow_write=allow,
                                token_url=TOKEN_URL, transport=fake.transport, sleep=lambda s: None, clock=Clock())
    return c, fake


class Slack(SlackFake):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.posts = []

    def handle(self, req):
        if req.url.path != "/api/chat.postMessage":
            return super().handle(req)
        self.log.append(req)
        if req.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401)
        self.posts.append(req)
        body = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "channel": body["channel"], "ts": "1700000100.000200"})


def slack(allow=True, fake=None):
    fake = fake or Slack()
    c = SlackConnector(ConnectorConfig(base_url=SLACK_URL, auth_token=SecretStr(SLACK_TOKEN)), allow_write=allow,
                       transport=fake.transport, sleep=lambda s: None)
    return c, fake


class Hub:
    def __init__(self, reply=None):
        self.posts, self.reply, self.log = [], reply, []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, req):
        self.log.append(req)
        if req.method != "POST" or req.url.path != "/crm/v3/objects/contacts":
            return httpx.Response(404)
        self.posts.append(req)
        props = json.loads(req.content)["properties"]
        return httpx.Response(201, json=self.reply or {"id": "501", "properties": props, "createdAt": "2026-03-02T00:00:00Z"})


def hub(allow=True, fake=None):
    fake = fake or Hub()
    c = HubSpotConnector(ConnectorConfig(base_url=HUB_URL, auth_token=SecretStr(HUB_TOKEN)), allow_write=allow,
                         transport=fake.transport, sleep=lambda s: None)
    return c, fake


# ------------------------------------------------------------------ the allow_write gate
def test_every_writer_refuses_without_allow_write_and_makes_no_request():
    cases = [(gmail(allow=False), "send_message", ComposeEmailInput(**MAIL)), (gmail(allow=False), "create_draft", ComposeEmailInput(**MAIL)),
             (cal(allow=False), "create_meeting", CreateMeetingInput(**MEETING)),
             (hub(allow=False), "create_lead", CreateLeadInput(**LEAD)),
             (slack(allow=False), "post_message", PostMessageInput(channel_id="C0000001", text="hi"))]
    for (conn, fake), method, data in cases:
        with pytest.raises(ConnectorConfigError):
            getattr(conn, method)(data)
        assert not fake.log, method


def test_write_flag_must_be_a_boolean_and_capabilities_follow_it():
    from app.connectors.writes import check_write_flag
    check_write_flag({"allow_write": True})
    for bad in ("yes", 1, None):
        with pytest.raises(ConnectorConfigError):
            check_write_flag({"allow_write": bad})
    assert write_enabled({"allow_write": True}) and not write_enabled({"allow_write": "true"}) and not write_enabled({})
    assert [c.name for c in gmail(allow=False)[0].capabilities() if c.write] == []
    assert [c.name for c in gmail()[0].capabilities() if c.write] == ["draft", "send"]
    assert [c.name for c in slack()[0].capabilities() if c.write] == ["message.post"]


def test_oauth_write_scopes_are_only_allowed_with_allow_write_and_never_broader():
    c, fake = gmail(scope=MAIL_WRITE_SCOPE, allow=False)                 # a writing grant on a read-only connection
    with pytest.raises(ConnectorConfigError):
        c.list_messages(ListMessagesInput())                              # even a READ is refused: the grant is too broad
    assert not [r for r in fake.log if r.url.host != "oauth.test"]
    for scope in (f"{MAIL_WRITE_SCOPE} https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"):
        c, fake = gmail(scope=scope)
        with pytest.raises(ConnectorConfigError):
            c.send_message(ComposeEmailInput(**MAIL))
        assert not fake.posts
    c, fake = cal(scope=f"{CAL_WRITE_SCOPE} https://www.googleapis.com/auth/calendar")          # full calendar access
    with pytest.raises(ConnectorConfigError):
        c.create_meeting(CreateMeetingInput(**MEETING))
    assert not fake.posts


# ------------------------------------------------------------------ gmail
def test_gmail_draft_and_send_post_exactly_what_was_approved():
    c, fake = gmail()
    d = c.create_draft(ComposeEmailInput(**MAIL))
    s = c.send_message(ComposeEmailInput(**MAIL))
    assert d.draft_id == "r-123" and s.message_id == f"{11:016x}"
    assert [r.url.path for r in fake.posts] == ["/gmail/v1/users/me/drafts", "/gmail/v1/users/me/messages/send"]
    for req in fake.posts:
        m = raw_of(req)
        assert m["To"] == "a@x.com" and m["Cc"] == "c@x.com" and m["Subject"] == "Hello" and m["Bcc"] is None
        assert "Line two" in m.get_payload(decode=True).decode()
    assert RTOK not in json.dumps(d.model_dump()) and CANARY not in json.dumps(s.model_dump())


def test_gmail_send_is_not_retried_after_a_server_error():
    fake = WGoogle(scope=MAIL_WRITE_SCOPE)
    orig = fake.handle
    fake.handle = lambda req: httpx.Response(503) if req.method == "POST" and req.url.host != "oauth.test" else orig(req)
    c, _ = gmail(fake=fake)
    fake.transport = httpx.MockTransport(fake.handle)
    c._client = httpx.Client(base_url=GMAIL_URL, transport=fake.transport)
    with pytest.raises(ConnectorUnavailableError):
        c.send_message(ComposeEmailInput(**MAIL))


def test_gmail_malformed_write_replies_are_bad_responses():
    for reply in ([], {"id": "not hex!"}, {"threadId": f"{1:016x}"}):
        fake = WGoogle(scope=MAIL_WRITE_SCOPE)
        c, _ = gmail(fake=fake)
        c._client = httpx.Client(base_url=GMAIL_URL, transport=httpx.MockTransport(lambda r, reply=reply: httpx.Response(200, json=reply)))
        with pytest.raises(ConnectorBadResponseError):
            c.send_message(ComposeEmailInput(**MAIL))


@pytest.mark.parametrize("kw", [{"subject": "Hi\r\nBcc: evil@x.com"}, {"subject": "a\nb"}, {"to": ["nope"]}, {"to": []},
                                {"to": ["a@x.com", "A@x.com"]}, {"to": [f"u{i}@x.com" for i in range(6)]},
                                {"cc": ["a@x.com"]}, {"to": ["a@x.com\r\nBcc: e@x.com"]}, {"body": "   "},
                                {"body": "x" * 10_001}, {"body": "ok \u202e evil"}, {"body": "a\x00b"}, {"extra": 1},
                                {"to": ["Name <a@x.com>"]}])
def test_invalid_emails_are_rejected_before_anything_is_sent(kw):
    with pytest.raises(ValidationError):
        ComposeEmailInput(**{**MAIL, **kw})


# ------------------------------------------------------------------ calendar
def test_calendar_meeting_body_and_notification_flag():
    c, fake = cal()
    out = c.create_meeting(CreateMeetingInput(**MEETING)).model_dump()["event"]
    assert out["id"] == "evt00042" and out["attendee_count"] == 1 and "a@x.com" not in json.dumps(out)
    req = fake.posts[0]
    assert req.url.params["sendUpdates"] == "none"
    body = json.loads(req.content)
    assert body["summary"] == "Kickoff" and body["attendees"] == [{"email": "a@x.com"}] and body["location"] == "Room 1"
    assert "conferenceData" not in body
    c.create_meeting(CreateMeetingInput(**{**MEETING, "notify_attendees": True}))
    assert fake.posts[1].url.params["sendUpdates"] == "all"


@pytest.mark.parametrize("kw", [{"end": "2026-03-02T09:00:00+00:00"}, {"end": "2026-03-02T19:00:00+00:00"},
                                {"start": "2026-03-02T10:00:00"}, {"attendees": ["bad"]}, {"summary": "a\nb"},
                                {"attendees": [f"u{i}@x.com" for i in range(11)]}, {"notify_attendees": "yes"},
                                {"description": "x" * 1001}, {"location": "a\x00b"}, {"extra": 1}])
def test_invalid_meetings_are_rejected(kw):
    with pytest.raises(ValidationError):
        CreateMeetingInput(**{**MEETING, **kw})


def test_cancelled_event_reply_is_a_bad_response():
    c, fake = cal()
    c._client = httpx.Client(base_url=CAL_URL, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "id": "evt00042", "status": "cancelled", "start": {"dateTime": "2026-03-02T10:00:00Z"}, "end": {"dateTime": "2026-03-02T11:00:00Z"}})))
    with pytest.raises(ConnectorBadResponseError):
        c.create_meeting(CreateMeetingInput(**MEETING))


# ------------------------------------------------------------------ crm
def test_hubspot_create_sends_only_given_properties_and_checks_the_result():
    c, fake = hub()
    out = c.create_lead(CreateLeadInput(**LEAD)).model_dump()["lead"]
    assert json.loads(fake.posts[0].content) == {"properties": {"email": "New@Lead.com", "firstname": "Ann", "company": "Acme"}}
    assert out["id"] == "501" and out["email"] == "New@Lead.com"
    c, _ = hub(fake=Hub(reply={"id": "502", "properties": {"email": "other@x.com"}}))      # created something else
    with pytest.raises(ConnectorBadResponseError):
        c.create_lead(CreateLeadInput(**LEAD))


@pytest.mark.parametrize("kw", [{"email": "nope"}, {"first_name": "a\nb"}, {"company": "x" * 201}, {"first_name": " "}, {"x": 1}])
def test_invalid_leads_are_rejected(kw):
    with pytest.raises(ValidationError):
        CreateLeadInput(**{**LEAD, **kw})


# ------------------------------------------------------------------ slack
def test_slack_post_goes_to_a_public_channel_without_mentions_or_unfurls():
    c, fake = slack()
    out = c.post_message(PostMessageInput(channel_id="C0000001", text="Status: done"))
    assert out.model_dump() == {"channel_id": "C0000001", "ts": "1700000100.000200"}
    body = json.loads(fake.posts[0].content)
    assert body == {"channel": "C0000001", "text": "Status: done", "parse": "none", "link_names": False,
                    "unfurl_links": False, "unfurl_media": False}


def test_slack_never_posts_to_private_channels_or_wrong_replies():
    fake = Slack(channels=[{"id": "C0000009", "name": "secret", "is_channel": True, "is_private": True}])
    c, _ = slack(fake=fake)
    with pytest.raises(ConnectorNotFoundError):
        c.post_message(PostMessageInput(channel_id="C0000009", text="hi"))
    assert not fake.posts
    c, fake = slack()
    c._client = httpx.Client(base_url=SLACK_URL, headers={}, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": True, "channel": {"id": "C0000001", "name": "g", "is_channel": True, "is_private": False}}
                                 if r.url.path.endswith("conversations.info") else {"ok": True, "channel": "C0000777", "ts": "1.2"})))
    with pytest.raises(ConnectorBadResponseError):
        c.post_message(PostMessageInput(channel_id="C0000001", text="hi"))


@pytest.mark.parametrize("text", ["<!channel> hi", "x <!here>", "<!everyone>", "<!subteam^S123>", "", "a\x00b", "x" * 2001])
def test_invalid_chat_text_is_rejected(text):
    with pytest.raises(ValidationError):
        PostMessageInput(channel_id="C0000001", text=text)
    with pytest.raises(ValidationError):
        PostMessageInput(channel_id="D0000001", text="hi")


# ------------------------------------------------------------------ tool definitions
def test_write_tools_are_approval_gated_and_never_retried():
    tools = {t.id: t for d in (crm_write_tool_definitions, email_write_tool_definitions, calendar_write_tool_definitions,
                              chat_write_tool_definitions) for t in d(lambda ws: None)}
    assert sorted(tools) == ["calendar.meeting.create", "chat.message.post", "crm.lead.create", "email.draft", "email.send"]
    perms = {"calendar.meeting.create": "calendar:write", "chat.message.post": "chat:post", "crm.lead.create": "crm:write",
             "email.draft": "email:draft", "email.send": "email:send"}
    for tid, t in tools.items():
        assert t.required_permission == perms[tid] and t.approval_required and t.max_retries == 0
    assert tools["email.send"].risk_level == RiskLevel.HIGH and tools["chat.message.post"].risk_level == RiskLevel.HIGH
    assert all(tools[t].risk_level == RiskLevel.MEDIUM for t in ("crm.lead.create", "email.draft", "calendar.meeting.create"))


# ------------------------------------------------------------------ through the kernel
def _builders():
    def g(kind):
        def build(r, config, secret, settings):
            conn = GmailConnector if kind == "mail" else GoogleCalendarConnector
            scope = MAIL_WRITE_SCOPE if kind == "mail" else CAL_WRITE_SCOPE
            fake = r.fakes.setdefault(secret, WGoogle(scope=scope))
            return conn(build_config(config, secret, settings), allow_write=write_enabled(config),
                        token_url=config["oauth_url"], transport=fake.transport, sleep=lambda s: None)
        return build

    def s(r, config, secret, settings):
        fake = r.fakes.setdefault(secret, Slack(key=secret))
        return SlackConnector(build_config(config, secret, settings), allow_write=write_enabled(config), transport=fake.transport,
                              sleep=lambda x: None)

    def h(r, config, secret, settings):
        fake = r.fakes.setdefault(secret, Hub())
        return HubSpotConnector(build_config(config, secret, settings), allow_write=write_enabled(config), transport=fake.transport,
                                sleep=lambda x: None)
    return {"gmail": g("mail"), "google_calendar": g("cal"), "slack": s, "hubspot": h}


# provider, domain, secret, config, tool, input, expected output key
CASES = {
    "email.send": ("gmail", "email", SECRET, {"base_url": GMAIL_URL, "oauth_url": TOKEN_URL}, MAIL, "message_id"),
    "email.draft": ("gmail", "email", SECRET, {"base_url": GMAIL_URL, "oauth_url": TOKEN_URL}, MAIL, "draft_id"),
    "calendar.meeting.create": ("google_calendar", "calendar", SECRET, {"base_url": CAL_URL, "oauth_url": TOKEN_URL}, MEETING, "event"),
    "chat.message.post": ("slack", "chat", SLACK_TOKEN, {"base_url": SLACK_URL}, {"channel_id": "C0000001", "text": "hello"}, "ts"),
    "crm.lead.create": ("hubspot", "crm", HUB_TOKEN, {"base_url": HUB_URL}, LEAD, "lead"),
}


@pytest.fixture(params=sorted(CASES))
def case(request, db_session, monkeypatch):
    provider, domain, secret, config, data, key = CASES[request.param]
    rig = make_rig(db_session, monkeypatch, provider, {domain}, _builders()[provider], creg.SPECS[provider].check_config)
    yield request.param, provider, secret, config, data, key, rig
    rig.wc.close()


def decide_and_run(rig, ws, ex, approve=True):
    appr = rig.db.scalar(select(Approval).where(Approval.execution_id == ex.id))
    rig.svc.approvals.decide(appr.id, principal(rig.db, "owner@x.com", ws["id"]), approve=approve)
    return rig.svc.execute_approved(principal(rig.db, "admin@x.com", ws["id"]), ex.id) if approve else None


def posts_of(rig, secret):
    return len(getattr(rig.fakes.get(secret), "posts", []))


def test_write_waits_for_approval_then_runs_exactly_once(client, team, case):
    tool, provider, secret, config, data, key, rig = case
    hs, ws = team
    add_cred(client, hs["admin"], ws, provider, secret, {**config, "allow_write": True})
    ex = rig.run("admin@x.com", ws, tool, data)
    assert ex.status == ExecutionStatus.AWAITING_APPROVAL and posts_of(rig, secret) == 0       # nothing happened yet
    done = decide_and_run(rig, ws, ex)
    assert done.status == ExecutionStatus.SUCCEEDED and key in done.output and posts_of(rig, secret) == 1
    with pytest.raises(Exception):                                                              # no second run of the same approval
        rig.svc.execute_approved(principal(rig.db, "admin@x.com", ws["id"]), ex.id)
    assert posts_of(rig, secret) == 1


def test_rejected_write_never_reaches_the_remote(client, team, case):
    tool, provider, secret, config, data, key, rig = case
    hs, ws = team
    add_cred(client, hs["admin"], ws, provider, secret, {**config, "allow_write": True})
    ex = rig.run("admin@x.com", ws, tool, data)
    decide_and_run(rig, ws, ex, approve=False)
    assert rig.db.get(type(ex), ex.id).status == ExecutionStatus.REJECTED and posts_of(rig, secret) == 0
    with pytest.raises(Exception):
        rig.svc.execute_approved(principal(rig.db, "admin@x.com", ws["id"]), ex.id)
    assert posts_of(rig, secret) == 0


def test_an_approved_write_on_a_read_only_connection_fails_and_sends_nothing(client, team, case):
    tool, provider, secret, config, data, key, rig = case
    hs, ws = team
    add_cred(client, hs["admin"], ws, provider, secret, config)                                  # no allow_write
    ex = rig.run("admin@x.com", ws, tool, data)
    done = decide_and_run(rig, ws, ex)
    assert done.status == ExecutionStatus.FAILED and "ConnectorConfigError" in done.error and posts_of(rig, secret) == 0


def test_members_and_unscoped_agents_cannot_even_request_writes(client, team, case):
    tool, provider, secret, config, data, key, rig = case
    hs, ws = team
    add_cred(client, hs["admin"], ws, provider, secret, {**config, "allow_write": True})
    with pytest.raises(PolicyDeniedError):
        rig.run("member@x.com", ws, tool, data)
    p = principal(rig.db, "admin@x.com", ws["id"])
    narrow = Principal(user_id=p.user_id, workspace_id=p.workspace_id, permissions=p.permissions, agent="a", agent_scope=frozenset({"task:read"}))
    with pytest.raises(PolicyDeniedError):
        rig.svc.submit(narrow, tool, data)
    with pytest.raises(PolicyDeniedError):                                                        # requesters cannot approve themselves
        decide_and_run_self(rig, ws, rig.run("admin@x.com", ws, tool, data))
    assert not rig.fakes


def decide_and_run_self(rig, ws, ex):
    appr = rig.db.scalar(select(Approval).where(Approval.execution_id == ex.id))
    from app.kernel.approvals import ApprovalPermissionError
    try:
        rig.svc.approvals.decide(appr.id, principal(rig.db, "admin@x.com", ws["id"]), approve=True)
    except ApprovalPermissionError as exc:
        raise PolicyDeniedError("self_approval", str(exc))


def test_invalid_write_input_never_reaches_the_remote(client, team, case):
    tool, provider, secret, config, data, key, rig = case
    hs, ws = team
    add_cred(client, hs["admin"], ws, provider, secret, {**config, "allow_write": True})
    bad = {**data, "extra_field": 1}
    with pytest.raises(ToolInputError):
        rig.run("admin@x.com", ws, tool, bad)
    assert not rig.fakes


def test_audit_never_holds_secrets_or_written_text(client, team, db_session, monkeypatch):
    rig = make_rig(db_session, monkeypatch, "gmail", {"email"}, _builders()["gmail"], creg.SPECS["gmail"].check_config)
    hs, ws = team
    add_cred(client, hs["admin"], ws, "gmail", SECRET, {**CASES["email.send"][3], "allow_write": True})
    decide_and_run(rig, ws, rig.run("admin@x.com", ws, "email.send", MAIL))
    blob = json.dumps([e.payload for e in db_session.scalars(select(SystemEvent))])
    assert RTOK not in blob and CSEC not in blob and CANARY not in blob
    rig.wc.close()


def test_credential_endpoint_validates_allow_write_and_lists_write_capabilities(client, team, db_session, monkeypatch):
    rig = make_rig(db_session, monkeypatch, "slack", {"chat"}, _builders()["slack"], creg.SPECS["slack"].check_config)
    hs, ws = team
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=hs["admin"],
                    json={"provider": "slack", "name": "bad", "secret": "tok-123456", "config": {"base_url": SLACK_URL, "allow_write": "yes"}})
    assert r.status_code == 422
    cid = add_cred(client, hs["admin"], ws, "slack", SLACK_TOKEN, {"base_url": SLACK_URL, "allow_write": True})
    t = client.post(f"/workspaces/{ws['id']}/credentials/{cid}/test", headers=hs["admin"])
    assert t.status_code == 200 and t.json()["capabilities"] == ["channel.list", "message.list", "message.post"]
    rig.wc.close()
