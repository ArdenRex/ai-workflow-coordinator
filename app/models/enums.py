"""Kernel enums. Stored as plain strings so migrations stay portable."""
import enum


class RiskLevel(str, enum.Enum):
    LOW = "low"        # read / analyze / draft
    MEDIUM = "medium"  # create / schedule / update
    HIGH = "high"      # delete / financial / permission changes


class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"                    # recorded, not yet evaluated
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"


class Role(str, enum.Enum):
    OWNER = "owner"      # full control, billing, can delete the workspace
    ADMIN = "admin"      # manage members, connections, policies, approvals
    MEMBER = "member"    # day-to-day use
    VIEWER = "viewer"    # read-only


class AgentRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"   # paused on a human approval in the kernel
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"                     # deadline passed (queue, run or approval wait)


class PlanStatus(str, enum.Enum):
    PENDING = "pending"        # stored, not started
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"        # never started because something it depends on did not succeed
    CANCELLED = "cancelled"


class MemoryStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"   # replaced by a newer version; content purged
    DELETED = "deleted"         # deleted on request; content purged
    EXPIRED = "expired"         # lifetime ran out; content purged


class WorkflowStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"       # can no longer be started; existing runs are unaffected


class WorkflowRunStatus(str, enum.Enum):
    PENDING = "pending"         # recorded, not started
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
