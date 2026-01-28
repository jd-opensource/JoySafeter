"""
密码强度验证
"""

import re
from typing import List, Tuple

from app.common.exceptions import BadRequestException


def validate_password_strength(password: str) -> Tuple[bool, List[str]]:
    """
    验证密码强度

    注意：如果输入是 SHA-256 哈希值（64个十六进制字符），则跳过验证
    因为前端已经对密码进行了 SHA-256 哈希处理

    要求（仅对原始密码）：
    - 至少 8 个字符
    - 至少包含一个大写字母
    - 至少包含一个小写字母
    - 至少包含一个数字
    - 至少包含一个特殊字符

    返回: (是否有效, 错误消息列表)
    """
    # 检查是否是 SHA-256 哈希值（64个十六进制字符）
    if len(password) == 64 and all(c in "0123456789abcdef" for c in password.lower()):
        # 这是 SHA-256 哈希值，跳过验证
        return True, []

    errors: List[str] = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")

    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")

    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>\[\]\\/_+=\-]', password):
        errors.append("Password must contain at least one special character")

    return len(errors) == 0, errors


def validate_password_or_raise(password: str) -> None:
    """
    验证密码强度，如果不满足要求则抛出异常
    """
    is_valid, errors = validate_password_strength(password)
    if not is_valid:
        raise BadRequestException("Password does not meet security requirements: " + "; ".join(errors))
