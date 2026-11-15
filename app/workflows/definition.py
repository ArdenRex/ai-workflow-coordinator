"""Workflow definition: an immutable, validated, versioned template. Pure data and logic: no database, no LLM, no I/O.

A workflow is a DAG of agent steps (the same shape and rules as an orchestration plan) plus, per step, a bounded
retry policy and timeout, plus the triggers that may start it (manual, a named event, or a fixed interval).

A definition grants NO authority. Each step will run as an ordinary agent run, so the starting user's permissions,
the agent's scope and tool rules, workspace policy, approvals and audit all still apply, and the kernel remains the
only place work executes. A trigger only says WHEN a run may be requested, never what it may do.

Safety properties, enforced here and fail-closed
- Reuses the plan rules: slug ids, 1..HARD_MAX_STEPS steps, bounded dependencies and instructions, no cycles.
  `to_plan()` returns the ExecutionPlan, so the graph logic exists once.
- Bounded retries: 1..HARD_MAX_ATTEMPTS attempts, delays up to MAX_DELAY_SECONDS, no jitter (deterministic).
- Bounded time: every step has a timeout; schedules have a minimum interval; at most MAX_TRIGGERS triggers.
- No secrets: names, descriptions and instructions that look like credentials are rejected without echoing them.
- Strict parsing: `from_dict` rejects unknown keys and wrong types (a bool is not an int).
- Content-free identity: `digest()` is a SHA-256 over the canonical behaviour (name and description excluded).
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple, Union

from app.agents.registry import AgentRegistry
from app.memory.model import contains_secret
from app.orchestration.errors import InvalidPlanError
from app.orchestration.plan import (HARD_MAX_STEPS, ExecutionPlan, PlanStep,
                                    validate_for_workspace as _validate_plan_for_workspace)
from app.workflows.errors import InvalidWorkflowError

WORKFLOW_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){0,3}$")
MAX_NAME_CHARS = 100
MAX_DESCRIPTION_CHARS = 300
MAX_VERSION = 1_000_000
HARD_MAX_ATTEMPTS = 5
MAX_DELAY_SECONDS = 3600
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 120
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 30 * 24 * 3600
MAX_TRIGGERS = 5
BACKOFFS = ("fixed", "exponential")
_LINE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")                       # one-line fields: no newline or tab either
_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")    # multi-line text: newline and tab allowed


def _bad(code: str, msg: str) -> InvalidWorkflowError:
    return InvalidWorkflowError(code, msg)


def _int(value: Any, code: str, msg: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise _bad(code, msg)
    return value


def _no_secret(*texts: str) -> None:
    if any(contains_secret(t) for t in texts):
        raise _bad("secret_detected", "Workflow text must not contain credentials")


# ------------------------------------------------------------------ retry
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff: str = "fixed"
    delay_seconds: int = 0
    max_delay_seconds: int = MAX_DELAY_SECONDS

    def __post_init__(self) -> None:
        _int(self.max_attempts, "invalid_retry", f"max_attempts must be 1..{HARD_MAX_ATTEMPTS}", 1, HARD_MAX_ATTEMPTS)
        if self.backoff not in BACKOFFS:
            raise _bad("invalid_retry", "backoff must be 'fixed' or 'exponential'")
        _int(self.delay_seconds, "invalid_retry", f"delay_seconds must be 0..{MAX_DELAY_SECONDS}", 0, MAX_DELAY_SECONDS)
        _int(self.max_delay_seconds, "invalid_retry", f"max_delay_seconds must be 0..{MAX_DELAY_SECONDS}",
             0, MAX_DELAY_SECONDS)
        if self.max_delay_seconds < self.delay_seconds:
            raise _bad("invalid_retry", "max_delay_seconds cannot be below delay_seconds")

    def should_retry(self, failed_attempts: int) -> bool:
        """True while another attempt is allowed after `failed_attempts` failures."""
        return 1 <= failed_attempts < self.max_attempts

    def delay_after(self, failed_attempts: int) -> int:
        """Seconds to wait before the next attempt. Deterministic and never above max_delay_seconds."""
        if failed_attempts < 1:
            return 0
        d = self.delay_seconds if self.backoff == "fixed" else self.delay_seconds * (2 ** (failed_attempts - 1))
        return min(d, self.max_delay_seconds)

    def to_dict(self) -> Dict[str, Any]:
        return {"max_attempts": self.max_attempts, "backoff": self.backoff,
                "delay_seconds": self.delay_seconds, "max_delay_seconds": self.max_delay_seconds}


# ------------------------------------------------------------------ steps
@dataclass(frozen=True)
class WorkflowStep:
    id: str
    agent_id: str
    instruction: str
    depends_on: Tuple[str, ...] = ()
    retry: RetryPolicy = RetryPolicy()
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        try:
            ps = PlanStep(self.id, self.agent_id, self.instruction, tuple(self.depends_on))
        except InvalidPlanError as e:
            raise _bad(e.code, str(e)) from None
        if not isinstance(self.retry, RetryPolicy):
            raise _bad("invalid_retry", "retry must be a RetryPolicy")
        _int(self.timeout_seconds, "invalid_timeout", f"timeout_seconds must be 1..{MAX_TIMEOUT_SECONDS}",
             1, MAX_TIMEOUT_SECONDS)
        _no_secret(ps.instruction)
        object.__setattr__(self, "instruction", ps.instruction)
        object.__setattr__(self, "depends_on", ps.depends_on)

    def plan_step(self) -> PlanStep:
        return PlanStep(self.id, self.agent_id, self.instruction, self.depends_on)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "agent_id": self.agent_id, "instruction": self.instruction,
                "depends_on": list(self.depends_on), "retry": self.retry.to_dict(),
                "timeout_seconds": self.timeout_seconds}


# ------------------------------------------------------------------ triggers
@dataclass(frozen=True)
class ManualTrigger:
    def to_dict(self) -> Dict[str, Any]:
        return {"type": "manual"}


@dataclass(frozen=True)
class EventTrigger:
    event_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or not EVENT_TYPE_RE.match(self.event_type):
            raise _bad("invalid_trigger", "event_type must be dotted lowercase slugs, e.g. lead.created")

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "event", "event_type": self.event_type}


@dataclass(frozen=True)
class ScheduleTrigger:
    interval_seconds: int

    def __post_init__(self) -> None:
        _int(self.interval_seconds, "invalid_trigger",
             f"interval_seconds must be {MIN_INTERVAL_SECONDS}..{MAX_INTERVAL_SECONDS}",
             MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "schedule", "interval_seconds": self.interval_seconds}


Trigger = Union[ManualTrigger, EventTrigger, ScheduleTrigger]


# ------------------------------------------------------------------ definition
@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    steps: Tuple[WorkflowStep, ...]
    version: int = 1
    description: str = ""
    triggers: Tuple[Trigger, ...] = (ManualTrigger(),)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not WORKFLOW_ID_RE.match(self.id):
            raise _bad("invalid_workflow_id", "Workflow ids must be lowercase slugs (max 40 characters)")
        name = self.name.strip() if isinstance(self.name, str) else ""
        if not name or len(name) > MAX_NAME_CHARS or _LINE_CONTROL.search(name):
            raise _bad("invalid_name", f"Names are one line of 1..{MAX_NAME_CHARS} characters")
        desc = self.description.strip() if isinstance(self.description, str) else None
        if desc is None or len(desc) > MAX_DESCRIPTION_CHARS or _TEXT_CONTROL.search(desc):
            raise _bad("invalid_description", f"Descriptions are plain text up to {MAX_DESCRIPTION_CHARS} characters")
        _int(self.version, "invalid_version", f"version must be 1..{MAX_VERSION}", 1, MAX_VERSION)
        _no_secret(name, desc)
        steps = tuple(self.steps)
        if not steps or not all(isinstance(s, WorkflowStep) for s in steps):
            raise _bad("invalid_workflow", "A workflow holds one or more WorkflowStep items")
        triggers = tuple(self.triggers)
        if not 1 <= len(triggers) <= MAX_TRIGGERS:
            raise _bad("invalid_trigger", f"A workflow needs 1..{MAX_TRIGGERS} triggers")
        if not all(isinstance(t, (ManualTrigger, EventTrigger, ScheduleTrigger)) for t in triggers):
            raise _bad("invalid_trigger", "Unknown trigger")
        if len(set(triggers)) != len(triggers):
            raise _bad("duplicate_trigger", "Triggers must be unique")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", desc)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "triggers", triggers)
        self.to_plan()   # graph rules: size, unique ids, dependencies exist, no cycles

    def to_plan(self) -> ExecutionPlan:
        try:
            return ExecutionPlan(tuple(s.plan_step() for s in self.steps))
        except InvalidPlanError as e:
            raise _bad(e.code, str(e)) from None

    def step(self, step_id: str) -> WorkflowStep:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "version": self.version,
                "steps": [s.to_dict() for s in self.steps], "triggers": [t.to_dict() for t in self.triggers]}

    def digest(self) -> str:
        """Identity of the behaviour only (name and description excluded); dependency order is ignored."""
        steps = []
        for s in self.steps:
            d = s.to_dict()
            d["depends_on"] = sorted(d["depends_on"])
            steps.append(d)
        triggers = sorted(json.dumps(t.to_dict(), sort_keys=True) for t in self.triggers)
        canon = {"id": self.id, "version": self.version, "steps": steps, "triggers": triggers}
        return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ------------------------------------------------------------------ parsing
def _keys(data: Any, allowed: set, required: set, what: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise _bad("invalid_workflow", f"{what} must be an object")
    keys = set(data)
    if not keys <= allowed:
        raise _bad("unknown_field", f"{what} has an unsupported field")
    if not required <= keys:
        raise _bad("missing_field", f"{what} is missing a required field")
    return data


def _retry(data: Any) -> RetryPolicy:
    d = _keys(data, {"max_attempts", "backoff", "delay_seconds", "max_delay_seconds"}, set(), "retry")
    return RetryPolicy(**dict(d))


def _step(data: Any) -> WorkflowStep:
    d = _keys(data, {"id", "agent_id", "instruction", "depends_on", "retry", "timeout_seconds"},
              {"id", "agent_id", "instruction"}, "step")
    deps = d.get("depends_on", [])
    if not isinstance(deps, (list, tuple)):
        raise _bad("invalid_workflow", "depends_on must be a list")
    kw: Dict[str, Any] = {"id": d["id"], "agent_id": d["agent_id"], "instruction": d["instruction"],
                          "depends_on": tuple(deps)}
    if "retry" in d:
        kw["retry"] = _retry(d["retry"])
    if "timeout_seconds" in d:
        kw["timeout_seconds"] = d["timeout_seconds"]
    return WorkflowStep(**kw)


def _trigger(data: Any) -> Trigger:
    if not isinstance(data, Mapping) or data.get("type") not in ("manual", "event", "schedule"):
        raise _bad("invalid_trigger", "Unknown trigger type")
    kind = data["type"]
    if kind == "manual":
        _keys(data, {"type"}, {"type"}, "trigger")
        return ManualTrigger()
    if kind == "event":
        _keys(data, {"type", "event_type"}, {"type", "event_type"}, "trigger")
        return EventTrigger(data["event_type"])
    _keys(data, {"type", "interval_seconds"}, {"type", "interval_seconds"}, "trigger")
    return ScheduleTrigger(data["interval_seconds"])


def from_dict(data: Any) -> WorkflowDefinition:
    """Strict parser for untrusted input (HTTP bodies, stored JSON). Unknown keys and wrong types are rejected."""
    d = _keys(data, {"id", "name", "description", "version", "steps", "triggers"}, {"id", "name", "steps"}, "workflow")
    steps, triggers = d["steps"], d.get("triggers", [{"type": "manual"}])
    if not isinstance(steps, (list, tuple)) or not isinstance(triggers, (list, tuple)):
        raise _bad("invalid_workflow", "steps and triggers must be lists")
    if len(steps) > HARD_MAX_STEPS or len(triggers) > MAX_TRIGGERS:   # bound the work before parsing anything
        raise _bad("invalid_workflow", "Too many steps or triggers")
    kw: Dict[str, Any] = {"id": d["id"], "name": d["name"], "steps": tuple(_step(s) for s in steps),
                          "triggers": tuple(_trigger(t) for t in triggers)}
    if "description" in d:
        kw["description"] = d["description"]
    if "version" in d:
        kw["version"] = d["version"]
    return WorkflowDefinition(**kw)


def validate_for_workspace(defn: WorkflowDefinition, agents: AgentRegistry, *, max_steps: int) -> None:
    """Checks that depend on the running system: the size ceiling and that every named agent is registered."""
    try:
        _validate_plan_for_workspace(defn.to_plan(), agents, max_steps=max_steps)
    except InvalidPlanError as e:
        raise _bad(e.code, str(e)) from None
