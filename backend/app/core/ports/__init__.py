"""
Ports — Protocol interfaces defining the boundary between core/ and services/.

core/ modules depend on these Protocols (dependency inversion).
services/ modules provide concrete implementations.
"""

from app.core.ports.execution import EventContext, ExecutionEventPort, ExecutionReaderPort

__all__ = [
    "EventContext",
    "ExecutionEventPort",
    "ExecutionReaderPort",
]
