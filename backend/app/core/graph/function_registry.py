"""
Function Registry - Predefined function registry for FunctionNodeExecutor.

Provides a safe way to execute predefined functions instead of arbitrary code.
"""

from typing import Any, Callable, Dict, Optional

from loguru import logger


class FunctionRegistry:
    """预定义函数注册表，提供安全的函数执行。"""

    _functions: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, func: Callable) -> None:
        """注册一个预定义函数。

        Args:
            name: 函数名称
            func: 函数对象
        """
        if not callable(func):
            raise ValueError(f"Function '{name}' must be callable")
        cls._functions[name] = func
        logger.debug(f"[FunctionRegistry] Registered function: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[Callable]:
        """获取预定义函数。

        Args:
            name: 函数名称

        Returns:
            函数对象，如果不存在返回 None
        """
        return cls._functions.get(name)

    @classmethod
    def list_all(cls) -> Dict[str, Callable]:
        """列出所有注册的函数。"""
        return cls._functions.copy()

    @classmethod
    def execute(cls, name: str, *args, **kwargs) -> Any:
        """执行预定义函数。

        Args:
            name: 函数名称
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果

        Raises:
            ValueError: 如果函数不存在
        """
        func = cls.get(name)
        if func is None:
            raise ValueError(f"Function '{name}' not found in registry")
        return func(*args, **kwargs)


# ==================== 预置函数库 ====================


def _math_add(state: Dict[str, Any], a: Any, b: Any) -> Dict[str, Any]:
    """数学加法函数。"""
    try:
        result = float(a) + float(b)
        return {"result": result, "status": "success"}
    except (ValueError, TypeError) as e:
        return {"result": None, "status": "error", "error_msg": str(e)}


def _math_multiply(state: Dict[str, Any], a: Any, b: Any) -> Dict[str, Any]:
    """数学乘法函数。"""
    try:
        result = float(a) * float(b)
        return {"result": result, "status": "success"}
    except (ValueError, TypeError) as e:
        return {"result": None, "status": "error", "error_msg": str(e)}


def _string_concat(state: Dict[str, Any], *args) -> Dict[str, Any]:
    """字符串连接函数。"""
    try:
        result = "".join(str(arg) for arg in args)
        return {"result": result, "status": "success"}
    except Exception as e:
        return {"result": None, "status": "error", "error_msg": str(e)}


def _dict_get(state: Dict[str, Any], key: str, default: Any = None) -> Dict[str, Any]:
    """从 state.context 获取值。"""
    context = state.get("context", {})
    result = context.get(key, default)
    return {"result": result, "status": "success"}


def _dict_set(state: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    """设置 state.context 的值。"""
    context = state.get("context", {})
    context[key] = value
    return {"result": value, "status": "success", "context": context}


# 注册预置函数
FunctionRegistry.register("math_add", _math_add)
FunctionRegistry.register("math_multiply", _math_multiply)
FunctionRegistry.register("string_concat", _string_concat)
FunctionRegistry.register("dict_get", _dict_get)
FunctionRegistry.register("dict_set", _dict_set)
