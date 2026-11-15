"""Step 14.1: authentication throttling, security headers, request size cap, production config guards."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.throttle import MAX_KEYS, Throttle

PW = "correct-horse-battery"


def make(**kw):
    s = Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)
    return create_app(s)


@pytest.fixture
def tclient(engine):
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def build(**kw):
        app = make(**kw)

        def _db():
            db = factory()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = _db
        return TestClient(app)
    return build


def reg(c, email="a@example.com"):
    assert c.post("/auth/register", json={"email": email, "password": PW}).status_code == 201


def login(c, email="a@example.com", pw=PW):
    return c.post("/auth/login", json={"email": email, "password": pw})


# ------------------------------------------------------------------ throttle unit
def test_throttle_locks_after_the_limit_and_expires():
    t = [0.0]
    th = Throttle(max_failures=3, window_seconds=100, max_requests_per_minute=0, clock=lambda: t[0])
    for _ in range(3):
        assert th.check_login("e", "1.1.1.1") is None
        th.record_failure("e", "1.1.1.1")
    assert th.check_login("e", "1.1.1.1") >= 1
    assert th.check_login("e", "2.2.2.2") is None                    # a different address is not locked by the per-address limit
    t[0] = 101.0
    assert th.check_login("e", "1.1.1.1") is None


def test_email_wide_limit_stops_a_distributed_guesser():
    th = Throttle(max_failures=2, window_seconds=100, max_requests_per_minute=0, clock=lambda: 0.0)
    for i in range(8):                                               # 8 = 4x the per-address limit, each from a new address
        th.record_failure("victim", f"10.0.0.{i}")
    assert th.check_login("victim", "10.0.0.99") is not None
    assert th.check_login("other", "10.0.0.99") is None


def test_success_clears_only_that_address_and_zero_disables():
    th = Throttle(max_failures=2, window_seconds=100, max_requests_per_minute=0, clock=lambda: 0.0)
    th.record_failure("e", "a")
    th.record_failure("e", "a")
    assert th.check_login("e", "a") is not None
    th.record_success("e", "a")
    assert th.check_login("e", "a") is None
    off = Throttle(max_failures=0, window_seconds=100, max_requests_per_minute=0)
    for _ in range(50):
        off.record_failure("e", "a")
    assert off.check_login("e", "a") is None and off.check_request("a") is None


def test_request_limit_is_per_address_and_per_minute():
    t = [0.0]
    th = Throttle(max_failures=5, window_seconds=100, max_requests_per_minute=3, clock=lambda: t[0])
    assert [th.check_request("a") for _ in range(3)] == [None] * 3
    assert th.check_request("a") >= 1 and th.check_request("b") is None
    t[0] = 61.0
    assert th.check_request("a") is None


def test_memory_is_bounded():
    th = Throttle(max_failures=5, window_seconds=100, max_requests_per_minute=0, clock=lambda: 0.0)
    for i in range(MAX_KEYS + 500):
        th.record_failure(f"e{i}", "a")
    assert len(th._hits) <= MAX_KEYS


# ------------------------------------------------------------------ HTTP
def test_login_locks_after_repeated_failures_even_with_the_right_password(tclient):
    c = tclient(auth_max_failed_logins=3)
    reg(c)
    for _ in range(3):
        assert login(c, pw="wrong-password-1").status_code == 401
    r = login(c)                                                     # correct password, but the key is locked
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "access_token" not in r.text


def test_lockout_answer_does_not_reveal_whether_the_account_exists(tclient):
    c = tclient(auth_max_failed_logins=2)
    reg(c)
    for email in ("a@example.com", "ghost@example.com"):
        for _ in range(2):
            login(c, email, "wrong-password-1")
    assert login(c, "a@example.com").status_code == login(c, "ghost@example.com").status_code == 429


def test_a_successful_login_is_not_throttled_below_the_limit(tclient):
    c = tclient(auth_max_failed_logins=3)
    reg(c)
    login(c, pw="wrong-password-1")
    assert login(c).status_code == 200
    login(c, pw="wrong-password-1")
    login(c, pw="wrong-password-1")
    assert login(c).status_code == 200                               # success cleared the earlier failures


def test_request_rate_limit_covers_register_and_login(tclient):
    c = tclient(auth_max_requests_per_minute=4)
    codes = [c.post("/auth/register", json={"email": f"u{i}@example.com", "password": PW}).status_code for i in range(6)]
    assert codes[:4] == [201] * 4 and codes[4:] == [429, 429]
    assert login(c).status_code == 429


def test_security_headers_on_every_response_and_docs_still_work_in_dev(tclient):
    c = tclient()
    for r in (c.get("/health"), c.get("/auth/me"), c.get("/nope")):
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "content-security-policy" not in c.get("/docs").headers
    assert "script-src 'self'" in c.get("/dashboard").headers["content-security-policy"]      # a route's own stricter policy wins


def test_oversized_declared_body_gets_413_before_any_work(tclient):
    c = tclient(max_request_bytes=2048)
    r = c.post("/auth/register", content=b"x" * 5000, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.headers["x-content-type-options"] == "nosniff"
    assert c.post("/auth/register", json={"email": "b@example.com", "password": PW}).status_code == 201


@pytest.mark.parametrize("kw,msg", [
    ({"allowed_origins": "*"}, "explicit origins"),
    ({"auth_max_failed_logins": 0}, "throttling"),
    ({"auth_max_requests_per_minute": 0}, "throttling"),
])
def test_production_refuses_unsafe_security_settings(kw, msg):
    base = dict(app_env="production", app_secret_key="x" * 40, database_url="postgresql://u:p@h/db", llm_provider="openai_compatible",
                llm_base_url="https://llm.example", llm_api_key="k", _env_file=None)
    Settings(**base)                                                 # the baseline is valid
    with pytest.raises(ValueError, match=msg):
        Settings(**{**base, **kw})


@pytest.mark.parametrize("kw", [{"auth_max_failed_logins": 101}, {"auth_lockout_window_seconds": 5}, {"auth_max_requests_per_minute": -1},
                                {"max_request_bytes": 10}])
def test_new_settings_are_range_checked(kw):
    with pytest.raises(ValueError):
        Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None, **kw)
