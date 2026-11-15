"""Step F1: the frontend's API calls match the real API, and the frontend folder is safe to commit."""
import re
from pathlib import Path

from app.main import create_app
from app.config import Settings

FRONT = Path(__file__).resolve().parent.parent / "frontend"


def norm(path):
    return re.sub(r"\{[^}]*\}", "{}", path)


def api_calls():
    src = (FRONT / "src" / "api.js").read_text()
    calls = []
    for chunk in re.split(r'request\((?=[`"])', src)[1:]:
        path = re.match(r'[`"](/[^`"?]*)', chunk).group(1)
        method = re.search(r'method:\s*"(\w+)"', chunk)
        calls.append((method.group(1) if method else "GET", norm(re.sub(r"\$\{[^}]*\}", "{}", path))))
    return calls


def test_every_frontend_call_exists_in_the_api_with_that_method():
    raw = create_app(Settings(app_env="test", _env_file=None)).openapi()["paths"]
    schema = {norm(k): v for k, v in raw.items()}
    calls = api_calls()
    assert len(calls) >= 24, calls
    for method, path in calls:
        assert path in schema and method.lower() in schema[path], (method, path)


def test_login_and_password_schemas_accept_the_fields_the_frontend_sends():
    schema = create_app(Settings(app_env="test", _env_file=None)).openapi()["components"]["schemas"]
    assert "remember_me" in schema["LoginRequest"]["properties"]
    assert {"current_password", "new_password", "remember_me"} <= set(schema["PasswordChangeRequest"]["properties"])
    assert "full_name" in schema["RegisterRequest"]["properties"]


def test_the_frontend_ignores_build_output_and_holds_no_secrets():
    assert {"node_modules", "build", ".env"} <= set((FRONT / ".gitignore").read_text().split())
    assert not (FRONT / ".env").exists()
    assert (FRONT / ".env.example").read_text().count("=") == 1
