from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger

from .base import CLIMessage, CLIResult, RuntimeSession
from .container_bridge import ContainerProcessBridge


class OpenClawProvider:
    """Runtime provider for OpenClaw CLI.

    OpenClaw outputs NDJSON events on *stderr* (not stdout).  We spawn
    ``openclaw agent --local --json --session-id <id> --message <prompt>``
    and read stderr line-by-line.

    Event types (from the wire protocol):
      text, tool_use, tool_result, error, lifecycle, step_start, step_finish
    """

    provider_type = "openclaw"

    def __init__(self, executable_path: str = "openclaw") -> None:
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
        session_id = resume_session_id or f"joysafeter-{int(time.time() * 1e9)}"

        cmd = [
            self.executable_path,
            "agent",
            "--local",
            "--json",
            "--session-id",
            session_id,
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--message", prompt])

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
            self._drain(process, queue, result_future, session_id, timeout),
            name=f"openclaw-drain-{container_id[:12]}",
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

    # ── drain loop ──────────────────────────────────────────────────────

    async def _drain(
        self,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[CLIMessage | None],
        result_future: asyncio.Future[CLIResult],
        session_id: str,
        timeout: int,
    ) -> None:
        accumulated_text: list[str] = []
        final_status = "completed"
        final_error = ""
        final_error_payload: dict[str, Any] | None = None

        try:
            async with asyncio.timeout(timeout):
                # OpenClaw writes JSON events to stderr
                assert process.stderr is not None
                async for raw_line in process.stderr:
                    line = raw_line.decode().strip()
                    if not line:
                        continue

                    for msg in self._parse_line(line):
                        if msg.type == "text":
                            accumulated_text.append(msg.content)
                        if msg.type == "error":
                            final_status = "failed"
                            final_error = msg.content
                            final_error_payload = msg.error_payload
                        await queue.put(msg)

        except TimeoutError:
            if not result_future.done():
                result_future.set_result(
                    CLIResult(
                        status="timeout",
                        error="OpenClaw agent timed out",
                        error_payload={
                            "code": "OPENCLAW_AGENT_TIMEOUT",
                            "message": "OpenClaw agent timed out",
                            "data": {"session_id": session_id},
                            "source": "runtime",
                            "retryable": True,
                        },
                        session_id=session_id,
                    )
                )
        except Exception as e:
            logger.error(f"OpenClaw drain error: {e}")
            if not result_future.done():
                result_future.set_result(
                    CLIResult(
                        status="failed",
                        error=str(e),
                        error_payload={
                            "code": "OPENCLAW_AGENT_DRAIN_FAILED",
                            "message": str(e),
                            "data": {"session_id": session_id},
                            "source": "runtime",
                            "retryable": False,
                        },
                        session_id=session_id,
                    )
                )
        finally:
            if not result_future.done():
                exit_code = await process.wait()
                if final_status == "failed":
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            output="\n".join(accumulated_text),
                            error=final_error,
                            error_payload=final_error_payload,
                            session_id=session_id,
                        )
                    )
                elif exit_code == 0 or accumulated_text:
                    result_future.set_result(
                        CLIResult(
                            status="completed",
                            output="\n".join(accumulated_text),
                            session_id=session_id,
                        )
                    )
                else:
                    stdout_bytes = await process.stdout.read() if process.stdout else b""
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            error=f"Exit code {exit_code}: {stdout_bytes.decode()[:2000]}",
                            error_payload={
                                "code": "OPENCLAW_AGENT_EXIT_FAILED",
                                "message": f"Exit code {exit_code}: {stdout_bytes.decode()[:2000]}",
                                "data": {"session_id": session_id, "exit_code": exit_code},
                                "source": "runtime",
                                "retryable": False,
                            },
                            session_id=session_id,
                        )
                    )
            await queue.put(None)

    # ── event parsing (testable without Docker) ─────────────────────────

    def _parse_line(self, line: str) -> list[CLIMessage]:
        """Parse a single stderr line into CLIMessage list.

        Non-JSON lines (plain log output) are silently skipped.
        """
        if not line or line[0] != "{":
            return []

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return []

        if not isinstance(event, dict) or "type" not in event:
            return []

        return self._parse_event(event)

    def _parse_event(self, event: dict) -> list[CLIMessage]:
        """Map an OpenClaw NDJSON event to CLIMessage(s)."""
        event_type = event.get("type", "")

        if event_type == "text":
            text = event.get("text", "")
            if text:
                return [CLIMessage(type="text", content=text)]
            return []

        if event_type == "tool_use":
            input_data = event.get("input")
            if isinstance(input_data, str):
                try:
                    input_data = json.loads(input_data)
                except json.JSONDecodeError:
                    input_data = None
            return [
                CLIMessage(
                    type="tool_use",
                    tool=event.get("tool", ""),
                    call_id=event.get("callId", ""),
                    input=input_data if isinstance(input_data, dict) else None,
                )
            ]

        if event_type == "tool_result":
            return [
                CLIMessage(
                    type="tool_result",
                    tool=event.get("tool", ""),
                    call_id=event.get("callId", ""),
                    output=event.get("text", ""),
                )
            ]

        if event_type == "error":
            error_payload = _extract_error_payload(event)
            return [CLIMessage(type="error", content=error_payload["message"], error_payload=error_payload)]

        if event_type == "lifecycle":
            phase = event.get("phase", "")
            if phase in ("error", "failed", "cancelled"):
                error_payload = _extract_error_payload(event)
                return [CLIMessage(type="error", content=error_payload["message"], error_payload=error_payload)]
            return []

        if event_type == "step_start":
            return [CLIMessage(type="text", content="[step started]")]

        if event_type == "step_finish":
            return [CLIMessage(type="text", content="[step finished]")]

        # Unknown event type — skip
        return []


def _extract_error_payload(event: dict) -> dict[str, Any]:
    """Extract canonical error payload from an OpenClaw event."""
    err_obj = event.get("error")
    if isinstance(err_obj, dict):
        code = err_obj.get("code") or event.get("code") or "OPENCLAW_AGENT_ERROR"
        data = err_obj.get("data") if isinstance(err_obj.get("data"), dict) else None
        if err_obj.get("message"):
            return {
                "code": str(code),
                "message": str(err_obj["message"]),
                "data": data,
                "source": "runtime",
                "retryable": False,
            }
        if isinstance(data, dict) and data.get("message"):
            return {
                "code": str(code),
                "message": str(data["message"]),
                "data": data,
                "source": "runtime",
                "retryable": False,
            }
        if err_obj.get("name"):
            return {
                "code": str(code),
                "message": str(err_obj["name"]),
                "data": data,
                "source": "runtime",
                "retryable": False,
            }

    if event.get("text"):
        return {
            "code": str(event.get("code") or "OPENCLAW_AGENT_ERROR"),
            "message": str(event["text"]),
            "data": None,
            "source": "runtime",
            "retryable": False,
        }
    if event.get("message"):
        return {
            "code": str(event.get("code") or "OPENCLAW_AGENT_ERROR"),
            "message": str(event["message"]),
            "data": None,
            "source": "runtime",
            "retryable": False,
        }

    return {
        "code": str(event.get("code") or "OPENCLAW_AGENT_ERROR"),
        "message": "unknown openclaw error",
        "data": None,
        "source": "runtime",
        "retryable": False,
    }
