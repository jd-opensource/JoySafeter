"""
Model wrapper module.
"""

from .base import BaseModelWrapper
from .chat_model import ChatModelWrapper

__all__ = [
    "BaseModelWrapper",
    "ChatModelWrapper",
]
