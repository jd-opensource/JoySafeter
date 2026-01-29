import asyncio
import inspect

# ============= 1. 元数据与过滤定义 =============
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set, Type

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, create_schema_from_function
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class ToolSourceType(str, Enum):
    BUILTIN = "builtin"
    MCP = "mcp"
    CUSTOM = "custom"
    LANGCHAIN = "langchain"


@dataclass
class ToolMetadata:
    """工具元数据，包含来源、权限、缓存等信息"""

    source_type: ToolSourceType
    tags: Set[str] = field(default_factory=set)
    category: Optional[str] = None
    toolset_name: Optional[str] = None
    priority: int = 0
    enabled: bool = True

    # MCP specific fields
    mcp_server_name: Optional[str] = None  # MCP server identifier (unique per user)
    mcp_tool_name: Optional[str] = None  # Original tool name from MCP server

    # Ownership fields - for scoped tool queries
    owner_user_id: Optional[str] = None  # User who owns this tool/MCP server
    owner_workspace_id: Optional[str] = None  # Workspace scope (NULL = user-level, global)

    # Execution control
    requires_confirmation: bool = False
    external_execution: bool = False
    stop_after_tool_call: bool = False
    show_result: bool = False

    # Caching
    cache_results: bool = False
    cache_ttl: int = 3600
    cache_dir: Optional[str] = None

    # Extension point
    custom_attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolFilter:
    """工具过滤器，用于查询符合条件的工具"""

    source_types: Optional[Set[ToolSourceType]] = None
    categories: Optional[Set[str]] = None
    include_tools: Optional[Set[str]] = None
    exclude_tools: Optional[Set[str]] = None
    mcp_servers: Optional[Set[str]] = None
    toolset_names: Optional[Set[str]] = None
    required_tags: Optional[Set[str]] = None
    excluded_tags: Optional[Set[str]] = None
    min_priority: int = 0
    include_disabled: bool = False
    requires_confirmation: Optional[bool] = None
    external_execution_only: bool = False

    # Ownership filters
    owner_user_id: Optional[str] = None  # Filter by owner user
    owner_workspace_id: Optional[str] = None  # Filter by workspace scope
    include_global: bool = True  # Include tools without owner (builtin, global)

    def matches_tool(self, tool_name: str, metadata: ToolMetadata) -> bool:
        """检查工具是否匹配过滤条件"""
        if self.include_tools and tool_name not in self.include_tools:
            return False
        if self.exclude_tools and tool_name in self.exclude_tools:
            return False
        if self.source_types and metadata.source_type not in self.source_types:
            return False
        if self.categories and metadata.category not in self.categories:
            return False
        if self.mcp_servers and metadata.mcp_server_name and metadata.mcp_server_name not in self.mcp_servers:
            return False
        if self.toolset_names and metadata.toolset_name and metadata.toolset_name not in self.toolset_names:
            return False
        if self.required_tags and not self.required_tags.intersection(metadata.tags):
            return False
        if self.excluded_tags and self.excluded_tags.intersection(metadata.tags):
            return False
        if self.min_priority > 0 and metadata.priority < self.min_priority:
            return False
        if not self.include_disabled and not metadata.enabled:
            return False
        if self.requires_confirmation is not None and metadata.requires_confirmation != self.requires_confirmation:
            return False
        if self.external_execution_only and not metadata.external_execution:
            return False

        # Ownership filtering
        if not self._matches_ownership(metadata):
            return False

        return True

    def _matches_ownership(self, metadata: ToolMetadata) -> bool:
        """
        检查工具所有权是否匹配

        所有权语义:
        - Global tools (owner_user_id=None): 内置工具，对所有用户可见
        - User-level tools (owner_workspace_id=None): 用户私有工具，仅所有者可见
        - Workspace-level tools (owner_workspace_id!=None): 工作区共享工具，工作区内所有成员可见
        """
        # If no owner filter specified, match all
        if self.owner_user_id is None and self.owner_workspace_id is None:
            return True

        # Global tools (no owner) - included if include_global is True
        if metadata.owner_user_id is None:
            return self.include_global

        # Workspace-level tools: match by workspace_id (any user's tools in the workspace)
        if metadata.owner_workspace_id is not None:
            if self.owner_workspace_id is not None:
                return metadata.owner_workspace_id == self.owner_workspace_id
            # If no workspace filter, workspace-level tools are not visible
            return False

        # User-level tools: require exact user match
        if self.owner_user_id is not None:
            return metadata.owner_user_id == self.owner_user_id

        return True


# ============= 2. 增强工具类 (适配器模式) =============


class EnhancedTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""
    args_schema: Optional[Type[BaseModel]] = None
    label_name: Optional[str] = None

    tool_metadata: ToolMetadata = Field(
        default_factory=lambda: ToolMetadata(source_type=ToolSourceType.CUSTOM), exclude=True
    )

    _entrypoint: Optional[Callable] = PrivateAttr(default=None)
    _wrapped_tool: Optional[BaseTool] = PrivateAttr(default=None)

    def get_label_name(self) -> str:
        """获取标签名称，如果未设置则返回 name"""
        return self.label_name if self.label_name is not None else self.name

    async def _execute_logic(self, kwargs: dict, config: Optional[RunnableConfig] = None) -> Any:
        """核心执行逻辑：处理超时、包装调用"""
        timeout = self.tool_metadata.custom_attrs.get("execution_timeout", 60)

        # 过滤掉 deepagents FilesystemMiddleware 注入的 runtime 参数
        # runtime 是 middleware 内部使用的，不应该传递给实际工具
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != "runtime"}

        # 打印工具调用信息：工具名称和参数
        # logger.info(f"[Tool Call] 工具名称: {self.name}, 参数: {filtered_kwargs}")

        try:
            if self._wrapped_tool:
                # 关键：调用 ainvoke 解决 config 参数缺失问题
                return await asyncio.wait_for(
                    self._wrapped_tool.ainvoke(filtered_kwargs, config=config), timeout=timeout
                )

            if self._entrypoint:
                if inspect.iscoroutinefunction(self._entrypoint):
                    return await asyncio.wait_for(self._entrypoint(**filtered_kwargs), timeout=timeout)
                return await asyncio.to_thread(self._entrypoint, **filtered_kwargs)

            raise ValueError("No execution path found.")
        except Exception as e:
            logger.error(f"Tool {self.name} failed: {e}")
            return f"Error: {str(e)}"

    def _run(self, *args, run_manager=None, **kwargs) -> Any:
        config = RunnableConfig(callbacks=run_manager.get_child() if run_manager else None)
        try:
            return asyncio.run(self._execute_logic(kwargs, config))
        except RuntimeError:
            return asyncio.get_event_loop().run_until_complete(self._execute_logic(kwargs, config))

    async def _arun(self, *args, run_manager=None, **kwargs) -> Any:
        config = RunnableConfig(callbacks=run_manager.get_child() if run_manager else None)
        return await self._execute_logic(kwargs, config)

    @classmethod
    def from_langchain_tool(cls, tool: BaseTool, tool_metadata: Optional[ToolMetadata] = None):
        """将 @tool 或 BaseTool 子类转换为 EnhancedTool"""
        metadata = tool_metadata or ToolMetadata(source_type=ToolSourceType.LANGCHAIN)
        # 提取原有描述
        args_schema = tool.args_schema
        if args_schema is not None and not isinstance(args_schema, type):
            args_schema = None  # type: ignore[assignment]
        instance = cls(
            name=tool.name,
            description=tool.description,
            args_schema=args_schema,
            tool_metadata=metadata,  # type: ignore[arg-type]
        )
        instance._wrapped_tool = tool
        return instance

    @classmethod
    def from_callable(cls, callable_func: Callable, name=None, description=None, tool_metadata=None):
        """将函数转换为 EnhancedTool"""
        t_name = name or callable_func.__name__
        t_desc = description or callable_func.__doc__ or ""
        metadata = tool_metadata or ToolMetadata(source_type=ToolSourceType.BUILTIN)

        instance = cls(
            name=t_name,
            description=t_desc,
            args_schema=create_schema_from_function(t_name, callable_func),
            tool_metadata=metadata,
        )
        instance._entrypoint = callable_func
        return instance

    @classmethod
    def from_entrypoint(
        cls,
        name: str,
        description: str,
        entrypoint: Callable,
        args_schema: Optional[Type[BaseModel]] = None,
        tool_metadata: Optional[ToolMetadata] = None,
    ):
        """
        从 entrypoint 函数创建 EnhancedTool

        Args:
            name: 工具名称
            description: 工具描述
            entrypoint: 执行入口函数（可以是同步或异步函数）
            args_schema: 参数验证模型（可选）
            tool_metadata: 工具元数据（可选）
        """
        metadata = tool_metadata or ToolMetadata(source_type=ToolSourceType.CUSTOM)

        instance = cls(name=name, description=description, args_schema=args_schema, tool_metadata=metadata)
        instance._entrypoint = entrypoint
        return instance

    @classmethod
    def from_entrypoint_with_schema(
        cls,
        name: str,
        description: str,
        args_schema: Optional[Type[BaseModel]],
        entrypoint: Callable[..., Any],
        tool_metadata: Optional[ToolMetadata] = None,
    ) -> "EnhancedTool":
        """
        Create an EnhancedTool from a pre-built async/sync entrypoint and an optional args schema.
        Used by MCP integration where we already have a callable and JSON-schema-derived args model.
        """
        metadata = tool_metadata or ToolMetadata(source_type=ToolSourceType.CUSTOM)
        desc = description or entrypoint.__doc__ or ""

        instance = cls(
            name=name,
            description=desc,
            args_schema=args_schema,
            tool_metadata=metadata,
        )
        instance._entrypoint = entrypoint
        return instance
