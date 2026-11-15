"""Tool registry. Agents can only use tools registered here; nothing else exists.

Each tool declares: id, description, input/output schemas, required permission,
risk level, approval requirement and execution limits.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from app.kernel.errors import (DuplicateToolError, InvalidToolDefinitionError,
                               ToolInputError, ToolNotFoundError, ToolOutputError)
from app.models.enums import RiskLevel

TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")   # e.g. crm.lead.create
PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_*]*)+$")     # e.g. customer:read
MAX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    required_permission: str
    risk_level: RiskLevel
    requires_approval: Optional[bool] = None   # None => derived from risk level
    timeout_seconds: int = 30
    max_retries: int = 0
    handler: Optional[Callable[..., Any]] = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not TOOL_ID_RE.match(self.id):
            raise InvalidToolDefinitionError(f"Invalid tool id: {self.id!r}")
        if not self.description.strip():
            raise InvalidToolDefinitionError("Tool description is required")
        if not PERMISSION_RE.match(self.required_permission):
            raise InvalidToolDefinitionError(f"Invalid permission: {self.required_permission!r}")
        if not (1 <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise InvalidToolDefinitionError("timeout_seconds out of range")
        if not (0 <= self.max_retries <= 5):
            raise InvalidToolDefinitionError("max_retries out of range")
        # High-risk tools can never opt out of approval.
        if self.risk_level == RiskLevel.HIGH and self.requires_approval is False:
            raise InvalidToolDefinitionError("High-risk tools must require approval")
        # Writes must not be retried blindly: retries only for low-risk (read) tools.
        if self.max_retries and self.risk_level != RiskLevel.LOW:
            raise InvalidToolDefinitionError("Only low-risk tools may declare retries")

    @property
    def approval_required(self) -> bool:
        """Default policy: HIGH always; LOW never; MEDIUM only if declared."""
        if self.requires_approval is not None:
            return self.requires_approval
        return self.risk_level == RiskLevel.HIGH

    def describe(self) -> dict:
        """Safe, serializable description (what an LLM/planner is allowed to see)."""
        return {
            "id": self.id,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "requires_approval": self.approval_required,
            "required_permission": self.required_permission,
            "input_schema": self.input_schema.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        if tool.id in self._tools:
            raise DuplicateToolError(f"Tool already registered: {tool.id}")
        self._tools[tool.id] = tool
        return tool

    def get(self, tool_id: str) -> ToolDefinition:
        try:
            return self._tools[tool_id]
        except KeyError:
            raise ToolNotFoundError(f"Unknown tool: {tool_id}") from None

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def list(self) -> List[ToolDefinition]:
        return sorted(self._tools.values(), key=lambda t: t.id)

    def validate_input(self, tool_id: str, data: Dict[str, Any]) -> BaseModel:
        tool = self.get(tool_id)
        try:
            return tool.input_schema.model_validate(data)
        except ValidationError as exc:
            raise ToolInputError(_summarize(exc)) from None

    def validate_output(self, tool_id: str, data: Any) -> BaseModel:
        tool = self.get(tool_id)
        try:
            return tool.output_schema.model_validate(data)
        except ValidationError as exc:
            raise ToolOutputError(_summarize(exc)) from None


def _summarize(exc: ValidationError) -> str:
    # Field paths and messages only; never echo submitted values (may be sensitive).
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors())
