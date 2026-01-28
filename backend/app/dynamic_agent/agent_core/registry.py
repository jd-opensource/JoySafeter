"""Tool registry for managing available tools."""

from typing import List, Optional

from app.dynamic_agent.agent_core.types import Tool


class ToolRegistry:
    """
    Central registry for all available tools.

    Manages tool registration, filtering (read-only vs write),
    and tool lookup.
    """

    _tools: List[Tool] = []

    @classmethod
    def register(cls, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool to register
        """
        # Check if already registered
        if any(t.name == tool.name for t in cls._tools):
            raise ValueError(f"Tool {tool.name} already registered")

        cls._tools.append(tool)

    @classmethod
    def unregister(cls, tool_name: str) -> None:
        """
        Unregister a tool by name.

        Args:
            tool_name: Name of tool to unregister
        """
        cls._tools = [t for t in cls._tools if t.name != tool_name]

    @classmethod
    def get_all_tools(cls) -> List[Tool]:
        """Get all registered tools."""
        return cls._tools.copy()

    @classmethod
    def get_read_only_tools(cls) -> List[Tool]:
        """Get only read-only tools."""
        return [t for t in cls._tools if t.is_read_only()]

    @classmethod
    def get_write_tools(cls) -> List[Tool]:
        """Get only write tools."""
        return [t for t in cls._tools if not t.is_read_only()]

    @classmethod
    def get_tool(cls, name: str) -> Optional[Tool]:
        """
        Get tool by name.

        Args:
            name: Tool name

        Returns:
            Tool if found, None otherwise
        """
        for tool in cls._tools:
            if tool.name == name:
                return tool
        return None

    @classmethod
    def clear(cls) -> None:
        """Clear all registered tools (useful for testing)."""
        cls._tools = []

    @classmethod
    async def get_enabled_tools(cls) -> List[Tool]:
        """Get all enabled tools."""
        enabled = []
        for tool in cls._tools:
            if await tool.is_enabled():
                enabled.append(tool)
        return enabled

    @classmethod
    def filter_tools(
        cls,
        exclude: Optional[List[str]] = None,
        include_only: Optional[List[str]] = None,
        read_only: Optional[bool] = None,
    ) -> List[Tool]:
        """
        Filter tools by criteria.

        Args:
            exclude: Tool names to exclude
            include_only: Only include these tool names
            read_only: If True, only read-only; if False, only write; if None, all

        Returns:
            Filtered list of tools
        """
        tools = cls._tools.copy()

        # Apply exclusions
        if exclude:
            tools = [t for t in tools if t.name not in exclude]

        # Apply inclusions
        if include_only:
            tools = [t for t in tools if t.name in include_only]

        # Apply read-only filter
        if read_only is not None:
            tools = [t for t in tools if t.is_read_only() == read_only]

        return tools
