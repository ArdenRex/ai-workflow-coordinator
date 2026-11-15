"""Execution plan: an immutable, validated DAG of steps. Pure data and graph logic: no database, no LLM, no I/O.

A step names ONE agent and carries an instruction (text that becomes that agent run's goal) plus the ids of the
steps it depends on. A plan grants no authority: each step later runs as an ordinary agent run, so the user's
permissions, the agent's scope and tool rules, the workspace policy, approvals and audit all still apply.

Safety properties, enforced here and fail-closed
- Bounded: 1..HARD_MAX_STEPS steps, at most MAX_DEPENDENCIES per step, bounded instruction length, no control chars.
- Well-formed: unique slug ids, every dependency exists, no self-dependency, no cycles (Kahn's algorithm).
- Workspace-bound: `validate_for_workspace` checks every agent is registered and the plan fits the configured size.
- Deterministic: ordering, levels and readiness depend only on the plan and the supplied states (ties by declaration
  order), so the same plan always schedules the same way.
- Content-free identity: `digest()` is a SHA-256 over the canonical structure, so later stages can bind to a plan
  without storing instructions.
Failure handling is expressed as pure functions over step states (`ready_steps`, `steps_to_skip`) so the orchestrator
(7.4) only has to apply them.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Set, Tuple

from app.agents.definition import AGENT_ID_RE
from app.agents.registry import AgentRegistry
from app.models.enums import StepState
from app.orchestration.errors import InvalidPlanError

STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HARD_MAX_STEPS = 20
MAX_DEPENDENCIES = 5
MAX_INSTRUCTION_CHARS = 1000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


_DEAD = frozenset({StepState.FAILED, StepState.SKIPPED, StepState.CANCELLED})


def _bad(code: str, msg: str) -> InvalidPlanError:
    return InvalidPlanError(code, msg)


@dataclass(frozen=True)
class PlanStep:
    id: str
    agent_id: str
    instruction: str
    depends_on: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not STEP_ID_RE.match(self.id):
            raise _bad("invalid_step_id", "Step ids must be lowercase slugs (max 32 characters)")
        if not isinstance(self.agent_id, str) or not AGENT_ID_RE.match(self.agent_id):
            raise _bad("invalid_agent_id", "Invalid agent id")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise _bad("invalid_instruction", "Every step needs an instruction")
        text = self.instruction.strip()
        if len(text) > MAX_INSTRUCTION_CHARS or _CONTROL.search(text):
            raise _bad("invalid_instruction", f"Instructions are limited to {MAX_INSTRUCTION_CHARS} plain characters")
        deps = tuple(dict.fromkeys(self.depends_on))
        if len(deps) > MAX_DEPENDENCIES:
            raise _bad("too_many_dependencies", f"A step may depend on at most {MAX_DEPENDENCIES} steps")
        for d in deps:
            if not isinstance(d, str) or not STEP_ID_RE.match(d):
                raise _bad("invalid_step_id", "Invalid dependency id")
        if self.id in deps:
            raise _bad("self_dependency", "A step cannot depend on itself")
        object.__setattr__(self, "instruction", text)
        object.__setattr__(self, "depends_on", deps)


@dataclass(frozen=True)
class ExecutionPlan:
    steps: Tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        steps = tuple(self.steps)
        if not 1 <= len(steps) <= HARD_MAX_STEPS:
            raise _bad("invalid_plan_size", f"A plan needs between 1 and {HARD_MAX_STEPS} steps")
        if not all(isinstance(s, PlanStep) for s in steps):
            raise _bad("invalid_plan", "A plan holds only PlanStep items")
        ids = [s.id for s in steps]
        if len(set(ids)) != len(ids):
            raise _bad("duplicate_step_id", "Step ids must be unique")
        known = set(ids)
        for s in steps:
            if not set(s.depends_on) <= known:
                raise _bad("unknown_dependency", "A step depends on a step that does not exist")
        object.__setattr__(self, "steps", steps)
        if len(_kahn(steps)) != len(steps):
            raise _bad("dependency_cycle", "The plan contains a dependency cycle")

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(s.id for s in self.steps)

    def get(self, step_id: str) -> PlanStep:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    def digest(self) -> str:
        canon = [{"id": s.id, "agent": s.agent_id, "instruction": s.instruction, "deps": sorted(s.depends_on)}
                 for s in self.steps]
        return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _kahn(steps: Tuple[PlanStep, ...]) -> List[PlanStep]:
    """Topological order; ties broken by declaration order. Shorter than len(steps) means a cycle."""
    remaining = {s.id: set(s.depends_on) for s in steps}
    out: List[PlanStep] = []
    while remaining:
        ready = [s for s in steps if s.id in remaining and not remaining[s.id]]
        if not ready:
            break
        for s in ready:
            out.append(s)
            del remaining[s.id]
        for deps in remaining.values():
            deps.difference_update(r.id for r in ready)
    return out


def topological_order(plan: ExecutionPlan) -> List[PlanStep]:
    return _kahn(plan.steps)


def levels(plan: ExecutionPlan) -> List[List[str]]:
    """Groups of steps whose dependencies are all in earlier groups: each group could run independently."""
    depth: Dict[str, int] = {}
    for s in topological_order(plan):
        depth[s.id] = 1 + max((depth[d] for d in s.depends_on), default=-1)
    out: List[List[str]] = [[] for _ in range(max(depth.values()) + 1)]
    for s in plan.steps:
        out[depth[s.id]].append(s.id)
    return out


def descendants(plan: ExecutionPlan, step_id: str) -> Set[str]:
    """Every step that directly or transitively depends on `step_id`."""
    out: Set[str] = set()
    frontier = {step_id}
    while frontier:
        nxt = {s.id for s in plan.steps if set(s.depends_on) & frontier} - out
        out |= nxt
        frontier = nxt
    return out


def _state(states: Mapping[str, StepState], sid: str) -> StepState:
    return states.get(sid, StepState.PENDING)


def ready_steps(plan: ExecutionPlan, states: Mapping[str, StepState]) -> List[PlanStep]:
    """PENDING steps whose dependencies have ALL succeeded. A failed, skipped or cancelled dependency never
    unblocks anything (fail closed); see `steps_to_skip`."""
    return [s for s in plan.steps if _state(states, s.id) == StepState.PENDING
            and all(_state(states, d) == StepState.SUCCEEDED for d in s.depends_on)]


def steps_to_skip(plan: ExecutionPlan, states: Mapping[str, StepState]) -> List[str]:
    """PENDING steps that can never run because a dependency (directly or transitively) failed, was skipped or
    was cancelled. Independent branches are untouched."""
    dead = {sid for sid in plan.ids if _state(states, sid) in _DEAD}
    skip: List[str] = []
    for s in topological_order(plan):
        if _state(states, s.id) == StepState.PENDING and set(s.depends_on) & dead:
            skip.append(s.id)
            dead.add(s.id)
    return skip


def is_finished(plan: ExecutionPlan, states: Mapping[str, StepState]) -> bool:
    return all(_state(states, sid) in _DEAD | {StepState.SUCCEEDED} for sid in plan.ids)


def outcome(plan: ExecutionPlan, states: Mapping[str, StepState]) -> str:
    """'succeeded' only if every step succeeded; otherwise 'failed' (partial results stay readable per step)."""
    return "succeeded" if all(_state(states, sid) == StepState.SUCCEEDED for sid in plan.ids) else "failed"


def validate_for_workspace(plan: ExecutionPlan, agents: AgentRegistry, *, max_steps: int) -> None:
    """Checks that depend on the running system: size ceiling and that every agent is registered."""
    if len(plan.steps) > max_steps:
        raise _bad("plan_too_large", f"A plan may have at most {max_steps} steps")
    for s in plan.steps:
        if not agents.has(s.agent_id):
            raise _bad("unknown_agent", "A step names an agent that does not exist")
