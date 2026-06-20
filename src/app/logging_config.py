"""Structured logging with a request-id that follows the whole request.

`request_id_var` is a ContextVar the middleware sets at the start of each request.
`RequestIdFilter` copies it onto every log record, so *every* log line emitted
while handling a request carries the same id — that's what lets you reconstruct
one request's full story from JSON logs.

`configure_logging(level, fmt)` installs one stdout handler. `fmt="json"` emits
one JSON object per line (for a log aggregator); `fmt="console"` is the
human-friendly format for local dev.
"""

import json
import logging
import sys
from contextvars import ContextVar

# Default "-" so logs emitted outside any request (startup/shutdown) still format.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Attach the current request id; JsonFormatter reads it back via getattr.
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | rid=%(request_id)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()  # avoid stacking duplicate handlers across app re-creation
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Let our root config own formatting for uvicorn's loggers too.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True
