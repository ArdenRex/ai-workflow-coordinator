"""Step 14.2: real concurrency on a server database. Skipped on SQLite (set TEST_DATABASE_URL to a PostgreSQL URL to run).

Each thread uses its OWN session and connection, so these exercise the database's real locking and unique constraints."""
import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.kernel.errors import PolicyDeniedError
from app.kernel.policy import WorkspacePolicy
from app.kernel.service import ToolExecutionService
from app.models import ToolExecution
from tests.conftest import TEST_DB_URL
from tests.test_execution_service import In, Out, P, Rig, ToolDefinition, ToolRegistry, RiskLevel  # noqa: F401

pytestmark = [pytest.mark.skipif(TEST_DB_URL.startswith("sqlite"), reason="needs a server database"),
              pytest.mark.usefixtures("seed_workspaces")]

THREADS = 8


def run_parallel(engine, work):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    results, errors, barrier = [], [], threading.Barrier(THREADS)

    def go(i):
        db = factory()
        try:
            barrier.wait(timeout=10)
            results.append(work(db, i))
        except Exception as exc:          # noqa: BLE001 - collected and asserted on
            errors.append(exc)
        finally:
            db.close()

    ts = [threading.Thread(target=go, args=(i,)) for i in range(THREADS)]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    return results, errors


def service(db, calls, policy=None):
    reg = ToolRegistry()

    def handler(ctx, data):
        calls.append(1)
        return {"value": data.n}
    reg.register(ToolDefinition(id="aceden.customer.read", description="d", input_schema=In, output_schema=Out,
                                required_permission="customer:read", risk_level=RiskLevel.LOW, handler=handler))
    return ToolExecutionService(db, reg, policy_provider=lambda ws: policy or WorkspacePolicy())


def count(engine):
    with engine.connect() as c:
        return c.scalar(select(func.count()).select_from(ToolExecution))


def test_parallel_submits_with_one_idempotency_key_run_the_tool_once(engine):
    calls = []
    results, errors = run_parallel(engine, lambda db, i: service(db, calls).submit(P(), "aceden.customer.read", {"n": 1}, idempotency_key="k").id)
    assert errors == [] and len(set(results)) == 1 and len(results) == THREADS
    assert count(engine) == 1 and len(calls) == 1


def test_parallel_submits_with_different_requests_on_one_key_conflict_cleanly(engine):
    from app.kernel.errors import IdempotencyConflictError
    calls = []
    results, errors = run_parallel(engine, lambda db, i: service(db, calls).submit(P(), "aceden.customer.read", {"n": i}, idempotency_key="k").id)
    assert count(engine) == 1 and len(calls) == 1
    assert all(isinstance(e, IdempotencyConflictError) for e in errors) and len(results) + len(errors) == THREADS


def limited_policy(n):
    from app.kernel.policy import ExecutionLimit
    return WorkspacePolicy(execution_limit=ExecutionLimit(max_executions=n, window_seconds=3600))


def test_parallel_runs_never_exceed_the_execution_cap(engine):
    calls = []
    cap = 3

    def work(db, i):
        try:
            return service(db, calls, limited_policy(cap)).submit(P(uid=f"u{i}"), "aceden.customer.read", {"n": i}).id
        except PolicyDeniedError as exc:
            return f"denied:{exc.reason_code}"
    results, errors = run_parallel(engine, work)
    ran = [r for r in results if not str(r).startswith("denied")]
    with engine.connect() as c:
        started = c.scalar(select(func.count()).select_from(ToolExecution).where(ToolExecution.started_at.is_not(None)))
        refused = c.scalar(select(func.count()).select_from(ToolExecution).where(ToolExecution.error == "execution_limit_reached"))
    assert errors == [], errors
    assert len(calls) == started == cap, (len(calls), started)                  # the tool ran exactly `cap` times
    assert len(ran) == cap and refused + cap == count(engine) == THREADS - len(results) + len(results)
