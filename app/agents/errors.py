class AgentError(Exception):
    pass


class InvalidAgentDefinitionError(AgentError):
    pass


class DuplicateAgentError(AgentError):
    pass


class AgentNotFoundError(AgentError):
    pass


class UnknownToolPatternError(InvalidAgentDefinitionError):
    pass


class RunError(AgentError):
    """Agent-run errors. Messages are safe to show to clients."""
    code = "run_error"


class RunNotFoundError(RunError):
    code = "run_not_found"


class RunForbiddenError(RunError):
    code = "run_forbidden"


class InvalidRunRequestError(RunError):
    code = "invalid_run_request"


class RunConflictError(RunError):
    code = "run_conflict"


class RunStateError(RunError):
    code = "run_invalid_state"


class RunLimitError(RunError):
    code = "run_limit_exceeded"


class RunCancelledError(RunError):
    code = "run_cancelled"


class RunExpiredError(RunError):
    code = "run_expired"
