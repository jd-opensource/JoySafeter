"""
速率限制工具
使用内存存储（简单实现），生产环境建议使用 Redis
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple

from fastapi import Request

from app.common.exceptions import TooManyRequestsException


class RateLimiter:
    """简单的内存速率限制器"""

    def __init__(self):
        # 存储格式: {key: [(timestamp, count), ...]}
        self._records: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        """
        检查是否超过速率限制

        返回: (是否允许, 剩余请求数)
        """
        async with self._lock:
            now = datetime.now()
            window_start = now - timedelta(seconds=window_seconds)

            # 清理过期记录
            records = self._records[key]
            records[:] = [(ts, count) for ts, count in records if ts > window_start]

            # 计算当前窗口内的请求数
            current_count = sum(count for _, count in records)

            if current_count >= max_requests:
                return False, 0

            # 记录本次请求
            records.append((now, 1))

            remaining = max_requests - current_count - 1
            return True, remaining

    async def reset(self, key: str):
        """重置指定 key 的速率限制"""
        async with self._lock:
            if key in self._records:
                del self._records[key]


# 全局速率限制器实例
rate_limiter = RateLimiter()


def get_client_identifier(request: Request) -> str:
    """获取客户端标识符（用于速率限制）"""
    # 优先使用 IP 地址
    client_ip = request.client.host if request.client else "unknown"

    # 如果有 X-Forwarded-For，使用第一个 IP
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    return client_ip


async def check_rate_limit_decorator(max_requests: int, window_seconds: int, key_func=None):
    """
    速率限制装饰器

    使用示例:
        @router.post("/login")
        @check_rate_limit_decorator(max_requests=5, window_seconds=60)
        async def login(...):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 从参数中获取 request
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                for key, value in kwargs.items():
                    if isinstance(value, Request):
                        request = value
                        break

            if not request:
                # 如果没有 request，跳过速率限制
                return await func(*args, **kwargs)

            # 获取客户端标识
            if key_func:
                identifier = key_func(request)
            else:
                identifier = get_client_identifier(request)

            # 检查速率限制
            allowed, remaining = await rate_limiter.check_rate_limit(
                f"{func.__name__}:{identifier}", max_requests, window_seconds
            )

            if not allowed:
                raise TooManyRequestsException(
                    f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds."
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
