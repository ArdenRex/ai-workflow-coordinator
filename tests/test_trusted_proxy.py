"""Step 15.2: client address behind reverse proxies, and the container healthcheck."""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.config import Settings
from app.security.clientip import client_ip
from tests.test_workspaces_api import PW, signup

ROOT = Path(__file__).resolve().parent.parent


class FakeApp:
    class state:
        trusted_proxy_count = 0


def req(xff=None, peer="10.0.0.9", n=0):
    app = type("A", (), {"state": type("S", (), {"trusted_proxy_count": n})()})()
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 5000), "app": app, "method": "GET", "path": "/"})


def test_by_default_the_forwarded_header_is_ignored():
    assert client_ip(req("6.6.6.6")) == "10.0.0.9" and client_ip(req(None)) == "10.0.0.9"


@pytest.mark.parametrize("xff,n,expected", [
    ("203.0.113.5", 1, "203.0.113.5"),                       # one proxy appended the real client
    ("1.1.1.1, 203.0.113.5", 1, "203.0.113.5"),              # the client sent its own value first: ignored
    ("evil, 1.1.1.1, 203.0.113.5", 2, "1.1.1.1"),            # two proxies: second from the right
    ("2001:db8::1", 1, "2001:db8::1"),
    ("", 1, "10.0.0.9"), (None, 1, "10.0.0.9"),             # no header: the direct peer
    ("203.0.113.5", 2, "10.0.0.9"),                          # fewer entries than proxies: not trusted
    ("not-an-ip", 1, "10.0.0.9"), ("999.1.1.1", 1, "10.0.0.9"), ("1.1.1.1:80", 1, "10.0.0.9"),
])
def test_the_nth_entry_from_the_right_is_used_and_anything_odd_falls_back(xff, n, expected):
    assert client_ip(req(xff, n=n)) == expected


def test_a_client_cannot_pick_its_own_address_even_with_a_proxy():
    for forged in ("9.9.9.9", "9.9.9.9, 9.9.9.9, 9.9.9.9", "127.0.0.1"):
        assert client_ip(req(f"{forged}, 203.0.113.5", n=1)) == "203.0.113.5"


def test_the_setting_is_bounded_and_allowed_in_production():
    for bad in (-1, 6):
        with pytest.raises(ValidationError):
            Settings(app_env="development", trusted_proxy_count=bad, _env_file=None)
    assert Settings(app_env="development", trusted_proxy_count=2, _env_file=None).trusted_proxy_count == 2


def test_the_activity_log_records_the_proxy_supplied_address_only_when_enabled(client):
    h = signup(client, "a@x.com")
    client.post("/auth/login", json={"email": "a@x.com", "password": PW}, headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.5"})
    ips = lambda: {e["ip"] for e in client.get("/auth/activity", headers=h).json()}
    assert "203.0.113.5" not in ips() and "6.6.6.6" not in ips()                      # disabled: the header is ignored
    client.app.state.trusted_proxy_count = 1
    client.post("/auth/login", json={"email": "a@x.com", "password": PW}, headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.5"})
    assert "203.0.113.5" in ips() and "6.6.6.6" not in ips()


def test_the_example_env_and_dockerfile_cover_the_new_pieces():
    assert "TRUSTED_PROXY_COUNT=0" in (ROOT / ".env.example").read_text()
    d = (ROOT / "Dockerfile").read_text()
    assert re.search(r"^HEALTHCHECK ", d, re.M) and "/health" in d and d.index("HEALTHCHECK") < d.index("CMD [")
