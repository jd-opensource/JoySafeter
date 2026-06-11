"""
Ports — Protocol interfaces defining the boundary between core/ and services/.

core/ modules depend on these Protocols (dependency inversion).
services/ modules provide concrete implementations.

See docs/PORT_SYSTEM.md for the full catalog and wiring guide.
"""

from app.joysafeter_domain.ports.agent_spawn import AgentSpawnPort
from app.joysafeter_domain.ports.context_event import ContextEventBridge
from app.joysafeter_domain.ports.execution import EventContext, ExecutionEventPort, ExecutionReaderPort
from app.joysafeter_domain.ports.mcp import McpServerPort
from app.joysafeter_domain.ports.memory import MemoryPort
from app.joysafeter_domain.ports.model import ModelPort
from app.joysafeter_domain.ports.observation import ObservationCollectorPort
from app.joysafeter_domain.ports.sandbox import SandboxPort
from app.joysafeter_domain.ports.skill import SkillPort

__all__ = [
    "AgentSpawnPort",
    "ContextEventBridge",
    "EventContext",
    "ExecutionEventPort",
    "ExecutionReaderPort",
    "McpServerPort",
    "MemoryPort",
    "ModelPort",
    "ObservationCollectorPort",
    "SandboxPort",
    "SkillPort",
]
