"""
Logging middleware.

Log detailed information for each request, including method, path, duration, status code, etc.
"""
# mypy: ignore-errors

import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.trace_context import get_trace_id, set_trace_id


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


class LoggingMiddleware(BaseHTTPMiddleware):
    """HTTP request logging middleware."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and log details."""
        start_time = time.time()
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"

        trace_id = set_trace_id(request.headers.get("X-Request-ID") or None)
        request.state.trace_id = trace_id
        log = logger.bind(trace_id=trace_id, method=method, path=path, client=client_host)

        log.info("request.start")

        try:
            response = await call_next(request)

            process_time = time.time() - start_time
            status_code = response.status_code
            message = f"request.completed status={status_code} duration={process_time:.3f}s"

            if status_code >= 500:
                log.error(message)
            elif status_code >= 400:
                log.warning(message)
            else:
                log.info(message)

            response.headers["X-Process-Time"] = str(process_time)
            response.headers["X-Trace-Id"] = trace_id
            return response

        except Exception as e:
            process_time = time.time() - start_time
            log.opt(exception=True).error(f"request.failed duration={process_time:.3f}s error={type(e).__name__}")
            raise


def setup_logging():
    """
    Configure loguru logging.

    Set up log format, level, output files, etc.
    """
    try:
        os.makedirs("logs", exist_ok=True)
    except PermissionError:
        # if unable to create logs directory (e.g. insufficient permissions in Docker), use console only
        pass
    logger.configure(
        patcher=lambda record: record["extra"].update(trace_id=get_trace_id() or record["extra"].get("trace_id", "-")),
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
            rotation="100 MB",  # rotate when file reaches 100 MB
            retention="30 days",  # retain logs for 30 days
            compression="zip",  # compress old logs
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
        # if unable to create log files (e.g. insufficient permissions), use console only
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
