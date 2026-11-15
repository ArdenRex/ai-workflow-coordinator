"""Runs the acceptance checks and writes docs/ACCEPTANCE.md. Usage (from the repository root): python scripts/acceptance_report.py"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Collect:
    def __init__(self):
        self.results = {}

    def pytest_runtest_logreport(self, report):
        name = report.nodeid.split("::")[-1]
        keys = re.findall(r"(?:^test_|_)(c\d\d)(?=_)", name)           # a test may cover several criteria, e.g. test_c04_c05_...
        for key in keys:
            if report.skipped:
                self.results[key] = "MANUAL"
            elif report.failed:
                self.results[key] = "FAIL"
            elif report.when == "call" and self.results.get(key) != "FAIL":
                self.results[key] = "PASS"


def main() -> int:
    from tests.test_acceptance import CRITERIA
    plug = Collect()
    code = pytest.main([str(ROOT / "tests" / "test_acceptance.py"), "-q", "-p", "no:cacheprovider", "-o", "addopts="], plugins=[plug])
    lines = ["# Acceptance report (Step 15.1)", "",
             f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by `python scripts/acceptance_report.py` "
             "from the success criteria in the blueprint.", "", "| # | Success criterion | Result |", "|---|---|---|"]
    for key, text in CRITERIA.items():
        lines.append(f"| {key[1:]} | {text} | {plug.results.get(key, 'NOT RUN')} |")
    passed = sum(v == "PASS" for v in plug.results.values())
    lines += ["", f"**{passed} of {len(CRITERIA)} criteria verified by software; MANUAL = needs a human or real customers.**"]
    lines += ["", "## What each check proves", "",
              "- 01: static scan: the core packages never import the Aceden connector or the provider registry and never mention Aceden (they may reuse the generic network guard, base config and errors).",
              "- 02, 08, 11: over HTTP with two workspaces and the role set (viewer, member, admin, owner, outsider).",
              "- 03: a connection is created and tested against a mock external system; the secret never appears in a response.",
              "- 04, 05: a goal produces `intent.resolved` and `plan.proposed` events and stops at approval; nothing executes.",
              "- 06: a two-step plan with a dependency runs to completion through the plans API.",
              "- 07: static scan: the only place a tool handler is invoked is `app/kernel/service.py`.",
              "- 09: resuming before approval, after rejection, and deciding as an outsider all fail; the action never runs.",
              "- 10: plan, approval request and decision, execution and result are all recorded with an actor.",
              "- 12: a workflow pauses at an approval and resumes exactly once after a human decision.",
              "- 13: failed executions raise a visible alert in the monitoring overview.",
              "- 14: evidence only: the security, isolation, backup and production documents and the sweep and hardening test files exist. The full suite is the real evidence.",
              "- 15: MANUAL. Measurable business value is shown with pilot customers, not by software tests.", ""]
    (ROOT / "docs" / "ACCEPTANCE.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(v in ("PASS", "MANUAL") for v in plug.results.values()) and len(plug.results) == len(CRITERIA) else 1


if __name__ == "__main__":
    raise SystemExit(main())
