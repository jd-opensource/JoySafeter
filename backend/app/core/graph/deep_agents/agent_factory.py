"""Agent factory — creates runnable agents from resolved configs.

Handles three agent types: standard agent, code_agent, a2a_agent.
Each returns a CompiledSubAgent that DeepAgents can orchestrate.
"""

from __future__ import annotations

from typing import Any, List

from deepagents import CompiledSubAgent
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from loguru import logger

from app.core.a2a.client import resolve_a2a_url, send_message
from app.core.graph.deep_agents.config import NodeConfig

LOG_PREFIX = "[AgentFactory]"


# ---------------------------------------------------------------------------
# Task extraction helper (shared by code_agent and a2a)
# ---------------------------------------------------------------------------


def _extract_task(inputs: dict) -> str:
    """Extract task text from agent inputs. Supports dict and BaseMessage formats."""
    task = inputs.get("task")
    if task:
        return str(task).strip()

    messages = inputs.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content"):
            return str(last_msg.content).strip()
        if isinstance(last_msg, dict):
            return str(last_msg.get("content", "")).strip()
        return str(last_msg).strip()

    return ""


# ---------------------------------------------------------------------------
# Standard agent worker
# ---------------------------------------------------------------------------


def build_standard_worker(
    config: NodeConfig,
    model: Any,
    tools: List[Any],
    middleware: List[Any],
) -> CompiledSubAgent:
    """Build a standard LLM agent worker as CompiledSubAgent."""
    logger.info(f"{LOG_PREFIX} Building worker: '{config.name}'")

    from langchain.agents import create_agent

    runnable = create_agent(
        model=model,
        tools=tools,
        system_prompt=config.system_prompt,
        middleware=middleware,
    )

    return CompiledSubAgent(
        name=config.name,
        description=config.description or f"Worker: {config.label or config.name}",
        runnable=runnable,
    )


# ---------------------------------------------------------------------------
# Code agent worker
# ---------------------------------------------------------------------------


def build_code_agent_worker(
    config: NodeConfig,
    model: Any,
    tools: List[Any],
    backend: Any = None,
) -> CompiledSubAgent:
    """Build a CodeAgent worker as CompiledSubAgent."""
    logger.info(
        f"{LOG_PREFIX} Building CodeAgent: '{config.name}' | mode={config.agent_mode} | executor={config.executor_type}"
    )

    from app.core.agent.code_agent import CodeAgent, LoopConfig

    executor = _build_code_executor(config, backend)
    loop_config = LoopConfig(
        max_steps=config.max_steps,
        enable_planning=config.enable_planning,
        max_observation_length=10000,
    )
    llm_call = _create_llm_wrapper(model)
    tools_dict = {
        t.name if hasattr(t, "name") else t.__name__: t for t in tools if hasattr(t, "name") or hasattr(t, "__name__")
    }

    code_agent = CodeAgent(
        llm=llm_call,
        tools=tools_dict if tools_dict else None,
        executor=executor,
        config=loop_config,
        name=config.name,
        description=config.description or "",
        enable_data_analysis=config.enable_data_analysis,
        additional_authorized_imports=config.additional_imports,
    )

    async def invoke(inputs: dict) -> dict:
        task = _extract_task(inputs)
        if config.agent_mode == "tool_executor":
            result = await code_agent.run(f"Execute the following task and return the result directly:\n\n{task}")
        else:
            result = await code_agent.run(task)
        return {
            "messages": [AIMessage(content=str(result) if result else "Task completed.")],
            "result": result,
        }

    return CompiledSubAgent(
        name=config.name,
        description=config.description or "",
        runnable=RunnableLambda(invoke),
    )


# ---------------------------------------------------------------------------
# A2A agent worker
# ---------------------------------------------------------------------------


async def build_a2a_worker(config: NodeConfig) -> CompiledSubAgent:
    """Build an A2A remote agent worker as CompiledSubAgent."""
    a2a_url = config.a2a_url
    auth_headers = config.a2a_auth_headers

    if not a2a_url and config.agent_card_url:
        a2a_url = await resolve_a2a_url(config.agent_card_url, auth_headers=auth_headers)

    if not a2a_url:
        raise ValueError(f"A2A agent '{config.name}' requires a2a_url or agent_card_url")

    logger.info(f"{LOG_PREFIX} Building A2A agent: '{config.name}' → {a2a_url}")

    captured_url = a2a_url
    captured_auth = auth_headers

    async def invoke(inputs: dict) -> dict:
        task = _extract_task(inputs)
        result = await send_message(
            captured_url,
            task,
            auth_headers=captured_auth,
            wait_for_completion=True,
        )
        if not result.ok:
            content = f"[A2A error] {result.error or 'Unknown error'}"
        else:
            content = result.text or ""
        return {
            "messages": [AIMessage(content=content)],
            "a2a_result": result,
        }

    return CompiledSubAgent(
        name=config.name,
        description=config.description or "Remote A2A agent",
        runnable=RunnableLambda(invoke),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_code_executor(config: NodeConfig, backend: Any = None) -> Any:
    """Build executor for CodeAgent."""
    from app.core.agent.code_agent import LocalPythonExecutor

    def _local():
        return LocalPythonExecutor(
            enable_data_analysis=config.enable_data_analysis,
            additional_authorized_imports=config.additional_imports,
        )

    if backend and config.executor_type in ("docker", "auto"):
        from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter
        from app.core.agent.code_agent.executor.backend_executor import BackendPythonExecutor

        if isinstance(backend, PydanticSandboxAdapter):
            docker_executor = BackendPythonExecutor(backend=backend)
            if config.executor_type == "docker":
                return docker_executor
            # auto: route between local and docker
            from app.core.agent.code_agent import ExecutorRouter

            return ExecutorRouter(local=_local(), docker=docker_executor, allow_dangerous=True)

    return _local()


def _create_llm_wrapper(model: Any) -> Any:
    """Create async LLM call wrapper for CodeAgent."""
    from langchain_core.messages import HumanMessage

    async def llm_call(prompt: str) -> str:
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)

    return llm_call
