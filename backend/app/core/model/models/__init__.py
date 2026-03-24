"""
模型包装器模块
"""

from .base import BaseModelWrapper
from .chat_model import ChatModelWrapper

__all__ = [
    "BaseModelWrapper",
    "ChatModelWrapper",
]
