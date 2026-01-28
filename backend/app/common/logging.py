"""
日志中间件

记录每个请求的详细信息，包括请求方法、路径、耗时、响应状态码等
"""
# mypy: ignore-errors

import os
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class LoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求并记录日志"""
        start_time = time.time()
        method = request.method
        str(request.url)
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"

        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
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
    配置 loguru 日志

    设置日志格式、级别、输出文件等
    """
    try:
        os.makedirs("logs", exist_ok=True)
    except PermissionError:
        # 如果无法创建 logs 目录（例如在 Docker 容器中权限不足），只使用控制台输出
        pass
    logger.configure(extra={"trace_id": "-", "method": "-", "path": "-", "client": "-"})

    # 移除默认的 handler
    logger.remove()

    # 添加控制台输出（带颜色）
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

    # 添加文件输出（所有日志）
    try:
        logger.add(
            "logs/app.log",
            rotation="100 MB",  # 文件大小达到 100MB 时轮转
            retention="30 days",  # 保留 30 天的日志
            compression="zip",  # 压缩旧日志
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | trace_id={extra[trace_id]} | "
                "{extra[method]} {extra[path]} | {name}:{function}:{line} | {message}"
            ),
            level="INFO",
        )

        # 添加错误日志文件
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
        # 如果无法创建日志文件（例如权限不足），只使用控制台输出
        pass

    logger.info("✅ 日志系统初始化完成")
