"""Connector errors. Messages are generic: never include response bodies, URLs with
query strings, or credentials."""


class ConnectorError(Exception):
    code = "connector_error"
    retryable = False


class ConnectorConfigError(ConnectorError):
    code = "connector_config_invalid"


class ConnectorAuthError(ConnectorError):
    code = "connector_auth_failed"


class ConnectorNotFoundError(ConnectorError):
    code = "connector_resource_not_found"


class ConnectorRequestError(ConnectorError):
    code = "connector_bad_request"


class ConnectorRateLimitedError(ConnectorError):
    code = "connector_rate_limited"
    retryable = True

    def __init__(self, message: str = "Rate limited by external system", retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ConnectorTimeoutError(ConnectorError):
    code = "connector_timeout"
    retryable = True


class ConnectorUnavailableError(ConnectorError):
    code = "connector_unavailable"
    retryable = True


class ConnectorBadResponseError(ConnectorError):
    code = "connector_bad_response"
