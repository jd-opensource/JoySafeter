from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from app.common.app_errors import InternalServiceError
from app.utils.safe_task import safe_create_task

from .base import CLIMessage, CLIResult, RuntimeSession
from .container_bridge import ContainerProcessBridge


class CodexProvider:
    """Runtime provider for OpenAI Codex CLI.

    Codex uses JSON-RPC 2.0 over stdio. We spawn ``codex app-server --listen
    stdio://``, perform the initialize / thread/start / turn/start handshake,
    then read NDJSON lines from stdout.  Each line is either:

    * A *response* (has ``id`` + ``result`` or ``error``) — matched to a
      pending request.
    * A *server request* (has ``id`` + ``method``) — auto-approved.
    * A *notification* (has ``method``, no ``id``) — mapped to CLIMessage.
    """

    provider_type = "codex"

    def __init__(self, executable_path: str = "codex") -> None:
        self.executable_path = executable_path
        self.bridge = ContainerProcessBridge()

    # ── public API ──────────────────────────────────────────────────────

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
    ) -> RuntimeSession:
        cmd = [self.executable_path, "app-server", "--listen", "stdio://"]

        process = await self.bridge.exec_streaming(
            container_id,
            cmd,
            env=env,
            workdir=cwd,
        )

        queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue(maxsize=512)
        loop = asyncio.get_event_loop()
        result_future: asyncio.Future[CLIResult] = loop.create_future()

        drain_task = asyncio.create_task(
            self._drain(process, queue, result_future, prompt, model, timeout),
            name=f"codex-drain-{container_id[:12]}",
        )

        async def inject(message: str) -> None:
            if process.stdin and not process.stdin.is_closing():
                process.stdin.write(f"{message}\n".encode())
                await process.stdin.drain()

        async def cancel() -> None:
            process.terminate()

        return RuntimeSession(
            messages=queue,
            result=result_future,
            _inject_fn=inject,
            _cancel_fn=cancel,
            _drain_task=drain_task,
        )

    # ── JSON-RPC helpers ────────────────────────────────────────────────

    _next_id: int = 0

    async def _rpc_request(
        self,
        process: asyncio.subprocess.Process,
        method: str,
        params: dict,
    ) -> dict:
        """Send a JSON-RPC request and wait for the matching response."""
        self._next_id += 1
        req_id = self._next_id
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        line = json.dumps(msg) + "\n"
        assert process.stdin is not None
        process.stdin.write(line.encode())
        await process.stdin.drain()
        return {"_pending_id": req_id}

    async def _rpc_notify(
        self,
        process: asyncio.subprocess.Process,
        method: str,
    ) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        line = json.dumps(msg) + "\n"
        assert process.stdin is not None
        process.stdin.write(line.encode())
        await process.stdin.drain()

    async def _rpc_respond(
        self,
        process: asyncio.subprocess.Process,
        req_id: int,
        result: dict,
    ) -> None:
        msg = {"jsonrpc": "2.0", "id": req_id, "result": result}
        line = json.dumps(msg) + "\n"
        assert process.stdin is not None
        process.stdin.write(line.encode())
        await process.stdin.drain()

    # ── drain loop ──────────────────────────────────────────────────────

    async def _drain(
        self,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[CLIMessage | None],
        result_future: asyncio.Future[CLIResult],
        prompt: str,
        model: str | None,
        timeout: int,
    ) -> None:
        accumulated_text: list[str] = []
        pending: dict[int, asyncio.Future[dict]] = {}
        turn_done: asyncio.Future[bool] = asyncio.get_event_loop().create_future()

        async def wait_response(req_id: int) -> dict:
            """Register a pending request and wait for its response."""
            fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
            pending[req_id] = fut
            return await fut

        def handle_line(line: str) -> None:
            """Route a single JSON-RPC line."""
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(raw, dict):
                return

            has_id = "id" in raw

            # Response to our request
            if has_id and ("result" in raw or "error" in raw):
                req_id = raw.get("id")
                if req_id in pending and not pending[req_id].done():
                    if "error" in raw:
                        pending[req_id].set_exception(RuntimeError(f"RPC error: {raw['error']}"))
                    else:
                        pending[req_id].set_result(raw.get("result", {}))
                return

            # Server request (has id + method) — auto-approve
            if has_id and "method" in raw:
                method = raw.get("method", "")
                safe_create_task(
                    self._rpc_respond(process, raw["id"], {"decision": "accept"}),
                    name=f"codex-rpc-{raw['id']}",
                )
                return

            # Notification (no id, has method)
            if "method" in raw:
                for msg in self._parse_notification(raw):
                    if msg.type == "text":
                        accumulated_text.append(msg.content)
                    try:
                        queue.put_nowait(msg)
                    except asyncio.QueueFull:
                        logger.warning(f"Codex event queue full, dropping message: {msg.type}")

                # Detect turn completion
                method = raw.get("method", "")
                params = raw.get("params", {})
                if method == "turn/completed":
                    status = _nested_str(params, "turn", "status")
                    aborted = status in ("cancelled", "canceled", "aborted", "interrupted")
                    if not turn_done.done():
                        turn_done.set_result(aborted)
                elif method == "codex/event":
                    msg_data = (params or {}).get("msg", {})
                    if isinstance(msg_data, dict):
                        msg_type = msg_data.get("type", "")
                        if msg_type == "task_complete":
                            if not turn_done.done():
                                turn_done.set_result(False)
                        elif msg_type == "turn_aborted":
                            if not turn_done.done():
                                turn_done.set_result(True)

        try:
            async with asyncio.timeout(timeout):
                # 1. Send initialize
                await self._rpc_request(
                    process,
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "joysafeter-agent",
                            "title": "JoySafeter Agent",
                            "version": "0.1.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                )
                init_id = self._next_id

                # Read lines until we get the initialize response
                assert process.stdout is not None
                async for raw_line in process.stdout:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(raw, dict) and raw.get("id") == init_id and "result" in raw:
                        break
                    handle_line(line)

                # 2. Send initialized notification
                await self._rpc_notify(process, "initialized")

                # 3. Start thread
                await self._rpc_request(
                    process,
                    "thread/start",
                    {
                        "model": model,
                        "cwd": None,
                        "approvalPolicy": None,
                        "sandbox": None,
                    },
                )
                thread_start_id = self._next_id
                thread_id = ""

                assert process.stdout is not None
                async for raw_line in process.stdout:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(raw, dict) and raw.get("id") == thread_start_id and "result" in raw:
                        result_data = raw.get("result", {})
                        thread_data = result_data.get("thread", {}) if isinstance(result_data, dict) else {}
                        thread_id = thread_data.get("id", "") if isinstance(thread_data, dict) else ""
                        break
                    handle_line(line)

                if not thread_id:
                    raise InternalServiceError(
                        "Codex thread start returned no thread ID",
                        code="CODEX_THREAD_START_INVALID",
                        data=None,
                    )

                logger.info(f"codex thread started: {thread_id}")

                # 4. Start turn
                await self._rpc_request(
                    process,
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": prompt}],
                    },
                )

                # 5. Read events until turn completes
                assert process.stdout is not None
                async for raw_line in process.stdout:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    handle_line(line)
                    if turn_done.done():
                        break

        except TimeoutError:
            if not result_future.done():
                result_future.set_result(
                    CLIResult(
                        status="timeout",
                        error="Codex agent timed out",
                        error_payload={
                            "code": "CODEX_TIMEOUT",
                            "message": "Codex agent timed out",
                            "data": None,
                            "source": "runtime",
                            "retryable": True,
                        },
                    )
                )
        except Exception as e:
            logger.error(f"Codex drain error: {e}")
            if not result_future.done():
                result_future.set_result(
                    CLIResult(
                        status="failed",
                        error=str(e),
                        error_payload={
                            "code": "CODEX_DRAIN_FAILED",
                            "message": str(e),
                            "data": None,
                            "source": "runtime",
                            "retryable": False,
                        },
                    )
                )
        finally:
            if not result_future.done():
                exit_code = await process.wait()
                aborted = turn_done.done() and turn_done.result()
                if aborted:
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            output="\n".join(accumulated_text),
                            error="Turn was aborted",
                            error_payload={
                                "code": "CODEX_TURN_ABORTED",
                                "message": "Turn was aborted",
                                "data": None,
                                "source": "runtime",
                                "retryable": False,
                            },
                        )
                    )
                elif exit_code == 0 or accumulated_text:
                    result_future.set_result(
                        CLIResult(
                            status="completed",
                            output="\n".join(accumulated_text),
                        )
                    )
                else:
                    stderr_bytes = await process.stderr.read() if process.stderr else b""
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            error=f"Exit code {exit_code}: {stderr_bytes.decode()[:2000]}",
                            error_payload={
                                "code": "CODEX_EXIT_FAILED",
                                "message": f"Exit code {exit_code}: {stderr_bytes.decode()[:2000]}",
                                "data": {"exit_code": exit_code},
                                "source": "runtime",
                                "retryable": False,
                            },
                        )
                    )
            await queue.put(None)

    # ── event parsing (testable without Docker) ─────────────────────────

    def _parse_notification(self, raw: dict) -> list[CLIMessage]:
        """Parse a JSON-RPC notification into CLIMessage list.

        Handles both legacy ``codex/event`` notifications and raw v2
        ``item/*`` / ``turn/*`` notifications.
        """
        method = raw.get("method", "")
        params = raw.get("params", {}) or {}

        # Legacy codex/event format
        if method == "codex/event" or method.startswith("codex/event/"):
            return self._parse_legacy_event(params)

        # Raw v2 item notifications
        if method.startswith("item/"):
            return self._parse_item_notification(method, params)

        if method == "turn/error":
            payload = _extract_codex_error_payload(params)
            return [CLIMessage(type="error", content=payload["message"], error_payload=payload)]

        return []

    def _parse_legacy_event(self, params: dict) -> list[CLIMessage]:
        msg_data = params.get("msg")
        if not isinstance(msg_data, dict):
            return []

        msg_type = msg_data.get("type", "")
        messages: list[CLIMessage] = []

        if msg_type == "agent_message":
            text = msg_data.get("message", "")
            if text:
                messages.append(CLIMessage(type="text", content=text))
        elif msg_type == "exec_command_begin":
            messages.append(
                CLIMessage(
                    type="tool_use",
                    tool="exec_command",
                    call_id=msg_data.get("call_id", ""),
                    input={"command": msg_data.get("command", "")},
                )
            )
        elif msg_type == "exec_command_end":
            messages.append(
                CLIMessage(
                    type="tool_result",
                    tool="exec_command",
                    call_id=msg_data.get("call_id", ""),
                    output=msg_data.get("output", ""),
                )
            )
        elif msg_type == "patch_apply_begin":
            messages.append(
                CLIMessage(
                    type="tool_use",
                    tool="patch_apply",
                    call_id=msg_data.get("call_id", ""),
                )
            )
        elif msg_type == "patch_apply_end":
            messages.append(
                CLIMessage(
                    type="tool_result",
                    tool="patch_apply",
                    call_id=msg_data.get("call_id", ""),
                )
            )

        return messages

    def _parse_item_notification(self, method: str, params: dict) -> list[CLIMessage]:
        item = params.get("item", {})
        if not isinstance(item, dict):
            return []

        item_type = item.get("type", "")
        item_id = item.get("id", "")

        if method == "item/started" and item_type == "commandExecution":
            return [
                CLIMessage(
                    type="tool_use",
                    tool="exec_command",
                    call_id=item_id,
                    input={"command": item.get("command", "")},
                )
            ]

        if method == "item/completed" and item_type == "commandExecution":
            return [
                CLIMessage(
                    type="tool_result",
                    tool="exec_command",
                    call_id=item_id,
                    output=item.get("aggregatedOutput", ""),
                )
            ]

        if method == "item/started" and item_type == "fileChange":
            return [
                CLIMessage(
                    type="tool_use",
                    tool="patch_apply",
                    call_id=item_id,
                )
            ]

        if method == "item/completed" and item_type == "fileChange":
            return [
                CLIMessage(
                    type="tool_result",
                    tool="patch_apply",
                    call_id=item_id,
                )
            ]

        if method == "item/completed" and item_type == "agentMessage":
            text = item.get("text", "")
            if text:
                return [CLIMessage(type="text", content=text)]

        return []


def _nested_str(m: dict, *keys: str) -> str:
    current = m
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, {})
    return current if isinstance(current, str) else ""


def _extract_codex_error_payload(params: dict[str, Any]) -> dict[str, Any]:
    error = params.get("error")
    if isinstance(error, dict):
        return {
            "code": str(error.get("code") or "CODEX_RUNTIME_ERROR"),
            "message": str(error.get("message") or "Codex runtime error"),
            "data": error.get("data") if isinstance(error.get("data"), dict) else None,
            "source": "runtime",
            "retryable": False,
        }
    return {
        "code": "CODEX_RUNTIME_ERROR",
        "message": str(params.get("message") or "Codex runtime error"),
        "data": None,
        "source": "runtime",
        "retryable": False,
    }
