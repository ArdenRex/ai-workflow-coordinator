"""Substep 12.3b: every place that SHOWS or DECIDES on a tool's risk uses the workspace-effective risk."""
import pathlib
import re

import pytest

from app.intelligence.catalog import build_catalog
from app.kernel.policy import WorkspacePolicy
from app.models.enums import RiskLevel
from tests.test_planning import OWNER, P, intent, make_registry, plan_json, run

pytestmark = pytest.mark.usefixtures("seed_workspaces")


def test_catalog_shows_effective_risk_and_never_lowers_it():
    reg = make_registry()
    pol = WorkspacePolicy(risk_overrides={"aceden.task.list": RiskLevel.HIGH, "aceden.task.update": RiskLevel.LOW})
    got = {e.tool_id: e for e in build_catalog(reg, P(OWNER), pol)}
    assert got["aceden.task.list"].risk_level == "high" and got["aceden.task.list"].requires_approval is True
    assert got["aceden.task.update"].risk_level == "medium"          # a lower override is ignored
    base = {e.tool_id: e for e in build_catalog(reg, P(OWNER), None)}
    assert base["aceden.task.list"].risk_level == "low"              # no policy: unchanged


def test_plan_proposal_carries_effective_risk(db_session):
    reg = make_registry()
    pol = WorkspacePolicy(risk_overrides={"aceden.task.list": RiskLevel.MEDIUM})
    _, r = run(db_session, [plan_json()], reg, policy=pol)
    pr = r.proposal
    assert (pr.risk_level, pr.requires_approval, pr.decision) == ("medium", True, "require_approval")


def test_plan_proposal_without_override_is_unchanged(db_session):
    _, r = run(db_session, [plan_json()], make_registry(), policy=WorkspacePolicy())
    assert (r.proposal.risk_level, r.proposal.decision) == ("low", "allow")


# Files allowed to read a ToolDefinition's own (base) risk, and why:
#  registry.py      defines it and validates it     policy.py        effective_risk() is the one reader
#  policy_store.py  checks an override is above it  agents/definition.py  agent risk ceiling (base risk, documented limit)
ALLOWED_BASE_RISK_READERS = {"kernel/registry.py", "kernel/policy.py", "kernel/policy_store.py", "agents/definition.py"}


def test_no_decision_path_reads_a_tools_base_risk_directly():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    pat = re.compile(r"\b(?:tool|t|td)\.risk_level\b")
    seen, offenders = 0, []
    for f in root.rglob("*.py"):
        rel = f.relative_to(root).as_posix()
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                seen += 1
                if rel not in ALLOWED_BASE_RISK_READERS:
                    offenders.append(f"{rel}:{n}")
    assert seen >= 3, "guard found no base-risk reads: its pattern is broken"
    assert offenders == []
