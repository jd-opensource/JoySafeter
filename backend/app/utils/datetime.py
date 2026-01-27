"""
日期时间工具函数

提供时区感知的日期时间辅助函数
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """
    获取当前 UTC 时间（时区感知）

    替代已弃用的 datetime.utcnow()，使用 datetime.now(UTC) 实现。

    Returns:
        datetime: 当前 UTC 时间，带时区信息

    Example:
        >>> from app.utils.datetime import utc_now
        >>> now = utc_now()
        >>> print(now.tzinfo)  # UTC
    """
    return datetime.now(UTC)
