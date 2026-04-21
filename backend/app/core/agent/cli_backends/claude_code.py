from __future__ import annotations

import asyncio
import json

from loguru import logger

from .base import CLIMessage, CLIResult, RuntimeSession
from .container_bridge import ContainerProcessBridge


class ClaudeCodeProvider:
    provider_type = "claude_code"

    def __init__(self, executable_path: str = "claude"):
        self.executable_path = executable_path
        self.bridge = ContainerProcessBridge()

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
        cmd = [
            self.executable_path,
            "-p",
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            "200",
            "--permission-mode",
            "bypassPermissions" if auto_approve else "default",
        ]
        if model:
            cmd.extend(["--model", model])
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])

        process = await self.bridge.exec_streaming(
            container_id,
            cmd,
            env=env,
            workdir=cwd,
        )
        logger.info(f"[claude] docker exec started for container {container_id[:12]}, pid={process.pid}")

        # Send the initial prompt via stdin as stream-json (not --print)
        if not resume_session_id and process.stdin:
            user_msg = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                },
            })
            process.stdin.write(f"{user_msg}\n".encode())
            await process.stdin.drain()
            logger.info(f"[claude] Sent initial prompt via stdin ({len(prompt)} chars)")

        queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue(maxsize=512)
        loop = asyncio.get_event_loop()
        result_future: asyncio.Future[CLIResult] = loop.create_future()

        drain_task = asyncio.create_task(
            self._drain(process, queue, result_future, timeout),
            name=f"claude-drain-{container_id[:12]}",
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

    async def _drain(
        self,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[CLIMessage | None],
        result_future: asyncio.Future[CLIResult],
        timeout: int,
    ) -> None:
        accumulated_text: list[str] = []
        session_id = ""
        usage: dict = {}
        is_error = False

        try:
            async with asyncio.timeout(timeout):
                assert process.stdout is not None
                logger.info(f"[claude] Drain loop started, reading stdout...")
                async for raw_line in process.stdout:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(f"[claude] Non-JSON line from stdout: {line[:200]}")
                        continue

                    if not isinstance(event, dict):
                        continue

                    event_type = event.get("type", "unknown")
                    logger.info(f"[claude] Received event: type={event_type}")

                    for msg in self._parse_event(event):
                        if msg.type == "text":
                            accumulated_text.append(msg.content)
                        await queue.put(msg)

                    if event.get("type") == "result":
                        result_data = event.get("result", {})
                        if isinstance(result_data, dict):
                            session_id = result_data.get("session_id", "")
                        if "usage" in event:
                            usage = event["usage"]
                        if event.get("is_error"):
                            is_error = True
                        # result received — close stdin so the process exits cleanly
                        if process.stdin and not process.stdin.is_closing():
                            process.stdin.close()
                        break

        except TimeoutError:
            if not result_future.done():
                result_future.set_result(CLIResult(status="timeout", error="Agent timed out"))
        except Exception as e:
            logger.error(f"Claude drain error: {e}")
            if not result_future.done():
                result_future.set_result(CLIResult(status="failed", error=str(e)))
        finally:
            if not result_future.done():
                exit_code = await process.wait()
                if is_error:
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            output="\n".join(accumulated_text),
                            error="\n".join(accumulated_text) or "Claude Code reported an error",
                            session_id=session_id,
                            usage=usage,
                        )
                    )
                elif exit_code == 0 or accumulated_text:
                    result_future.set_result(
                        CLIResult(
                            status="completed",
                            output="\n".join(accumulated_text),
                            session_id=session_id,
                            usage=usage,
                        )
                    )
                else:
                    stderr_bytes = await process.stderr.read() if process.stderr else b""
                    result_future.set_result(
                        CLIResult(
                            status="failed",
                            error=f"Exit code {exit_code}: {stderr_bytes.decode()[:2000]}",
                            usage=usage,
                        )
                    )
            await queue.put(None)

    def _parse_event(self, event: dict) -> list[CLIMessage]:
        messages: list[CLIMessage] = []
        event_type = event.get("type", "")

        if event_type == "assistant" and "message" in event:
            msg = event["message"]
            for block in msg.get("content", []) if isinstance(msg, dict) else []:
                if isinstance(block, str):
                    messages.append(CLIMessage(type="text", content=block))
                    continue
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    messages.append(CLIMessage(type="text", content=block.get("text", "")))
                elif block_type == "tool_use":
                    messages.append(
                        CLIMessage(
                            type="tool_use",
                            tool=block.get("name", ""),
                            call_id=block.get("id", ""),
                            input=block.get("input"),
                        )
                    )
                elif block_type == "thinking":
                    messages.append(CLIMessage(type="thinking", content=block.get("thinking", "")))

        elif event_type == "tool_result":
            messages.append(
                CLIMessage(
                    type="tool_result",
                    tool=event.get("tool", ""),
                    call_id=event.get("call_id", ""),
                    output=str(event.get("output", ""))[:8192],
                )
            )

        elif event_type == "control_request":
            request = event.get("request", {})
            messages.append(
                CLIMessage(
                    type="approval_request",
                    tool=request.get("tool_name", ""),
                    call_id=event.get("request_id", ""),
                    input=request.get("input"),
                    content=request.get("subtype", ""),
                )
            )

        return messages
