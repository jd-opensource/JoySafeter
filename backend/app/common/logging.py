"""
Logging middleware.

Log detailed information for each request, including method, path, duration, status code, etc.
Uses OpenTelemetry for trace-context propagation so that HTTP request logs, engine
observations, and outgoing A2A calls share the same trace_id.
"""
# mypy: ignore-errors

import logging
import os
import time

from loguru import logger
from opentelemetry import propagate, trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _get_otel_trace_id() -> str:
    """Read trace_id from the current OTel span context (hex, 32-char)."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        return format(ctx.trace_id, "032x")
    return ""


class InterceptHandler(logging.Handler):
    """Intercept standard logging messages and route them to loguru."""

    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        logging_file = getattr(logging, "__file__", "")
        while frame and frame.f_code.co_filename == logging_file:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class LoggingMiddleware:
    """Pure ASGI logging middleware with OTel trace-context propagation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        method = scope.get("method", "-")
        path = scope.get("path", "-")
        client = scope.get("client")
        client_host = client[0] if client else "unknown"

        # Extract incoming W3C traceparent so upstream traces are continued
        carrier = {
            k.decode(): v.decode()
            for k, v in scope.get("headers", [])
            if k in (b"traceparent", b"tracestate")
        }
        parent_ctx = propagate.extract(carrier) if carrier else None

        tracer = trace.get_tracer("joysafeter.http")
        with tracer.start_as_current_span(
            "http.request",
            context=parent_ctx,
            attributes={
                "http.method": method,
                "http.path": path,
                "http.client": client_host,
            },
        ) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")

            log = logger.bind(trace_id=trace_id, method=method, path=path, client=client_host)
            log.info("request.start")

            status_code = 500
            response_process_time = 0.0

            async def send_wrapper(message: Message) -> None:
                nonlocal status_code, response_process_time
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    response_process_time = time.time() - start_time
                    if "headers" not in message:
                        message["headers"] = []
                    message["headers"] = list(message["headers"]) + [
                        [b"x-process-time", str(response_process_time).encode()],
                        [b"x-trace-id", trace_id.encode()],
                    ]
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as e:
                process_time = time.time() - start_time
                log.opt(exception=True).error(f"request.failed duration={process_time:.3f}s error={type(e).__name__}")
                raise

            process_time = response_process_time or (time.time() - start_time)
            message = f"request.completed status={status_code} duration={process_time:.3f}s"
            if status_code >= 500:
                log.error(message)
            elif status_code >= 400:
                log.warning(message)
            else:
                log.info(message)


def setup_logging():
    """
    Configure loguru logging.

    Set up log format, level, output files, etc.
    """
    try:
        os.makedirs("logs", exist_ok=True)
    except PermissionError:
        pass
    logger.configure(
        patcher=lambda record: record["extra"].update(
            trace_id=_get_otel_trace_id() or record["extra"].get("trace_id", "-")
        ),
        extra={"trace_id": "-", "method": "-", "path": "-", "client": "-"},
    )

    # remove default handler
    logger.remove()

    # add console output (with color)
    logger.add(
        sink=lambda msg: print(msg, end=""),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "trace_id={extra[trace_id]} | "
            "{extra[method]} {extra[path]} | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level="INFO",
        colorize=True,
    )

    # add file output (all logs)
    try:
        logger.add(
            "logs/app.log",
            rotation="100 MB",
            retention="30 days",
            compression="zip",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | trace_id={extra[trace_id]} | "
                "{extra[method]} {extra[path]} | {name}:{function}:{line} | {message}"
            ),
            level="INFO",
        )

        # add error log file
        logger.add(
            "logs/error.log",
            rotation="50 MB",
            retention="30 days",
            compression="zip",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | trace_id={extra[trace_id]} | "
                "{extra[method]} {extra[path]} | {name}:{function}:{line} | {message}"
            ),
            level="ERROR",
        )
    except (PermissionError, OSError):
        pass

    # intercept ALL standard logging into loguru (root + named loggers)
    intercept_handler = InterceptHandler()
    root_logger = logging.root
    root_logger.handlers = [intercept_handler]
    root_logger.setLevel(logging.DEBUG)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        std_logger = logging.getLogger(logger_name)
        std_logger.handlers = [intercept_handler]
        std_logger.propagate = False

    logger.info("Logging system initialized")
