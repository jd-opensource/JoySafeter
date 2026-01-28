"""
Rate limiting decorator for API endpoints
使用 Redis 实现基于 IP 和用户的速率限制
"""

import time
from functools import wraps
from typing import Callable, Optional

from fastapi import HTTPException, Request


class RateLimiter:
    """基于内存的速率限制器（简单实现，生产环境应使用 Redis）"""

    def __init__(self):
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        检查是否允许请求

        Args:
            key: 限流键（通常是 IP 地址或用户 ID）
            max_requests: 时间窗口内允许的最大请求数
            window_seconds: 时间窗口（秒）

        Returns:
            True if allowed, False otherwise
        """
        now = time.time()

        # 获取该键的请求历史
        if key not in self._requests:
            self._requests[key] = []

        # 清理过期的请求记录
        cutoff_time = now - window_seconds
        self._requests[key] = [req_time for req_time in self._requests[key] if req_time > cutoff_time]

        # 检查是否超过限制
        if len(self._requests[key]) >= max_requests:
            return False

        # 记录本次请求
        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        """获取剩余请求次数"""
        now = time.time()
        cutoff_time = now - window_seconds

        if key not in self._requests:
            return max_requests

        # 清理过期记录
        self._requests[key] = [req_time for req_time in self._requests[key] if req_time > cutoff_time]

        used = len(self._requests[key])
        return max(0, max_requests - used)


# 全局速率限制器实例
_rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """获取客户端 IP 地址"""
    # 优先从 X-Forwarded-For 获取（考虑代理/负载均衡）
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return str(forwarded).split(",")[0].strip()

    # 从 X-Real-IP 获取
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return str(real_ip)

    # 直接从 client 获取
    if request.client:
        return str(request.client.host)

    return "unknown"


def rate_limit(max_requests: int = 5, window_seconds: int = 60, key_func: Optional[Callable[[Request], str]] = None):
    """
    速率限制装饰器

    Args:
        max_requests: 时间窗口内允许的最大请求数
        window_seconds: 时间窗口（秒）
        key_func: 自定义键函数，接收 Request 对象，返回限流键
                  默认使用 IP 地址

    Example:
        @router.post("/login")
        @rate_limit(max_requests=5, window_seconds=60)
        async def login(request: Request, ...):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从参数中提取 Request 对象
            request: Optional[Request] = None

            # 从位置参数查找
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # 从关键字参数查找（检查多个可能的名称）
            if not request:
                for key in ["http_request", "request", "req"]:
                    if key in kwargs and isinstance(kwargs[key], Request):
                        request = kwargs[key]
                        break

            if not request:
                # 如果找不到 Request 对象，跳过限流
                return await func(*args, **kwargs)

            # 生成限流键
            if key_func:
                rate_limit_key = key_func(request)
            else:
                rate_limit_key = f"rate_limit:ip:{get_client_ip(request)}"

            # 检查速率限制
            if not _rate_limiter.is_allowed(rate_limit_key, max_requests, window_seconds):
                remaining = _rate_limiter.get_remaining(rate_limit_key, max_requests, window_seconds)
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {window_seconds} seconds.",
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(int(time.time() + window_seconds)),
                    },
                )

            # 添加速率限制响应头
            remaining = _rate_limiter.get_remaining(rate_limit_key, max_requests, window_seconds)

            # 执行原函数
            result = await func(*args, **kwargs)

            return result

        return wrapper

    return decorator


# 预定义的常用速率限制配置
def auth_rate_limit():
    """认证端点的速率限制：5次/分钟"""
    return rate_limit(max_requests=5, window_seconds=60)


def strict_rate_limit():
    """严格的速率限制：3次/分钟"""
    return rate_limit(max_requests=3, window_seconds=60)


def api_rate_limit():
    """一般 API 的速率限制：60次/分钟"""
    return rate_limit(max_requests=60, window_seconds=60)
