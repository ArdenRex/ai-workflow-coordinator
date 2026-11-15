"""Kernel errors. Messages are safe to show to clients (no internals/secrets)."""


class KernelError(Exception):
    code = "kernel_error"


class ToolNotFoundError(KernelError):
    code = "tool_not_found"


class DuplicateToolError(KernelError):
    code = "duplicate_tool"


class InvalidToolDefinitionError(KernelError):
    code = "invalid_tool_definition"


class ToolInputError(KernelError):
    code = "invalid_tool_input"


class ToolOutputError(KernelError):
    code = "invalid_tool_output"


class ApprovalNotFoundError(KernelError):
    code = "approval_not_found"


class ApprovalStateError(KernelError):
    code = "approval_invalid_state"


class ApprovalPermissionError(KernelError):
    code = "approval_forbidden"


class ApprovalExpiredError(KernelError):
    code = "approval_expired"


class PolicyDeniedError(KernelError):
    code = "policy_denied"

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class ExecutionStateError(KernelError):
    code = "execution_invalid_state"


class IdempotencyConflictError(KernelError):
    code = "idempotency_conflict"
