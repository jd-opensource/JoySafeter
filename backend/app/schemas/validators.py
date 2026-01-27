"""
自定义验证器模块

提供增强的参数验证功能和详细的错误提示
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict


class ValidationErrorDetail(BaseModel):
    """验证错误详情"""

    field: str
    message: str
    value: Any = None
    type: str = "validation_error"


class EnhancedBaseModel(BaseModel):
    """增强的基础模型，提供更好的验证错误处理"""

    model_config = ConfigDict(
        str_strip_whitespace=True,  # 自动去除字符串前后空格
        validate_assignment=True,  # 允许赋值时验证
    )


# 密码验证器
def validate_password_strength(password: str, strict: bool = False) -> str:
    """验证密码强度"""
    if len(password) < 8:
        raise ValueError("密码长度至少为8位")
    if strict:
        if not re.search(r"[A-Z]", password):
            raise ValueError("密码必须包含至少一个大写字母")

        if not re.search(r"[a-z]", password):
            raise ValueError("密码必须包含至少一个小写字母")

        if not re.search(r"\d", password):
            raise ValueError("密码必须包含至少一个数字")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("密码必须包含至少一个特殊字符")

    return password


def validate_username(username: str) -> str:
    """验证用户名"""
    if not username:
        raise ValueError("用户名不能为空")

    if len(username) < 3:
        raise ValueError("用户名长度至少为3位")

    if len(username) > 50:
        raise ValueError("用户名长度不能超过50位")

    # 只允许字母、数字、下划线和连字符
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise ValueError("用户名只能包含字母、数字、下划线和连字符")

    # 不能以数字开头
    if username[0].isdigit():
        raise ValueError("用户名不能以数字开头")

    return username


def validate_nickname(nickname: str) -> str:
    """验证昵称"""
    if not nickname:
        raise ValueError("昵称不能为空")

    if len(nickname) < 2:
        raise ValueError("昵称长度至少为2位")

    if len(nickname) > 50:
        raise ValueError("昵称长度不能超过50位")

    # 检查是否包含非法字符（这里只禁止一些明显的有问题的字符）
    if re.search(r'[<>"/\\|]', nickname):
        raise ValueError("昵称包含非法字符")

    return nickname


def validate_email_domain(email: str) -> str:
    """验证邮箱域名"""
    # 检查常见的一次性邮箱域名
    disposable_domains = [
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "temp-mail.org",
        "throwaway.email",
        "yopmail.com",
    ]

    domain = email.split("@")[-1].lower()
    if domain in disposable_domains:
        raise ValueError("不支持使用临时邮箱")

    return email


def validate_thread_id(thread_id: str) -> str:
    """验证会话线程ID"""
    if not thread_id:
        raise ValueError("会话ID不能为空")

    # 允许UUID格式或其他自定义格式
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    if not re.match(uuid_pattern, thread_id, re.IGNORECASE):
        raise ValueError("会话ID格式不正确")

    return thread_id


def validate_temperature(temp: float) -> float:
    """验证温度参数"""
    if not (0.0 <= temp <= 2.0):
        raise ValueError("温度参数必须在0.0到2.0之间")

    return temp


def validate_max_tokens(tokens: int) -> int:
    """验证最大token数"""
    if tokens < 1:
        raise ValueError("最大token数必须大于0")

    if tokens > 32768:  # 一些模型的上限
        raise ValueError("最大token数不能超过32768")

    return tokens


# 增强的字段验证器 - 在Pydantic模型中使用field_validator


def create_validation_error_response(errors: list) -> dict[str, Any]:
    """创建验证错误响应"""
    return {
        "success": False,
        "code": 422,
        "message": "请求参数验证失败",
        "errors": [
            ValidationErrorDetail(
                field=error["loc"][0] if error["loc"] else "unknown",
                message=error["msg"],
                value=error.get("input"),
                type=error["type"],
            ).model_dump()
            for error in errors
        ],
    }
