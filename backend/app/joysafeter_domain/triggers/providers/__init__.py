"""Trigger provider registry package.

Importing the concrete provider modules registers them as a side effect, so a
single ``from ...providers import get_provider`` makes all built-in types
available.
"""

from __future__ import annotations

from . import cron, manual, webhook  # noqa: F401  (import for registration side-effect)
from .base import TriggerProvider, get_provider, register, supported_kinds

__all__ = ["TriggerProvider", "get_provider", "register", "supported_kinds"]
