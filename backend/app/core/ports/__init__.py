"""
Ports — Protocol interfaces defining the boundary between core/ and services/.

core/ modules depend on these Protocols (dependency inversion).
services/ modules provide concrete implementations.
"""

from app.core.ports.agent_spawn import AgentSpawnPort
from app.core.ports.copilot import CopilotPort
from app.core.ports.execution import EventContext, ExecutionEventPort, ExecutionReaderPort
from app.core.ports.memory import MemoryPort
from app.core.ports.model import ModelPort
from app.core.ports.observation import ObservationCollectorPort

__all__ = [
    "AgentSpawnPort",
    "CopilotPort",
    "EventContext",
    "ExecutionEventPort",
    "ExecutionReaderPort",
    "MemoryPort",
    "ModelPort",
    "ObservationCollectorPort",
]
