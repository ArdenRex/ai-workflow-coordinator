"""Logging setup with a request-id aware formatter. Secrets must never be logged."""
import contextvars
import logging
import sys

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | rid=%(request_id)s | %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
