import asyncio
import logging
import uuid
from typing import Optional

from app.conductor.runtime.adapter import (
    HarnessAdapter,
    HarnessEvent,
    HarnessInput,
    HarnessResult,
    RunningHarness,
)

logger = logging.getLogger(__name__)


class MockAdapter(HarnessAdapter):
    """Mock adapter for testing without real CLI tools.

    Generates synthetic events with configurable delay and returns canned output.
    """

    def __init__(
        self,
        response_delay: float = 0.5,
        default_output: str = "Mock response from conductor test adapter.",
        simulate_events: int = 3,
    ):
        self._delay = response_delay
        self._default_output = default_output
        self._simulate_events = simulate_events

    def provider(self) -> str:
        return "mock"

    async def is_available(self) -> bool:
        return True

    async def start(self, input: HarnessInput) -> RunningHarness:
        harness = RunningHarness()
        asyncio.create_task(self._simulate(harness, input))
        return harness

    async def cancel(self, harness: RunningHarness) -> None:
        harness._done.set()

    async def send_input(self, harness: RunningHarness, content: str) -> None:
        logger.debug("MockAdapter received input: %s", content[:100])
        await harness._events.put(
            HarnessEvent(
                event_type="system",
                payload={"type": "system", "message": f"Received input: {content[:50]}"},
            )
        )

    async def _simulate(self, harness: RunningHarness, input: HarnessInput) -> None:
        session_id = input.session_id or str(uuid.uuid4())

        try:
            # Simulate initial processing
            await harness._events.put(
                HarnessEvent(
                    event_type="system",
                    payload={
                        "type": "system",
                        "subtype": "init",
                        "session_id": session_id,
                    },
                )
            )
            await asyncio.sleep(self._delay * 0.2)

            # Simulate thinking/processing events
            for i in range(self._simulate_events):
                await asyncio.sleep(self._delay / self._simulate_events)
                await harness._events.put(
                    HarnessEvent(
                        event_type="assistant",
                        payload={
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Processing step {i + 1}/{self._simulate_events}...",
                                    }
                                ]
                            },
                        },
                    )
                )

            # Simulate final result
            output = f"{self._default_output}\n\nPrompt was: {input.prompt[:200]}"
            await harness._events.put(
                HarnessEvent(
                    event_type="result",
                    payload={
                        "type": "result",
                        "result": output,
                        "session_id": session_id,
                        "usage": {
                            "input_tokens": len(input.prompt.split()) * 2,
                            "output_tokens": len(output.split()) * 2,
                        },
                    },
                )
            )

            harness._result = HarnessResult(
                output=output,
                usage={
                    "input_tokens": len(input.prompt.split()) * 2,
                    "output_tokens": len(output.split()) * 2,
                },
                session_id=session_id,
                work_dir=input.work_dir,
            )

        except asyncio.CancelledError:
            harness._result = HarnessResult(error="Cancelled")
        except Exception as e:
            harness._result = HarnessResult(error=str(e))
        finally:
            harness._done.set()
