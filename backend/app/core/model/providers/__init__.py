"""
模型供应商模块
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List, Optional, Type

from .AiSafety import AiSafetyProvider
from .base import BaseProvider, ModelType

# 向后兼容：显式导入现有 provider（避免破坏现有代码）
from .OpenaiApiCompatible import OpenAIAPICompatibleProvider

# Provider 类缓存
_provider_classes_cache: Optional[List[Type[BaseProvider]]] = None


def _discover_provider_classes() -> List[Type[BaseProvider]]:
    """
    自动发现所有继承自 BaseProvider 的类

    Returns:
        所有发现的 Provider 类列表
    """
    global _provider_classes_cache

    if _provider_classes_cache is not None:
        return _provider_classes_cache

    provider_classes: List[Type[BaseProvider]] = []

    # 获取当前包路径
    package_path = Path(__file__).parent
    package_name = __name__

    # 遍历目录中的所有模块
    for importer, modname, ispkg in pkgutil.iter_modules([str(package_path)]):
        # 跳过 __init__ 和 base 模块
        if modname in ("__init__", "base"):
            continue

        try:
            # 动态导入模块
            module = importlib.import_module(f".{modname}", package=package_name)

            # 遍历模块中的所有成员
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # 检查是否是 BaseProvider 的子类（排除 BaseProvider 本身）
                if issubclass(obj, BaseProvider) and obj is not BaseProvider and obj.__module__ == module.__name__:
                    provider_classes.append(obj)
        except Exception as e:
            # 导入失败时记录警告，但不中断程序
            import warnings

            warnings.warn(f"Failed to import provider module '{modname}': {e}", ImportWarning)

    _provider_classes_cache = provider_classes
    return provider_classes


def get_all_provider_classes() -> List[Type[BaseProvider]]:
    """
    获取所有 Provider 类

    Returns:
        所有 Provider 类的列表
    """
    return _discover_provider_classes()


def get_all_provider_instances() -> List[BaseProvider]:
    """
    获取所有 Provider 实例

    Returns:
        所有 Provider 实例的列表
    """
    classes = get_all_provider_classes()
    instances = []
    for cls in classes:
        try:
            # Try to instantiate - most providers have __init__ that calls super().__init__()
            instance = cls()  # type: ignore[call-arg]
            instances.append(instance)
        except TypeError:
            # If __init__ requires arguments, skip this provider
            continue
    return instances


__all__ = [
    "BaseProvider",
    "ModelType",
    "OpenAIAPICompatibleProvider",
    "AiSafetyProvider",
    "get_all_provider_classes",
    "get_all_provider_instances",
]
