"""
Tool Registry - Unified Tool Registration Center

Manages all types of tools: Builtin, MCP, Custom, etc.
Acts as the Single Source of Truth for in-memory tool management.
"""

from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Union

from langchain_core.tools import BaseTool
from loguru import logger

from app.core.tools.tool import EnhancedTool, ToolFilter, ToolMetadata, ToolSourceType

# MCP tool key separator
MCP_TOOL_KEY_SEPARATOR = "::"


class ToolRegistry:
    """Unified Tool Registration Center"""

    def __init__(self):
        self._tools: OrderedDict[str, EnhancedTool] = OrderedDict()
        self._tool_metadata: Dict[str, ToolMetadata] = {}

        # Indexing for faster query
        self._source_type_index: Dict[ToolSourceType, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._category_index: Dict[str, Set[str]] = {}
        self._mcp_server_index: Dict[str, Set[str]] = {}

        # User/Workspace ownership index (for fast query of tools owned by user)
        self._owner_user_index: Dict[str, Set[str]] = {}
        self._owner_workspace_index: Dict[str, Set[str]] = {}

    # ==================== MCP Tool Key Generation ====================

    @staticmethod
    def make_mcp_tool_key(server_name: str, tool_name: str) -> str:
        """
        Generate unique key for MCP tool

        Args:
            server_name: MCP server name
            tool_name: Tool name

        Returns:
            Unique key, format: {server_name}::{tool_name}
        """
        return f"{server_name}{MCP_TOOL_KEY_SEPARATOR}{tool_name}"

    @staticmethod
    def parse_mcp_tool_key(key: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse MCP tool key

        Args:
            key: Tool key

        Returns:
            (server_name, tool_name) or (None, None) if not an MCP tool key
        """
        if MCP_TOOL_KEY_SEPARATOR not in key:
            return None, None
        parts = key.split(MCP_TOOL_KEY_SEPARATOR, 1)
        return parts[0], parts[1] if len(parts) > 1 else None

    def get_mcp_tool(self, server_name: str, tool_name: str) -> Optional[EnhancedTool]:
        """
        Get MCP tool by server_name + tool_name

        Args:
            server_name: MCP server name
            tool_name: Tool name

        Returns:
            EnhancedTool or None
        """
        key = self.make_mcp_tool_key(server_name, tool_name)
        return self._tools.get(key)

    def register(
        self,
        tool_input: Union[EnhancedTool, BaseTool, Callable],
        overwrite: bool = False,
        use_label_name_as_key: bool = False,
        **meta_kwargs,
    ) -> EnhancedTool:
        """
        Universal registration interface. Supports:
        1. registry.register(my_enhanced_tool)
        2. registry.register(langchain_structured_tool, category="search")
        3. registry.register(async_def_function, priority=10)

        Args:
            tool_input: Tool object or callable
            overwrite: Whether to overwrite existing tool
            use_label_name_as_key: Whether to use label_name as storage key (used by MCP tools)
            **meta_kwargs: Metadata arguments
        """
        # 1. Conversion logic (Adapter)
        if isinstance(tool_input, EnhancedTool):
            final_tool = tool_input
        elif isinstance(tool_input, BaseTool):
            final_tool = EnhancedTool.from_langchain_tool(tool_input)
        elif callable(tool_input):
            final_tool = EnhancedTool.from_callable(tool_input)
        else:
            raise ValueError(f"Unknown tool type: {type(tool_input)}")

        # 2. Inject/Update metadata
        for key, value in meta_kwargs.items():
            if hasattr(final_tool.tool_metadata, key):
                setattr(final_tool.tool_metadata, key, value)
            else:
                final_tool.tool_metadata.custom_attrs[key] = value

        if use_label_name_as_key and final_tool.label_name:
            storage_key = final_tool.label_name
        else:
            storage_key = final_tool.name
            if final_tool.label_name is None:
                final_tool.label_name = final_tool.name

        if storage_key in self._tools and not overwrite:
            return self._tools[storage_key]
        self._tools[storage_key] = final_tool
        self._tool_metadata[storage_key] = final_tool.tool_metadata
        self._update_indexes(storage_key, final_tool.tool_metadata)

        logger.info(
            f"Registered tool: name={final_tool.name}, label_name={final_tool.get_label_name()}, "
            f"storage_key={storage_key} [{final_tool.tool_metadata.source_type.value}]"
        )
        return final_tool

    def register_builtin(
        self,
        callable_func: Callable[..., Any],
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        category: Optional[str] = None,
        **metadata_kwargs,
    ) -> EnhancedTool:
        """Register builtin tool"""
        # Ensure tool_type is stored in custom_attrs at registration time
        custom_attrs = metadata_kwargs.pop("custom_attrs", {})
        custom_attrs["tool_type"] = "builtin"  # Set tool_type at registration

        metadata = ToolMetadata(
            source_type=ToolSourceType.BUILTIN,
            tags=tags or set(),
            category=category,
            custom_attrs=custom_attrs,
            **metadata_kwargs,
        )

        tool = EnhancedTool.from_callable(
            callable_func=callable_func, name=name, description=description, tool_metadata=metadata
        )

        return self.register(tool)

    def register_mcp_tool(
        self,
        tool: EnhancedTool,
        mcp_server_name: str,
        mcp_tool_name: str,
        owner_user_id: Optional[str] = None,
        owner_workspace_id: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        category: Optional[str] = None,
        **metadata_kwargs,
    ) -> EnhancedTool:
        """Register MCP tool

        Important:
        - tool.name remains the real tool name (mcp_tool_name), seen by LLM and used when calling
        - tool.label_name is set to server_name::tool_name, used for management and display
        - Registry uses label_name as key internally
        """
        # Ensure tool_type is stored in custom_attrs at registration time
        custom_attrs = metadata_kwargs.pop("custom_attrs", {})
        custom_attrs["tool_type"] = "mcp"  # Set tool_type at registration

        tool.tool_metadata = ToolMetadata(
            source_type=ToolSourceType.MCP,
            mcp_server_name=mcp_server_name,
            mcp_tool_name=mcp_tool_name,
            owner_user_id=owner_user_id,
            owner_workspace_id=owner_workspace_id,
            tags=tags or set(),
            category=category,
            custom_attrs=custom_attrs,
            **metadata_kwargs,
        )

        tool.name = mcp_tool_name
        tool.label_name = self.make_mcp_tool_key(mcp_server_name, mcp_tool_name)

        return self.register(tool, use_label_name_as_key=True)

    def register_langchain_tool(
        self,
        langchain_tool: BaseTool,
        tags: Optional[Set[str]] = None,
        category: Optional[str] = None,
        priority: int = 0,
        enabled: bool = True,
        source_type: Optional[ToolSourceType] = None,
        **metadata_kwargs,
    ) -> EnhancedTool:
        """Register LangChain tool

        Args:
            langchain_tool: LangChain BaseTool instance (e.g. tool created with @tool decorator)
            tags: Tool tags set
            category: Tool category
            priority: Tool priority
            enabled: Whether enabled
            source_type: Tool source type, defaults to LANGCHAIN if None
            **metadata_kwargs: Other metadata arguments (e.g. requires_confirmation, external_execution etc.)

        Returns:
            Registered EnhancedTool instance

        Example:
            from langchain_core.tools import tool

            @tool
            def my_tool(query: str) -> str:
                \"\"\"Search tool\"\"\"
                return f"Searching: {query}"

            registry.register_langchain_tool(
                my_tool,
                category="search",
                tags={"search", "web"},
                priority=10
            )
        """
        # Ensure tool_type is stored in custom_attrs at registration time
        custom_attrs = metadata_kwargs.pop("custom_attrs", {})
        # Set tool_type based on source_type
        if source_type is None:
            source_type = ToolSourceType.LANGCHAIN
        # For builtin tools, should mark as "builtin"
        if source_type == ToolSourceType.BUILTIN:
            custom_attrs["tool_type"] = "builtin"
        else:
            custom_attrs["tool_type"] = source_type.value

        metadata = ToolMetadata(
            source_type=source_type,
            tags=tags or set(),
            category=category,
            priority=priority,
            enabled=enabled,
            custom_attrs=custom_attrs,
            **metadata_kwargs,
        )

        tool = EnhancedTool.from_langchain_tool(tool=langchain_tool, tool_metadata=metadata)

        return self.register(tool)

    def register_batch(
        self, tools: List[EnhancedTool], tool_metadata_list: Optional[List[ToolMetadata]] = None
    ) -> List[EnhancedTool]:
        """Batch register tools"""
        registered = []
        for i, tool in enumerate(tools):
            if tool_metadata_list and i < len(tool_metadata_list):
                # If metadata provided, update tool metadata
                tool.tool_metadata = tool_metadata_list[i]
            registered.append(self.register(tool))
        return registered

    def unregister(self, tool_name: str) -> bool:
        """Unregister tool"""
        if tool_name not in self._tools:
            return False

        tool_metadata = self._tool_metadata[tool_name]

        # Remove from index
        self._remove_from_indexes(tool_name, tool_metadata)

        # Remove tool
        del self._tools[tool_name]
        del self._tool_metadata[tool_name]

        logger.debug(f"Tool unregistered: {tool_name}")
        return True

    # ==================== MCP Batch Operations ====================

    def register_mcp_tools(
        self,
        mcp_server_name: str,
        tools: List[EnhancedTool],
        owner_user_id: Optional[str] = None,
        owner_workspace_id: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        category: Optional[str] = None,
    ) -> List[EnhancedTool]:
        """
        Batch register MCP server tools

        Args:
            mcp_server_name: MCP server name
            tools: Tool list
            owner_user_id: Owner user ID
            owner_workspace_id: Workspace ID (optional)
            tags: Shared tags set
            category: Shared category

        Returns:
            Registered tool list
        """
        registered = []
        base_tags = tags or set()
        base_tags.add("mcp")

        for tool in tools:
            original_name = tool.name
            try:
                registered_tool = self.register_mcp_tool(
                    tool=tool,
                    mcp_server_name=mcp_server_name,
                    mcp_tool_name=original_name,
                    owner_user_id=owner_user_id,
                    owner_workspace_id=owner_workspace_id,
                    tags=base_tags.copy(),
                    category=category,
                )
                registered.append(registered_tool)
            except Exception as e:
                logger.error(f"Failed to register MCP tool {original_name} from {mcp_server_name}: {e}")

        logger.info(f"Registered {len(registered)} tools from MCP server: {mcp_server_name}")
        return registered

    def unregister_mcp_server_tools(self, mcp_server_name: str) -> int:
        """
        Unregister all tools of an MCP server

        Args:
            mcp_server_name: MCP server name

        Returns:
            Number of unregistered tools
        """
        tools_to_remove = self._mcp_server_index.get(mcp_server_name, set()).copy()
        count = 0

        for tool_name in tools_to_remove:
            if self.unregister(tool_name):
                count += 1

        logger.info(f"Unregistered {count} tools from MCP server: {mcp_server_name}")
        return count

    def get_mcp_server_tools(self, mcp_server_name: str) -> List[EnhancedTool]:
        """
        Get all tools of an MCP server

        Args:
            mcp_server_name: MCP server name

        Returns:
            Tool list
        """
        tool_names = self._mcp_server_index.get(mcp_server_name, set())
        return [self._tools[name] for name in tool_names if name in self._tools]

    # ==================== Scoped Queries ====================

    def get_tools_for_scope(
        self,
        user_id: str,
        workspace_id: Optional[str] = None,
        filter_config: Optional[ToolFilter] = None,
        include_builtin: bool = True,
    ) -> List[EnhancedTool]:
        """
        Get tools available in user/workspace scope

        Includes:
        - Builtin tools (builtin) - if include_builtin=True
        - Tools owned by user (owner_user_id == user_id, owner_workspace_id is None)
        - Workspace level tools (owner_workspace_id == workspace_id) - if workspace_id provided

        Args:
            user_id: User ID
            workspace_id: Workspace ID (optional)
            filter_config: Additional filter conditions
            include_builtin: Whether to include builtin tools

        Returns:
            List of matching tools
        """
        # Build a filter that matches the scope
        scope_filter = ToolFilter(
            owner_user_id=user_id,
            owner_workspace_id=workspace_id,
            include_global=include_builtin,  # Global tools = builtin tools without owner
        )

        # Merge with additional filter if provided
        if filter_config:
            # Copy filter_config and add ownership constraints
            merged_filter = ToolFilter(
                source_types=filter_config.source_types,
                categories=filter_config.categories,
                include_tools=filter_config.include_tools,
                exclude_tools=filter_config.exclude_tools,
                mcp_servers=filter_config.mcp_servers,
                toolset_names=filter_config.toolset_names,
                required_tags=filter_config.required_tags,
                excluded_tags=filter_config.excluded_tags,
                min_priority=filter_config.min_priority,
                include_disabled=filter_config.include_disabled,
                requires_confirmation=filter_config.requires_confirmation,
                external_execution_only=filter_config.external_execution_only,
                owner_user_id=user_id,
                owner_workspace_id=workspace_id,
                include_global=include_builtin,
            )
            return self.get_tools(merged_filter)

        return self.get_tools(scope_filter)

    def get_tool(self, name: str) -> Optional[EnhancedTool]:
        """Get a single tool"""
        return self._tools.get(name)

    def get_tools(
        self, filter_config: Optional[ToolFilter] = None, sort_by_priority: bool = True
    ) -> List[EnhancedTool]:
        """Get tool list based on filter conditions"""
        if filter_config is None:
            tools = list(self._tools.values())
        else:
            tools = self._filter_tools(filter_config)

        # Sort by priority
        if sort_by_priority:
            tools.sort(key=lambda t: t.tool_metadata.priority, reverse=True)

        return tools

    def get_tool_names(self, filter_config: Optional[ToolFilter] = None) -> List[str]:
        """Get list of tool names (returns label_name, used for management and display)"""
        tools = self.get_tools(filter_config)
        return [tool.get_label_name() for tool in tools]

    def _filter_tools(self, filter_config: ToolFilter) -> List[EnhancedTool]:
        """Filter using index acceleration"""
        candidate_names: Optional[Set[str]] = None

        # Filter candidates quickly using index
        if filter_config.source_types:
            type_candidates = set()
            for source_type in filter_config.source_types:
                type_candidates.update(self._source_type_index.get(source_type, set()))
            candidate_names = type_candidates if candidate_names is None else candidate_names & type_candidates

        if filter_config.mcp_servers:
            server_candidates = set()
            for server in filter_config.mcp_servers:
                server_candidates.update(self._mcp_server_index.get(server, set()))
            candidate_names = server_candidates if candidate_names is None else candidate_names & server_candidates

        if filter_config.categories:
            category_candidates = set()
            for category in filter_config.categories:
                category_candidates.update(self._category_index.get(category, set()))
            candidate_names = category_candidates if candidate_names is None else candidate_names & category_candidates

        # If no index used, use all tools
        if candidate_names is None:
            candidate_names = set(self._tools.keys())

        # Detailed filter on candidates
        filtered_tools = []
        for tool_name in candidate_names:
            tool = self._tools[tool_name]
            tool_metadata = self._tool_metadata[tool_name]

            if filter_config.matches_tool(tool_name, tool_metadata):
                filtered_tools.append(tool)

        return filtered_tools

    def _update_indexes(self, tool_name: str, tool_metadata: ToolMetadata):
        """Update indexes"""
        # Source type index
        if tool_metadata.source_type not in self._source_type_index:
            self._source_type_index[tool_metadata.source_type] = set()
        self._source_type_index[tool_metadata.source_type].add(tool_name)

        # Tag index
        for tag in tool_metadata.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(tool_name)

        # Category index
        if tool_metadata.category:
            if tool_metadata.category not in self._category_index:
                self._category_index[tool_metadata.category] = set()
            self._category_index[tool_metadata.category].add(tool_name)

        # MCP server index
        if tool_metadata.mcp_server_name:
            if tool_metadata.mcp_server_name not in self._mcp_server_index:
                self._mcp_server_index[tool_metadata.mcp_server_name] = set()
            self._mcp_server_index[tool_metadata.mcp_server_name].add(tool_name)

        # User ownership index
        if tool_metadata.owner_user_id:
            if tool_metadata.owner_user_id not in self._owner_user_index:
                self._owner_user_index[tool_metadata.owner_user_id] = set()
            self._owner_user_index[tool_metadata.owner_user_id].add(tool_name)

        # Workspace ownership index
        if tool_metadata.owner_workspace_id:
            if tool_metadata.owner_workspace_id not in self._owner_workspace_index:
                self._owner_workspace_index[tool_metadata.owner_workspace_id] = set()
            self._owner_workspace_index[tool_metadata.owner_workspace_id].add(tool_name)

    def _remove_from_indexes(self, tool_name: str, tool_metadata: ToolMetadata):
        """Remove from indexes"""
        # Source type index
        if tool_metadata.source_type in self._source_type_index:
            self._source_type_index[tool_metadata.source_type].discard(tool_name)

        # Tag index
        for tag in tool_metadata.tags:
            if tag in self._tag_index:
                self._tag_index[tag].discard(tool_name)

        # Category index
        if tool_metadata.category and tool_metadata.category in self._category_index:
            self._category_index[tool_metadata.category].discard(tool_name)

        # MCP server index
        if tool_metadata.mcp_server_name and tool_metadata.mcp_server_name in self._mcp_server_index:
            self._mcp_server_index[tool_metadata.mcp_server_name].discard(tool_name)

        # User ownership index
        if tool_metadata.owner_user_id and tool_metadata.owner_user_id in self._owner_user_index:
            self._owner_user_index[tool_metadata.owner_user_id].discard(tool_name)

        # Workspace ownership index
        if tool_metadata.owner_workspace_id and tool_metadata.owner_workspace_id in self._owner_workspace_index:
            self._owner_workspace_index[tool_metadata.owner_workspace_id].discard(tool_name)

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """List all tools and their metadata"""
        return {
            name: {
                "tool": tool,
                "metadata": {
                    "source_type": tool.tool_metadata.source_type.value,
                    "tags": list(tool.tool_metadata.tags),
                    "category": tool.tool_metadata.category,
                    "priority": tool.tool_metadata.priority,
                    "enabled": tool.tool_metadata.enabled,
                    "mcp_server": tool.tool_metadata.mcp_server_name,
                    "mcp_tool_name": tool.tool_metadata.mcp_tool_name,
                    "toolset": tool.tool_metadata.toolset_name,
                    "requires_confirmation": tool.tool_metadata.requires_confirmation,
                    "external_execution": tool.tool_metadata.external_execution,
                    "owner_user_id": tool.tool_metadata.owner_user_id,
                    "owner_workspace_id": tool.tool_metadata.owner_workspace_id,
                },
            }
            for name, tool in self._tools.items()
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get registration statistics"""
        return {
            "total_tools": len(self._tools),
            "by_source_type": {source_type.value: len(tools) for source_type, tools in self._source_type_index.items()},
            "by_category": {category: len(tools) for category, tools in self._category_index.items()},
            "mcp_servers": list(self._mcp_server_index.keys()),
            "tags": list(self._tag_index.keys()),
            "owner_users": list(self._owner_user_index.keys()),
            "owner_workspaces": list(self._owner_workspace_index.keys()),
        }


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_global_registry() -> ToolRegistry:
    """Get or create the global tool registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        _initialize_builtin_tools(_global_registry)
    return _global_registry


def _initialize_builtin_tools(registry: ToolRegistry):
    """Initialize builtin tools in the registry."""
    try:
        from app.core.tools.buildin.research_tools import tavily_search, think_tool
        from app.core.tools.buildin.skill_management import SkillManagementTools

        # 1. Register research tools (LangChain tools created with @tool decorator)
        registry.register_langchain_tool(
            tavily_search,
            category="research",
            tags={"search", "web", "research"},
            source_type=ToolSourceType.BUILTIN,
        )

        registry.register_langchain_tool(
            think_tool,
            category="research",
            tags={"reflection", "thinking", "research"},
            source_type=ToolSourceType.BUILTIN,
        )

        # 2. Register execution tools (FileTools, PythonTools, SkillManagement)
        # We instantiate them with dummy paths because we only need their metadata (name, description, args)
        # for frontend display. The actual execution uses instances created in node_tools.py with real user context.
        #
        # NOTE: We use the SAME names as in node_tools.py -> aliases map

        # --- Skill Management ---
        # We use a dummy user_id for registration purposes
        skill_tools = SkillManagementTools(user_id="system_registration")
        registry.register_builtin(
            callable_func=skill_tools.deploy_local_skill,
            name="deploy_local_skill",
            description="Deploy a local skill from the sandbox to the system (private).",
            category="system",
            tags={"skill", "deployment"},
        )

        # --- Skill Preview ---
        from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox

        registry.register_builtin(
            callable_func=preview_skill_in_sandbox,
            name="preview_skill",
            description="Preview a skill generated in the sandbox. Reads all files from the skill directory and returns structured JSON with file contents and validation results.",
            category="skill",
            tags={"skill", "preview", "sandbox"},
        )

        logger.info("Builtin tools (research + execution) registered successfully")

    except Exception as e:
        logger.warning(f"Failed to register some builtin tools: {e}")
