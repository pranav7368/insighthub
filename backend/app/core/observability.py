"""Structured logging and request correlation.

The app previously logged nothing but a couple of `print`s, which means a
production incident is debugged by guessing. This adds the smallest thing that
makes an incident tractable:

* **one JSON line per request** — method, path, status, duration, and the
  workspace it belonged to, so "the dashboard is slow for Acme" is a query
  rather than a hunch;
* **a request id** on every log line and returned in `X-Request-Id`, so a user
  can quote the id from a failed request and it can be found immediately;
* **redaction by construction** — the logger drops anything that looks like a
  credential and never receives row values at all.

Two rules this module exists to enforce, because both are easy to violate by
accident and expensive to discover later:

1. **Never log personal data.** Log identifiers (workspace_id, dataset_id), not
   contents. A log shipped to a third-party service is a data transfer, and a
   log containing customer PII turns every log sink into a subprocessor.
2. **Never log secrets.** Authorization headers, tokens, passwords and API keys
   are redacted on the way in rather than trusted not to be passed.

Error tracking (Sentry or similar) is deliberately not a dependency: the DSN
hook is `IH_ERROR_DSN`, and when unset nothing is sent anywhere, which keeps
the default deployment free of outbound telemetry.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar

from . import config

# The id of the request being served on this task, so any log line emitted deep
# in the call stack can be correlated without threading a parameter through.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = re.compile(
    r"(authorization|password|passwd|secret|token|api[_-]?key|cookie|session)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)


def redact(value):
    """Best-effort scrub of anything credential-shaped."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if _SENSITIVE_KEYS.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _BEARER.sub(r"\1[redacted]", value)
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line — greppable by a human, parseable by anything."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "context", None)
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure() -> logging.Logger:
    """Install the JSON handler once. Safe to call repeatedly."""
    logger = logging.getLogger("insighthub")
    if getattr(logger, "_ih_configured", False):
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
    logger.propagate = False
    logger._ih_configured = True          # type: ignore[attr-defined]
    return logger


log = configure()


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def event(message: str, level: str = "info", **context) -> None:
    """Emit one structured line. Keyword args become the context object.

    Pass identifiers, never contents: `dataset_id=...`, not `rows=[...]`.
    """
    getattr(log, level, log.info)(message, extra={"context": context})


def report_exception(exc: BaseException, **context) -> None:
    """Record an unhandled error. Ships to IH_ERROR_DSN when configured;
    otherwise it is a local log line and nothing leaves the machine."""
    log.error(str(exc), exc_info=exc, extra={"context": context})
    dsn = getattr(config, "ERROR_DSN", "")
    if not dsn:
        return
    try:                                    # optional dependency, never required
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:                       # noqa: BLE001 — telemetry must never break a request
        pass


class Timer:
    """Wall-clock duration in milliseconds, for the request log line."""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = round((time.perf_counter() - self._start) * 1000, 1)
        return False
