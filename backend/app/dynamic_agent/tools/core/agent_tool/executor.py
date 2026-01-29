"""Sub-Agent Core Execution Logic.

This module handles the core execution flow for Sub-Agent tasks:
- Tool selection and invocation (_try_run_with_tools)
- Single-task execution (_process_one)
- Result formatting

Dependencies: models.py (for AgentResult, AgentState)
"""

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from loguru import logger
from openai import APIError

from app.dynamic_agent.core.config import conf
from app.dynamic_agent.core.constants import MCP_TOOL_JOINER
from app.dynamic_agent.core.shared_constants import SUBAGENT_TIMEOUT_SECONDS, SUMMARY_MAX_LENGTH
from app.dynamic_agent.infra.context import tool_registry
from app.dynamic_agent.infra.llm import DEBUG, create_llm_instance
from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.tools.core.tool_selection.tool_selection_base import (
    DynamicToolSelectionAgent,
    create_select_agent,
)

from ...base import base_tools, base_tools_for_selection
from .models import AgentResult, _render_task


def extract_json_from_string(text: str) -> Union[List, dict, str]:
    """Generic function to extract JSON object or array from a string.

    Supports multi-layer extraction strategies:
    1. Direct JSON parsing
    2. Regex extraction of JSON Array [...]
    3. Regex extraction of JSON Objects {...} and wrap them in an array

    Args:
        text: String that may contain JSON

    Returns:
        Extracted JSON object (list or dict), or original string (if extraction fails)

    Examples:
        >>> extract_json_from_string('["a", "b"]')
        ['a', 'b']
        >>> extract_json_from_string('```json\\n["a"]\\n```')
        ['a']
        >>> extract_json_from_string('Result: {"x": 1}')
        {'x': 1}
        >>> extract_json_from_string('{"a": 1} {"b": 2}')
        [{'a': 1}, {'b': 2}]
    """
    if not text:
        return text

    # Strategy 1: Direct parsing
    try:
        result = json.loads(text)
        # Ensure return type matches: list[Any] | dict[Any, Any] | str
        if isinstance(result, (list, dict, str)):
            return result  # type: ignore[return-value]
        return str(result)  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract JSON Array [...]
    array_pattern = r"\[.*?\]"
    match = re.search(array_pattern, text, re.DOTALL)
    if match:
        try:
            extracted = match.group(0)
            result = json.loads(extracted)
            if isinstance(result, (list, dict, str)):
                return result  # type: ignore[return-value]
            return str(result)  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    # Strategy 3: Extract all JSON Objects {...} and wrap them in an array
    object_pattern = r"\{[^{}]*\}"
    objects = re.findall(object_pattern, text, re.DOTALL)
    if objects:
        try:
            parsed_objects = [json.loads(obj) for obj in objects]
            if len(parsed_objects) == 1:
                result = parsed_objects[0]
                if isinstance(result, (list, dict, str)):
                    return result  # type: ignore[return-value]
                return str(result)  # type: ignore[return-value]
            return parsed_objects  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    # All strategies failed, return original string
    return text


EARLY_SUMMARY_SYSTEM_PROMPT = """
You are an EARLY STOP summarizer.

You are given the message history of an agent execution
that was stopped early due to iteration limits.

Your task:
- Produce the best possible FINAL ANSWER to the original user task
- Use only the information already present in the messages
- Do NOT call tools
- Do NOT ask follow-up questions
- Do NOT continue reasoning loops

If information is incomplete, make reasonable assumptions
and clearly state them.

Return ONLY the final answer.
"""


def early_summarize_with_llm(
    messages,
    llm: ChatOpenAI,
):
    """
    LLM-based EARLY summarizer.
    Guaranteed single-shot, no recursion.
    """

    if not messages:
        return {"messages": [AIMessage(content="Final Answer: No information available.")]}

    summary_messages = [
        SystemMessage(content=EARLY_SUMMARY_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                "Here is the agent message history:\n\n"
                + "\n".join(f"[{m.__class__.__name__}] {m.content}" for m in messages if getattr(m, "content", None))
                + "\n\nProduce the FINAL ANSWER."
            )
        ),
    ]
    temp_llm = create_llm_instance()
    temp_llm.bind(parallel_tool_calls=False)
    response = temp_llm.invoke(summary_messages)

    # ⚠️ Key: Returns "terminated state messages"
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        content_str = " ".join(str(item) for item in content)
    else:
        content_str = str(content) if content is not None else ""
    return f"Final Answer (EARLY STOP):\n{content_str}"


async def _try_run_with_tools(llm: BaseChatModel, task_text: str, tools: List[Any], agent_name: str) -> str:
    """Run agent with tools using LangGraph ReAct pattern.

    Args:
        llm: llm instance
        task_text: Task description
        tools: List of LangChain tools
        agent_name: Name of the agent (for logging)

    Returns:
        Agent's final output as string
    """
    from langchain.agents import create_agent

    initial_state = {"messages": [HumanMessage(content=task_text)]}
    try:
        logger.debug(f"Agent '{agent_name}' creating LangGraph ReAct agent with {len(tools)} tools")

        # Disable parallel tool calls to ensure sequential execution
        # This prevents the LLM from calling multiple tools simultaneously,
        # which makes it easier to track which payload actually succeeded
        # llm_sequential = llm.bind_tools(tools, parallel_tool_calls=False)

        # Get scene-aware system prompt
        # Check if CTF mode is active from metadata
        # Import locally to avoid circular dependency
        from .agent_tool_prompts import get_sub_agent_prompt

        metadata = MetadataContext.get() or {}
        metadata.get("is_ctf", False)
        # scene = SceneType.CTF.value if is_ctf else None
        scene = metadata.get("mode", "")
        system_prompt = get_sub_agent_prompt(scene)

        logger.debug(f"Sub-Agent using scene: {scene if scene else 'default'}")

        llm = create_llm_instance()
        llm.bind(parallel_tool_calls=False)
        from typing import Any as AnyType

        app: AnyType = create_agent(llm, [t for t in tools if t], system_prompt=system_prompt)
        app = app.bind(llm={"parallel_tool_calls": False})  # type: ignore[assignment]

        metadata = MetadataContext.get() or {}
        from app.dynamic_agent.observability.langfuse import callbacks

        # Get tracking handler from parent metadata (singleton handler)
        # The handler uses task_id from MetadataContext to track the correct task
        tracking_handler = metadata.get("tracking_handler") if metadata else None
        callback_list = [tracking_handler] + callbacks() if tracking_handler else callbacks()

        # Sub-Agent recursion limit: 64 steps max (about 32 tool calls)
        # Prompt encourages stopping earlier, this is a hard safety limit
        final_state = await app.ainvoke(  # type: ignore[arg-type]
            initial_state,
            config={
                "callbacks": callback_list,
                "metadata": {k: v for k, v in metadata.items() if k not in ["callbacks", "tracking_handler"]},
                "recursion_limit": 64,
            },
        )

        # Extract final response
        messages = final_state.get("messages", [])  # type: ignore[union-attr]
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, AIMessage):
                content = last_message.content
                # Handle content that might be str or list
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    return str(content)
                else:
                    return str(content)
            content_val = getattr(last_message, "content", None) if hasattr(last_message, "content") else None
            # Handle content that might be str, list, or None
            if content_val is None:
                return str(last_message)
            elif isinstance(content_val, str):
                return content_val
            elif isinstance(content_val, list):
                return str(content_val)
            else:
                return str(content_val)

        return "No response generated"
    except Exception as e:
        import traceback

        logger.error(traceback.format_exc())
        traceback.print_exc()
        if isinstance(e, GraphRecursionError) or isinstance(e, APIError):
            result = early_summarize_with_llm(initial_state["messages"], create_llm_instance())
            return str(result) if result is not None else "No response generated"

        raise e


async def _process_one(task_detail: str, level: int, llm: BaseChatModel) -> AgentResult:
    """Process a single Sub-Agent task and return structured result.

    Args:
        task_detail: task description
        llm: language model instance

    Returns:
        AgentResult with execution details
    """
    t0 = time.time()
    temp_llm = create_llm_instance()

    # Extract a concise name from task_detail using LLM
    try:
        name_prompt = f"Provide a 3-5 word title for this task: {task_detail[:200]}"
        temp_llm.bind(parallel_tool_calls=False)
        name_response = temp_llm.invoke([HumanMessage(content=name_prompt)], config={"callbacks": []})
        content = name_response.content
        # Handle content that might be str or list
        if isinstance(content, str):
            name = content.strip()[:50]
        elif isinstance(content, list):
            name = str(content)[:50]
        else:
            name = str(content)[:50]
    except Exception as e:
        logger.warning(f"Failed to generate name using LLM: {e}, using truncated task_detail")
        name = task_detail[:50]

    # Append timestamp suffix (precise to seconds)
    timestamp_suffix = time.strftime("%Y%m%d_%H%M%S")
    name = f"{name}_{timestamp_suffix}"

    logger.info(f"Starting agent '{name}' at level {level}")

    # Create subtask in database
    parent_metadata = MetadataContext.get()

    # Get parent task ID from current task_id (not from stack)
    parent_task_id = parent_metadata.get("task_id") if parent_metadata else None

    # Get current_step_id (set by tracking handler in on_tool_start)
    current_step_id = parent_metadata.get("current_step_id") if parent_metadata else None

    subtask_id = None
    subtask_metadata: Optional[Dict[str, Any]] = None

    if parent_task_id:
        from app.dynamic_agent.agent_core.task_manager import TaskManager
        from app.dynamic_agent.storage import get_storage_manager
        from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO

        try:
            # Get task manager and create subtask
            storage_manager = get_storage_manager()
            pool = storage_manager.backend.pool if storage_manager.backend else None
            if pool is None:
                raise RuntimeError("Storage backend pool is not available")
            task_manager = TaskManager(TaskDAO(pool))

            session_id = (parent_metadata or {}).get("langfuse_session_id", "default_session")
            subtask_id, _ = await task_manager.create_task(
                session_id=session_id,
                user_input=task_detail,
                metadata={"agent_name": name, "level": level},
                parent_id=parent_task_id,  # Link to parent task
                created_by_step_id=current_step_id,  # Link to the step that created this task
            )

            logger.info(f"Created subtask {subtask_id} for agent '{name}' (parent: {parent_task_id})")

            # Create independent metadata copy for this subtask
            subtask_metadata = dict(parent_metadata or {})  # Copy parent metadata
            subtask_metadata["task_id"] = subtask_id  # Set current task ID
            # Note: Tracking handler is singleton (inherited from parent), uses task_id from MetadataContext

        except Exception as e:
            error = f"Failed to create subtask for agent '{name}': {e}"
            logger.error(error, exc_info=True)
            raise Exception(error)

    # Set subtask metadata for this execution context
    if subtask_metadata:
        MetadataContext.set(subtask_metadata)

    mode = parent_metadata.get("mode") if parent_metadata else None
    # Check CTF mode FIRST to skip dynamic tool selection
    # metadata = MetadataContext.get() or {}

    # is_ctf = parent_metadata.get('is_ctf', False) or detect_scene(task_detail) == SceneType.CTF
    is_ctf = mode == "ctf"
    # Initialize tool_instances before if/else branches
    tool_instances: List[Any] = []
    if is_ctf:
        # CTF Mode: Use CTF_PRESET_TOOLS directly (skip dynamic selection entirely)
        from app.dynamic_agent.core.constants import CTF_PRESET_TOOLS
        from app.dynamic_agent.tools.builtin.think_tool.think_tool import think_tool
        from app.dynamic_agent.tools.builtin.todo_tool import TODO_TOOLS

        # Debug: check what tools are available in registry
        all_tools = list(tool_registry._tools_obj.keys())
        logger.debug(f"🔍 Tool registry has {len(all_tools)} tools: {all_tools[:10]}...")

        for preset_tool_name in CTF_PRESET_TOOLS:
            full_name = f"{conf.NAME}{MCP_TOOL_JOINER}{preset_tool_name}"
            tool = tool_registry.get_tool(full_name)
            if tool:
                tool_instances.append(tool)
                logger.debug(f"✅ Found tool: {full_name}")
            else:
                logger.warning(f"❌ Tool NOT found: {full_name}")
        # Add think_tool for reasoning, TODO_TOOLS for task management
        tool_instances.append(think_tool)
        tool_instances.extend(TODO_TOOLS)
        # Add ask_human tool for requesting human help when stuck
        from app.dynamic_agent.tools.builtin.ask_human_tool import ask_human

        tool_instances.append(ask_human)
        # Add report_finding tool for tracking discoveries
        from app.dynamic_agent.tools.builtin.report_finding_tool import report_finding

        tool_instances.append(report_finding)
        # Add knowledge_search tool for CTF bypass techniques
        from app.dynamic_agent.tools.builtin.knowledge_search_tool import knowledge_search

        tool_instances.append(knowledge_search)
        logger.debug(f"🚩 CTF sub-agent using preset tools: {[t.name for t in tool_instances]}")
    else:
        select_agent: DynamicToolSelectionAgent = create_select_agent(temp_llm, base_tools_for_selection, verbose=DEBUG)
        metadata_context = MetadataContext.get() or {}
        result = await select_agent.arun([{"role": "user", "content": task_detail}], metadata_context)

        initial_tools = result.get("output", "")

        # Use generic JSON extraction function
        initial_tools = extract_json_from_string(initial_tools)

        # Verify extraction result is a list
        if not isinstance(initial_tools, list):
            msg = f"Cannot extract valid tool list from LLM output, model returned:\n{str(initial_tools)}"
            logger.error(msg)
            raise Exception("Failed to create sub-agent, please retry later")

        # todo multi mcp server
        selected_tool_instances: List[Any] = []
        for tool_name in initial_tools:
            tool = tool_registry.get_tool(f"{conf.NAME}{MCP_TOOL_JOINER}{tool_name}")
            if tool is not None:
                selected_tool_instances.append(tool)
        for item in base_tools:
            if item not in selected_tool_instances:
                selected_tool_instances.append(item)
        # Assign to tool_instances (already initialized before if/else)
        tool_instances[:] = selected_tool_instances

        from ... import check_iterations, final_response

        if final_response not in tool_instances:
            tool_instances.append(final_response)
        if check_iterations not in tool_instances:
            tool_instances.append(check_iterations)

        from app.dynamic_agent.tools.core.agent_tool.agent_tool import MAX_AGENT_LEVEL, agent_tool

        if level < MAX_AGENT_LEVEL:
            tool_instances.append(agent_tool)

    task_text = _render_task(task_detail)
    output = ""
    ok = False
    err = None

    try:
        logger.debug(f"Agent '{name}' using {len(tool_instances)} tool(s)")

        # Update subtask metadata with tools list
        if subtask_id:
            try:
                # Extract tool names and descriptions
                tool_list = []
                for tool in tool_instances:
                    if hasattr(tool, "name") and hasattr(tool, "description"):
                        tool_list.append({"name": tool.name, "description": tool.description})

                # Get task manager to update metadata
                from app.dynamic_agent.agent_core.task_manager import TaskManager
                from app.dynamic_agent.storage import get_storage_manager
                from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO

                storage_manager = get_storage_manager()
                pool = storage_manager.backend.pool if storage_manager.backend else None
                if pool is not None:
                    tm = TaskManager(TaskDAO(pool))

                    # Update subtask metadata with tools information
                    await tm.update_task_metadata(
                        task_id=subtask_id, metadata_updates={"tools": tool_list, "tools_count": len(tool_list)}
                    )
                logger.info(f"Updated subtask {subtask_id} metadata with {len(tool_list)} tools")
            except Exception as e:
                logger.warning(f"Failed to update subtask metadata with tools list: {e}")

        # Sub-Agent timeout
        timeout = SUBAGENT_TIMEOUT_SECONDS

        try:
            output = await asyncio.wait_for(_try_run_with_tools(llm, task_text, tool_instances, name), timeout=timeout)
            ok = True

            logger.info(f"Agent '{name}' completed successfully in {int((time.time() - t0) * 1000)}ms")

            # Update subtask status to COMPLETED
            if subtask_id and parent_task_id:
                try:
                    from app.dynamic_agent.storage import get_storage_manager
                    from app.dynamic_agent.storage.models import TaskStatus

                    storage = get_storage_manager()
                    if storage.backend and storage.backend.task_dao:
                        await storage.backend.task_dao.update_task(
                            task_id=subtask_id,
                            status=TaskStatus.COMPLETED,
                            completed_at=datetime.utcnow(),
                            result_summary=output[:500] if output else None,  # Store first 500 chars
                        )
                    logger.debug(f"Subtask {subtask_id} marked as COMPLETED")
                except Exception as e:
                    logger.error(f"Failed to update subtask status: {e}", exc_info=True)
        except asyncio.TimeoutError:
            ok = False
            err = f"Subagent execution timed out after {timeout}s"
            logger.error(f"Agent '{name}' timed out after {timeout}s")
            # Return partial result if available
            output = f"[TIMEOUT] Execution exceeded {timeout}s limit. Partial results may be incomplete."

    except KeyboardInterrupt:
        raise
    except Exception as e:
        ok = False
        output = ""
        err = str(e)
        logger.error(f"Agent '{name}' failed: {e}", exc_info=True)

        # Update subtask status to FAILED
        if subtask_id and parent_task_id:
            try:
                from app.dynamic_agent.storage import get_storage_manager
                from app.dynamic_agent.storage.models import TaskStatus

                storage = get_storage_manager()
                if storage.backend and storage.backend.task_dao:
                    await storage.backend.task_dao.update_task(
                        task_id=subtask_id,
                        status=TaskStatus.FAILED,
                        completed_at=datetime.utcnow(),
                        result_summary=str(e)[:500],
                    )
                logger.debug(f"Subtask {subtask_id} marked as FAILED")
            except Exception as update_err:
                logger.error(f"Failed to update subtask status: {update_err}", exc_info=True)

    dur_ms = int((time.time() - t0) * 1000)

    # Sub-Agent is responsible for its own summary - just truncate if too long
    if output and len(output) > SUMMARY_MAX_LENGTH:
        output = output[: SUMMARY_MAX_LENGTH - 50] + "\n...[truncated]"

    return AgentResult(name=name, level=level, duration_ms=dur_ms, ok=ok, result=output, error=err)


__all__ = ["_try_run_with_tools", "_process_one"]
