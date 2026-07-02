import asyncio
import hashlib
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
from app.joysafeter_orchestrator.runtime.claude_settings import (
    write_claude_settings,
)

logger = logging.getLogger(__name__)


def _secret_fingerprint_items(secrets: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (str(key), hashlib.sha256(str(value).encode("utf-8")).hexdigest())
        for key, value in sorted((secrets or {}).items())
    ]


def _compute_fingerprint(input: HarnessInput) -> str:
    parts = [
        input.permission_mode or "",
        input.model or "",
        input.system_prompt or "",
        json.dumps(sorted(input.env.items())),
        json.dumps(_secret_fingerprint_items(input.secrets)),
        json.dumps(input.mcp_servers, sort_keys=True),
        json.dumps(sorted(input.allowed_tools)),
        json.dumps(sorted(input.ask_tools)),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class _TurnState:
    def __init__(self):
        self.events: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        self.done = asyncio.Event()
        self.output_parts: list[str] = []
        self.usage: Optional[dict[str, Any]] = None
        self.session_id: Optional[str] = None
        self.work_dir: Optional[str] = None
        self.error: Optional[str] = None
        self.status: HarnessResultStatus = HarnessResultStatus.COMPLETED
        self.start_time: float = time.monotonic()


class _PersistentSession:
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.fingerprint: Optional[str] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.stdin_lock = asyncio.Lock()
        self.current_turn: Optional[_TurnState] = None
        self.session_id: Optional[str] = None


class NativeAdapter(HarnessAdapter):
    def __init__(self):
        self._binary = shutil.which("claude") or "claude"
        self._sessions: dict[str, _PersistentSession] = {}

    def provider(self) -> str:
        return "native"

    async def is_available(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    def _session_key(self, input: HarnessInput) -> str:
        return input.session_id or "default"

    async def _ensure_session(self, input: HarnessInput) -> _PersistentSession:
        key = self._session_key(input)
        fingerprint = _compute_fingerprint(input)

        session = self._sessions.get(key)
        if session and session.process and session.process.returncode is None:
            if session.fingerprint == fingerprint:
                return session
            logger.info("Fingerprint changed for session %s, restarting process", key)
            await self._kill_process(session)

        session = _PersistentSession()
        session.fingerprint = fingerprint

        # Write tool permissions + MCP servers to work_dir/.claude/settings.json
        # before spawning so claude picks them up at startup.
        if input.work_dir:
            write_claude_settings(input.work_dir, input)

        cmd = [
            self._binary,
            "-p",
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
            "--permission-prompt-tool",
            "stdio",
        ]
        if input.permission_mode:
            cmd.extend(["--permission-mode", input.permission_mode])
        if input.model:
            cmd.extend(["--model", input.model])
        if input.session_id:
            cmd.extend(["--resume", input.session_id])
        if input.system_prompt:
            cmd.extend(["--append-system-prompt", input.system_prompt])

        env = {**os.environ, **input.env, **input.secrets}
        session.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=input.work_dir,
            env=env,
        )
        session.reader_task = asyncio.create_task(self._persistent_reader(session), name=f"native-reader-{key}")
        self._sessions[key] = session
        return session

    async def start(self, input: HarnessInput) -> RunningHarness:
        harness = RunningHarness()

        if input.skill_archives and input.work_dir:
            await self._extract_skill_archives(input.work_dir, input.skill_archives)

        session = await self._ensure_session(input)
        turn = _TurnState()
        session.current_turn = turn

        harness.process = session.process
        harness._events = turn.events

        prompt_msg = (
            json.dumps(
                {
                    "type": "user",
                    "content": input.prompt,
                }
            )
            + "\n"
        )
        async with session.stdin_lock:
            if session.process and session.process.stdin:
                session.process.stdin.write(prompt_msg.encode())
                await session.process.stdin.drain()

        async def _wait_turn() -> HarnessResult:
            await turn.done.wait()
            duration = int((time.monotonic() - turn.start_time) * 1000)
            return HarnessResult(
                output="\n".join(turn.output_parts),
                usage=turn.usage,
                session_id=turn.session_id or session.session_id,
                work_dir=turn.work_dir,
                status=turn.status,
                error=turn.error,
                duration_ms=duration,
            )

        harness._wait_override = _wait_turn

        return harness

    async def cancel(self, harness: RunningHarness) -> None:
        key = None
        for k, s in self._sessions.items():
            if s.process is harness.process:
                key = k
                break

        if key:
            session = self._sessions[key]
            cancel_msg = (
                json.dumps(
                    {
                        "type": "control_request",
                        "request_id": f"cancel_{uuid.uuid4().hex[:8]}",
                        "request": {"subtype": "interrupt"},
                    }
                )
                + "\n"
            )
            async with session.stdin_lock:
                if session.process and session.process.stdin:
                    try:
                        session.process.stdin.write(cancel_msg.encode())
                        await session.process.stdin.drain()
                    except Exception:
                        pass
            if session.current_turn:
                session.current_turn.status = HarnessResultStatus.ABORTED
                session.current_turn.done.set()
        else:
            if harness.process and harness.process.returncode is None:
                harness.process.terminate()
                try:
                    await asyncio.wait_for(harness.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    harness.process.kill()

    async def send_input(self, harness: RunningHarness, content: str) -> None:
        for k, s in self._sessions.items():
            if s.process is harness.process:
                msg = self._build_live_protocol_message(content)
                if msg:
                    async with s.stdin_lock:
                        if s.process and s.process.stdin:
                            s.process.stdin.write((json.dumps(msg) + "\n").encode())
                            await s.process.stdin.drain()
                return

        if harness.process and harness.process.stdin:
            raw = f"__joysafeter_input_v1__:{content}\n"
            harness.process.stdin.write(raw.encode())
            await harness.process.stdin.drain()

    def _build_live_protocol_message(self, content: str) -> Optional[dict]:
        if not content.startswith("__joysafeter_input_v1__:"):
            return {"type": "user", "content": content}

        payload_str = content[len("__joysafeter_input_v1__:") :]
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            return {"type": "user", "content": content}

        msg_type = payload.get("type", "")

        if msg_type == "tool_confirmation":
            request_id = payload.get("request_id", "")
            if payload.get("approved"):
                return {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": request_id,
                        "response": {
                            "behavior": "allow",
                            "updatedInput": {},
                        },
                    },
                }
            else:
                return {
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": request_id,
                        "response": {
                            "behavior": "deny",
                            "message": payload.get("deny_message", "denied by user"),
                        },
                    },
                }
        elif msg_type == "custom_tool_result":
            return {
                "type": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": payload.get("tool_use_id", ""),
                        "content": payload.get("result", ""),
                    }
                ],
            }
        elif msg_type == "interrupt":
            return {
                "type": "control_request",
                "request_id": payload.get("request_id", f"int_{uuid.uuid4().hex[:8]}"),
                "request": {"subtype": "interrupt"},
            }

        return {"type": "user", "content": content}

    async def _persistent_reader(self, session: _PersistentSession) -> None:
        try:
            while session.process and session.process.stdout:
                line = await session.process.stdout.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "unknown")
                turn = session.current_turn

                if event_type == "assistant" and "message" in event:
                    msg = event["message"]
                    for block in msg.get("content", []):
                        block_type = block.get("type", "")
                        if block_type == "text":
                            if turn:
                                turn.output_parts.append(block.get("text", ""))
                        elif block_type == "tool_use":
                            if turn:
                                await turn.events.put(
                                    HarnessEvent(
                                        event_type="tool_use",
                                        payload=block,
                                    )
                                )
                    if turn:
                        await turn.events.put(
                            HarnessEvent(
                                event_type="assistant",
                                payload=event,
                            )
                        )
                    if "usage" in msg:
                        if turn:
                            turn.usage = msg["usage"]

                elif event_type == "control_request":
                    request = event.get("request", {})
                    subtype = request.get("subtype", "")
                    if subtype == "can_use_tool":
                        if turn:
                            await turn.events.put(
                                HarnessEvent(
                                    event_type="tool_use",
                                    payload={
                                        "type": "tool_use",
                                        "name": request.get("tool_name", ""),
                                        "input": request.get("tool_input", {}),
                                        "request_id": event.get("request_id", ""),
                                    },
                                    is_control_request=True,
                                )
                            )

                elif event_type == "user":
                    if turn:
                        await turn.events.put(
                            HarnessEvent(
                                event_type="user",
                                payload=event,
                            )
                        )

                elif event_type == "system":
                    sid = event.get("session_id")
                    if sid:
                        session.session_id = sid
                    if turn:
                        turn.session_id = sid
                        await turn.events.put(
                            HarnessEvent(
                                event_type="system",
                                payload=event,
                            )
                        )

                elif event_type == "result":
                    if turn:
                        turn.usage = event.get("usage", turn.usage)
                        turn.session_id = event.get("session_id", turn.session_id)
                        if "result" in event:
                            turn.output_parts.append(event["result"])
                        turn.done.set()
                        session.current_turn = None

                elif event_type == "log":
                    if turn:
                        await turn.events.put(
                            HarnessEvent(
                                event_type="log",
                                payload=event,
                            )
                        )

                else:
                    if turn:
                        await turn.events.put(
                            HarnessEvent(
                                event_type=event_type,
                                payload=event,
                            )
                        )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Persistent reader error: %s", e)

        if session.current_turn and not session.current_turn.done.is_set():
            session.current_turn.status = HarnessResultStatus.FAILED
            session.current_turn.error = "Process exited unexpectedly"
            session.current_turn.done.set()

    async def _kill_process(self, session: _PersistentSession) -> None:
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
            if session.process and session.process.stdin and session.process.returncode is None:
                try:
                    end_msg = json.dumps({"type": "end_session"}) + "\n"
                    session.process.stdin.write(end_msg.encode())
                    await session.process.stdin.drain()
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            await self._kill_process(session)
        self._sessions.clear()

    async def _extract_skill_archives(self, container_id: str, archives: list) -> None:
        for archive in archives:
            target_dir = f"/workspace/.claude/{archive.target}"
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    "-i",
                    container_id,
                    "sh",
                    "-c",
                    f"mkdir -p {target_dir}/{archive.name} && tar xzf - -C {target_dir}/{archive.name}",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate(input=archive.data)
                if proc.returncode != 0:
                    logger.warning(
                        "Failed to extract skill %s: %s",
                        archive.name,
                        stderr.decode() if stderr else "unknown error",
                    )
            except Exception as e:
                logger.warning("Failed to extract skill %s: %s", archive.name, e)
