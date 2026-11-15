class WorkflowError(Exception):
    """Messages are safe to show to clients; `code` is a fixed slug."""
    code = "workflow_error"


class InvalidWorkflowError(WorkflowError):
    code = "invalid_workflow"

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WorkflowRequestError(WorkflowError):
    """Stored-workflow errors. Messages are safe to show to clients."""
    code = "workflow_request_error"


class WorkflowNotFoundError(WorkflowRequestError):
    code = "workflow_not_found"


class WorkflowForbiddenError(WorkflowRequestError):
    code = "workflow_forbidden"


class InvalidWorkflowRequestError(WorkflowRequestError):
    code = "invalid_workflow_request"


class WorkflowConflictError(WorkflowRequestError):
    code = "workflow_conflict"


class WorkflowStateError(WorkflowRequestError):
    code = "workflow_invalid_state"


class WorkflowCancelledError(WorkflowRequestError):
    code = "workflow_cancelled"


class WorkflowLimitError(WorkflowRequestError):
    code = "workflow_limit"
