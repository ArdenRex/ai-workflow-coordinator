"""Import every model module here so Alembic autogenerate sees all tables."""
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin  # noqa: F401
from app.models.enums import (AgentRunStatus, ApprovalStatus, ExecutionStatus, MemoryStatus, PlanStatus,  # noqa: F401
                              RiskLevel, Role, StepState, WorkflowRunStatus, WorkflowStatus)
from app.models.identity import AuthEvent, Membership, User, Workspace  # noqa: F401
from app.models.kernel import Approval, SystemEvent, ToolExecution  # noqa: F401
from app.models.credentials import Credential  # noqa: F401
from app.models.agents import AgentRun  # noqa: F401
from app.models.orchestration import PlanRecord, PlanStepRecord  # noqa: F401
from app.models.memory import MemoryRecord  # noqa: F401
from app.models.workflows import (WorkflowEventRecord, WorkflowRecord, WorkflowRunRecord, WorkflowScheduleRecord,
                                 WorkflowStepRecord)  # noqa: F401
from app.models.policy import WorkspacePolicyRecord  # noqa: F401
