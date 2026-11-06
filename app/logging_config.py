"""Structured logging: one JSON object per line on stdout, plus a request middleware with the access log.

Same fields as the rest of Colegio Smart services (timestamp, level, service, logger, message, traceId, userId,
institutionId, exception), so one query in the log platform works across services. Never log emails, names or
tokens: identify people by userId.
"""
import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

SERVICE = "lectura-api"
# Per-request mutable context: the auth dependency fills userId/institutionId after the middleware created it
request_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar("request_context", default=None)

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}
QUIET_PATHS = {"/actuator/health"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": SERVICE,
            "logger": record.name,
            "message": record.getMessage(),
        }
        ctx = request_context.get()
        if ctx:
            entry.update({k: v for k, v in ctx.items() if k in ("traceId", "userId", "institutionId") and v is not None})
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD and not k.startswith("_")})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn would write its own access line (no user, no trace); the middleware below replaces it
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False


def _trace_id(headers: list[tuple[bytes, bytes]]) -> str:
    """Trace id of the W3C traceparent header (the frontend and api-colegio-smart send it), else a new one."""
    for key, value in headers:
        if key == b"traceparent":
            parts = value.decode("latin-1").split("-")
            if len(parts) >= 2 and parts[1].strip():
                return parts[1].strip()
    return uuid.uuid4().hex


class RequestLogMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so the context variable reaches the endpoints and the worker threads
    they start. Logs one line per request with method, path, status and duration."""

    def __init__(self, app):
        self.app = app
        self.log = logging.getLogger("lectura.access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ctx = {"traceId": _trace_id(scope["headers"])}
        token = request_context.set(ctx)
        status = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self.log.exception("unhandled error", extra={"method": scope["method"], "path": scope["path"]})
            raise
        finally:
            if scope["path"] not in QUIET_PATHS:
                code = status["code"]
                self.log.log(logging.ERROR if code >= 500 else logging.INFO, "request", extra={
                    "method": scope["method"], "path": scope["path"], "status": code,
                    "durationMs": round((time.perf_counter() - started) * 1000, 1)})
            request_context.reset(token)
