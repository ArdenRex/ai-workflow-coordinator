"""Result aggregation: a plan's steps -> one safe, deterministic summary. Pure: no database, no LLM, no I/O.

Content-free by construction. It reads only step keys, agent ids, states, fixed error codes and the whitelisted
outcome fields the orchestrator stored (outcome word, tool id, execution id, run id). It never sees a goal,
an instruction, a tool output or model text, so nothing here can leak one.
"""
from typing import Any, Dict, Iterable, Mapping, Optional

from app.models.enums import PlanStatus as P
from app.models.enums import StepState as S

_ORDER = (S.SUCCEEDED, S.FAILED, S.SKIPPED, S.CANCELLED, S.RUNNING, S.WAITING_APPROVAL, S.PENDING)


def headline(plan_status: P, counts: Mapping[str, int]) -> str:
    """One fixed word for 'where is this plan': pending, running, waiting_approval, succeeded, failed, cancelled."""
    if plan_status == P.RUNNING and counts.get(S.WAITING_APPROVAL.value, 0):
        return "waiting_approval"
    return plan_status.value


def summarize(plan_status: P, steps: Iterable[Any], pending_executions: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """`steps` are plan step records; `pending_executions` maps run id -> pending kernel execution id (so a UI can
    route a waiting step to its approval). Returns counts, progress, failures and what needs attention."""
    steps = list(steps)
    pending_executions = pending_executions or {}
    counts = {s.value: 0 for s in _ORDER}
    for st in steps:
        counts[st.status.value] += 1
    total = len(steps)
    done = counts[S.SUCCEEDED.value] + counts[S.FAILED.value] + counts[S.SKIPPED.value] + counts[S.CANCELLED.value]
    failures = [{"step": st.step_key, "agent": st.agent_id, "error_code": st.error_code or "step_failed"}
                for st in steps if st.status == S.FAILED]
    skipped = [st.step_key for st in steps if st.status == S.SKIPPED]
    waiting = [{"step": st.step_key, "agent": st.agent_id, "run_id": st.run_id,
                "execution_id": pending_executions.get(st.run_id)}
               for st in steps if st.status == S.WAITING_APPROVAL]
    succeeded_steps = [{"step": st.step_key, "agent": st.agent_id, **_safe(st.result)}
                       for st in steps if st.status == S.SUCCEEDED]
    return {"headline": headline(plan_status, counts), "total_steps": total, "finished_steps": done,
            "counts": counts, "succeeded": succeeded_steps, "failures": failures, "skipped": skipped,
            "needs_attention": {"approvals": waiting, "failed_steps": [f["step"] for f in failures]}}


def _safe(result: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    keep = ("outcome", "reason", "tool_id", "execution_id", "run_id", "missing_count")
    return {k: v for k, v in (result or {}).items() if k in keep and isinstance(v, (str, int))}
