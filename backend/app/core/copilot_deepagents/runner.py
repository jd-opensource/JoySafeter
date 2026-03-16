"""
DeepAgents Copilot - 非流式与流式运行入口。

run_copilot_manager: 一次性调用并返回结果。
stream_copilot_manager: 流式产出事件供前端消费。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from loguru import logger

from .manager import (
    create_copilot_manager,
)
from .utils import (
    _apply_layout_to_actions,
    _extract_actions_from_result,
    _extract_final_message,
    _fix_edge_node_ids,
    _parse_tool_output_to_action,
    safe_read_validation,
)


async def run_copilot_manager(
    *,
    user_prompt: str,
    graph_context: Dict[str, Any],
    graph_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    运行 DeepAgents Copilot Manager（非流式）。

    Returns:
        {
            "message": str,
            "actions": List[dict],
            "run_id": str,
            "artifacts_path": str,
        }
    """
    from langchain_core.messages import HumanMessage

    manager, store = create_copilot_manager(
        graph_id=graph_id,
        user_id=user_id,
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
    )

    context_summary = {
        "nodes": len(graph_context.get("nodes", [])),
        "edges": len(graph_context.get("edges", [])),
    }

    full_prompt = f"""用户请求: {user_prompt}

当前图状态:
- 节点数: {context_summary["nodes"]}
- 边数: {context_summary["edges"]}

请按照工作流程生成完整的 Agent 工作流图。"""

    store.write_request(
        {
            "user_prompt": user_prompt,
            "graph_context_summary": context_summary,
            "conversation_history": conversation_history or [],
        }
    )

    result = await manager.ainvoke({"messages": [HumanMessage(content=full_prompt)]})

    actions = _extract_actions_from_result(result)
    final_message = _extract_final_message(result)

    store.write_actions(actions)
    store.write_index(
        {
            "graph_id": graph_id,
            "run_id": store.run_id,
            "user_id": user_id,
            "actions_count": len(actions),
            "ok": True,
        }
    )

    return {
        "message": final_message,
        "actions": actions,
        "run_id": store.run_id,
        "artifacts_path": str(store.run_dir),
    }


async def stream_copilot_manager(
    *,
    user_prompt: str,
    graph_context: Dict[str, Any],
    graph_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    运行 DeepAgents Copilot Manager（流式）。

    Yields SSE 事件:
        - status: 阶段更新
        - content: 流式内容
        - tool_call: 工具调用
        - tool_result: 工具结果
        - result: 最终结果
        - done: 完成
        - error: 错误
    """
    from langchain_core.messages import HumanMessage

    try:
        manager, store = create_copilot_manager(
            graph_id=graph_id,
            user_id=user_id,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
        )

        yield {"type": "status", "stage": "thinking", "message": "正在分析请求..."}

        context_summary = {
            "nodes": len(graph_context.get("nodes", [])),
            "edges": len(graph_context.get("edges", [])),
        }

        full_prompt = f"""用户请求: {user_prompt}

当前图状态:
- 节点数: {context_summary["nodes"]}
- 边数: {context_summary["edges"]}

请按照工作流程生成完整的 Agent 工作流图。"""

        store.write_request(
            {
                "user_prompt": user_prompt,
                "graph_context_summary": context_summary,
                "conversation_history": conversation_history or [],
            }
        )

        collected_actions: List[Dict[str, Any]] = []
        final_message = ""

        async for event in manager.astream_events(
            {"messages": [HumanMessage(content=full_prompt)]},
            version="v2",
            config={"recursion_limit": 300},
        ):
            event_dict_raw = event if isinstance(event, dict) else {}
            event_dict: Dict[str, Any] = cast(Dict[str, Any], event_dict_raw)
            event_kind = event_dict.get("event", "")

            if event_kind == "on_chat_model_stream":
                data = event_dict.get("data", {})
                chunk = data.get("chunk") if isinstance(data, dict) else None
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"type": "content", "content": chunk.content}

            elif event_kind == "on_tool_start":
                tool_name = event_dict.get("name", "")
                data = event_dict.get("data", {})
                tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "input": tool_input,
                }

                if tool_name == "task":
                    subagent = tool_input.get("subagent_type", "") or tool_input.get("name", "")
                    if "analyst" in subagent:
                        yield {"type": "status", "stage": "analyzing", "message": "正在分析需求..."}
                    elif "architect" in subagent:
                        yield {"type": "status", "stage": "planning", "message": "正在设计架构..."}
                    elif "validator" in subagent:
                        yield {"type": "status", "stage": "validating", "message": "正在验证设计..."}

            elif event_kind == "on_tool_end":
                tool_name = event_dict.get("name", "")
                data = event_dict.get("data", {})
                tool_output_raw = data.get("output") if isinstance(data, dict) else None

                if tool_name in ["create_node", "connect_nodes", "delete_node", "update_config"] and tool_output_raw:
                    action = _parse_tool_output_to_action(tool_output_raw)
                    if action and action not in collected_actions:
                        collected_actions.append(action)
                        yield {"type": "tool_result", "action": action}

            elif event_kind == "on_chat_model_end":
                data = event_dict.get("data", {})
                output = data.get("output") if isinstance(data, dict) else None
                if output and hasattr(output, "content"):
                    final_message = output.content

        yield {"type": "status", "stage": "processing", "message": "处理结果..."}
        yield {"type": "status", "stage": "layout", "message": "优化布局..."}
        collected_actions = _apply_layout_to_actions(collected_actions, store)
        collected_actions = _fix_edge_node_ids(collected_actions, store)

        store.write_actions(collected_actions)

        validation = safe_read_validation(store)
        health_score = validation.health_score if validation else None

        store.write_index(
            {
                "graph_id": graph_id,
                "run_id": store.run_id,
                "user_id": user_id,
                "actions_count": len(collected_actions),
                "health_score": health_score,
                "ok": True,
            }
        )

        yield {
            "type": "result",
            "message": final_message,
            "actions": collected_actions,
            "batch": True,
        }

        # done is NOT yielded here; generate_actions_async publishes it
        # AFTER _persist_graph_from_actions completes, so frontend can
        # safely refetch the authoritative state on "done".

        logger.info(f"[DeepAgentsCopilot] Completed run_id={store.run_id} actions={len(collected_actions)}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[DeepAgentsCopilot] Error: {error_msg}")
        
        # Determine error code and potentially simplify message
        error_code = "AGENT_ERROR"
        if "api_key" in error_msg.lower() or "credential" in error_msg.lower():
            error_code = "CREDENTIAL_ERROR"
        elif "RateLimitReached" in error_msg:
            # Try to extract a more readable message for rate limits
            import re
            match = re.search(r"retry after (\d+) milliseconds", error_msg)
            if match:
                seconds = int(match.group(1)) // 1000
                error_msg = f"Rate limit reached. Please retry after {seconds} seconds."
            else:
                error_msg = "Rate limit reached. Please try again later."

        yield {
            "type": "error",
            "message": error_msg,
            "code": error_code,
        }
