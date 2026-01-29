from typing import Any, Dict, List, Optional, Set

from app.core.tools.tool import EnhancedTool, ToolFilter, ToolSourceType
from app.core.tools.tool_registry import ToolRegistry


class AgentToolSelector:
    """
    Agent 工具动态选择器
    支持多种选择策略和场景
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._task_type_configs: Dict[str, ToolFilter] = {}
        self._register_default_task_configs()

    def _register_default_task_configs(self):
        """注册默认的任务类型配置"""
        self._task_type_configs = {
            "coding": ToolFilter(required_tags={"code", "development"}, categories={"dev_tools"}),
            "research": ToolFilter(
                required_tags={"search", "analysis"}, source_types={ToolSourceType.BUILTIN, ToolSourceType.MCP}
            ),
            "data_analysis": ToolFilter(required_tags={"data", "analysis"}, min_priority=5),
            "file_operations": ToolFilter(
                required_tags={"file", "io"},
            ),
        }

    def register_task_config(self, task_type: str, filter_config: ToolFilter):
        """注册自定义任务类型配置"""
        self._task_type_configs[task_type] = filter_config

    def select_for_task(
        self, task_type: str, context: Optional[Dict[str, Any]] = None, additional_filters: Optional[ToolFilter] = None
    ) -> List[EnhancedTool]:
        """根据任务类型选择工具"""
        base_filter = self._task_type_configs.get(task_type, ToolFilter())

        # 合并额外的过滤条件
        if additional_filters:
            base_filter = self._merge_filters(base_filter, additional_filters)

        # 根据上下文调整过滤器
        if context:
            base_filter = self._adjust_filter_by_context(base_filter, context)

        return self.registry.get_tools(base_filter)

    def select_by_tags(
        self, tags: Set[str], source_type: Optional[ToolSourceType] = None, exclude_tags: Optional[Set[str]] = None
    ) -> List[EnhancedTool]:
        """根据标签选择工具"""
        filter_config = ToolFilter(
            required_tags=tags, excluded_tags=exclude_tags, source_types={source_type} if source_type else None
        )
        return self.registry.get_tools(filter_config)

    def select_by_category(self, category: str, source_type: Optional[ToolSourceType] = None) -> List[EnhancedTool]:
        """根据类别选择工具"""
        filter_config = ToolFilter(categories={category}, source_types={source_type} if source_type else None)
        return self.registry.get_tools(filter_config)

    def select_by_mcp_server(self, server_name: str, include_tools: Optional[Set[str]] = None) -> List[EnhancedTool]:
        """根据 MCP 服务器选择工具"""
        filter_config = ToolFilter(mcp_servers={server_name}, include_tools=include_tools)
        return self.registry.get_tools(filter_config)

    def select_by_toolset(
        self, toolset_name: str, source_type: ToolSourceType = ToolSourceType.MCP
    ) -> List[EnhancedTool]:
        """根据工具集选择工具"""
        filter_config = ToolFilter(toolset_names={toolset_name}, source_types={source_type})
        return self.registry.get_tools(filter_config)

    def select_safe_tools(self, include_confirmation: bool = False) -> List[EnhancedTool]:
        """选择安全的工具(不需要确认或外部执行)"""
        if include_confirmation:
            filter_config = ToolFilter(external_execution_only=False)
        else:
            # 手动过滤需要确认的工具
            all_tools = self.registry.get_tools()
            return [
                tool
                for tool in all_tools
                if not tool.tool_metadata.requires_confirmation and not tool.tool_metadata.external_execution
            ]
        return self.registry.get_tools(filter_config)

    def select_by_names(self, tool_names: List[str], strict: bool = True) -> List[EnhancedTool]:
        """根据工具名称列表选择"""
        tools = []
        for name in tool_names:
            tool = self.registry.get_tool(name)
            if tool:
                tools.append(tool)
            elif strict:
                raise ValueError(f"Tool '{name}' not found in registry")
        return tools

    def select_by_query(self, query: str, limit: int = 5) -> List[EnhancedTool]:
        """向量方式
        Embeds the query and description, finds nearest neighbors.
        Useful when the Agent doesn't know which tool to ask for.
        """
        return []

    def _merge_filters(self, base: ToolFilter, additional: ToolFilter) -> ToolFilter:
        """合并两个过滤器"""
        merged = ToolFilter()

        # 合并集合类型字段
        for field in [
            "source_types",
            "required_tags",
            "excluded_tags",
            "categories",
            "mcp_servers",
            "toolset_names",
            "include_tools",
            "exclude_tools",
        ]:
            base_val = getattr(base, field)
            add_val = getattr(additional, field)
            if base_val and add_val:
                setattr(merged, field, base_val & add_val)  # 交集
            else:
                setattr(merged, field, base_val or add_val)

        # 合并其他字段
        merged.include_disabled = base.include_disabled or additional.include_disabled
        merged.min_priority = max(base.min_priority, additional.min_priority)
        merged.requires_confirmation = (
            additional.requires_confirmation
            if additional.requires_confirmation is not None
            else base.requires_confirmation
        )
        merged.external_execution_only = base.external_execution_only or additional.external_execution_only

        return merged

    def _adjust_filter_by_context(self, filter_config: ToolFilter, context: Dict[str, Any]) -> ToolFilter:
        """根据上下文调整过滤器"""
        # 可以根据上下文信息动态调整过滤条件
        # 例如:根据用户权限、当前环境等

        if context.get("safe_mode"):
            filter_config.requires_confirmation = False
            filter_config.external_execution_only = False

        if context.get("priority_threshold"):
            filter_config.min_priority = context["priority_threshold"]

        return filter_config
