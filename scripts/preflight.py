"""Launch-gate preflight (Step 15.3). Run it against a DEPLOYED instance.

    python scripts/preflight.py https://ai-os.example.com                # read-only gates only
    python scripts/preflight.py https://ai-os.example.com --smoke        # also the first-day journey (creates one test user + workspace)
    python scripts/preflight.py https://ai-os.example.com --check-migrations   # also compares the database with the code's migration head

Uses only the standard library. Exit code 0 = every gate passed, 1 = at least one failed.
Output holds gate names and fixed text only: never a token, password or response body.
"""
import argparse
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request

EXPECTED_HEADERS = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer", "cache-control": "no-store"}
EVIL_ORIGIN = "https://preflight-evil.invalid"


class Http:
    """Tiny transport. Tests replace it with an in-process adapter that has the same request() method."""

    def __init__(self, base: str, timeout: float = 15.0):
        self.base, self.timeout = base.rstrip("/"), timeout
        self.ctx = ssl.create_default_context()

    def request(self, method, path, headers=None, body=None):
        data = None if body is None else json.dumps(body).encode()
        h = dict(headers or {})
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _json(raw):
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return None


class Gates:
    def __init__(self):
        self.results = []                                   # (name, ok, fixed-text detail)

    def add(self, name, ok, detail=""):
        self.results.append((name, bool(ok), "" if ok else detail))

    def run(self, name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:                            # never print exception text: it could carry a URL or a token
            ok, detail = False, f"check crashed ({type(exc).__name__})"
        self.add(name, ok, detail)

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


def read_only_gates(http, g: Gates):
    def ready():
        s, _, b = http.request("GET", "/ready")
        return s == 200 and (_json(b) or {}).get("database") is True, f"/ready answered {s}"
    g.run("G1 /ready is 200 and the database is reachable", ready)

    def health_minimal():
        s, _, b = http.request("GET", "/health")
        d = _json(b) or {}
        return s == 200 and "version" not in d and "env" not in d, "/health is down or reveals version/environment (is APP_ENV=production?)"
    g.run("G2 /health is up and reveals no version or environment", health_minimal)

    def schema_off():
        bad = [p for p in ("/openapi.json", "/docs", "/redoc") if http.request("GET", p)[0] != 404]
        return not bad, "publicly served: " + ", ".join(bad)
    g.run("G3 API schema and docs are not public", schema_off)

    def headers():
        _, h, _ = http.request("GET", "/health")
        missing = [k for k, v in EXPECTED_HEADERS.items() if h.get(k, "").lower() != v.lower()]
        if "content-security-policy" not in h:
            missing.append("content-security-policy")
        return not missing, "missing or wrong: " + ", ".join(missing)
    g.run("G4 security headers are present", headers)

    def auth_required():
        paths = ["/auth/me", "/workspaces", "/auth/activity"]
        bad = [p for p in paths if http.request("GET", p)[0] != 401]
        return not bad, "answered without a token: " + ", ".join(bad)
    g.run("G5 protected routes answer 401 without a token", auth_required)

    def cors():
        _, h, _ = http.request("OPTIONS", "/auth/login", {"Origin": EVIL_ORIGIN, "Access-Control-Request-Method": "POST"})
        allow = h.get("access-control-allow-origin", "")
        return allow not in ("*", EVIL_ORIGIN), "an unknown origin is allowed by CORS"
    g.run("G6 CORS refuses an unknown origin", cors)

    def bad_login_generic():
        s, _, b = http.request("POST", "/auth/login", body={"email": f"nobody-{secrets.token_hex(4)}@example.com", "password": "Wrong-pass-123!"})
        txt = (b or b"").decode("utf-8", "ignore").lower()
        return s in (401, 429) and "traceback" not in txt and "wrong-pass" not in txt, f"unexpected login answer {s}"
    g.run("G7 a bad login gives a generic 401 and echoes nothing", bad_login_generic)

    def validation_no_echo():
        canary = "CANARY-" + secrets.token_hex(6)
        s, _, b = http.request("POST", "/auth/register", body={"password": canary})
        return s == 422 and canary not in (b or b"").decode("utf-8", "ignore"), f"validation error answered {s} or echoed the request body"
    g.run("G8 a validation error does not echo the request body", validation_no_echo)


def migration_gate(g: Gates):
    def check():
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text

        from app.database import get_engine
        root = Path(__file__).resolve().parent.parent
        head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
        with get_engine().connect() as conn:
            cur = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        return cur == [head], "database revision does not equal the code's migration head (run: alembic upgrade head)"
    g.run("G9 database is at the code's migration head", check)


def smoke_journey(http, g: Gates):
    """First-day journey from docs/PRODUCTION.md section 10, minus the approval step (that needs a real connected system)."""
    email = f"preflight-{secrets.token_hex(5)}@example.com"
    pw = "Pf-" + secrets.token_urlsafe(18) + "9!"
    state = {}

    def register_login():
        s1, _, _ = http.request("POST", "/auth/register", body={"email": email, "password": pw})
        s2, _, b = http.request("POST", "/auth/login", body={"email": email, "password": pw})
        tok = (_json(b) or {}).get("access_token")
        state["h"] = {"Authorization": f"Bearer {tok}"} if tok else None
        return s1 == 201 and s2 == 200 and bool(tok), f"register {s1}, login {s2}"
    g.run("S1 register and log in", register_login)
    if not state.get("h"):
        return

    def workspace():
        s, _, b = http.request("POST", "/workspaces", state["h"], {"name": "Preflight check"})
        state["ws"] = (_json(b) or {}).get("id")
        s2, _, b2 = http.request("GET", "/workspaces", state["h"])
        return s == 201 and bool(state["ws"]) and s2 == 200, f"create {s}, list {s2}"
    g.run("S2 create and list a workspace", workspace)

    def overview():
        if not state.get("ws"):
            return False, "no workspace"
        s, _, b = http.request("GET", f"/workspaces/{state['ws']}/monitoring/overview?window_seconds=3600", state["h"])
        d = _json(b) or {}
        return s == 200 and isinstance(d, dict) and bool(d), f"overview answered {s}"
    g.run("S3 the monitoring overview loads for the workspace owner", overview)

    def dashboard():
        s, h, _ = http.request("GET", "/dashboard")
        csp = h.get("content-security-policy", "")
        return s == 200 and "script-src" in csp and "unsafe-inline" not in csp, f"/dashboard answered {s} or has a weak CSP"
    g.run("S4 /dashboard is served with a strict CSP", dashboard)

    def activity():
        s, _, b = http.request("GET", "/auth/activity?limit=10", state["h"])
        kinds = {e.get("event_type") or e.get("event") for e in (_json(b) or []) if isinstance(e, dict)}
        return s == 200 and bool(kinds & {"register", "login"}), f"activity answered {s} or lacks register/login"
    g.run("S5 account activity records register and login", activity)

    def logout():
        s, _, _ = http.request("POST", "/auth/logout", state["h"])
        s2, _, _ = http.request("GET", "/auth/me", state["h"])
        return s == 204 and s2 == 401, f"logout {s}; old token then answered {s2}"
    g.run("S6 logout revokes the old token", logout)


def render(g: Gates) -> str:
    lines = ["ACEDEN AI OS preflight", ""]
    for name, ok, detail in g.results:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"  -> {detail}"))
    lines += ["", f"{len(g.results) - len(g.failed)} of {len(g.results)} gates passed."]
    lines.append("RESULT: READY" if not g.failed else "RESULT: NOT READY - fix the FAIL lines above")
    lines.append("Not covered here: a real LLM and connector pass, load testing, an external security review, the PostgreSQL restore drill.")
    return "\n".join(lines)


def main(argv=None, http=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", default="")
    p.add_argument("--smoke", action="store_true", help="also run the first-day journey (creates one test user and workspace)")
    p.add_argument("--check-migrations", action="store_true", help="compare the database (DATABASE_URL) with the migration head")
    a = p.parse_args(argv)
    if http is None:
        if not a.url.startswith(("http://", "https://")):
            print("Give the instance URL, e.g. https://ai-os.example.com")
            return 2
        if a.url.startswith("http://"):
            print("WARNING: plain http. Production must be served over TLS.")
        http = Http(a.url)
    g = Gates()
    read_only_gates(http, g)
    if a.check_migrations:
        migration_gate(g)
    if a.smoke:
        smoke_journey(http, g)
    print(render(g))
    return 1 if g.failed else 0


if __name__ == "__main__":
    sys.exit(main())
