"""Shared rig for domain connector tests: a per-provider fake transport behind the real kernel, registry and credentials."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.connectors import registry as creg
from app.connectors.registry import ConnectorSpec
from app.connectors.workspace import WorkspaceConnectors, register_workspace_tools
from app.kernel.registry import ToolRegistry
from app.kernel.service import ToolExecutionService
from tests.test_workspace_connectors import principal


def add_cred(client, h, ws, provider, secret, config, name="conn"):
    r = client.post(f"/workspaces/{ws['id']}/credentials", headers=h,
                    json={"provider": provider, "name": name, "secret": secret, "config": config})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class DomainRig:
    def __init__(self, db, wc, svc):
        self.db, self.wc, self.svc, self.fakes = db, wc, svc, {}

    def run(self, email, ws, tool, data=None):
        return self.svc.submit(principal(self.db, email, ws["id"]), tool, data or {})


def make_rig(db_session, monkeypatch, provider, domains, build_for, check=None):
    """`build_for(rig, config, secret, settings)` returns the connector for a stored credential."""
    holder = {}

    def build(config, secret, settings, **kw):
        return build_for(holder["rig"], config, secret, settings)
    monkeypatch.setitem(creg.SPECS, provider, ConnectorSpec(provider, build, frozenset(domains), check))
    wc = WorkspaceConnectors(sessionmaker(bind=db_session.get_bind(), expire_on_commit=False), get_settings())
    rig = DomainRig(db_session, wc, ToolExecutionService(db_session, register_workspace_tools(ToolRegistry(), wc)))
    holder["rig"] = rig
    return rig
