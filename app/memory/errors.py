class MemoryError_(Exception):
    """Base for memory errors. Messages are fixed text, safe to show to clients; `code` is a fixed slug.
    They never contain the content that was rejected."""
    code = "memory_error"


class InvalidMemoryError(MemoryError_):
    code = "invalid_memory"

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MemoryNotFoundError(MemoryError_):
    code = "memory_not_found"


class MemoryForbiddenError(MemoryError_):
    code = "memory_forbidden"


class MemoryConflictError(MemoryError_):
    code = "memory_conflict"


class MemoryLimitError(MemoryError_):
    code = "memory_limit"
