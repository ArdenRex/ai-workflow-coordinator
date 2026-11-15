"""LLM errors. Messages are generic: never include prompts, completions, URLs or keys."""


class LLMError(Exception):
    code = "llm_error"
    retryable = False


class LLMConfigError(LLMError):
    code = "llm_config_invalid"


class LLMInputError(LLMError):
    code = "llm_input_invalid"


class LLMInputTooLargeError(LLMInputError):
    code = "llm_input_too_large"


class LLMAuthError(LLMError):
    code = "llm_auth_failed"


class LLMRateLimitedError(LLMError):
    code = "llm_rate_limited"
    retryable = True


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    retryable = True


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    retryable = True


class LLMBadResponseError(LLMError):
    code = "llm_bad_response"


class LLMStructuredOutputError(LLMError):
    """The model never produced output that validates against the schema (after bounded repair)."""
    code = "llm_structured_invalid"
