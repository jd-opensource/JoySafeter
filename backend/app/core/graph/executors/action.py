"""
Action Executors - Executors for simple actions (Reply, Input, HTTP).
"""
import time
from typing import Any, Dict, Union

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from app.core.graph.graph_state import GraphState
from app.models.graph import GraphNode
from app.core.graph.executors.agent import apply_node_output_mapping


class DirectReplyNodeExecutor:
    """Executor for a Direct Reply node in the graph."""

    STATE_READS: tuple = ("messages", "context")
    STATE_WRITES: tuple = ("messages", "current_node")

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.template = self._get_template()

    def _get_template(self) -> str:
        """Extract template from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        template = config.get("template", "")
        return str(template) if template is not None else ""

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Return the template message."""
        content = self.template
        context = state.get("context", {})
        for key, value in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        return_dict = {
            "messages": [AIMessage(content=content)],
            "current_node": self.node_id,
        }
        
        # Apply output mapping
        # For DirectReply, the 'result' is the content string
        data = self.node.data or {}
        config = data.get("config", {})
        
        # We wrap content in a dict so users can map 'result.content' or just 'result'
        result_wrapper = {"content": content, "text": content}
        
        apply_node_output_mapping(config, result_wrapper, return_dict, self.node_id)
        
        return return_dict


class HumanInputNodeExecutor:
    """Executor for Human-in-the-Loop Interrupt Gate.

    Pauses graph execution for human review.  When the graph is
    resumed (by the frontend sending a ``Command``), normal execution
    continues from this point.
    """

    STATE_READS: tuple = ("messages",)
    STATE_WRITES: tuple = ("messages", "current_node")

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Simple interrupt gate — let interrupt_before pause execution."""
        logger.info(
            f"[HumanInputNode] Executing node '{self.node_id}'"
        )

        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], HumanMessage):
            logger.info(
                f"[HumanInputNode] Processed human input: "
                f"{messages[-1].content[:100]}"
            )

        return {"current_node": self.node_id}


class HttpRequestNodeExecutor:
    """Executor for HTTP Request node.
    
    Performs REST API calls.
    """
    
    STATE_READS: tuple = ("context", "*")
    STATE_WRITES: tuple = ("*") # Via output mapping

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        
        data = self.node.data or {}
        self.config = data.get("config", {})
        self.url = self.config.get("url")
        self.method = self.config.get("method", "GET")
        self.headers = self.config.get("headers", {})
        self.body = self.config.get("body", "")

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        import httpx
        
        start_time = time.time()
        logger.info(f"[HttpRequestNode] >>> {self.method} {self.url} | node_id={self.node_id}")
        
        try:
            # Resolve template variables in URL/Body/Headers
            # For simplicity, skipping deep template resolution here, but should be done.
            
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=self.method,
                    url=self.url,
                    headers=self.headers,
                    content=self.body if self.body else None,
                    timeout=30.0
                )
                
                result_data = {
                    "status_code": response.status_code,
                    "text": response.text,
                    "headers": dict(response.headers),
                    "json": None
                }
                
                try:
                    result_data["json"] = response.json()
                except Exception:
                    pass
                
                logger.info(f"[HttpRequestNode] <<< Status: {response.status_code}")
                
                return_dict = {
                    "current_node": self.node_id
                }
                
                apply_node_output_mapping(self.config, result_data, return_dict, self.node_id)
                
                return return_dict

        except Exception as e:
            logger.error(f"[HttpRequestNode] Request failed: {e}")
            return {"messages": [AIMessage(content=f"HTTP Request failed: {e}")]}
