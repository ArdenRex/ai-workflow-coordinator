"""Step 14.3: automatic surface sweeps. They discover routes and tables themselves, so a future addition cannot dodge them."""
import uuid

import pytest
from sqlalchemy import inspect

from app.database import Base
from tests.route_discovery import api_routes
from tests.test_isolation import _call, world  # noqa: F401

# The ONLY operations reachable without a token. Adding a public route means editing this list on purpose.
PUBLIC = {("POST", "/auth/register"), ("POST", "/auth/login"), ("GET", "/health"), ("GET", "/ready")}


def test_only_the_listed_operations_are_public(client, app):
    ops = [(m, r.path) for r in api_routes(app) for m in r.methods]
    assert len(ops) > 60 and PUBLIC <= set(ops)                  # guard against a vacuous pass
    for method, path in ops:
        if (method, path) in PUBLIC:
            continue
        concrete = path
        for p in r_params(path):
            concrete = concrete.replace("{" + p + "}", str(uuid.uuid4()))
        res = client.request(method, concrete, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert res.status_code == 401, (method, path, res.status_code)


def r_params(path):
    import re
    return re.findall(r"{([^}]+)}", path)


def test_every_workspace_table_has_a_workspace_foreign_key_and_index():
    missing_fk, missing_ix = [], []
    for table in Base.metadata.sorted_tables:
        if "workspace_id" not in table.c:
            continue
        col = table.c.workspace_id
        if not any(fk.column.table.name == "workspaces" for fk in col.foreign_keys) and table.name != "workspaces":
            missing_fk.append(table.name)
        indexed = col.index or any(list(ix.columns)[0].name == "workspace_id" for ix in table.indexes) \
            or any(list(c.columns)[0].name == "workspace_id" for c in table.constraints if hasattr(c, "columns") and len(c.columns))
        if not indexed:
            missing_ix.append(table.name)
    assert len([t for t in Base.metadata.sorted_tables if "workspace_id" in t.c]) >= 15      # not vacuous
    assert missing_fk == [], f"workspace_id without a foreign key: {missing_fk}"
    assert missing_ix == [], f"workspace_id without a leading index/constraint: {missing_ix}"


@pytest.mark.parametrize("body", [{}, [], "text", {"x": {"y": [1] * 50}}])
def test_no_workspace_route_answers_5xx_to_unknown_ids_or_junk_bodies(client, app, world, body):
    """An owner of workspace A calls every workspace route with random ids and junk bodies: always a clean 4xx or 2xx, never a 500."""
    hs, a, b = world
    routes = api_routes(app, contains="{workspace_id}")
    assert len(routes) >= 50
    bad = []
    for route in routes:
        for method in route.methods:
            path = route.path.replace("{workspace_id}", a["id"])
            for p in route.param_convertors:
                path = path.replace("{" + p + "}", str(uuid.uuid4()))
            res = client.request(method, path, headers=hs["a_owner"], json=body if method in ("POST", "PUT", "PATCH") else None)
            if res.status_code >= 500:
                bad.append((method, route.path, res.status_code, res.text[:120]))
    assert bad == [], bad
