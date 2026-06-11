from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol


class CLISessionInvalidError(Exception):
    """Raised when a CLI provider reports its resume session_id is unusable
    (expired, missing, or not found on disk).

    Signals the ExecutionRunner to clear the persisted session, rebuild the
    prompt from thread history, and retry the execute call without --resume.
    """

    def __init__(self, session_id: str, reason: str = ""):
        self.session_id = session_id
        self.reason = reason
        super().__init__(f"CLI session invalid: session_id={session_id} reason={reason}")


@dataclass
class CLIMessage:
    type: str  # "text" | "thinking" | "tool_use" | "tool_result" | "error" | "artifact" | "approval_request"
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict | None = None
    output: str = ""
    error_payload: dict[str, Any] | None = None
    # Observation/instrumentation fields — used by CLIObservationExtractor
    tool_name: str | None = None
    tool_input: dict | None = None
    usage: dict | None = None


def build_control_response(request_id: str, behavior: str) -> str:
    return json.dumps(
        {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": request_id,
                "response": {"behavior": behavior},
            },
        }
    )


@dataclass
class CLIResult:
    status: str  # "completed" | "failed" | "timeout" | "blocked"
    output: str = ""
    error: str = ""
    error_payload: dict[str, Any] | None = None
    session_id: str = ""
    branch_name: str = ""
    usage: dict | None = None
    # Set true when the provider detects that resume_session_id was rejected
    # by the underlying CLI. The ExecutionRunner reacts by evicting the cached
    # session id and retrying without --resume (history is rebuilt from the
    # event log). Provider responsibility: this flag is the contract for
    # signalling "the session is gone" without Runner-side string matching.
    session_invalid: bool = False


@dataclass
class RuntimeSession:
    messages: asyncio.Queue[CLIMessage | None]
    result: asyncio.Future[CLIResult]
    _inject_fn: Callable[[str], Awaitable[None]] | None = None
    _cancel_fn: Callable[[], Awaitable[None]] | None = None
    _drain_task: asyncio.Task | None = None

    async def inject_message(self, message: str) -> None:
        if self._inject_fn:
            await self._inject_fn(message)

    async def cancel(self) -> None:
        if self._cancel_fn:
            await self._cancel_fn()
        if self._drain_task:
            self._drain_task.cancel()

    async def iter_messages(self) -> AsyncIterator[CLIMessage]:
        while True:
            msg = await self.messages.get()
            if msg is None:
                break
            yield msg


class RuntimeProvider(Protocol):
    provider_type: str

    async def execute(
        self,
        prompt: str,
        *,
        container_id: str,
        cwd: str | None = None,
        model: str | None = None,
        timeout: int = 7200,
        resume_session_id: str | None = None,
        env: dict[str, str] | None = None,
        auto_approve: bool = True,
    ) -> RuntimeSession: ...
