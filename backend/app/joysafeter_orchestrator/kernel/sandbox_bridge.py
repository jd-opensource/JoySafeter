import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus

logger = logging.getLogger(__name__)


class SandboxBridgeStatus(str, Enum):
    CONNECTED = "connected"
    BUSY = "busy"
    IDLE = "idle"
    DISCONNECTED = "disconnected"


@dataclass
class WsOutMessage:
    """Message sent to task subscribers (WebSocket clients)."""

    type: str  # "event", "status", "complete"
    payload: dict[str, Any] = field(default_factory=dict)


class SandboxBridge:
    """Per-sandbox orchestration state, managing task execution and subscriber fan-out."""

    def __init__(
        self,
        sandbox_db_id: uuid.UUID,
        external_id: str,
    ):
        self.sandbox_db_id = sandbox_db_id
        self.sandbox_id: str = str(sandbox_db_id)  # alias – Rust has both sandbox_id and sandbox_db_id
        self.external_id = external_id
        self.status = SandboxBridgeStatus.CONNECTED
        self.current_task_id: Optional[uuid.UUID] = None
        self.current_owner_epoch: Optional[int] = None
        self.last_result_status: "JoySafeterTaskStatus | None" = None
        self.last_result_error: str | None = None
        self.task_available: asyncio.Event = asyncio.Event()
        self._task_subscribers: dict[uuid.UUID, list[asyncio.Queue[WsOutMessage]]] = {}
        self.confirmation_event = asyncio.Event()
        self.pending_control_request_ids: dict[str, str] = {}
        self.setup_done = False
        self.last_error: Optional[str] = None
        self._cancel_event = asyncio.Event()
        self._control_queue: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._requires_action_pending = False
        # gRPC runner channel
        self.runner_connected = asyncio.Event()
        self.runner_stream: Optional[Any] = None
        self.runner_capabilities: set[str] = set()
        # Serializes ALL writes to runner_stream. grpc.aio forbids concurrent
        # writes to one stream, and the orchestrator writes from several
        # coroutines (the gRPC handler loop + API/relay/shutdown paths), so every
        # producer must funnel through write_to_runner().
        self._write_lock: asyncio.Lock = asyncio.Lock()

    async def broadcast_to_task(self, task_id: uuid.UUID, msg: WsOutMessage) -> None:
        subs = self._task_subscribers.get(task_id, [])
        dead: list[asyncio.Queue] = []
        for q in subs:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        if dead:
            self._task_subscribers[task_id] = [q for q in subs if q not in dead]

    def subscribe(self, task_id: uuid.UUID) -> asyncio.Queue[WsOutMessage]:
        if task_id not in self._task_subscribers:
            self._task_subscribers[task_id] = []
        q: asyncio.Queue[WsOutMessage] = asyncio.Queue(maxsize=256)
        self._task_subscribers[task_id].append(q)
        return q

    def unsubscribe(self, task_id: uuid.UUID, q: asyncio.Queue) -> None:
        if task_id in self._task_subscribers:
            self._task_subscribers[task_id] = [x for x in self._task_subscribers[task_id] if x is not q]
            if not self._task_subscribers[task_id]:
                del self._task_subscribers[task_id]

    def remove_task_subscribers(self, task_id: uuid.UUID) -> None:
        self._task_subscribers.pop(task_id, None)

    async def send_control_input(self, content: str) -> None:
        await self._control_queue.put(content)
        self.confirmation_event.set()

    async def write_to_runner(self, message) -> bool:
        """The single, serialized way to send a message to the runner stream.

        Holds a per-bridge lock so writes can never overlap (grpc.aio forbids
        concurrent writes to one stream). Returns True if written, False if the
        stream is not currently connected (message dropped rather than raising).
        """
        if self.runner_stream is None:
            return False
        async with self._write_lock:
            stream = self.runner_stream
            if stream is None:
                return False
            await stream.write(message)
            return True

    def request_cancel(self) -> None:
        self._cancel_event.set()


class SandboxBridgeRegistry:
    """Global registry mapping sandbox DB ID -> SandboxBridge."""

    def __init__(self):
        self._bridges: dict[uuid.UUID, SandboxBridge] = {}
        self._lock = asyncio.Lock()

    async def register(self, sandbox_db_id: uuid.UUID, external_id: str) -> SandboxBridge:
        async with self._lock:
            # Fix 3.1: if an old bridge exists, disconnect it cleanly before replacing
            old = self._bridges.get(sandbox_db_id)
            if old is not None:
                old.status = SandboxBridgeStatus.DISCONNECTED
                old._cancel_event.set()
                logger.warning(
                    "Bridge replaced for sandbox %s (old session displaced by reconnect)",
                    sandbox_db_id,
                )
            bridge = SandboxBridge(sandbox_db_id, external_id)
            self._bridges[sandbox_db_id] = bridge
            return bridge

    async def get_or_register(self, sandbox_db_id: uuid.UUID, external_id: str) -> SandboxBridge:
        async with self._lock:
            existing = self._bridges.get(sandbox_db_id)
            if existing is not None:
                return existing
            bridge = SandboxBridge(sandbox_db_id, external_id)
            self._bridges[sandbox_db_id] = bridge
            return bridge

    async def get(self, sandbox_db_id: uuid.UUID) -> Optional[SandboxBridge]:
        return self._bridges.get(sandbox_db_id)

    async def remove(self, sandbox_db_id: uuid.UUID) -> Optional[SandboxBridge]:
        async with self._lock:
            return self._bridges.pop(sandbox_db_id, None)

    def get_by_task(self, task_id: uuid.UUID) -> Optional[SandboxBridge]:
        for bridge in self._bridges.values():
            if bridge.current_task_id == task_id:
                return bridge
        return None

    def all_bridges(self) -> list[SandboxBridge]:
        return list(self._bridges.values())

    def count(self) -> int:
        return len(self._bridges)
