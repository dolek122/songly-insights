"""Structured (JSON) logs and request ids (ADR 0018).

With LOG_FORMAT=json every log line is one JSON object, e.g.
    {"time": "...", "level": "INFO", "logger": "songly.access", "message": "GET /api/v1/... 200",
     "request_id": "3f2a...", "method": "GET", "route": "...", "status": 200, "duration_ms": 4.1}
Tools like Loki or `jq` can then filter by field instead of parsing text.

The request id is kept in a ContextVar: a variable that has its own value in every request
(every request runs in its own asyncio task, and tasks get a copy of the context). So any
log written while handling a request, in any module, gets the same request_id.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if (rid := request_id.get()) is not None:
            data["request_id"] = rid
        # Extra fields: logger.info("...", extra={"fields": {"status": 200}})
        data.update(getattr(record, "fields", {}))
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        # default=str: values like datetime or UUID are written as text instead of failing.
        return json.dumps(data, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Send all logs, including uvicorn's, to stdout as JSON (Docker collects stdout)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn has its own handlers (plain text); let its messages go through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
        # Our LOG_LEVEL decides, not a level set earlier by uvicorn or another library
        # (Prefect, for example, sets "uvicorn" to WARNING).
        uvicorn_logger.setLevel(logging.NOTSET)
        uvicorn_logger.disabled = False
