"""Workflow, run, event, schedule and tick endpoints. Thin: authority, digests, ordering, dedupe and audit all live in
the workflow services; nothing here can execute a tool or approve anything.

Definitions  POST /workflows · GET /workflows · GET /workflows/{key} · GET /workflows/{key}/versions
             POST /workflows/{key}/versions/{version}/archive
Runs         POST /workflows/{key}/runs (manual start, PENDING) · GET /workflow-runs[/{id}]
             POST /workflow-runs/{id}/drive · POST /workflow-runs/{id}/cancel
Events       POST /workflow-events · GET /workflow-events[/{id}]
Schedules    GET /workflow-schedules · POST /workflow-schedules (arm) · POST /workflow-schedules/disarm
Tick         POST /workflow-tick (admin; limited to THIS workspace; fires due schedules and drives schedule/event runs)

Humans only: the caller is the signed-in user acting as themselves, so an agent can never define, start, emit, arm or
tick. Every step still runs as an ordinary agent run under the run owner's permissions, the agent's scope, policy,
approvals and audit. Only a run's creator can drive it (an admin may see and cancel it, never drive it). Responses carry
ids, states, counters and fixed codes; run and step records never hold instructions. Definitions do hold their template
text, so reading one needs `agent:run` and the text is only ever returned from the single-definition read. Errors are
fixed text plus a code; rejected input is never echoed. Anything the caller may not see is a plain 404.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents import errors as ae
from app.agents.executor import AgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.runs import AgentRunService
from app.api.agent_runs import _http as run_http
from app.api.agent_runs import get_agent_registry
from app.api.ai import _http as llm_http
from app.api.ai import get_tool_registry
from app.config import Settings, get_settings
from app.database import get_db
from app.kernel.policy_store import session_policy_provider
from app.identity.context import WorkspaceContext, require_permission
from app.llm import errors as llm_errors
from app.llm.credentials import workspace_llm
from app.memory.context import memory_provider
from app.models.enums import StepState, WorkflowRunStatus, WorkflowStatus
from app.models.workflows import (WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord, WorkflowScheduleRecord,
                                  WorkflowStepRecord)
from app.workflows import errors as we
from app.workflows.definition import from_dict
from app.workflows.engine import WorkflowEngine
from app.workflows.events import EventService
from app.workflows.scheduler import ScheduleService, Scheduler
from app.workflows.store import WorkflowService

MAX_DB_INT = 2_147_483_647          # 14.6: a larger integer overflows the database driver (a 500); refuse it as a 422 instead

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workflows"])


# ------------------------------------------------------------------ errors
def _http(exc: we.WorkflowError) -> HTTPException:
    """Fixed client-facing text plus the fixed code; never the rejected input."""
    if isinstance(exc, we.WorkflowNotFoundError):
        return HTTPException(404, "Not found")
    if isinstance(exc, we.WorkflowForbiddenError):
        return HTTPException(403, "Insufficient permissions")
    if isinstance(exc, we.InvalidWorkflowError):
        return HTTPException(422, f"The workflow is not valid ({exc.code})")
    if isinstance(exc, we.InvalidWorkflowRequestError):
        return HTTPException(422, "The workflow request is not valid")
    if isinstance(exc, we.WorkflowLimitError):
        return HTTPException(409, "A workflow limit has been reached")
    if isinstance(exc, (we.WorkflowConflictError, we.WorkflowStateError, we.WorkflowCancelledError)):
        return HTTPException(409, "The workflow is not in a state that allows this")
    return HTTPException(400, "The workflow request could not be processed")


def _wf(db: Session, settings: Settings, agents: AgentRegistry) -> WorkflowService:
    return WorkflowService(db, agents, settings)


def _engine(db: Session, settings: Settings, agents: AgentRegistry, tools, llm, wf: WorkflowService) -> WorkflowEngine:
    runs = AgentRunService(db, agents, settings)
    return WorkflowEngine(wf, runs, AgentExecutor(db, runs, agents, tools, llm,
                                                  context_provider=memory_provider(db, settings),
                                                  base_policy_provider=session_policy_provider(db)))


# ------------------------------------------------------------------ views
class WorkflowView(BaseModel):
    key: str
    version: int
    name: str
    status: WorkflowStatus
    steps: int
    triggers: List[Dict[str, Any]]
    created_at: datetime
    archived_at: Optional[datetime]
    definition: Optional[Dict[str, Any]] = None       # the template text: only on the single-definition read

    @classmethod
    def of(cls, r: WorkflowRecord, *, full: bool = False) -> "WorkflowView":
        d = r.definition or {}
        return cls(key=r.workflow_key, version=r.version, name=r.name, status=r.status, steps=len(d.get("steps", [])),
                   triggers=list(d.get("triggers", [])), created_at=r.created_at, archived_at=r.archived_at,
                   definition=d if full else None)


class StepView(BaseModel):
    key: str
    agent_id: str
    status: StepState
    depends_on: List[str]
    attempts: int
    max_attempts: int
    next_attempt_at: Optional[datetime]
    agent_run_id: Optional[str]
    result: Optional[Dict[str, Any]]
    error_code: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    @classmethod
    def of(cls, s: WorkflowStepRecord) -> "StepView":
        return cls(key=s.step_key, agent_id=s.agent_id, status=s.status, depends_on=list(s.depends_on or []),
                   attempts=s.attempts, max_attempts=s.max_attempts, next_attempt_at=s.next_attempt_at,
                   agent_run_id=s.agent_run_id, result=s.result, error_code=s.error_code, started_at=s.started_at,
                   finished_at=s.finished_at)


class RunView(BaseModel):
    """Content-free: ids, states, counters and fixed codes. No instructions, digests or tool output."""
    id: str
    workflow_key: str
    version: int
    status: WorkflowRunStatus
    requested_by: str
    trigger_type: str
    step_count: int
    cancel_requested: bool
    error_code: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    steps: List[StepView] = []

    @classmethod
    def of(cls, r: WorkflowRunRecord, steps: Optional[List[WorkflowStepRecord]] = None) -> "RunView":
        v = cls(id=r.id, workflow_key=r.workflow_key, version=r.version, status=r.status, requested_by=r.requested_by,
                trigger_type=r.trigger_type, step_count=r.step_count, cancel_requested=r.cancel_requested,
                error_code=r.error_code, started_at=r.started_at, finished_at=r.finished_at, created_at=r.created_at)
        if steps is not None:
            v.steps = [StepView.of(s) for s in steps]
        return v


class DriveView(BaseModel):
    drive_state: str                      # completed | cancelled | paused_approval | in_flight | waiting_retry
    retry_at: Optional[datetime] = None
    run: RunView


class EventView(BaseModel):
    id: str
    event_type: str
    event_ref: str
    emitted_by: str
    matched: int
    started: int
    skipped: int
    truncated: bool
    dispatched_at: Optional[datetime]
    created_at: datetime
    run_ids: List[str] = []

    @classmethod
    def of(cls, e: WorkflowEventRecord, run_ids=()) -> "EventView":
        return cls(id=e.id, event_type=e.event_type, event_ref=e.event_ref, emitted_by=e.emitted_by,
                   matched=e.matched_count, started=e.started_count, skipped=e.skipped_count, truncated=e.truncated,
                   dispatched_at=e.dispatched_at, created_at=e.created_at, run_ids=list(run_ids))


class EmitResponse(BaseModel):
    duplicate: bool
    event: EventView


class ScheduleView(BaseModel):
    id: str
    workflow_key: str
    interval_seconds: int
    enabled: bool
    armed_by: str
    next_fire_at: datetime
    last_fired_at: Optional[datetime]
    fired_count: int
    skipped_count: int
    disabled_reason: Optional[str]

    @classmethod
    def of(cls, s: WorkflowScheduleRecord) -> "ScheduleView":
        return cls(id=s.id, workflow_key=s.workflow_key, interval_seconds=s.interval_seconds, enabled=s.enabled,
                   armed_by=s.armed_by, next_fire_at=s.next_fire_at, last_fired_at=s.last_fired_at,
                   fired_count=s.fired_count, skipped_count=s.skipped_count, disabled_reason=s.disabled_reason)


class TickView(BaseModel):
    fired: int
    skipped: int
    disabled: int
    driven: int
    states: Dict[str, int]
    errors: Dict[str, int]


# ------------------------------------------------------------------ requests
class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Optional[int] = Field(default=None, ge=1, le=MAX_DB_INT)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)


class EmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=140)
    event_ref: str = Field(min_length=1, max_length=128)


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_key: str = Field(min_length=1, max_length=40)
    interval_seconds: int = Field(ge=1, le=10_000_000)      # the exact 60 s .. 30 day range is enforced by the model


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drive: bool = True                                      # False: only fire due schedules (needs no model)


# ------------------------------------------------------------------ definitions
@router.post("/workflows", response_model=WorkflowView)
def define_workflow(body: Dict[str, Any], ctx: WorkspaceContext = Depends(require_permission("agent:manage")),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                    agents: AgentRegistry = Depends(get_agent_registry)):
    """Store one immutable version (a new key starts at 1, a change is the next version). Admins only."""
    try:
        rec = _wf(db, settings, agents).define(ctx.principal(), from_dict(body))
    except we.WorkflowError as exc:
        raise _http(exc)
    return WorkflowView.of(rec, full=True)


@router.get("/workflows", response_model=List[WorkflowView])
def list_workflows(ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                   agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return [WorkflowView.of(r) for r in _wf(db, settings, agents).list_definitions(ctx.principal())]
    except we.WorkflowError as exc:
        raise _http(exc)


@router.get("/workflows/{key}", response_model=WorkflowView)
def get_workflow(key: str, version: Optional[int] = Query(None, ge=1, le=MAX_DB_INT),
                 ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                 agents: AgentRegistry = Depends(get_agent_registry)):
    svc = _wf(db, settings, agents)
    try:
        rec = svc.get_definition(ctx.principal(), key, version)
        svc.definition_of(rec)                                  # integrity check: a tampered row fails closed
    except we.WorkflowError as exc:
        raise _http(exc)
    return WorkflowView.of(rec, full=True)


@router.get("/workflows/{key}/versions", response_model=List[WorkflowView])
def workflow_versions(key: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                      agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return [WorkflowView.of(r) for r in _wf(db, settings, agents).versions(ctx.principal(), key)]
    except we.WorkflowError as exc:
        raise _http(exc)


@router.post("/workflows/{key}/versions/{version}/archive", response_model=WorkflowView)
def archive_workflow(key: str, version: int = Path(ge=1, le=MAX_DB_INT), ctx: WorkspaceContext = Depends(require_permission("agent:manage")),
                     db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                     agents: AgentRegistry = Depends(get_agent_registry)):
    """Stops new runs from that version; existing runs are untouched."""
    try:
        return WorkflowView.of(_wf(db, settings, agents).archive(ctx.principal(), key, version))
    except we.WorkflowError as exc:
        raise _http(exc)


# ------------------------------------------------------------------ runs
@router.post("/workflows/{key}/runs", response_model=RunView, status_code=201)
def start_run(key: str, body: StartRunRequest, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry)):
    """A manual start only creates a PENDING run owned by the caller; POST .../drive executes it."""
    svc = _wf(db, settings, agents)
    try:
        run = svc.create_run(ctx.principal(), key, version=body.version, idempotency_key=body.idempotency_key)
        return RunView.of(run, svc.steps(ctx.principal(), run.id))
    except we.WorkflowError as exc:
        raise _http(exc)


@router.get("/workflow-runs", response_model=List[RunView])
def list_runs(status: Optional[WorkflowRunStatus] = None, workflow_key: Optional[str] = Query(None, max_length=40),
              limit: int = Query(50, ge=1, le=200),
              ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry)):
    rows = _wf(db, settings, agents).list_runs(ctx.principal(), status=status, workflow_key=workflow_key, limit=limit)
    return [RunView.of(r) for r in rows]


@router.get("/workflow-runs/{run_id}", response_model=RunView)
def get_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
            db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
            agents: AgentRegistry = Depends(get_agent_registry)):
    svc = _wf(db, settings, agents)
    try:
        return RunView.of(svc.get_run(ctx.principal(), run_id), svc.steps(ctx.principal(), run_id))
    except we.WorkflowError as exc:
        raise _http(exc)


@router.post("/workflow-runs/{run_id}/drive", response_model=DriveView)
def drive_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    """Run or continue a run. Creator only. Call again after approvals are decided or a retry delay has passed."""
    user, svc = ctx.principal(), _wf(db, settings, agents)
    try:
        svc.get_run(user, run_id)                               # 404 for anything the caller cannot see, before the model
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            out = _engine(db, settings, agents, tools, llm, svc).drive(user, run_id)
        return DriveView(drive_state=out.state, retry_at=out.retry_at,
                         run=RunView.of(out.run, svc.steps(user, run_id)))
    except llm_errors.LLMError as exc:
        raise llm_http(exc)
    except we.WorkflowError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)


@router.post("/workflow-runs/{run_id}/cancel", response_model=RunView)
def cancel_run(run_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    """Creator or admin. Needs no model call, so it does not resolve an LLM."""
    user, svc = ctx.principal(), _wf(db, settings, agents)
    try:
        rec = _engine(db, settings, agents, tools, None, svc).cancel(user, run_id)
        return RunView.of(rec, svc.steps(user, run_id))
    except we.WorkflowError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)


# ------------------------------------------------------------------ events
def _events(db: Session, settings: Settings, agents: AgentRegistry) -> EventService:
    return EventService(db, _wf(db, settings, agents), settings)


@router.post("/workflow-events", response_model=EmitResponse)
def emit_event(body: EmitRequest, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
               agents: AgentRegistry = Depends(get_agent_registry)):
    """Content-free intake: a type and a reference, no payload. Idempotent on (type, ref). It creates PENDING runs
    owned by the caller for matching workflows; it executes nothing."""
    try:
        res = _events(db, settings, agents).emit(ctx.principal(), body.event_type, body.event_ref)
    except we.WorkflowError as exc:
        raise _http(exc)
    return EmitResponse(duplicate=res.duplicate, event=EventView.of(res.event, res.run_ids))


@router.get("/workflow-events", response_model=List[EventView])
def list_events(limit: int = Query(50, ge=1, le=200),
                ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                agents: AgentRegistry = Depends(get_agent_registry)):
    return [EventView.of(e) for e in _events(db, settings, agents).list_events(ctx.principal(), limit=limit)]


@router.get("/workflow-events/{event_id}", response_model=EventView)
def get_event(event_id: str, ctx: WorkspaceContext = Depends(require_permission("agent:run")),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              agents: AgentRegistry = Depends(get_agent_registry)):
    svc = _events(db, settings, agents)
    try:
        return EventView.of(svc.get_event(ctx.principal(), event_id), svc.run_ids(ctx.principal(), event_id))
    except we.WorkflowError as exc:
        raise _http(exc)


# ------------------------------------------------------------------ schedules
def _schedules(db: Session, settings: Settings, agents: AgentRegistry) -> ScheduleService:
    return ScheduleService(db, _wf(db, settings, agents), settings)


@router.get("/workflow-schedules", response_model=List[ScheduleView])
def list_schedules(ctx: WorkspaceContext = Depends(require_permission("agent:run")),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                   agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return [ScheduleView.of(s) for s in _schedules(db, settings, agents).list_schedules(ctx.principal())]
    except we.WorkflowError as exc:
        raise _http(exc)


@router.post("/workflow-schedules", response_model=ScheduleView)
def arm_schedule(body: ScheduleRequest, ctx: WorkspaceContext = Depends(require_permission("agent:manage")),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                 agents: AgentRegistry = Depends(get_agent_registry)):
    """Arm an interval the workflow's newest active version declares. Runs belong to the caller, whose role is
    re-checked at every fire. Admins only."""
    try:
        return ScheduleView.of(_schedules(db, settings, agents).arm(ctx.principal(), body.workflow_key,
                                                                    body.interval_seconds))
    except we.WorkflowError as exc:
        raise _http(exc)


@router.post("/workflow-schedules/disarm", response_model=ScheduleView)
def disarm_schedule(body: ScheduleRequest, ctx: WorkspaceContext = Depends(require_permission("agent:manage")),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                    agents: AgentRegistry = Depends(get_agent_registry)):
    try:
        return ScheduleView.of(_schedules(db, settings, agents).disarm(ctx.principal(), body.workflow_key,
                                                                       body.interval_seconds))
    except we.WorkflowError as exc:
        raise _http(exc)


# ------------------------------------------------------------------ tick
@router.post("/workflow-tick", response_model=TickView)
def tick(body: TickRequest, ctx: WorkspaceContext = Depends(require_permission("agent:manage")),
         db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
         agents: AgentRegistry = Depends(get_agent_registry), tools=Depends(get_tool_registry)):
    """One bounded scheduler pass for THIS workspace only (never another tenant's schedules or runs). Admins only.
    Runs are driven as their owners with the ordinary engine; manual runs are never driven here."""
    svc = _wf(db, settings, agents)

    def run(llm) -> TickView:
        t = Scheduler(db, svc, _engine(db, settings, agents, tools, llm, svc), settings).tick(
            drive=body.drive, workspace_id=ctx.workspace.id)
        return TickView(fired=t.fired, skipped=t.skipped, disabled=t.disabled, driven=t.driven, states=dict(t.states),
                        errors=dict(t.errors))
    try:
        if not body.drive:
            return run(None)
        with workspace_llm(db, settings, ctx.workspace.id) as llm:
            return run(llm)
    except llm_errors.LLMError as exc:
        raise llm_http(exc)
    except we.WorkflowError as exc:
        raise _http(exc)
    except ae.AgentError as exc:
        raise run_http(exc)
