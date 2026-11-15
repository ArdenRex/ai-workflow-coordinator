"""Step 14.9: release hygiene. No credentials in the repository, a sane ignore list, and the production checklist matches the code."""
import re
from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "venv", ".venv", "node_modules"}
PATTERNS = {
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    "bearer literal": re.compile(r"Bearer\s+[A-Za-z0-9\-_]{40,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}"),
    "database url with real password": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:(?!password|pass|secret|postgres|u\b|p\b|x\b|\*|\$|<|\{)[^@\s]{8,}@(?!localhost|127\.0\.0\.1|db\b|h\b)"),
}


# Fabricated placeholder secrets that tests feed to the secret-refusal logic. Any other file with a hit fails the scan.
FIXTURE_FILES = {"tests/test_memory_model.py", "tests/test_chat_slack.py", "tests/test_release_hygiene.py"}


def repo_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.suffix not in {".db", ".zip", ".png", ".ico", ".pyc"}:
            yield p


def test_no_credentials_are_committed():
    hits = []
    for p in repo_files():
        if str(p.relative_to(ROOT)) in FIXTURE_FILES:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for name, rx in PATTERNS.items():
            if rx.search(text):
                hits.append((str(p.relative_to(ROOT)), name))
    assert hits == [], hits


def test_no_env_or_database_files_are_in_the_tree():
    assert not (ROOT / ".env").exists()
    assert not [p for p in ROOT.rglob("*.db") if not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]
    ignore = (ROOT / ".gitignore").read_text().split()
    assert {".env", "*.db"} <= set(ignore)


def test_example_env_holds_only_placeholders():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith(("APP_SECRET_KEY=", "ACEDEN_API_KEY=", "LLM_API_KEY=")):
            value = line.split("=", 1)[1].strip()
            assert value == "" or "change" in value.lower() or "your" in value.lower() or "example" in value.lower() or "dev-" in value.lower(), line


def test_the_production_checklist_matches_the_code():
    from app.config import Settings
    doc = (ROOT / "docs" / "PRODUCTION.md").read_text()
    head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    assert f"`{head}`" in doc, f"docs/PRODUCTION.md must name the current migration head {head}"
    guarded = ["APP_ENV", "APP_SECRET_KEY", "DATABASE_URL", "ALLOWED_ORIGINS", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY",
               "AUTH_MAX_FAILED_LOGINS", "AUTH_MAX_REQUESTS_PER_MINUTE", "ALLOW_PRIVATE_CONNECTOR_HOSTS", "CONNECTOR_MAX_CALLS_PER_MINUTE",
               "ACEDEN_BASE_URL", "APP_SECRET_KEY_PREVIOUS"]
    fields = {f.upper() for f in Settings.model_fields}
    assert set(guarded) <= fields
    assert [g for g in guarded if g not in doc] == []


def test_requirements_pin_every_package_exactly_except_the_cryptography_range():
    lines = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    loose = [l for l in lines if "==" not in l and not l.startswith("cryptography")]
    assert loose == [], loose


def test_the_runbook_covers_the_operations_that_matter():
    doc = (ROOT / "docs" / "RUNBOOK.md").read_text()
    for needle in ("alembic upgrade head", "APP_SECRET_KEY_PREVIOUS", "python -m app.reencrypt", "/auth/logout", "monitoring/alerts",
                   "TRUSTED_PROXY_COUNT", "/ready", "pg_restore"):
        assert needle in doc, needle
    rules = set(re.findall(r'fire\("([a-z_]+)"', (ROOT / "app" / "monitoring" / "alerts.py").read_text()))
    assert len(rules) == 12 and [r for r in sorted(rules) if r not in doc] == [], "every alert rule must be explained in the runbook"


def test_the_launch_checklist_references_real_files_and_commands():
    doc = (ROOT / "docs" / "LAUNCH.md").read_text()
    for ref in ("scripts/preflight.py", "scripts/acceptance_report.py", "docs/PRODUCTION.md", "docs/RUNBOOK.md", "docs/BACKUP.md", "docs/POSTGRES.md", "docs/SECURITY.md", "docs/ACCEPTANCE.md"):
        assert ref in doc and (ROOT / ref).exists(), ref
    assert "DONE" in doc and "OPEN" in doc



def test_vercel_entry_point_and_config_are_consistent():
    import json
    cfg = json.loads((ROOT / "vercel.json").read_text())
    assert cfg["rewrites"][0]["destination"] == "/api/index" and "api/index.py" in cfg["functions"]
    assert (ROOT / "api" / "index.py").exists()
    ignore = (ROOT / ".vercelignore").read_text().split()
    assert {"frontend", "tests", "docs", ".env"} <= set(ignore)
    front = json.loads((ROOT / "frontend" / "vercel.json").read_text())
    assert front["outputDirectory"] == "build"
    doc = (ROOT / "docs" / "DEPLOY_VERCEL.md").read_text()
    assert "REACT_APP_API_URL" in doc and "ALLOWED_ORIGINS" in doc and "alembic upgrade head" in doc


def test_the_vercel_entry_point_serves_the_app():
    import importlib.util
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert TestClient(mod.app).get("/health").status_code == 200
