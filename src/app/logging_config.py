"""Structured-ish logging configuration.

Real services log to stdout in a consistent, parseable format so a log
aggregator (CloudWatch, Loki, Datadog) can index them. Here we keep it simple:
one handler, one formatter, configured once at startup from `lifespan`.

The next lesson upgrade is true JSON logs + a per-request correlation id; the
middleware in main.py already attaches a request id you could log here.
"""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    # Clear pre-existing handlers so repeated app creation (e.g. in tests) doesn't
    # stack duplicate handlers and double-print every line.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; let our root config own formatting.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True
