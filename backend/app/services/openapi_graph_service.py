"""
OpenAPI Graph Service — 核心业务逻辑

负责：
- 启动 graph 后台执行 (run)
- 查询执行状态 (status)
- 中止执行 (abort)
- 获取执行结果 (result)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain.messages import AIMessage, HumanMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.database import AsyncSessionLocal
from app.core.model.utils.credential_resolver import LLMCredentialResolver
from app.models.graph_execution import ExecutionStatus, GraphExecution
from app.repositories.graph import GraphRepository
from app.repositories.graph_execution import GraphExecutionRepository
from app.services.graph_service import GraphService
from app.utils.task_manager import task_manager

from .base import BaseService


class OpenApiGraphService(BaseService):
    """OpenAPI Graph 执行服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.exec_repo = GraphExecutionRepository(db)
        self.graph_repo = GraphRepository(db)

    async def run_graph(
        self,
        *,
        graph_id: uuid.UUID,
        user_id: str,
        api_key_id: uuid.UUID,
        variables: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        启动 graph 执行（后台异步）。

        Returns:
            {"executionId": str, "status": str}
        """
        # 验证 graph 存在
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException("Graph not found")

        # 如果 API Key 是 workspace 类型，验证 graph 属于该 workspace
        if workspace_id and graph.workspace_id != workspace_id:
            raise ForbiddenException("Graph does not belong to the API key's workspace")

        # 创建执行记录
        execution = GraphExecution(
            graph_id=graph_id,
            user_id=user_id,
            api_key_id=api_key_id,
            status=ExecutionStatus.INIT,
            input_variables=variables or {},
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)

        execution_id = execution.id
        logger.info(f"[OpenAPI] Graph execution created | execution_id={execution_id} graph_id={graph_id}")

        # 启动后台执行任务
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
        """后台执行 graph（使用独立 DB session）"""
        try:
            async with AsyncSessionLocal() as db:
                # 更新状态为 executing
                exec_repo = GraphExecutionRepository(db)
                execution = await exec_repo.get(execution_id)
                if not execution:
                    return

                execution.status = ExecutionStatus.EXECUTING
                execution.started_at = datetime.now(timezone.utc)
                await db.commit()

                # 获取 LLM 凭据
                llm_params = await LLMCredentialResolver.get_llm_params(
                    db=db,
                    api_key=None,
                    base_url=None,
                    llm_model=None,
                    max_tokens=4096,
                    user_id=user_id,
                )

                # 编译 graph
                graph_service = GraphService(db)
                compiled_graph = await graph_service.create_graph_by_graph_id(
                    graph_id=graph_id,
                    llm_model=llm_params["llm_model"],
                    api_key=llm_params["api_key"],
                    base_url=llm_params["base_url"],
                    max_tokens=llm_params["max_tokens"],
                    user_id=user_id,
                )

                # 构建输入消息
                # 如果 variables 中有 message 字段，使用它作为用户消息
                user_message = variables.pop("message", "")
                if not user_message:
                    user_message = variables.pop("query", "请执行任务")

                initial_context = {}
                # 将剩余 variables 作为 context
                for key, value in variables.items():
                    initial_context[key] = value

                # 同时加载 graph.variables.context
                graph_model = await GraphRepository(db).get(graph_id)
                if graph_model and graph_model.variables:
                    context_vars = graph_model.variables.get("context", {})
                    for key, value in context_vars.items():
                        if key not in initial_context:  # variables 优先
                            if isinstance(value, dict) and "value" in value:
                                initial_context[key] = value["value"]
                            else:
                                initial_context[key] = value

                # 配置
                thread_id = f"openapi_{execution_id}"
                config = {
                    "configurable": {"thread_id": thread_id, "user_id": user_id},
                    "recursion_limit": 150,
                }

                # 注册到 task_manager 以支持 abort
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
                    # 被 abort 中止
                    execution = await exec_repo.get(execution_id)
                    if execution:
                        execution.status = ExecutionStatus.FAILED
                        execution.error_message = "Execution aborted by user"
                        execution.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                    return
                finally:
                    await task_manager.unregister_task(thread_id)

                # 提取结果
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

                # 更新执行记录
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
        """获取执行状态"""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        return {
            "executionId": str(execution.id),
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
        """中止执行"""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        if execution.status != ExecutionStatus.EXECUTING:
            raise BadRequestException(f"Cannot abort execution with status: {execution.status.value}")

        # 通过 task_manager 停止任务
        thread_id = f"openapi_{execution_id}"
        stopped = await task_manager.stop_task(thread_id)
        if stopped:
            await task_manager.cancel_task(thread_id)

        # 更新状态
        execution.status = ExecutionStatus.FAILED
        execution.error_message = "Aborted by user"
        execution.finished_at = datetime.now(timezone.utc)
        await self.db.commit()

        return {
            "executionId": str(execution.id),
            "status": execution.status.value,
        }

    async def get_result(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Dict[str, Any]:
        """获取执行结果"""
        execution = await self.exec_repo.get_by_id_and_user(execution_id, user_id)
        if not execution:
            raise NotFoundException("Execution not found")

        return {
            "executionId": str(execution.id),
            "status": execution.status.value,
            "output": execution.output,
            "errorMessage": execution.error_message,
            "startedAt": execution.started_at.isoformat() if execution.started_at else None,
            "finishedAt": execution.finished_at.isoformat() if execution.finished_at else None,
        }
