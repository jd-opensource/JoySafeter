"""
OpenAPI Graph Service — core business logic.

Responsibilities:
- Start graph background execution (run)
- Query execution status (status)
- Abort execution (abort)
- Get execution result (result)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain.messages import AIMessage, HumanMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.database import AsyncSessionLocal
from app.models.graph_execution import ExecutionStatus, GraphExecution
from app.repositories.graph import GraphRepository
from app.repositories.graph_execution import GraphExecutionRepository
from app.services.graph_service import GraphService
from app.utils.task_manager import task_manager

from .base import BaseService


class OpenApiGraphService(BaseService):
    """OpenAPI graph execution service."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.exec_repo = GraphExecutionRepository(db)
        self.graph_repo = GraphRepository(db)

    async def run_graph(
        self,
        *,
        graph_id: uuid.UUID,
        user_id: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start graph execution (background async).

        Returns:
            {"executionId": str, "status": str}
        """
        # verify graph exists
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        # create execution record
        execution = GraphExecution(
            graph_id=graph_id,
            user_id=user_id,
            status=ExecutionStatus.INIT,
            input_variables=variables or {},
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)

        execution_id = execution.id
        logger.info(f"[OpenAPI] Graph execution created | execution_id={execution_id} graph_id={graph_id}")

        # start background execution task
        asyncio.create_task(
            self._execute_graph_background(
                execution_id=execution_id,
                graph_id=graph_id,
                user_id=user_id,
                variables=variables or {},
            )
        )

        return {
            "executionId": str(execution_id),
            "status": ExecutionStatus.INIT.value,
        }

    async def _execute_graph_background(
        self,
        execution_id: uuid.UUID,
        graph_id: uuid.UUID,
        user_id: str,
        variables: Dict[str, Any],
    ) -> None:
        """Execute graph in background (using an independent DB session)."""
        try:
            async with AsyncSessionLocal() as db:
                # update status to executing
                exec_repo = GraphExecutionRepository(db)
                execution = await exec_repo.get(execution_id)
                if not execution:
                    return

                execution.status = ExecutionStatus.EXECUTING
                execution.started_at = datetime.now(timezone.utc)
                await db.commit()

                # compile graph
                graph_service = GraphService(db)
                compiled_graph = await graph_service.create_graph_by_graph_id(
                    graph_id=graph_id,
                    user_id=user_id,
                )

                # build input messages
                # if variables contains a message field, use it as the user message
                user_message = variables.pop("message", "")
                if not user_message:
                    user_message = variables.pop("query", "Execute task")

                initial_context = {}
                # put remaining variables into context
                for key, value in variables.items():
                    initial_context[key] = value

                # also load graph.variables.context
                graph_model = await GraphRepository(db).get(graph_id)
                if graph_model and graph_model.variables:
                    context_vars = graph_model.variables.get("context", {})
                    for key, value in context_vars.items():
                        if key not in initial_context:  # variables take precedence
                            if isinstance(value, dict) and "value" in value:
                                initial_context[key] = value["value"]
                            else:
                                initial_context[key] = value

                # configuration
                thread_id = f"openapi_{execution_id}"
                from langchain_core.runnables.config import RunnableConfig

                config: RunnableConfig = {
                    "configurable": {"thread_id": thread_id, "user_id": user_id},
                    "recursion_limit": 150,
                }

                # register with task_manager to support abort
                invoke_task = asyncio.create_task(
                    compiled_graph.ainvoke(
                        {"messages": [HumanMessage(content=user_message)], "context": initial_context},
                        config=config,
                    )
                )
                await task_manager.register_task(thread_id, invoke_task)

                try:
                    result = await invoke_task
                except asyncio.CancelledError:
                    # aborted by user
                    execution = await exec_repo.get(execution_id)
                    if execution:
                        execution.status = ExecutionStatus.FAILED
                        execution.error_message = "Execution aborted by user"
                        execution.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                    return
                finally:
                    await task_manager.unregister_task(thread_id)

                # extract result
                messages = result.get("messages", [])
                last_ai_msg = next(
                    (m for m in reversed(messages) if isinstance(m, AIMessage)),
                    None,
                )

                output_data: Dict[str, Any] = {}
                if last_ai_msg:
                    output_data["content"] = str(last_ai_msg.content) if last_ai_msg.content else ""
                    if hasattr(last_ai_msg, "tool_calls") and last_ai_msg.tool_calls:
                        output_data["tool_calls"] = [
                            {
                                "name": tc.get("name"),
                                "args": tc.get("args"),
                            }
                            for tc in last_ai_msg.tool_calls
                        ]

                # update execution record
                execution = await exec_repo.get(execution_id)
                if execution:
                    execution.status = ExecutionStatus.FINISH
                    execution.output = output_data
                    execution.finished_at = datetime.now(timezone.utc)
                    await db.commit()

                logger.info(f"[OpenAPI] Graph execution completed | execution_id={execution_id}")

        except Exception as e:
            logger.error(f"[OpenAPI] Graph execution failed | execution_id={execution_id} error={e}")
            try:
                async with AsyncSessionLocal() as db:
                    exec_repo = GraphExecutionRepository(db)
                    execution = await exec_repo.get(execution_id)
                    if execution:
                        execution.status = ExecutionStatus.FAILED
                        execution.error_message = str(e)[:2000]
                        execution.finished_at = datetime.now(timezone.utc)
                        await db.commit()
            except Exception as inner_e:
                logger.error(f"[OpenAPI] Failed to update execution status: {inner_e}")

    async def get_status(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Dict[str, Any]:
        """Get execution status."""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        return {
            "executionId": str(execution.id),
            "graphId": str(execution.graph_id),
            "status": execution.status.value,
            "startedAt": execution.started_at.isoformat() if execution.started_at else None,
            "finishedAt": execution.finished_at.isoformat() if execution.finished_at else None,
            "errorMessage": execution.error_message,
        }

    async def abort_execution(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Dict[str, Any]:
        """Abort execution."""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        if execution.status != ExecutionStatus.EXECUTING:
            raise BadRequestException(f"Cannot abort execution with status: {execution.status.value}")

        # stop the task via task_manager
        thread_id = f"openapi_{execution_id}"
        stopped = await task_manager.stop_task(thread_id)
        if stopped:
            await task_manager.cancel_task(thread_id)

        # update status
        execution.status = ExecutionStatus.FAILED
        execution.error_message = "Aborted by user"
        execution.finished_at = datetime.now(timezone.utc)
        await self.db.commit()

        return {
            "executionId": str(execution.id),
            "graphId": str(execution.graph_id),
            "status": execution.status.value,
        }

    async def get_result(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Dict[str, Any]:
        """Get execution result."""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        return {
            "executionId": str(execution.id),
            "graphId": str(execution.graph_id),
            "status": execution.status.value,
            "output": execution.output,
            "errorMessage": execution.error_message,
            "startedAt": execution.started_at.isoformat() if execution.started_at else None,
            "finishedAt": execution.finished_at.isoformat() if execution.finished_at else None,
        }
