"""
Tracking Event Queue Processor.

This module processes tracking events from the queue and persists them to the database.
It runs in the main event loop and handles start/end event matching.
"""

import asyncio
import time
from typing import Dict, Optional
from uuid import UUID

from loguru import logger

from app.dynamic_agent.observability.tracking_events import (
    ChatModelEndEvent,
    ChatModelStartEvent,
    LLMEndEvent,
    LLMStartEvent,
    ToolEndEvent,
    ToolErrorEvent,
    ToolStartEvent,
    TrackingEvent,
    TrackingEventType,
    get_tracking_queue,
)
from app.dynamic_agent.storage.models import ExecutionStepStatus, ExecutionStepType
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO


class TrackingEventProcessor:
    """
    Processes tracking events from the queue and persists to database.

    This class runs in the main event loop and:
    1. Receives events from the queue
    2. Matches start/end events
    3. Persists data to database using the provided TaskDAO
    """

    def __init__(self, task_dao: TaskDAO, batch_size: int = 100, flush_interval: float = 1.0):
        """
        Initialize the event processor.

        Args:
            task_dao: TaskDAO instance for database operations
            batch_size: Maximum number of events to process in one batch
            flush_interval: Maximum time to wait before flushing pending events
        """
        self.task_dao = task_dao
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None

        # Track pending start events (waiting for end events)
        # Format: {step_key: (step_id, event_type)}
        self._pending_starts: Dict[str, tuple] = {}

        # Track step IDs by run_id for end events
        # Format: {step_key: step_id}
        self._step_ids: Dict[str, UUID] = {}

    async def start(self):
        """Start the event processor."""
        if self._running:
            logger.warning("[TrackingProcessor] Already running")
            return

        self._running = True
        self._processor_task = asyncio.create_task(self._process_loop())
        logger.info("[TrackingProcessor] Started event processor")

    async def stop(self):
        """Stop the event processor."""
        if not self._running:
            return

        self._running = False

        # Wait for processor to finish
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        # Process remaining events
        await self._flush_remaining()
        logger.info("[TrackingProcessor] Stopped event processor")

    async def _process_loop(self):
        """Main event processing loop."""
        queue = get_tracking_queue()

        while self._running:
            try:
                # Wait for events with timeout
                event = await asyncio.wait_for(queue.get(), timeout=self.flush_interval)

                await self._process_event(event)
                queue.task_done()

            except asyncio.TimeoutError:
                # Timeout - flush any pending start events that are old
                await self._flush_old_pending_starts()

            except asyncio.CancelledError:
                logger.info("[TrackingProcessor] Processing loop cancelled")
                break

            except Exception as e:
                logger.error(f"[TrackingProcessor] Error in processing loop: {e}", exc_info=True)

    async def _process_event(self, event: TrackingEvent):
        """Process a single tracking event."""
        try:
            if event.event_type == TrackingEventType.TOOL_START:
                await self._handle_tool_start(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.TOOL_END:
                await self._handle_tool_end(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.TOOL_ERROR:
                await self._handle_tool_error(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.LLM_START:
                await self._handle_llm_start(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.LLM_END:
                await self._handle_llm_end(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.CHAT_MODEL_START:
                await self._handle_chat_model_start(event)  # type: ignore[arg-type]

            elif event.event_type == TrackingEventType.CHAT_MODEL_END:
                await self._handle_chat_model_end(event)  # type: ignore[arg-type]

            else:
                logger.warning(f"[TrackingProcessor] Unknown event type: {event.event_type}")

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error processing event {event.event_type}: {e}", exc_info=True)

    async def _handle_tool_start(self, event: ToolStartEvent):
        """Handle tool start event."""
        if not event.task_id:
            return

        try:
            # Use pre-generated step_id if available, otherwise create new step
            if event.pre_generated_step_id:
                step = await self.task_dao.create_step_with_id(
                    step_id=event.pre_generated_step_id,
                    task_id=event.task_id,
                    step_type=ExecutionStepType.TOOL,
                    name=event.tool_name,
                    input_data=event.input_data,
                )
                logger.debug(f"[TrackingProcessor] Created step {step.id} (pre-generated) for tool {event.tool_name}")
            else:
                step = await self.task_dao.create_step(
                    task_id=event.task_id,
                    step_type=ExecutionStepType.TOOL,
                    name=event.tool_name,
                    input_data=event.input_data,
                )
                logger.debug(f"[TrackingProcessor] Created step {step.id} for tool {event.tool_name}")

            # Store step_id for matching end event
            step_key = event.step_key or f"{event.task_id}:{event.run_id}"
            self._step_ids[step_key] = step.id
            self._pending_starts[step_key] = (step.id, event.event_type, int(time.time() * 1000))

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error creating step for tool {event.tool_name}: {e}")

    async def _handle_tool_end(self, event: ToolEndEvent):
        """Handle tool end event."""
        step_key = event.step_key or f"{event.task_id}:{event.run_id}"

        if step_key not in self._step_ids:
            logger.warning(f"[TrackingProcessor] No step_id found for {step_key}")
            return

        step_id = self._step_ids[step_key]

        try:
            await self.task_dao.update_step(
                step_id=step_id,
                status=ExecutionStepStatus.COMPLETED,
                output_data=event.output_data,
            )

            # Clean up
            del self._step_ids[step_key]
            if step_key in self._pending_starts:
                del self._pending_starts[step_key]

            logger.debug(f"[TrackingProcessor] Updated step {step_id} to COMPLETED")

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error updating step {step_id}: {e}")

    async def _handle_tool_error(self, event: ToolErrorEvent):
        """Handle tool error event."""
        step_key = event.step_key or f"{event.task_id}:{event.run_id}"

        if step_key not in self._step_ids:
            logger.warning(f"[TrackingProcessor] No step_id found for {step_key}")
            return

        step_id = self._step_ids[step_key]

        try:
            await self.task_dao.update_step(
                step_id=step_id,
                status=ExecutionStepStatus.FAILED,
                error_message=event.error_message,
            )

            # Clean up
            del self._step_ids[step_key]
            if step_key in self._pending_starts:
                del self._pending_starts[step_key]

            logger.debug(f"[TrackingProcessor] Updated step {step_id} to FAILED")

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error updating step {step_id}: {e}")

    async def _handle_llm_start(self, event: LLMStartEvent):
        """Handle LLM start event."""
        if not event.task_id:
            return

        try:
            input_data = {
                "prompts": event.prompts,
                "model_name": event.model_name,
                "invocation_params": event.invocation_params,
                "prompt_count": len(event.prompts),
                "total_prompt_length": sum(len(p) for p in event.prompts),
            }

            # Use pre-generated step_id if available, otherwise create new step
            if event.pre_generated_step_id:
                step = await self.task_dao.create_step_with_id(
                    step_id=event.pre_generated_step_id,
                    task_id=event.task_id,
                    step_type=ExecutionStepType.LLM,
                    name=f"LLM Call: {event.model_name}",
                    input_data=input_data,
                )
                logger.debug(f"[TrackingProcessor] Created step {step.id} (pre-generated) for LLM {event.model_name}")
            else:
                step = await self.task_dao.create_step(
                    task_id=event.task_id,
                    step_type=ExecutionStepType.LLM,
                    name=f"LLM Call: {event.model_name}",
                    input_data=input_data,
                )
                logger.debug(f"[TrackingProcessor] Created step {step.id} for LLM {event.model_name}")

            step_key = event.step_key or f"{event.task_id}:{event.run_id}"
            self._step_ids[step_key] = step.id
            self._pending_starts[step_key] = (step.id, event.event_type, int(time.time() * 1000))

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error creating step for LLM {event.model_name}: {e}")

    async def _handle_llm_end(self, event: LLMEndEvent):
        """Handle LLM end event."""
        step_key = event.step_key or f"{event.task_id}:{event.run_id}"

        if step_key not in self._step_ids:
            logger.warning(f"[TrackingProcessor] No step_id found for {step_key}")
            return

        step_id = self._step_ids[step_key]

        try:
            await self.task_dao.update_step(
                step_id=step_id,
                status=ExecutionStepStatus.COMPLETED,
                output_data=event.output_data,
            )

            # Clean up
            del self._step_ids[step_key]
            if step_key in self._pending_starts:
                del self._pending_starts[step_key]

            logger.debug(f"[TrackingProcessor] Updated LLM step {step_id} to COMPLETED")

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error updating LLM step {step_id}: {e}")

    async def _handle_chat_model_start(self, event: ChatModelStartEvent):
        """Handle ChatModel start event."""
        if not event.task_id:
            return

        try:
            input_data = {
                "messages": event.messages_data,
                "model_name": event.model_name,
                "message_count": len(event.messages_data),
            }

            # Use pre-generated step_id if available, otherwise create new step
            if event.pre_generated_step_id:
                step = await self.task_dao.create_step_with_id(
                    step_id=event.pre_generated_step_id,
                    task_id=event.task_id,
                    step_type=ExecutionStepType.LLM,
                    name=f"LLM Call: {event.model_name}",
                    input_data=input_data,
                )
                logger.debug(
                    f"[TrackingProcessor] Created step {step.id} (pre-generated) for ChatModel {event.model_name}"
                )
            else:
                step = await self.task_dao.create_step(
                    task_id=event.task_id,
                    step_type=ExecutionStepType.LLM,
                    name=f"LLM Call: {event.model_name}",
                    input_data=input_data,
                )
                logger.debug(f"[TrackingProcessor] Created step {step.id} for ChatModel {event.model_name}")

            step_key = event.step_key or f"{event.task_id}:{event.run_id}"
            self._step_ids[step_key] = step.id
            self._pending_starts[step_key] = (step.id, event.event_type, int(time.time() * 1000))

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error creating step for ChatModel {event.model_name}: {e}")

    async def _handle_chat_model_end(self, event: ChatModelEndEvent):
        """Handle ChatModel end event."""
        step_key = event.step_key or f"{event.task_id}:{event.run_id}"

        if step_key not in self._step_ids:
            logger.warning(f"[TrackingProcessor] No step_id found for {step_key}")
            return

        step_id = self._step_ids[step_key]

        try:
            await self.task_dao.update_step(
                step_id=step_id,
                status=ExecutionStepStatus.COMPLETED,
                output_data=event.output_data,
            )

            # Clean up
            del self._step_ids[step_key]
            if step_key in self._pending_starts:
                del self._pending_starts[step_key]

            logger.debug(f"[TrackingProcessor] Updated ChatModel step {step_id} to COMPLETED")

        except Exception as e:
            logger.error(f"[TrackingProcessor] Error updating ChatModel step {step_id}: {e}")

    async def _flush_old_pending_starts(self):
        """Flush pending start events that are too old (missing end events)."""
        # This is a safety mechanism for cases where end events are lost
        # In production, you might want to mark these as FAILED instead of deleting
        current_time = time.time()
        timeout = 300  # 5 minutes

        old_keys = [
            key
            for key, (step_id, event_type, start_time) in self._pending_starts.items()
            if current_time - start_time > timeout
        ]

        for key in old_keys:
            step_id, event_type = self._pending_starts[key]
            logger.warning(f"[TrackingProcessor] Flushing old pending start: {key} (step_id={step_id})")

            # Mark as failed due to timeout
            try:
                await self.task_dao.update_step(
                    step_id=step_id,
                    status=ExecutionStepStatus.FAILED,
                    error_message="End event not received (timeout)",
                )
            except Exception as e:
                logger.error(f"[TrackingProcessor] Error flushing old step {step_id}: {e}")

            # Clean up
            del self._pending_starts[key]
            if key in self._step_ids:
                del self._step_ids[key]

    async def _flush_remaining(self):
        """Flush all remaining pending events on shutdown."""
        if self._pending_starts:
            logger.info(f"[TrackingProcessor] Flushing {len(self._pending_starts)} remaining pending events")

            for step_key, (step_id, event_type, start_time) in list(self._pending_starts.items()):
                try:
                    await self.task_dao.update_step(
                        step_id=step_id,
                        status=ExecutionStepStatus.FAILED,
                        error_message="Incomplete (processor shutdown)",
                    )
                except Exception as e:
                    logger.error(f"[TrackingProcessor] Error flushing remaining step {step_id}: {e}")

            self._pending_starts.clear()
            self._step_ids.clear()


# Global processor instance
_tracking_processor: Optional[TrackingEventProcessor] = None


def get_tracking_processor() -> Optional[TrackingEventProcessor]:
    """Get the global tracking event processor."""
    return _tracking_processor


def set_tracking_processor(processor: TrackingEventProcessor):
    """Set the global tracking event processor."""
    global _tracking_processor
    _tracking_processor = processor
