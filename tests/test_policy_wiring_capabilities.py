"""Substep 12.2a: a stored workspace policy takes effect on the Step 11 HTTP routes and composite tools."""
import pathlib

from app.kernel.policy import WorkspacePolicy
from app.kernel.policy_store import session_policy_provider
from tests.test_workspace_connectors import team, signup, mkws, public_dns  # noqa: F401  (fixtures)
from app.runtime import build_runtime, get_policy_provider
from app.config import Settings

ROUTES = ("attention", "opportunities", "changes", "meetings")


def test_capability_routes_use_the_request_policy_provider_and_no_default_policy():
    text = pathlib.Path("app/api/capabilities.py").read_text()
    assert text.count("ToolExecutionService(db, tools, policy_provider=policy)") == len(ROUTES)
    assert "ToolExecutionService(db, tools)" not in text
    assert text.count("Depends(request_policy_provider)") == len(ROUTES)


def test_every_composite_tool_is_built_with_the_shared_provider():
    text = pathlib.Path("app/runtime.py").read_text()
    assert text.count("policy_provider=policy") == 4 and text.count("get_policy_provider()") >= 1
    reg, _ = build_runtime(Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None))
    assert callable(get_policy_provider())


def test_a_stored_policy_reaches_the_kernel_built_by_each_capability_route(client, team, monkeypatch):
    from tests.test_policy_store import put
    import app.api.capabilities as cap
    hs, ws = team
    seen = {}

    def fake(name, method):
        class Fake:
            def __init__(self, kernel, *a, **k):
                seen.setdefault(name, kernel)
            def __getattr__(self, _n):
                def call(principal):
                    raise _Stop()
                return call
        return Fake

    class _Stop(Exception):
        pass

    for name, cls in (("attention", "AttentionService"), ("opportunities", "OpportunityService"),
                      ("changes", "ChangesService"), ("meetings", "MeetingService")):
        monkeypatch.setattr(cap, cls, fake(name, None))
    path = f"/workspaces/{ws['id']}/capabilities/"

    def kernels():
        seen.clear()
        for name in ROUTES:
            try:
                client.post(path + name, headers=hs["admin"])
            except _Stop:
                pass
        return seen

    for k in kernels().values():
        assert k.policy_provider(ws["id"]) == WorkspacePolicy()                    # no row = baseline
    put(client, hs["admin"], ws, expected_version=0, autonomy_level=2, disabled_tools=["system.ping"])
    ks = kernels()
    assert set(ks) == set(ROUTES)
    for k in ks.values():
        assert k.policy_provider(ws["id"]).disabled_tools == frozenset({"system.ping"})   # stored policy now reaches every route


def test_session_provider_fails_closed(db_session):
    class Boom:
        def scalar(self, *_a, **_k):
            raise RuntimeError("store down")
    try:
        session_policy_provider(Boom())("ws")
    except RuntimeError:
        return
    raise AssertionError("a store error must propagate, never become a default")
