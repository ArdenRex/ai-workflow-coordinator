"""Workspace policy store (Step 12.1): autonomy level + tightening knobs, one versioned row per workspace.

Rules:
- A policy can only TIGHTEN (disable a tool, force approval). The kernel's own order in policy.evaluate() is unchanged, so a stored policy
  can never waive a tool's approval requirement or the HIGH-risk rule.
- No row = the baseline: level 3 ("AI prepares actions"), nothing disabled, reads run unattended, everything else needs approval. That is
  exactly `WorkspacePolicy()`, i.e. today's behaviour.
- Levels 1-4 can be set (4 needs an execution cap and is the only level that can loosen anything, see 12.4). Level 5 (12.5) is level 4 plus mandatory guardrails; it adds no extra authority
  (we do not claim autonomy that is not enforced).
- Updates are compare-and-swap on `version` (409 on a stale write). Every change writes a content-free audit event.
- The provider reads the store on every call and FAILS CLOSED: a store error propagates, it never returns a looser default.
- Error messages are fixed text and never echo the rejected input.
"""
import enum
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.kernel.audit import record_event
from app.kernel.permissions import Principal
from app.kernel.policy import (ALLOWED_WINDOWS, MAX_ESCALATION_THRESHOLD, MAX_EXECUTIONS_CEILING, ROUTING_RISKS, ROUTING_TARGET,
                               EscalationRule, ExecutionLimit,
                               WorkspacePolicy)
from app.kernel.registry import ToolRegistry
from app.models.enums import RiskLevel
from app.models.policy import WorkspacePolicyRecord

MAX_TOOLS = 100
_KEYS = {"expected_version", "autonomy_level", "disabled_tools", "approval_required_tools", "risk_overrides", "execution_limit", "escalation", "approval_routing", "auto_execute_tools"}
_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class AutonomyLevel(enum.IntEnum):
    OBSERVE = 1      # AI observes
    RECOMMEND = 2    # AI recommends
    PREPARE = 3      # AI prepares actions (humans approve them): today's behaviour
    EXECUTE_LOW = 4  # AI runs an explicit allowlist of tools unattended, under a cap (12.4)
    AUTONOMOUS = 5   # level 4 plus mandatory guardrails: cap, escalation rule, owner-routed high-risk approvals (12.5)


DEFAULT_LEVEL = AutonomyLevel.PREPARE
SETTABLE_LEVELS = frozenset({AutonomyLevel.OBSERVE, AutonomyLevel.RECOMMEND, AutonomyLevel.PREPARE, AutonomyLevel.EXECUTE_LOW,
                             AutonomyLevel.AUTONOMOUS})


class PolicyError(Exception):
    code, message, http = "policy_error", "Policy error", 400


class InvalidPolicyError(PolicyError):
    code, message, http = "invalid_policy", "The policy is not valid", 422


class LevelUnavailableError(PolicyError):
    code, message, http = "autonomy_level_unavailable", "This autonomy level is not available yet", 422


class VersionConflictError(PolicyError):
    code, message, http = "version_conflict", "The policy changed; read it again and retry", 409


def _limit_from_stored(value: Any) -> Optional[ExecutionLimit]:
    """A stored limit that is not well-formed is a store error: fail closed (raise), never 'no limit'."""
    if value is None:
        return None
    return ExecutionLimit(max_executions=int(value["max_executions"]), window_seconds=int(value["window_seconds"]))


def _escalation_from_stored(value: Any) -> Optional[EscalationRule]:
    """Same rule as the limit: a malformed stored escalation raises (fail closed), never 'off'."""
    if value is None:
        return None
    return EscalationRule(threshold=int(value["threshold"]), window_seconds=int(value["window_seconds"]))


def _routing_from_stored(value: Any) -> Dict[str, str]:
    """Fail closed: a stored routing that is not exactly a map of known risk -> 'owner' raises, it never becomes 'no routing'."""
    out = {str(k): str(v) for k, v in (value or {}).items()}
    if any(k not in ROUTING_RISKS or v != ROUTING_TARGET for k, v in out.items()):
        raise ValueError("invalid stored approval routing")
    return out


LOOSE_LEVELS = (int(AutonomyLevel.EXECUTE_LOW), int(AutonomyLevel.AUTONOMOUS))


def _level5_rails(limit: Any, escalation: Any, routing: Any) -> bool:
    """Level 5 is only valid with ALL guardrails: an execution cap, an escalation rule, and high-risk approvals routed to the owner."""
    return limit is not None and escalation is not None and (routing or {}).get("high") == ROUTING_TARGET


def _auto_from_stored(rec: WorkspacePolicyRecord) -> frozenset:
    """Level-4 allowlist. Only honoured AT level 4 with a cap; anything else stored there is a store error (fail closed), never a quiet loosening."""
    tools = [str(t) for t in (rec.auto_execute_tools or [])]
    if rec.autonomy_level == int(AutonomyLevel.AUTONOMOUS) and not _level5_rails(rec.execution_limit, rec.escalation, rec.approval_routing):
        raise ValueError("invalid stored level-5 policy")
    if not tools:
        return frozenset()
    if rec.autonomy_level not in LOOSE_LEVELS or rec.execution_limit is None:
        raise ValueError("invalid stored auto-execute tools")
    return frozenset(tools)


def to_workspace_policy(rec: Optional[WorkspacePolicyRecord]) -> WorkspacePolicy:
    """The kernel's policy for a stored row. Levels 1-3 all keep the baseline automatic-execution limit (reads only)."""
    if rec is None:
        return WorkspacePolicy()
    return WorkspacePolicy(disabled_tools=frozenset(str(t) for t in rec.disabled_tools or []),
                           approval_required_tools=frozenset(str(t) for t in rec.approval_required_tools or []),
                           auto_execute_max_risk=RiskLevel.LOW,
                           risk_overrides={str(k): RiskLevel(v) for k, v in (rec.risk_overrides or {}).items()},
                           execution_limit=_limit_from_stored(rec.execution_limit),
                           escalation=_escalation_from_stored(rec.escalation),
                           approval_routing=_routing_from_stored(rec.approval_routing),
                           auto_execute_tools=_auto_from_stored(rec))


def db_policy_provider(session_factory: Callable[[], Session]) -> Callable[[str], WorkspacePolicy]:
    """Provider for ToolExecutionService / agent contexts. One short read per call; errors propagate (fail closed)."""
    def provider(workspace_id: str) -> WorkspacePolicy:
        db = session_factory()
        try:
            return to_workspace_policy(db.scalar(select(WorkspacePolicyRecord).where(WorkspacePolicyRecord.workspace_id == workspace_id)))
        finally:
            db.close()
    return provider


def session_policy_provider(db: Session) -> Callable[[str], WorkspacePolicy]:
    """Provider for code that already holds a session (an HTTP request). Reads on that session and never closes it. Fails closed."""
    def provider(workspace_id: str) -> WorkspacePolicy:
        return to_workspace_policy(db.scalar(select(WorkspacePolicyRecord).where(WorkspacePolicyRecord.workspace_id == workspace_id)))
    return provider


class PolicyService:
    def __init__(self, db: Session, tools: ToolRegistry) -> None:
        self.db, self.tools = db, tools

    def get(self, workspace_id: str) -> Optional[WorkspacePolicyRecord]:
        return self.db.scalar(select(WorkspacePolicyRecord).where(WorkspacePolicyRecord.workspace_id == workspace_id))

    # ------------------------------------------------------------------ validation (fixed errors, never echo input)
    def _tool_list(self, value: Any) -> List[str]:
        if not isinstance(value, list) or len(value) > MAX_TOOLS:
            raise InvalidPolicyError()
        out = set()
        for item in value:
            if not isinstance(item, str) or not self.tools.has(item):
                raise InvalidPolicyError()
            out.add(item)
        return sorted(out)

    def _risk_map(self, value: Any) -> Dict[str, str]:
        """tool id -> 'medium'|'high', each strictly ABOVE the tool's own risk (an override can only tighten; a no-op is refused)."""
        if not isinstance(value, dict) or len(value) > MAX_TOOLS:
            raise InvalidPolicyError()
        out: Dict[str, str] = {}
        for tool_id, level in value.items():
            if not isinstance(tool_id, str) or not isinstance(level, str) or not self.tools.has(tool_id):
                raise InvalidPolicyError()
            try:
                risk = RiskLevel(level)
            except ValueError:
                raise InvalidPolicyError()
            if _RANK[risk] <= _RANK[self.tools.get(tool_id).risk_level]:
                raise InvalidPolicyError()
            out[tool_id] = risk.value
        return dict(sorted(out.items()))

    @staticmethod
    def _limit(value: Any) -> Optional[Dict[str, int]]:
        """None/absent = no cap. Otherwise exactly {max_executions: 1..100000, window_seconds: 60|3600|86400}, plain ints only."""
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"max_executions", "window_seconds"}:
            raise InvalidPolicyError()
        m, w = value["max_executions"], value["window_seconds"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (m, w)) or not 1 <= m <= MAX_EXECUTIONS_CEILING or w not in ALLOWED_WINDOWS:
            raise InvalidPolicyError()
        return {"max_executions": m, "window_seconds": w}

    @staticmethod
    def _escalation(value: Any) -> Optional[Dict[str, int]]:
        """None/absent = off. Otherwise exactly {threshold: 1..1000, window_seconds: 60|3600|86400}, plain ints only."""
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"threshold", "window_seconds"}:
            raise InvalidPolicyError()
        t, w = value["threshold"], value["window_seconds"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (t, w)) or not 1 <= t <= MAX_ESCALATION_THRESHOLD or w not in ALLOWED_WINDOWS:
            raise InvalidPolicyError()
        return {"threshold": t, "window_seconds": w}

    @staticmethod
    def _routing(value: Any) -> Dict[str, str]:
        """{} = no routing. Otherwise a map of 'medium' and/or 'high' to 'owner' (decisions then need the owner-only permission)."""
        if not isinstance(value, dict):
            raise InvalidPolicyError()
        for k, v in value.items():
            if k not in ROUTING_RISKS or v != ROUTING_TARGET:
                raise InvalidPolicyError()
        return dict(sorted(value.items()))

    def _auto_tools(self, value: Any, level: int, limit: Any, escalation: Any, routing: Any, disabled: List[str], approval: List[str], risks: Dict[str, str]) -> List[str]:
        """Level-4 allowlist: known tools, own risk at most MEDIUM, no own approval requirement, not disabled/approval-ruled, not overridden to HIGH.
        Only at levels 4-5; both need an execution cap; level 5 also needs the escalation rule and owner-routed high-risk approvals."""
        tools = self._tool_list(value)
        if level in LOOSE_LEVELS and limit is None:
            raise InvalidPolicyError()
        if level == int(AutonomyLevel.AUTONOMOUS) and not _level5_rails(limit, escalation, routing):
            raise InvalidPolicyError()
        if tools and level not in LOOSE_LEVELS:
            raise InvalidPolicyError()
        for t in tools:
            d = self.tools.get(t)
            if (_RANK[d.risk_level] > _RANK[RiskLevel.MEDIUM] or d.approval_required or t in disabled or t in approval
                    or risks.get(t) == RiskLevel.HIGH.value):
                raise InvalidPolicyError()
        return tools

    def _parse(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(body, dict) or set(body) - _KEYS or "expected_version" not in body or "autonomy_level" not in body:
            raise InvalidPolicyError()
        ev, level = body["expected_version"], body["autonomy_level"]
        if isinstance(ev, bool) or not isinstance(ev, int) or ev < 0:
            raise InvalidPolicyError()
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 5:
            raise InvalidPolicyError()
        if AutonomyLevel(level) not in SETTABLE_LEVELS:
            raise LevelUnavailableError()
        disabled, approval = self._tool_list(body.get("disabled_tools", [])), self._tool_list(body.get("approval_required_tools", []))
        risks, limit = self._risk_map(body.get("risk_overrides", {})), self._limit(body.get("execution_limit"))
        escalation, routing = self._escalation(body.get("escalation")), self._routing(body.get("approval_routing", {}))
        return {"expected_version": ev, "autonomy_level": level, "disabled_tools": disabled, "approval_required_tools": approval,
                "risk_overrides": risks, "execution_limit": limit,
                "escalation": escalation, "approval_routing": routing,
                "auto_execute_tools": self._auto_tools(body.get("auto_execute_tools", []), level, limit, escalation, routing, disabled, approval, risks)}

    # ------------------------------------------------------------------ write
    def set(self, principal: Principal, body: Dict[str, Any]) -> WorkspacePolicyRecord:
        if principal.agent is not None:
            raise InvalidPolicyError()                         # humans only: an agent can never change policy
        v = self._parse(body)
        ws = principal.workspace_id
        current = self.get(ws)
        if (current.version if current else 0) != v["expected_version"]:
            raise VersionConflictError()
        values = {"autonomy_level": v["autonomy_level"], "disabled_tools": v["disabled_tools"],
                  "approval_required_tools": v["approval_required_tools"], "risk_overrides": v["risk_overrides"],
                  "execution_limit": v["execution_limit"], "escalation": v["escalation"], "approval_routing": v["approval_routing"],
                  "auto_execute_tools": v["auto_execute_tools"], "updated_by": principal.user_id}
        previous = current.autonomy_level if current else int(DEFAULT_LEVEL)
        if current is None:
            rec = WorkspacePolicyRecord(workspace_id=ws, version=1, **values)
            self.db.add(rec)
            new_version = 1
        else:
            new_version = current.version + 1
            res = self.db.execute(update(WorkspacePolicyRecord).where(WorkspacePolicyRecord.id == current.id,
                                                                      WorkspacePolicyRecord.version == current.version)
                                  .values(version=new_version, **values))
            if res.rowcount != 1:
                self.db.rollback()
                raise VersionConflictError()
            rec = current
        record_event(self.db, workspace_id=ws, event_type="policy.updated" if current else "policy.created", actor=principal.user_id,
                     payload={"version": new_version, "autonomy_level": v["autonomy_level"], "previous_level": previous,
                              "disabled_count": len(v["disabled_tools"]), "approval_required_count": len(v["approval_required_tools"]),
                              "risk_override_count": len(v["risk_overrides"]),
                              "has_execution_limit": v["execution_limit"] is not None,
                              "has_escalation": v["escalation"] is not None,
                              "approval_routing_count": len(v["approval_routing"]),
                              "auto_execute_count": len(v["auto_execute_tools"])})
        try:
            self.db.commit()
        except IntegrityError:                                 # two first writes raced: the unique constraint picked one
            self.db.rollback()
            raise VersionConflictError()
        self.db.expire_all()
        return self.get(ws)
