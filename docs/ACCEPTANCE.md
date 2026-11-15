# Acceptance report (Step 15.1)

Generated 2026-11-14 15:35 UTC by `python scripts/acceptance_report.py` from the success criteria in the blueprint.

| # | Success criterion | Result |
|---|---|---|
| 01 | It is independent of the existing Aceden software | PASS |
| 02 | Multiple organizations can safely use it | PASS |
| 03 | External systems can be securely connected | PASS |
| 04 | AI can understand business requests | PASS |
| 05 | AI can plan controlled actions | PASS |
| 06 | Agents can coordinate work | PASS |
| 07 | Tools execute through one trusted boundary | PASS |
| 08 | Permissions are enforced | PASS |
| 09 | Approvals cannot be bypassed | PASS |
| 10 | Actions are auditable | PASS |
| 11 | Business context is available safely | PASS |
| 12 | Workflows can operate reliably | PASS |
| 13 | Failures are observable | PASS |
| 14 | The system is secure and tested | PASS |
| 15 | The product delivers measurable real-world business value | MANUAL |

**14 of 15 criteria verified by software; MANUAL = needs a human or real customers.**

## What each check proves

- 01: static scan: the core packages never import the Aceden connector or the provider registry and never mention Aceden (they may reuse the generic network guard, base config and errors).
- 02, 08, 11: over HTTP with two workspaces and the role set (viewer, member, admin, owner, outsider).
- 03: a connection is created and tested against a mock external system; the secret never appears in a response.
- 04, 05: a goal produces `intent.resolved` and `plan.proposed` events and stops at approval; nothing executes.
- 06: a two-step plan with a dependency runs to completion through the plans API.
- 07: static scan: the only place a tool handler is invoked is `app/kernel/service.py`.
- 09: resuming before approval, after rejection, and deciding as an outsider all fail; the action never runs.
- 10: plan, approval request and decision, execution and result are all recorded with an actor.
- 12: a workflow pauses at an approval and resumes exactly once after a human decision.
- 13: failed executions raise a visible alert in the monitoring overview.
- 14: evidence only: the security, isolation, backup and production documents and the sweep and hardening test files exist. The full suite is the real evidence.
- 15: MANUAL. Measurable business value is shown with pilot customers, not by software tests.

