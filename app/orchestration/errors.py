class OrchestrationError(Exception):
    """Messages are safe to show to clients; `code` is a fixed slug."""
    code = "orchestration_error"


class InvalidPlanError(OrchestrationError):
    code = "invalid_plan"

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanRunError(OrchestrationError):
    """Stored-plan errors. Messages are safe to show to clients."""
    code = "plan_error"


class PlanNotFoundError(PlanRunError):
    code = "plan_not_found"


class PlanForbiddenError(PlanRunError):
    code = "plan_forbidden"


class InvalidPlanRequestError(PlanRunError):
    code = "invalid_plan_request"


class PlanConflictError(PlanRunError):
    code = "plan_conflict"


class PlanStateError(PlanRunError):
    code = "plan_invalid_state"


class PlanCancelledError(PlanRunError):
    code = "plan_cancelled"
