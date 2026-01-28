"""Permission strategies for tool access control."""

from typing import Any, Dict

from app.dynamic_agent.agent_core.types import (
    AssistantMessage,
    PermissionResult,
    Tool,
    ToolUseContext,
)


class DefaultPermissionStrategy:
    """
    Default permission strategy that allows all tools.

    This is useful for development and testing. In production,
    you should implement a strategy that integrates with your UI
    to request user permission.
    """

    async def check(
        self, tool: Tool, input: Dict[str, Any], context: ToolUseContext, assistant_message: AssistantMessage
    ) -> PermissionResult:
        """Allow all tools by default."""
        return PermissionResult(result=True)


class InteractivePermissionStrategy:
    """
    Permission strategy that prompts for user approval.

    This is a simple CLI-based implementation. For integration with
    a Node.js UI, you would implement a strategy that communicates
    via JSON-RPC to request permission from the UI.
    """

    def __init__(self):
        """Initialize with empty permission cache."""
        self.allowed_tools: set[str] = set()
        self.denied_tools: set[str] = set()

    async def check(
        self, tool: Tool, input: Dict[str, Any], context: ToolUseContext, assistant_message: AssistantMessage
    ) -> PermissionResult:
        """Check permission with user approval."""
        tool_key = f"{tool.name}:{str(input)}"

        # Check cache
        if tool_key in self.allowed_tools:
            return PermissionResult(result=True)

        if tool_key in self.denied_tools:
            return PermissionResult(result=False, message="Permission denied by user")

        # In a real implementation, this would communicate with the UI
        # For now, we'll just allow it
        self.allowed_tools.add(tool_key)
        return PermissionResult(result=True)


class NodeUIPermissionStrategy:
    """
    Permission strategy that integrates with Node.js UI via callback.

    This strategy calls back to the Node.js layer to display permission
    dialogs and get user approval.
    """

    def __init__(self, request_permission_callback):
        """
        Initialize with permission callback.

        Args:
            request_permission_callback: Async function that requests
                permission from Node.js UI and returns bool
        """
        self.request_permission = request_permission_callback

    async def check(
        self, tool: Tool, input: Dict[str, Any], context: ToolUseContext, assistant_message: AssistantMessage
    ) -> PermissionResult:
        """Request permission from Node.js UI."""
        try:
            approved = await self.request_permission(
                tool_name=tool.name, tool_input=input, context=context.model_dump()
            )

            if approved:
                return PermissionResult(result=True)
            else:
                return PermissionResult(result=False, message="Permission denied by user")
        except Exception as e:
            # If permission check fails, deny by default
            return PermissionResult(result=False, message=f"Permission check failed: {str(e)}")
