import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


@dataclass
class SkillArchive:
    name: str
    data: bytes  # decoded tar.gz content
    target: str  # "skills", "agents", or "commands"


@dataclass
class HarnessInput:
    prompt: str
    system_prompt: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    work_dir: Optional[str] = None
    session_id: Optional[str] = None
    permission_mode: str = "bypassPermissions"
    model: Optional[str] = None
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    secrets: dict[str, str] = field(default_factory=dict)
    workspace_path: Optional[str] = None
    custom_tools: list[dict[str, Any]] = field(default_factory=list)
    memory_mounts: list[dict[str, Any]] = field(default_factory=list)
    memory_system_prompt: Optional[str] = None
    skill_archives: list[SkillArchive] = field(default_factory=list)


@dataclass
class HarnessEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    is_control_request: bool = False


class HarnessResultStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    TIMEOUT = "timeout"


@dataclass
class HarnessResult:
    output: str = ""
    error: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    session_id: Optional[str] = None
    work_dir: Optional[str] = None
    status: HarnessResultStatus = HarnessResultStatus.COMPLETED
    duration_ms: Optional[int] = None


class RunningHarness:
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self._events: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        self._result: Optional[HarnessResult] = None
        self._done = asyncio.Event()

    async def events(self) -> AsyncIterator[HarnessEvent]:
        while not self._done.is_set() or not self._events.empty():
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    async def wait(self) -> HarnessResult:
        await self._done.wait()
        return self._result or HarnessResult(error="No result")


class HarnessAdapter(ABC):
    @abstractmethod
    async def start(self, input: HarnessInput) -> RunningHarness: ...

    @abstractmethod
    async def cancel(self, harness: RunningHarness) -> None: ...

    @abstractmethod
    async def send_input(self, harness: RunningHarness, content: str) -> None: ...

    @abstractmethod
    def provider(self) -> str: ...

    @abstractmethod
    async def is_available(self) -> bool: ...
