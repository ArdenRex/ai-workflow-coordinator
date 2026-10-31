"""
Part B of the billing block: entry points that DON'T use a login (public API
keys, Slack, Teams, WhatsApp, forwarded email, the Gmail poller, the reminder
scheduler) apply the same rule — see app/billing_access.py.

Real database, real application code; only the outside world (AI, Slack, Teams)
is faked. Needs a migrated Postgres (skipped otherwise).
"""
import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

NOW = datetime.now(timezone.utc)
PAST, FUTURE = NOW - timedelta(days=1), NOW + timedelta(days=3)
ALLOWED = [("active", None), ("exempt", None), ("trialing", FUTURE)]
BLOCKED = [("trialing", PAST), ("cancelled", None), ("past_due", None)]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal(); s.execute(text("select whatsapp_message_id from tasks limit 1")); s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")

    from app.database import SessionLocal
    from app.models import ApiKey, Task, User, UserRole, Workspace, WorkspaceSettings

    s = SessionLocal()
    made = types.SimpleNamespace(users=[], workspaces=[])

    def ws(owner=None):
        w = Workspace(name=f"ws-{uuid.uuid4().hex[:8]}", owner_id=owner.id if owner else None)
        s.add(w); s.commit(); s.refresh(w); made.workspaces.append(w.id)
        return w

    def user(status, ends=None, workspace=None, role=UserRole.architect, email=None, **extra):
        tag = uuid.uuid4().hex[:8]
        u = User(email=email or f"u-{tag}@example.com", name=f"U {tag}", role=role,
                 subscription_status=status, trial_ends_at=ends,
                 workspace_id=workspace.id if workspace else None, **extra)
        s.add(u); s.commit(); s.refresh(u); made.users.append(u.id)
        return u

    def team(status, ends=None, **extra):
        """A user who owns a fresh workspace."""
        u = user(status, ends, **extra)
        w = ws(owner=u)
        u.workspace_id = w.id; s.commit(); s.refresh(u)
        return u, w

    def tasks(w):
        s.expire_all()
        return s.query(Task).filter(Task.workspace_id == w.id).all()

    e = types.SimpleNamespace(s=s, ws=ws, user=user, team=team, tasks=tasks, factory=SessionLocal)
    yield e

    s.expire_all()
    for wid in made.workspaces:
        s.query(Task).filter(Task.workspace_id == wid).delete()
        s.query(ApiKey).filter(ApiKey.workspace_id == wid).delete()
        s.query(WorkspaceSettings).filter(WorkspaceSettings.workspace_id == wid).delete()
        w = s.get(Workspace, wid)
        if w:
            w.owner_id = None
    s.commit()
    for uid in made.users:
        u = s.get(User, uid)
        if u:
            s.query(ApiKey).filter(ApiKey.created_by == uid).delete()
            s.delete(u)
    s.commit()
    for wid in made.workspaces:
        w = s.get(Workspace, wid)
        if w:
            s.delete(w)
    s.commit(); s.close()


# ═════════════════════════ public API keys ═════════════════════════
@pytest.fixture(scope="module")
def client():
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        s = SessionLocal(); s.execute(text("select 1 from users limit 1")); s.close()
    except Exception as exc:
        pytest.skip(f"migrated Postgres not available: {exc}")
    import app.main as m
    return TestClient(m.app)


def make_key(env, w, created_by=None):
    from app import crud
    raw, _ = crud.create_api_key(env.s, w.id, "test key", created_by=created_by.id if created_by else None)
    return {"X-API-Key": raw}


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_api_key_works_for_allowed_owner(client, env, status, ends):
    owner, w = env.team(status, ends)
    r = client.post("/api/v1/tasks", headers=make_key(env, w), json={"title": "from zapier"})
    assert r.status_code == 201, r.text
    assert len(env.tasks(w)) == 1


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_api_key_blocked_when_owner_must_pay(client, env, status, ends):
    owner, w = env.team(status, ends)
    h = make_key(env, w)
    r = client.post("/api/v1/tasks", headers=h, json={"title": "should not be created"})
    assert r.status_code == 402 and "trial has ended" in r.json()["detail"]
    assert client.get("/api/v1/tasks", headers=h).status_code == 402
    assert env.tasks(w) == []


def test_api_key_follows_the_owner_when_admin_exempts_them(client, env):
    owner, w = env.team("trialing", PAST)
    h = make_key(env, w)
    assert client.post("/api/v1/tasks", headers=h, json={"title": "a"}).status_code == 402
    owner.subscription_status = "exempt"; env.s.commit()
    assert client.post("/api/v1/tasks", headers=h, json={"title": "b"}).status_code == 201


def test_api_key_ownerless_workspace_uses_key_creator_then_falls_back_to_allowed(client, env):
    creator = env.user("cancelled")
    w = env.ws(owner=None)
    assert client.get("/api/v1/tasks", headers=make_key(env, w, created_by=creator)).status_code == 402
    w2 = env.ws(owner=None)           # nobody to bill: behaviour unchanged
    assert client.get("/api/v1/tasks", headers=make_key(env, w2)).status_code == 200


def test_invalid_api_key_is_still_401(client, env):
    assert client.get("/api/v1/tasks", headers={"X-API-Key": "nope"}).status_code == 401


# ═════════════════════════ WhatsApp ═════════════════════════
def wa_payload(phone_id, text, mid=None):
    return {"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": phone_id},
        "messages": [{"from": "9230011", "id": mid or f"wamid.{uuid.uuid4().hex}", "type": "text", "text": {"body": text}}]}}]}]}


def wa_run(env, phone_id, text="Ali please send the invoice by Friday"):
    from app import whatsapp_bot as bot
    calls = []

    async def classify(t):
        calls.append(t); return True

    async def extract(t):
        return types.SimpleNamespace(task=t, assignee="Ali", deadline=None, priority=None, confidence=0.9)

    stats = run(bot.handle_webhook_payload(wa_payload(phone_id, text), session_factory=env.factory,
                                           classify=classify, extract=extract))
    return stats, calls


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_whatsapp_creates_tasks_for_allowed_users(env, status, ends):
    pid = f"PN{uuid.uuid4().int % 10**9}"
    u, w = env.team(status, ends, whatsapp_connected=True, whatsapp_phone_number_id=pid)
    stats, _ = wa_run(env, pid)
    assert stats["created"] == 1 and stats["skipped_billing"] == 0 and len(env.tasks(w)) == 1


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_whatsapp_skips_blocked_users_without_spending_an_ai_call(env, status, ends):
    pid = f"PN{uuid.uuid4().int % 10**9}"
    u, w = env.team(status, ends, whatsapp_connected=True, whatsapp_phone_number_id=pid)
    stats, ai_calls = wa_run(env, pid)
    assert stats["created"] == 0 and stats["skipped_billing"] == 1
    assert ai_calls == [] and env.tasks(w) == []


# ═════════════════════════ forwarded email ═════════════════════════
def run_email(env, monkeypatch, u):
    from app import email_bot
    calls = []

    async def fake_extract(text):
        calls.append(text)
        return types.SimpleNamespace(task="Send invoice", assignee=None, deadline=None, priority=None, confidence=0.9)

    monkeypatch.setattr(email_bot, "extract_task_from_message", fake_extract)
    return run(email_bot.process_inbound_email(f"Me <{u.email}>", "Invoice", "please send the invoice")), calls


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_email_creates_tasks_for_allowed_users(env, monkeypatch, status, ends):
    u, w = env.team(status, ends)
    task, _ = run_email(env, monkeypatch, u)
    assert task is not None and len(env.tasks(w)) == 1


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_email_skips_blocked_users_without_spending_an_ai_call(env, monkeypatch, status, ends):
    u, w = env.team(status, ends)
    task, ai_calls = run_email(env, monkeypatch, u)
    assert task is None and ai_calls == [] and env.tasks(w) == []


# ═════════════════════════ Gmail poller ═════════════════════════
def test_gmail_poll_skips_blocked_user_and_moves_the_clock_forward(env):
    from app.gmail_bot import poll_gmail_for_user
    u, w = env.team("trialing", PAST, gmail_connected=True, gmail_email="x@gmail.com",
                    gmail_last_checked_at=NOW - timedelta(days=40))
    stats = run(poll_gmail_for_user(env.s, u))
    assert stats.get("skipped_billing") is True and stats["error"] is None and stats["created"] == 0
    env.s.refresh(u)
    last = u.gmail_last_checked_at if u.gmail_last_checked_at.tzinfo else u.gmail_last_checked_at.replace(tzinfo=timezone.utc)
    assert NOW - last < timedelta(minutes=1)          # a later subscription won't import 40 days of mail


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_gmail_poll_proceeds_for_allowed_user(env, status, ends):
    from app.gmail_bot import poll_gmail_for_user
    u, w = env.team(status, ends, gmail_connected=True, gmail_email="x@gmail.com")   # no tokens -> stops at token step
    stats = run(poll_gmail_for_user(env.s, u))
    assert "skipped_billing" not in stats
    assert "access token" in (stats["error"] or "")


# ═════════════════════════ Slack ═════════════════════════
def slack_run(env, monkeypatch, sender, require_mention):
    from app import slack_bot
    posts, calls = [], []

    async def fake_extract(text):
        calls.append(text)
        return types.SimpleNamespace(task="Send the invoice", assignee=None, deadline=None, priority=None, confidence=0.95)

    monkeypatch.setattr(slack_bot, "extract_task_from_message", fake_extract)
    monkeypatch.setattr(slack_bot, "_post", lambda client, ch, ts, text: posts.append(text))
    event = {"channel": "C1", "ts": f"{uuid.uuid4().int % 10**10}.0001", "user": sender.slack_user_id,
             "text": "Ali please send the invoice by Friday"}
    slack_bot._process_message(event, MagicMock(), require_mention=require_mention)
    return posts, calls


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_slack_creates_tasks_for_allowed_users(env, monkeypatch, status, ends):
    u, w = env.team(status, ends, slack_user_id=f"U{uuid.uuid4().hex[:9].upper()}")
    posts, _ = slack_run(env, monkeypatch, u, require_mention=True)
    assert len(env.tasks(w)) == 1 and any("added to *To Do*" in p for p in posts)


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_slack_blocked_user_gets_a_notice_when_they_mention_the_bot(env, monkeypatch, status, ends):
    u, w = env.team(status, ends, slack_user_id=f"U{uuid.uuid4().hex[:9].upper()}")
    posts, _ = slack_run(env, monkeypatch, u, require_mention=True)
    assert env.tasks(w) == []
    assert any("trial has ended" in p for p in posts)


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_slack_blocked_user_is_ignored_silently_for_auto_detected_messages(env, monkeypatch, status, ends):
    u, w = env.team(status, ends, slack_user_id=f"U{uuid.uuid4().hex[:9].upper()}")
    posts, _ = slack_run(env, monkeypatch, u, require_mention=False)
    assert env.tasks(w) == [] and posts == []


# ═════════════════════════ Slack: which workspace does a task go to? ═════════════════════════
def slack_from(env, monkeypatch, slack_user, team, require_mention=True):
    """Run one Slack message from `slack_user` (maybe unlinked) in Slack team `team`; return the notices posted."""
    from app import slack_bot
    posts = []

    async def fake_extract(text):
        return types.SimpleNamespace(task="Send the invoice", assignee=None, deadline=None, priority=None, confidence=0.95)

    monkeypatch.setattr(slack_bot, "extract_task_from_message", fake_extract)
    monkeypatch.setattr(slack_bot, "_post", lambda client, ch, ts, text: posts.append(text))
    event = {"channel": "C1", "ts": f"{uuid.uuid4().int % 10**10}.0002", "user": slack_user, "team": team,
             "text": "Ali please send the invoice by Friday"}
    slack_bot._process_message(event, MagicMock(), require_mention=require_mention)
    return posts


def two_customers(env):
    tag = uuid.uuid4().hex[:6].upper()
    a, wa = env.team("active", slack_user_id=f"UA{tag}", slack_team_id=f"TA{tag}")
    b, wb = env.team("active", slack_user_id=f"UB{tag}", slack_team_id=f"TB{tag}")
    return tag, wa, wb


def test_unlinked_slack_user_goes_to_their_own_teams_workspace_not_a_strangers(env, monkeypatch):
    tag, wa, wb = two_customers(env)
    slack_from(env, monkeypatch, f"UNEWB{tag}", f"TB{tag}")           # not linked, but in customer B's Slack team
    assert len(env.tasks(wb)) == 1 and env.tasks(wa) == []
    slack_from(env, monkeypatch, f"UNEWA{tag}", f"TA{tag}")
    assert len(env.tasks(wa)) == 1 and len(env.tasks(wb)) == 1


def test_unlinked_slack_user_from_an_unknown_team_creates_nothing_anywhere(env, monkeypatch):
    tag, wa, wb = two_customers(env)
    posts = slack_from(env, monkeypatch, f"USTRANGER{tag}", f"TOTHER{tag}", require_mention=True)
    assert env.tasks(wa) == [] and env.tasks(wb) == []
    assert any("log in to the web app with Slack" in p for p in posts)          # told how to link
    quiet = slack_from(env, monkeypatch, f"USTRANGER{tag}", f"TOTHER{tag}", require_mention=False)
    assert quiet == [] and env.tasks(wa) == [] and env.tasks(wb) == []          # auto-detected: silent


def test_message_without_any_team_info_creates_nothing_when_several_workspaces_exist(env, monkeypatch):
    tag, wa, wb = two_customers(env)
    slack_from(env, monkeypatch, f"USTRANGER{tag}", None)
    assert env.tasks(wa) == [] and env.tasks(wb) == []


def test_slack_team_spread_over_two_workspaces_is_ambiguous_so_nothing_is_created(env, monkeypatch):
    tag = uuid.uuid4().hex[:6].upper()
    env.team("active", slack_user_id=f"U1{tag}", slack_team_id=f"TS{tag}")
    _, w2 = env.team("active", slack_user_id=f"U2{tag}", slack_team_id=f"TS{tag}")
    slack_from(env, monkeypatch, f"UNEW{tag}", f"TS{tag}")
    assert env.tasks(w2) == []


def test_linked_sender_always_uses_their_own_workspace_whatever_the_team(env, monkeypatch):
    tag, wa, wb = two_customers(env)
    slack_from(env, monkeypatch, f"UA{tag}", f"TB{tag}")                # A's user, message arrives tagged with B's team
    assert len(env.tasks(wa)) == 1 and env.tasks(wb) == []


def test_single_company_install_keeps_working_without_team_info(env, monkeypatch):
    """Exactly one workspace in the whole system -> unlinked senders still land on it (as before)."""
    from app import slack_bot
    tag = uuid.uuid4().hex[:6].upper()
    _, w = env.team("active", slack_user_id=f"UONLY{tag}")
    monkeypatch.setattr(slack_bot, "_only_workspace_id", lambda db: w.id)      # emulate a one-workspace database
    slack_from(env, monkeypatch, f"UNEW{tag}", None)
    assert len(env.tasks(w)) == 1


def test_only_workspace_id_helper_needs_exactly_one(env):
    from app import slack_bot
    assert env.ws() is not None and env.ws() is not None                       # at least two workspaces exist now
    assert slack_bot._only_workspace_id(env.s) is None


# ═════════════════════════ Microsoft Teams ═════════════════════════
def teams_run(env, monkeypatch, w, tenant):
    from app.routers import teams
    from app.models import WorkspaceSettings
    env.s.add(WorkspaceSettings(workspace_id=w.id, teams_tenant_id=tenant)); env.s.commit()
    replies = []

    async def fake_reply(activity, text):
        replies.append(text)

    monkeypatch.setattr(teams, "_reply", fake_reply)
    run(teams._handle_message({"text": "create task finish the Q3 report", "channelData": {"tenant": {"id": tenant}}}))
    return replies


@pytest.mark.parametrize("status,ends", ALLOWED)
def test_teams_creates_tasks_for_allowed_owner(env, monkeypatch, status, ends):
    owner, w = env.team(status, ends)
    teams_run(env, monkeypatch, w, f"tenant-{uuid.uuid4().hex}")
    assert len(env.tasks(w)) == 1


@pytest.mark.parametrize("status,ends", BLOCKED)
def test_teams_blocked_owner_gets_a_notice_and_no_task(env, monkeypatch, status, ends):
    owner, w = env.team(status, ends)
    replies = teams_run(env, monkeypatch, w, f"tenant-{uuid.uuid4().hex}")
    assert env.tasks(w) == [] and any("trial has ended" in r for r in replies)


# ═════════════════════════ scheduler (reminders + daily digest) ═════════════════════════
def test_ping_job_sends_no_reminders_for_blocked_owners(env, monkeypatch):
    from app import scheduler
    from app.models import Priority, Task, TaskStatus
    sent = []
    monkeypatch.setattr(scheduler, "_send_dm", lambda uid, text: sent.append(uid) or True)

    tag = uuid.uuid4().hex[:6].upper()
    good, gw = env.team("active")
    bad, bw = env.team("trialing", PAST)
    for owner, w, who in ((good, gw, f"UGOOD{tag}"), (bad, bw, f"UBAD{tag}")):
        env.s.add(Task(title=f"drifting {who}", task_description="x", priority=Priority.high, status=TaskStatus.to_do,
                       assignee="Ali", assignee_id=who, owner_id=owner.id, workspace_id=w.id,
                       created_at=NOW - timedelta(days=3), share_token=uuid.uuid4().hex[:20]))
    env.s.commit()

    scheduler._ping_overdue_tasks()
    assert f"UGOOD{tag}" in sent
    assert f"UBAD{tag}" not in sent
    env.s.expire_all()
    pinged = {t.title: t.pinged_at for t in env.tasks(gw) + env.tasks(bw)}
    assert pinged[f"drifting UGOOD{tag}"] is not None and pinged[f"drifting UBAD{tag}"] is None


def test_daily_rollup_skips_blocked_users_and_blocked_managers(env, monkeypatch):
    from app import scheduler
    from app.models import Priority, Task, TaskStatus
    sent = []
    monkeypatch.setattr(scheduler, "_send_dm", lambda uid, text: sent.append(uid) or True)

    tag = uuid.uuid4().hex[:6].upper()
    good, gw = env.team("exempt", slack_user_id=f"UGOOD{tag}")
    bad, bw = env.team("cancelled", slack_user_id=f"UBAD{tag}")
    for owner, w in ((good, gw), (bad, bw)):
        env.s.add(Task(title="due today", task_description="x", priority=Priority.medium, status=TaskStatus.to_do,
                       deadline="today", owner_id=owner.id, workspace_id=w.id, share_token=uuid.uuid4().hex[:20]))
        env.s.add(Task(title="long overdue", task_description="x", priority=Priority.high, status=TaskStatus.to_do,
                       deadline="2020-01-01", owner_id=owner.id, workspace_id=w.id, share_token=uuid.uuid4().hex[:20]))
    env.s.commit()

    result = scheduler._daily_rollup()                    # real queries, nothing faked
    assert "error" not in result, result
    assert sent.count(f"UGOOD{tag}") == 2    # personal digest (part 1) + manager summary (part 2)
    assert sent.count(f"UBAD{tag}") == 0     # nothing at all for the blocked user/manager


# ═════════════════════════ the daily-digest queries themselves ═════════════════════════
def _task(env, w, owner, title, deadline, status=None, priority=None, created_at=None):
    from app.models import Priority, Task, TaskStatus
    t = Task(title=title, task_description=title, deadline=deadline, owner_id=owner.id, workspace_id=w.id,
             status=status or TaskStatus.to_do, priority=priority or Priority.medium,
             share_token=uuid.uuid4().hex[:20], **({"created_at": created_at} if created_at else {}))
    env.s.add(t); env.s.commit()
    return t


def test_tasks_due_today_for_user(env):
    from app import crud
    from app.models import Priority, TaskStatus
    me, w = env.team("active"); other, _ = env.team("active")
    _task(env, w, me, "A medium today", "today")
    _task(env, w, me, "B high today", "Today by 5pm", priority=Priority.high)
    _task(env, w, me, "C tomorrow", "tomorrow")
    _task(env, w, me, "D long ago", "2020-01-01")
    _task(env, w, me, "E done", "today", status=TaskStatus.completed)
    _task(env, w, me, "F no deadline", None)
    _task(env, w, me, "G vague", "soon")
    _task(env, w, other, "H someone else's", "today")
    got = [t.title for t in crud.get_tasks_due_today_for_user(env.s, me.id)]
    assert got == ["B high today", "A medium today"]      # highest priority first


def test_relative_deadlines_count_from_when_the_task_was_created(env):
    from app import crud
    from app.models import Priority
    me, w = env.team("active")
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    _task(env, w, me, "said tomorrow, 3 days ago", "tomorrow", priority=Priority.high, created_at=three_days_ago)
    assert crud.get_tasks_due_today_for_user(env.s, me.id) == []                        # it was due 2 days ago...
    assert [t.title for t in crud.get_overdue_high_priority_tasks_for_workspace(env.s, w.id)] == \
           ["said tomorrow, 3 days ago"]                                                  # ...so it is overdue


def test_users_with_tasks_due_today(env):
    from app import crud
    ok, w = env.team("active", slack_user_id="UOK" + uuid.uuid4().hex[:6])
    no_slack, w2 = env.team("active")
    inactive, w3 = env.team("active", slack_user_id="UIN" + uuid.uuid4().hex[:6], is_active=False)
    tomorrow_only, w4 = env.team("active", slack_user_id="UTM" + uuid.uuid4().hex[:6])
    for u, w_, d in ((ok, w, "today"), (no_slack, w2, "today"), (inactive, w3, "today"), (tomorrow_only, w4, "tomorrow")):
        _task(env, w_, u, "t", d)
    mine = {ok.id, no_slack.id, inactive.id, tomorrow_only.id}
    got = {u.id for u in crud.get_all_active_users_with_tasks_due_today(env.s)} & mine
    assert got == {ok.id}


def test_overdue_high_priority_tasks_for_workspace(env):
    from app import crud
    from app.models import Priority, TaskStatus
    me, w = env.team("active"); _, other_w = env.team("active")
    _task(env, w, me, "critical 2020-06", "2020-06-01", priority=Priority.critical)
    _task(env, w, me, "high 2020-01", "2020-01-01", priority=Priority.high)
    _task(env, w, me, "medium overdue", "2020-01-01", priority=Priority.medium)
    _task(env, w, me, "done overdue", "2020-01-01", priority=Priority.high, status=TaskStatus.completed)
    _task(env, w, me, "high today", "today", priority=Priority.high)
    _task(env, w, me, "high future", "2999-01-01", priority=Priority.high)
    _task(env, w, me, "high vague", "soon", priority=Priority.high)
    _task(env, w, me, "high none", None, priority=Priority.high)
    _task(env, other_w, me, "other workspace", "2020-01-01", priority=Priority.high)
    assert [t.title for t in crud.get_overdue_high_priority_tasks_for_workspace(env.s, w.id)] == \
           ["high 2020-01", "critical 2020-06"]                                           # oldest first


def test_managers_for_workspace(env):
    from app import crud
    from app.models import UserRole
    boss, w = env.team("active", slack_user_id="UB" + uuid.uuid4().hex[:6])
    env.user("active", workspace=w, role=UserRole.navigator, slack_user_id="UN" + uuid.uuid4().hex[:6])
    env.user("active", workspace=w, role=UserRole.architect)                                       # no slack id
    env.user("active", workspace=w, role=UserRole.architect, slack_user_id="UI" + uuid.uuid4().hex[:6], is_active=False)
    _, other_w = env.team("active", slack_user_id="UO" + uuid.uuid4().hex[:6])
    assert [u.id for u in crud.get_managers_for_workspace(env.s, w.id)] == [boss.id]
