from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger

from app.core.tools.tool import EnhancedTool, ToolMetadata, ToolSourceType


class Toolkit:
    def __init__(
        self,
        name: str = "toolkit",
        tools: Optional[List[Callable]] = None,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        include_tools: Optional[List[str]] = None,
        exclude_tools: Optional[List[str]] = None,
        requires_confirmation_tools: Optional[List[str]] = None,
        external_execution_required_tools: Optional[List[str]] = None,
        stop_after_tool_call_tools: Optional[List[str]] = None,
        show_result_tools: Optional[List[str]] = None,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
        auto_register: bool = True,
        source_type: ToolSourceType = ToolSourceType.BUILTIN,
        tags: Optional[Set[str]] = None,
        category: Optional[str] = None,
        default_priority: int = 0,
        enabled: bool = True,
        toolset_name: Optional[str] = None,
        description_prefix: Optional[str] = None,
        custom_attrs: Optional[Dict[str, Any]] = None,
        mcp_server_name: Optional[str] = None,
    ):
        """Initialize a new Toolkit.

        Args:
            name: A descriptive name for the toolkit
            tools: List of tools to include in the toolkit
            instructions: Instructions for the toolkit
            add_instructions: Whether to add instructions to the toolkit
            include_tools: List of tool names to include in the toolkit
            exclude_tools: List of tool names to exclude from the toolkit
            requires_confirmation_tools: List of tool names that require user confirmation
            external_execution_required_tools: List of tool names that will be executed outside of the agent loop
            cache_results (bool): Enable in-memory caching of EnhancedTool results.
            cache_ttl (int): Time-to-live for cached results in seconds.
            cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.
            auto_register (bool): Whether to automatically register callables provided via the 'tools' parameter.
            stop_after_tool_call_tools (Optional[List[str]]): List of EnhancedTool names that should stop the agent after execution.
            show_result_tools (Optional[List[str]]): List of EnhancedTool names whose results should be shown.
        """
        self.name: str = name
        self.tools: List[Callable] = tools or []
        self.functions: Dict[str, EnhancedTool] = OrderedDict()
        self.instructions: Optional[str] = instructions
        self.add_instructions: bool = add_instructions

        self.requires_confirmation_tools: list[str] = requires_confirmation_tools or []
        self.external_execution_required_tools: list[str] = external_execution_required_tools or []

        self.stop_after_tool_call_tools: list[str] = stop_after_tool_call_tools or []
        self.show_result_tools: list[str] = show_result_tools or []

        self._check_tools_filters(
            available_tools=[tool.__name__ for tool in (tools or [])],
            include_tools=include_tools,
            exclude_tools=exclude_tools,
        )

        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

        self.cache_results: bool = cache_results
        self.cache_ttl: int = cache_ttl
        self.cache_dir: Optional[str] = cache_dir

        # Unified metadata defaults to align with ToolMetadata/ToolRegistry
        self.source_type: ToolSourceType = source_type
        self.tags: Set[str] = set(tags) if tags else set()
        self.category: Optional[str] = category
        self.default_priority: int = default_priority
        self.enabled: bool = enabled
        self.toolset_name: Optional[str] = toolset_name
        self.description_prefix: Optional[str] = description_prefix
        self.custom_attrs: Dict[str, Any] = custom_attrs or {}

        # MCP specific defaults for architectural alignment with MCP tool providers
        self.mcp_server_name: Optional[str] = None
        if self.source_type == ToolSourceType.MCP:
            # Prefer explicit mcp_server_name, fallback to toolkit name
            self.mcp_server_name = mcp_server_name or self.name
            # Expose server_params so ToolkitAdapter can recognize MCP-like toolkits
            self.server_params = {"name": self.mcp_server_name}

        # Automatically register all methods if auto_register is True
        if auto_register and self.tools:
            self._register_tools()

    def _check_tools_filters(
        self,
        available_tools: List[str],
        include_tools: Optional[List[str]] = None,
        exclude_tools: Optional[List[str]] = None,
    ) -> None:
        """Check if `include_tools` and `exclude_tools` are valid"""
        if include_tools or exclude_tools:
            if include_tools:
                missing_includes = set(include_tools) - set(available_tools)
                if missing_includes:
                    logger.warning(f"Included tool(s) not present in the toolkit: {', '.join(missing_includes)}")

            if exclude_tools:
                missing_excludes = set(exclude_tools) - set(available_tools)
                if missing_excludes:
                    logger.warning(f"Excluded tool(s) not present in the toolkit: {', '.join(missing_excludes)}")

        if self.requires_confirmation_tools:
            missing_requires_confirmation = set(self.requires_confirmation_tools) - set(available_tools)
            if missing_requires_confirmation:
                logger.warning(
                    f"Requires confirmation tool(s) not present in the toolkit: {', '.join(missing_requires_confirmation)}"
                )

        if self.external_execution_required_tools:
            missing_external_execution_required = set(self.external_execution_required_tools) - set(available_tools)
            if missing_external_execution_required:
                logger.warning(
                    f"External execution required tool(s) not present in the toolkit: {', '.join(missing_external_execution_required)}"
                )

    def _register_tools(self) -> None:
        """Register all tools."""
        for tool in self.tools:
            self.register(tool)

    def register(self, function: Callable[..., Any], name: Optional[str] = None):
        """Register a function with the toolkit.

        Args:
            function: The callable to register
            name: Optional custom name for the function

        Returns:
            The registered function
        """
        try:
            tool_name = name or function.__name__
            if self.include_tools is not None and tool_name not in self.include_tools:
                return
            if self.exclude_tools is not None and tool_name in self.exclude_tools:
                return

            metadata = ToolMetadata(
                source_type=self.source_type,
                tags=self.tags,
                category=self.category,
                priority=self.default_priority,
                enabled=self.enabled,
                toolset_name=self.toolset_name,
                mcp_server_name=self.mcp_server_name,
                requires_confirmation=tool_name in self.requires_confirmation_tools,
                external_execution=tool_name in self.external_execution_required_tools,
                stop_after_tool_call=tool_name in self.stop_after_tool_call_tools,
                show_result=tool_name in self.show_result_tools or tool_name in self.stop_after_tool_call_tools,
                cache_results=self.cache_results,
                cache_ttl=self.cache_ttl,
                cache_dir=self.cache_dir,
                custom_attrs=self.custom_attrs,
            )
            description_text = function.__doc__ or ""
            if self.description_prefix:
                description_text = f"{self.description_prefix}{description_text}"
            f = EnhancedTool.from_callable(
                callable_func=function,
                name=tool_name,
                description=description_text,
                tool_metadata=metadata,
            )
            self.functions[f.name] = f
            logger.debug(f"Function: {f.name} registered with {self.name}")
        except Exception as e:
            fname = getattr(function, "__name__", repr(function))
            logger.warning(f"Failed to create Function for: {fname}")
            raise e

    def get_tools(self) -> List[EnhancedTool]:
        """Return all registered Function objects in this toolkit."""
        return list(self.functions.values())

    def get_tool_names(self) -> List[str]:
        """Return names of all registered tools."""
        return list(self.functions.keys())

    def register_into_registry(self, registry) -> List[EnhancedTool]:
        """
        Register tools in a ToolRegistry-compatible object.
        The registry is expected to provide a `register(EnhancedTool)` method.
        """
        registered: List[EnhancedTool] = []
        for f in self.functions.values():
            registered.append(registry.register(f))
        return registered

    def update_tool_metadata(self, tool_name: str, **kwargs) -> None:
        """
        Update metadata of a specific tool in-place to align behaviors with ToolRegistry/ToolFilter.
        Example: update_tool_metadata("foo", priority=10, enabled=False, tags={"a","b"})
        """
        func = self.functions.get(tool_name)
        if not func:
            return
        for k, v in kwargs.items():
            if hasattr(func.tool_metadata, k):
                setattr(func.tool_metadata, k, v)

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} functions={list(self.functions.keys())}>"

    def __str__(self):
        return self.__repr__()
