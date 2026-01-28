"""
时间相关工具

提供获取当前时间和时间计算的功能
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """
    获取当前系统时间

    Returns:
        str: 当前时间的字符串表示，格式为 YYYY-MM-DD HH:MM:SS
    """
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculate_date_offset(days: str) -> str:
    """
    根据当前时间计算指定天数后的日期

    Args:
        days (str): 要加减的天数，正数表示未来，负数表示过去

    Returns:
        str: 计算后的日期字符串，格式为 YYYY-MM-DD HH:MM:SS
    """
    try:
        # 将字符串转换为整数
        days_int = int(days)
        now = datetime.now()
        target_date = now + timedelta(days=days_int)
        return target_date.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError) as e:
        return f"错误：无法解析天数 '{days}'，请输入有效的数字。错误信息：{str(e)}"


@tool
def get_time_info() -> Dict[str, Any]:
    """
    获取详细的时间信息

    Returns:
        Dict[str, Any]: 包含各种时间格式的字典
    """
    now = datetime.now()
    return {
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "weekday_cn": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()],
        "timestamp": now.timestamp(),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
    }


# 导出所有工具
__all__ = ["get_current_time", "calculate_date_offset", "get_time_info"]
