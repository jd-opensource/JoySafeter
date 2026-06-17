import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from typing import Any, Optional

from app.joysafeter_orchestrator.runtime.adapter import (
    HarnessAdapter,
    HarnessEvent,
    HarnessInput,
    HarnessResult,
    HarnessResultStatus,
    RunningHarness,
)

logger = logging.getLogger(__name__)


class _CodexSession:
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.stdin_lock = asyncio.Lock()
        self.thread_id: Optional[str] = None
        self.current_turn: Optional[_CodexTurnState] = None
        self._next_rpc_id = 1
        self._pending_rpcs: dict[int, asyncio.Future] = {}
        self._protocol: Optional[str] = None  # "legacy" or "raw", auto-detected


class _CodexTurnState:
    def __init__(self):
        self.events: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        self.done = asyncio.Event()
        self.output_parts: list[str] = []
        self.usage: Optional[dict[str, Any]] = None
        self.usage_event_emitted = False
        self.error: Optional[str] = None
        self.status: HarnessResultStatus = HarnessResultStatus.COMPLETED
        self.start_time: float = time.monotonic()
        self.model: str = "codex"
        self.agent_message_text_by_id: dict[str, str] = {}


class CodexAdapter(HarnessAdapter):
    def __init__(self):
        self._binary = shutil.which("codex") or "codex"
        self._sessions: dict[str, _CodexSession] = {}

    def provider(self) -> str:
        return "codex"

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    def _session_key(self, input: HarnessInput) -> str:
        return input.session_id or "default"

    async def _rpc_request(
        self, session: _CodexSession, method: str, params: Optional[dict] = None
    ) -> Any:
        rpc_id = session._next_rpc_id
        session._next_rpc_id += 1

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        session._pending_rpcs[rpc_id] = future

        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            msg["params"] = params

        async with session.stdin_lock:
            if session.process and session.process.stdin:
                session.process.stdin.write((json.dumps(msg) + "\n").encode())
                await session.process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            session._pending_rpcs.pop(rpc_id, None)
            raise RuntimeError(f"RPC {method} timed out")

    async def _send_notification(
        self, session: _CodexSession, method: str, params: Optional[dict] = None
    ) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        async with session.stdin_lock:
            if session.process and session.process.stdin:
                session.process.stdin.write((json.dumps(msg) + "\n").encode())
                await session.process.stdin.drain()

    async def _ensure_session(self, input: HarnessInput) -> _CodexSession:
        key = self._session_key(input)
        session = self._sessions.get(key)
        if session and session.process and session.process.returncode is None:
            logger.info("Reusing existing codex session: key=%s thread_id=%s", key, session.thread_id)
            print(f"[CODEX] Reusing session: key={key} thread_id={session.thread_id}", flush=True)
            return session
        print(
            f"[CODEX] Creating new session: key={key} input.session_id={input.session_id} "
            f"workspace_path={input.workspace_path}",
            flush=True,
        )
        logger.info(
            "Creating new codex session: key=%s input.session_id=%s workspace_path=%s",
            key, input.session_id, input.workspace_path,
        )

        session = _CodexSession()
        env = {**os.environ, **input.env, **input.secrets}

        if input.workspace_path:
            codex_home = os.path.join(input.workspace_path, ".codex")
            os.makedirs(codex_home, exist_ok=True)
            env["CODEX_HOME"] = codex_home
            logger.info("CODEX_HOME set to %s", codex_home)
        else:
            logger.warning("No workspace_path — CODEX_HOME not set, rollouts may not persist")

        cmd = [self._binary, "app-server", "--listen", "stdio://"]
        if input.model:
            cmd.extend(["--model", input.model])

        session.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=input.work_dir,
            env=env,
        )

        session.reader_task = asyncio.create_task(
            self._persistent_reader(session), name=f"codex-reader-{key}"
        )

        # JSON-RPC handshake
        init_result = await self._rpc_request(session, "initialize", {
            "protocolVersion": "2025-01-01",
            "clientInfo": {"name": "joysafeter", "version": "1.0"},
        })
        logger.debug("Codex initialize result: %s", init_result)

        await self._send_notification(session, "initialized")

        if input.session_id:
            try:
                thread_result = await self._rpc_request(session, "thread/resume", {
                    "threadId": input.session_id,
                })
                logger.info("Codex thread/resume succeeded for %s", input.session_id)
            except Exception:
                logger.warning(
                    "Codex thread/resume failed for %s, falling back to thread/start",
                    input.session_id,
                )
                thread_result = await self._rpc_request(session, "thread/start", {})
        else:
            thread_result = await self._rpc_request(session, "thread/start", {})

        if isinstance(thread_result, dict):
            thread = thread_result.get("thread", {})
            session.thread_id = (
                (thread.get("id") or thread.get("thread_id"))
                if isinstance(thread, dict) else None
            ) or thread_result.get("thread_id")
        print(
            f"[CODEX] Session established: key={key} thread_id={session.thread_id} "
            f"thread_result_keys={list(thread_result.keys()) if isinstance(thread_result, dict) else type(thread_result).__name__}",
            flush=True,
        )

        self._sessions[key] = session
        return session

    async def start(self, input: HarnessInput) -> RunningHarness:
        harness = RunningHarness()

        session = await self._ensure_session(input)
        turn = _CodexTurnState()
        turn.model = input.model or "codex"
        session.current_turn = turn
        harness.process = session.process
        harness._events = turn.events

        turn_params: dict[str, Any] = {"prompt": input.prompt}
        if session.thread_id:
            turn_params["thread_id"] = session.thread_id

        await self._send_notification(session, "turn/start", turn_params)

        async def _wait_turn() -> HarnessResult:
            await turn.done.wait()
            duration = int((time.monotonic() - turn.start_time) * 1000)
            output = "\n".join(turn.output_parts)
            print(
                f"[CODEX] Turn done: thread_id={session.thread_id} output_len={len(output)} "
                f"status={turn.status} error={turn.error}",
                flush=True,
            )
            return HarnessResult(
                output=output,
                usage=turn.usage,
                session_id=session.thread_id,
                status=turn.status,
                error=turn.error,
                duration_ms=duration,
            )

        harness.wait = _wait_turn
        return harness

    async def cancel(self, harness: RunningHarness) -> None:
        for k, s in self._sessions.items():
            if s.process is harness.process:
                try:
                    await self._send_notification(s, "turn/cancel", {})
                except Exception:
                    pass
                if s.current_turn:
                    s.current_turn.status = HarnessResultStatus.ABORTED
                    s.current_turn.done.set()
                return

        if harness.process and harness.process.returncode is None:
            harness.process.terminate()
            try:
                await asyncio.wait_for(harness.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                harness.process.kill()

    async def send_input(self, harness: RunningHarness, content: str) -> None:
        for k, s in self._sessions.items():
            if s.process is harness.process:
                await self._send_notification(s, "input", {"content": content})
                return

    def _extract_usage(self, data: dict) -> Optional[dict[str, Any]]:
        usage: Optional[dict[str, Any]] = None
        for key in ("usage", "token_usage", "tokens"):
            if key in data and isinstance(data[key], dict):
                usage = data[key]
                break
        token_usage = data.get("tokenUsage")
        if usage is None and isinstance(token_usage, dict):
            # Codex tokenUsage.total is thread-cumulative; use last for per-task accounting.
            usage = token_usage.get("last") or token_usage.get("total") or token_usage
        if not isinstance(usage, dict):
            return None
        return self._normalize_usage(usage)

    def _normalize_usage(self, usage: dict[str, Any]) -> dict[str, int]:
        def get_int(*keys: str) -> int:
            for key in keys:
                value = usage.get(key)
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)) and value > 0:
                    return int(value)
            return 0

        return {
            "input_tokens": get_int("input_tokens", "input", "prompt_tokens", "inputTokens"),
            "output_tokens": get_int("output_tokens", "output", "completion_tokens", "outputTokens"),
            "cache_read_tokens": get_int(
                "cache_read_tokens",
                "cache_read_input_tokens",
                "cachedInputTokens",
            ),
            "cache_write_tokens": get_int(
                "cache_write_tokens",
                "cache_creation_input_tokens",
                "cacheWriteTokens",
            ),
        }

    def _model_request_end_payload(self, model: str, usage: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "model_request_end",
            "model": model,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
            "cache_write_tokens": usage.get("cache_write_tokens", 0),
        }

    def _extract_text_value(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("text", "content", "delta"):
                text = self._extract_text_value(value.get(key))
                if text:
                    return text
        if isinstance(value, list):
            text = "".join(
                part for item in value
                if (part := self._extract_text_value(item))
            )
            return text or None
        return None

    def _extract_agent_message_delta(self, params: dict[str, Any]) -> Optional[str]:
        for key in ("delta", "textDelta", "contentDelta", "text", "content"):
            text = self._extract_text_value(params.get(key))
            if text:
                return text

        item = params.get("item")
        if isinstance(item, dict):
            for key in ("delta", "textDelta", "contentDelta"):
                text = self._extract_text_value(item.get(key))
                if text:
                    return text
        return None

    def _assistant_text_event(self, text: str) -> dict[str, Any]:
        return {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": text}],
            },
        }

    async def _persistent_reader(self, session: _CodexSession) -> None:
        try:
            while session.process and session.process.stdout:
                line = await session.process.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Response (has id + result/error)
                if "id" in msg and ("result" in msg or "error" in msg):
                    rpc_id = msg["id"]
                    future = session._pending_rpcs.pop(rpc_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(RuntimeError(str(msg["error"])))
                        else:
                            future.set_result(msg.get("result"))
                    continue

                # Request from server (has id + method)
                if "id" in msg and "method" in msg:
                    await self._handle_server_request(session, msg)
                    continue

                # Notification (has method, no id)
                if "method" in msg and "id" not in msg:
                    await self._handle_notification(session, msg)
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Codex reader error: %s", e)

        if session.current_turn and not session.current_turn.done.is_set():
            session.current_turn.status = HarnessResultStatus.FAILED
            session.current_turn.error = "Process exited unexpectedly"
            session.current_turn.done.set()

    async def _handle_server_request(self, session: _CodexSession, msg: dict) -> None:
        method = msg["method"]
        params = msg.get("params", {})
        rpc_id = msg["id"]
        turn = session.current_turn

        if method == "requestApproval":
            if turn:
                await turn.events.put(HarnessEvent(
                    event_type="tool_use",
                    payload=params,
                    is_control_request=True,
                ))
            response = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"decision": "accept"},
            }
            async with session.stdin_lock:
                if session.process and session.process.stdin:
                    session.process.stdin.write((json.dumps(response) + "\n").encode())
                    await session.process.stdin.drain()
        else:
            logger.debug("Unknown server request: %s", method)
            response = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {},
            }
            async with session.stdin_lock:
                if session.process and session.process.stdin:
                    session.process.stdin.write((json.dumps(response) + "\n").encode())
                    await session.process.stdin.drain()

    async def _handle_notification(self, session: _CodexSession, msg: dict) -> None:
        method = msg["method"]
        params = msg.get("params", {})
        turn = session.current_turn

        # Auto-detect protocol: legacy uses "codex/event", raw uses "turn/*" / "item/*"
        if method == "codex/event" and session._protocol is None:
            session._protocol = "legacy"
        elif method.startswith(("turn/", "item/")) and session._protocol is None:
            session._protocol = "raw"

        if method == "codex/event":
            await self._handle_legacy_event(session, params)
        elif method == "turn/started":
            if turn:
                await turn.events.put(HarnessEvent(
                    event_type="model_request_start",
                    payload={"type": "model_request_start", "model": turn.model},
                ))
        elif method == "turn/completed":
            if turn:
                turn.usage = self._extract_usage(params) or turn.usage
                if turn.usage and not turn.usage_event_emitted:
                    await turn.events.put(HarnessEvent(
                        event_type="model_request_end",
                        payload=self._model_request_end_payload(turn.model, turn.usage),
                    ))
                    turn.usage_event_emitted = True
                if "output" in params:
                    turn.output_parts.append(params["output"])
                turn.done.set()
                session.current_turn = None
        elif method == "thread/tokenUsage/updated":
            if turn:
                usage = self._extract_usage(params)
                if usage:
                    turn.usage = usage
                    await turn.events.put(HarnessEvent(
                        event_type="model_request_end",
                        payload=self._model_request_end_payload(turn.model, usage),
                    ))
                    turn.usage_event_emitted = True
        elif method == "item/started":
            if turn:
                await turn.events.put(HarnessEvent(event_type="item_started", payload=params))
        elif method == "item/agentMessage/delta":
            if turn:
                text = self._extract_agent_message_delta(params)
                if text:
                    item = params.get("item") if isinstance(params.get("item"), dict) else {}
                    item_id = item.get("id") or ""
                    if item_id:
                        turn.agent_message_text_by_id[item_id] = (
                            turn.agent_message_text_by_id.get(item_id, "") + text
                        )
                    await turn.events.put(HarnessEvent(
                        event_type="assistant",
                        payload=self._assistant_text_event(text),
                    ))
        elif method == "item/completed":
            if turn:
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                if item.get("type") == "agentMessage":
                    text = item.get("text") if isinstance(item.get("text"), str) else ""
                    item_id = item.get("id") or ""
                    already_sent = turn.agent_message_text_by_id.pop(item_id, "")
                    remaining_text = (
                        text[len(already_sent):]
                        if already_sent and text.startswith(already_sent)
                        else ("" if already_sent else text)
                    )
                    if remaining_text:
                        await turn.events.put(HarnessEvent(
                            event_type="assistant",
                            payload=self._assistant_text_event(remaining_text),
                        ))
                    if text:
                        turn.output_parts.append(text)
                else:
                    await turn.events.put(HarnessEvent(event_type="item_completed", payload=params))
                if "output" in params:
                    turn.output_parts.append(params["output"])
        else:
            if turn:
                await turn.events.put(HarnessEvent(event_type=method, payload=params))

    async def _handle_legacy_event(self, session: _CodexSession, params: dict) -> None:
        turn = session.current_turn
        event_name = params.get("event", "")

        if event_name == "task_started":
            if turn:
                await turn.events.put(HarnessEvent(event_type="turn_started", payload=params))
        elif event_name == "agent_message":
            if turn:
                text = params.get("message", "")
                if text:
                    turn.output_parts.append(text)
                await turn.events.put(HarnessEvent(event_type="assistant", payload=params))
        elif event_name == "exec_command_begin":
            if turn:
                await turn.events.put(HarnessEvent(event_type="tool_use", payload=params))
        elif event_name == "exec_command_end":
            if turn:
                await turn.events.put(HarnessEvent(event_type="tool_result", payload=params))
        elif event_name == "task_complete":
            if turn:
                turn.usage = self._extract_usage(params) or turn.usage
                if turn.usage and not turn.usage_event_emitted:
                    await turn.events.put(HarnessEvent(
                        event_type="model_request_end",
                        payload=self._model_request_end_payload(turn.model, turn.usage),
                    ))
                    turn.usage_event_emitted = True
                if "output" in params:
                    turn.output_parts.append(params["output"])
                turn.done.set()
                session.current_turn = None
        else:
            if turn:
                await turn.events.put(HarnessEvent(event_type=event_name, payload=params))

    async def _kill_process(self, session: _CodexSession) -> None:
        if session.reader_task:
            session.reader_task.cancel()
            try:
                await session.reader_task
            except asyncio.CancelledError:
                pass
        if session.process and session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                session.process.kill()

    async def close(self) -> None:
        for key, session in list(self._sessions.items()):
            await self._kill_process(session)
        self._sessions.clear()
