"""
ExecutionRunner — end-to-end orchestrator for CLI agent executions.

Lifecycle:
  1. Get or create container (from pool)
  2. Inject credentials, skills, and CLAUDE.md config
  3. Execute via RuntimeProvider (with session resume if available)
  4. Drain messages → append as ExecutionEvents
  5. Mark final status, store session_id back to pool
  6. Release container back to pool (NOT destroyed)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from app.joysafeter_shared.common.app_errors import normalize_app_error
from app.joysafeter_domain.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession, build_control_response
from app.joysafeter_domain.agent.cli_backends.container_pool import container_pool
from app.joysafeter_domain.agent.cli_backends.container_service import (
    CLIContainerService,
    ContainerConfig,
    ContainerInfo,
)
from app.joysafeter_domain.agent.cli_backends.injectors import (
    CLISkillInjector,
    RuntimeConfigInjector,
)
from app.joysafeter_domain.agent.cli_backends.registry import runtime_registry
from app.joysafeter_domain.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.joysafeter_domain.agent.cli_backends.session_registry import session_registry
from app.joysafeter_worker.events.event_types import ExecutionEventType
from app.joysafeter_shared.observation.types import ObservationLevel
from app.joysafeter_domain.ports.execution import EventContext, ExecutionEventPort, ExecutionReaderPort

if TYPE_CHECKING:
    from app.joysafeter_domain.models.agent import AgentRelease


class ExecutionRunner:
    """Orchestrates the full lifecycle of a CLI agent execution."""

    def __init__(
        self,
        event_port: ExecutionEventPort,
        reader_port: ExecutionReaderPort,
        container_service: Optional[CLIContainerService] = None,
        callbacks: Optional[RunnerCallbacks] = None,
    ):
        self._events = event_port
        self._reader = reader_port
        self.container_service = container_service or CLIContainerService()
        self.callbacks = callbacks
        self._auto_approve: bool = True
        self._session: Optional[RuntimeSession] = None

    async def run(
        self,
        *,
        execution_id: uuid.UUID,
        prompt: str,
        credentials: Optional[dict[str, str]] = None,
        skills: Optional[list[dict[str, Any]]] = None,
        container_config: Optional[ContainerConfig] = None,
        model: Optional[str] = None,
        timeout: int = 7200,
        collector: Any = None,
    ) -> CLIResult:
        """Run a full execution lifecycle.

        Returns the final CLIResult after the agent completes or fails.
        """
        container: Optional[ContainerInfo] = None
        execution = await self._reader.get_execution(execution_id)
        run = await self._reader.get_run_for_execution(execution_id)
        release = await self._reader.get_release_for_run(run.id)
        thread_id = run.thread_id

        # Inject run metadata so events route through the bus
        self._events.set_event_context(
            EventContext(
                run_id=run.id,
                project_id=run.project_id or "",
                trigger_medium=run.trigger_medium,
                run_purpose=run.run_purpose,
                thread_id=run.thread_id,
                task_id=run.task_id,
            )
        )

        logger.info(
            f"[exec:{execution_id}] Starting execution "
            f"(thread={thread_id}, release={release.id if release else 'draft'}, "
            f"engine={execution.engine_kind})"
        )

        try:
            # 1. Mark as dispatched
            await self._events.mark_status(execution_id=execution_id, status="dispatched")

            # 2. Acquire container from the thread-keyed pool.
            #    The pool handles adopt / provision / LRU internally; we only
            #    supply a create_fn for the provisioning path.
            async def _create_container() -> ContainerInfo:
                logger.info(f"[exec:{execution_id}] Creating new container for thread {thread_id}")
                return await self.container_service.create_container(
                    execution_id=execution_id,
                    config=container_config,
                    env=credentials,
                )

            container, prior_session_id = await container_pool.acquire(thread_id, _create_container)

            if prior_session_id:
                logger.info(
                    f"[exec:{execution_id}] Reusing container "
                    f"{container.container_id[:12]} with session {prior_session_id}"
                )

            await self._events.mark_status(
                execution_id=execution_id, status="running", container_id=container.container_id
            )

            # 3. Inject skills and config (idempotent — safe to re-run on reuse)
            await self._inject(
                container_id=container.container_id,
                skills=skills,
                release=release,
                working_dir=container.working_dir,
            )

            # 4. Record execution_started event
            await self._events.append_event(
                execution_id=execution_id,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                payload={
                    "container_id": container.container_id,
                    "engine_kind": execution.engine_kind,
                    "reused": prior_session_id is not None,
                },
            )

            # 5. Execute via provider (with session resume + credentials).
            #    If the provider reports its --resume session is invalid, we
            #    rebuild the prompt from thread history and retry once without
            #    --resume. This recovers the Agent's memory across CLI-side
            #    session loss (e.g., container restart, TTL expiry).
            provider = runtime_registry.get(execution.engine_kind)

            # Determine auto_approve from task settings
            if run.task_id:
                self._auto_approve = await self._reader.get_task_auto_approve(run.task_id)
            else:
                self._auto_approve = True

            # First attempt (may --resume the prior CLI session)
            result = await self._run_one_attempt(
                execution=execution,
                prompt=prompt,
                container=container,
                model=model,
                timeout=timeout,
                resume_session_id=prior_session_id,
                credentials=credentials,
                collector=collector,
                provider=provider,
            )

            # Recovery: if the resume was rejected, rebuild the prompt from
            # thread history and retry once without --resume. One retry, no
            # loop — the outer `finally` releases the container exactly once.
            if result.session_invalid and prior_session_id:
                logger.warning(
                    f"[exec:{execution_id}] CLI session {prior_session_id} invalid; "
                    "rebuilding prompt from thread history and retrying without --resume"
                )
                await container_pool.store_session(run.thread_id, "")
                if collector is not None:
                    try:
                        collector.record_event(
                            "cli_session_recovered",
                            input={"previous_session_id": prior_session_id},
                            level=ObservationLevel.WARNING,
                        )
                    except Exception as exc:
                        logger.warning(f"[exec:{execution_id}] collector.record_event failed: {exc}")

                history = await self._reader.load_thread_history(run.thread_id, before_run_id=run.id)
                rebuilt_prompt = _rebuild_prompt(history, prompt)
                session_registry.unregister(execution_id)
                # NOTE: container remains acquired — the retry reuses the
                # same slot and the outer `finally` still releases it once.
                result = await self._run_one_attempt(
                    execution=execution,
                    prompt=rebuilt_prompt,
                    container=container,
                    model=model,
                    timeout=timeout,
                    resume_session_id=None,
                    credentials=credentials,
                    collector=collector,
                    provider=provider,
                )

            # 8. Mark final status
            await self._finalize(execution_id, result, release)

            # 9. Store session_id so the next turn on this thread can --resume
            if result.session_id:
                await container_pool.store_session(thread_id, result.session_id)
                logger.info(f"[exec:{execution_id}] Stored session {result.session_id} for thread {thread_id}")

            return result

        except Exception as exc:
            logger.error(f"[exec:{execution_id}] ExecutionRunner error: {exc}")
            await self._mark_failed(execution_id, str(exc))
            app_error = normalize_app_error(
                exc,
                default_code="CLI_EXECUTION_RUNNER_FAILED",
                default_message="CLI execution runner failed",
                default_data={"execution_id": str(execution_id)},
            )
            return CLIResult(status="failed", error=app_error.message, error_payload=app_error.to_payload())

        finally:
            # 10. Unregister session; release the slot back to the pool.
            #     The container is kept alive for the next turn on this thread.
            session_registry.unregister(execution_id)
            if container:
                await container_pool.release(thread_id)

    async def _inject(
        self,
        *,
        container_id: str,
        skills: Optional[list[dict[str, Any]]],
        release: Optional[AgentRelease],
        working_dir: str,
    ) -> None:
        skill_injector = CLISkillInjector(self.container_service)
        config_injector = RuntimeConfigInjector(self.container_service)

        if skills:
            await skill_injector.inject(container_id, skills)

        # Pull instructions from release runtime_binding if present
        instructions = release.runtime_binding.get("instructions") if release else None
        skill_names = None
        if skills:
            skill_names = [s.get("name", "") for s in skills if s.get("name")]

        await config_injector.inject(
            container_id,
            instructions=instructions,
            skill_names=skill_names,
            working_dir=working_dir,
        )

    _DRAIN_BATCH_SIZE = 5
    _DRAIN_FLUSH_INTERVAL = 0.5  # seconds — flush at least every 500ms

    async def _run_one_attempt(
        self,
        *,
        execution: Any,
        prompt: str,
        container: ContainerInfo,
        model: Optional[str],
        timeout: int,
        resume_session_id: Optional[str],
        credentials: Optional[dict[str, str]],
        collector: Any,
        provider: Any,
    ) -> CLIResult:
        """Single provider.execute + drain + await-result cycle.

        Extracted so the outer :meth:`run` can express "first try → recover
        → retry" as straight-line code rather than a two-iteration loop.
        """
        session = await provider.execute(
            prompt,
            container_id=container.container_id,
            cwd=container.working_dir,
            model=model,
            timeout=timeout,
            resume_session_id=resume_session_id,
            env=credentials,
            auto_approve=self._auto_approve,
        )
        session_registry.register(execution.id, session)
        self._session = session

        await self._drain_to_events(execution.id, collector=collector, engine_kind=execution.engine_kind)
        result: CLIResult = await session.result
        return result

    async def _drain_to_events(
        self,
        execution_id: uuid.UUID,
        *,
        collector: Any = None,
        engine_kind: str = "cli",
    ) -> None:
        assert self._session is not None, "_drain_to_events called before session was set"
        pending: list[tuple[CLIMessage, str, dict[str, Any]]] = []
        logger.info(f"[exec:{execution_id}] _drain_to_events started")
        queue = self._session.messages

        # Observation: set up root span + extractor if collector is set
        root_span = None
        extractor = None
        if collector:
            from app.joysafeter_shared.observation.instrumentation.cli_extractor import CLIObservationExtractor

            root_span = collector.start_agent(name=f"cli:{engine_kind}")
            extractor = CLIObservationExtractor(collector, root_span)

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=self._DRAIN_FLUSH_INTERVAL)
            except asyncio.TimeoutError:
                # Timeout — flush whatever we have so far
                if pending:
                    await self._flush_pending(execution_id, pending)
                    pending.clear()
                continue

            if msg is None:
                break

            # Observation: process message through extractor
            if extractor:
                try:
                    await extractor.process_message(msg)
                except Exception as obs_exc:
                    logger.debug(f"[exec:{execution_id}] Observation extractor error: {obs_exc}")

            event_type = self._msg_to_event_type(msg)
            payload = self._msg_to_payload(msg)
            pending.append((msg, event_type, payload))

            needs_flush = len(pending) >= self._DRAIN_BATCH_SIZE or msg.type == "approval_request"
            if needs_flush:
                await self._flush_pending(execution_id, pending)
                pending.clear()

        if pending:
            await self._flush_pending(execution_id, pending)

        # Observation: flush pending and close root span
        if extractor:
            try:
                await extractor.flush_pending()
            except Exception as obs_exc:
                logger.debug(f"[exec:{execution_id}] Observation extractor flush error: {obs_exc}")
        if root_span:
            try:
                await root_span.end(output={"status": "completed"})
            except Exception:
                pass

        logger.info(f"[exec:{execution_id}] _drain_to_events finished")

    async def _flush_pending(
        self,
        execution_id: uuid.UUID,
        pending: list[tuple[CLIMessage, str, dict[str, Any]]],
    ) -> None:
        try:
            await self._events.batch_append_events(
                execution_id=execution_id,
                events=[{"event_type": event_type, "payload": payload} for _, event_type, payload in pending],
            )
            for msg, _, payload in pending:
                if msg.type == "approval_request":
                    if self._auto_approve:
                        request_id = payload.get("request_id", "")
                        assert self._session is not None
                        await self._session.inject_message(build_control_response(request_id, "allow"))
                        await self._events.append_event(
                            execution_id=execution_id,
                            event_type=ExecutionEventType.APPROVAL_RESOLVED,
                            payload={"decision": "auto_approved", "request_id": request_id},
                        )
                    else:
                        await self._events.mark_status(execution_id=execution_id, status="approval_wait")
                    break
        except Exception as exc:
            logger.warning(f"Failed to flush {len(pending)} events for {execution_id}: {exc}")

    async def _finalize(
        self,
        execution_id: uuid.UUID,
        result: CLIResult,
        release: Optional[AgentRelease],
    ) -> None:
        status = "succeeded" if result.status == "completed" else "failed"

        await self._events.complete_execution(
            execution_id=execution_id,
            terminal_status=status,
            result_summary=result.usage,
            error=result.error_payload or _build_completion_error(result.error),
            session_id=result.session_id,
        )

        if self.callbacks:
            try:
                await self.callbacks.on_execution_finalized(execution_id, status, result)
            except Exception as exc:
                logger.warning(f"Callback on_execution_finalized failed for {execution_id}: {exc}")

    async def _mark_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        try:
            error_payload = _build_completion_error(error[:2000])
            await self._events.append_event(
                execution_id=execution_id,
                event_type=ExecutionEventType.ERROR,
                payload=error_payload
                or {
                    "code": "EXECUTION_FAILED",
                    "message": error,
                    "data": None,
                    "source": "runtime",
                    "retryable": False,
                },
            )
            await self._events.complete_execution(
                execution_id=execution_id,
                terminal_status="failed",
                error=error_payload,
            )
        except Exception as exc:
            logger.error(f"Failed to mark execution {execution_id} as failed: {exc}")

        if self.callbacks:
            try:
                await self.callbacks.on_execution_failed(execution_id, error)
            except Exception as exc:
                logger.warning(f"Callback on_execution_failed failed for {execution_id}: {exc}")

    @staticmethod
    def _msg_to_event_type(msg: CLIMessage) -> ExecutionEventType:
        mapping = {
            "text": ExecutionEventType.ASSISTANT_TEXT,
            "thinking": ExecutionEventType.THINKING,
            "tool_use": ExecutionEventType.TOOL_USE_START,
            "tool_result": ExecutionEventType.TOOL_USE_END,
            "error": ExecutionEventType.ERROR,
            "artifact": ExecutionEventType.ARTIFACT_CREATED,
            "approval_request": ExecutionEventType.APPROVAL_REQUESTED,
        }
        return mapping.get(msg.type) or ExecutionEventType(msg.type)

    @staticmethod
    def _msg_to_payload(msg: CLIMessage) -> dict[str, Any]:
        if msg.type == "text":
            return {"content": msg.content}
        if msg.type == "thinking":
            return {"content": msg.content}
        if msg.type == "tool_use":
            return {
                "tool": {
                    "name": msg.tool,
                    "call_id": msg.call_id,
                    "input": msg.input,
                    "status": "running",
                },
            }
        if msg.type == "tool_result":
            return {
                "call_id": msg.call_id,
                "tool_name": msg.tool,
                "output": msg.output,
            }
        if msg.type == "error":
            return msg.error_payload or {
                "code": "EXECUTION_FAILED",
                "message": msg.content,
                "data": None,
                "source": "runtime",
                "retryable": False,
            }
        if msg.type == "artifact":
            return {"artifact": {"content": msg.content}}
        if msg.type == "approval_request":
            return {
                "request_id": msg.call_id,
                "subtype": msg.content,
                "tool_name": msg.tool,
                "input": msg.input,
                "message": f"Agent wants to use: {msg.tool or 'unknown tool'}",
            }
        return {"content": msg.content}


def _build_completion_error(message: str | None) -> dict[str, Any] | None:
    if not message:
        return None

    return {
        "code": "EXECUTION_FAILED",
        "message": message,
        "data": None,
        "source": "runtime",
        "retryable": False,
    }


def _rebuild_prompt(history: list[tuple[str, str]], current_prompt: str) -> str:
    """Collapse prior ``(role, content)`` turns into a prefix before the new prompt.

    Raw-text concatenation (the user-approved strategy). Long sessions will
    consume more tokens on recovery, but correctness is preserved and no
    external summariser is needed.
    """
    if not history:
        return current_prompt

    lines: list[str] = [
        "Earlier conversation (CLI session was reset; context is replayed below to restore continuity):",
        "",
    ]
    for role, content in history:
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {content}")
        lines.append("")
    lines.append("Continue the conversation with the following new user message:")
    lines.append("")
    lines.append(current_prompt)
    return "\n".join(lines)
