"""
State Variable Tracker - Tracks and analyzes state variables in graph.

Provides analysis of:
- Variables defined by nodes
- Variables used by nodes
- Variable dependencies and flow
- Variable scope (global vs scoped)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from app.models.graph import GraphEdge, GraphNode


@dataclass
class VariableDefinition:
    """变量定义信息。"""

    name: str
    source_node_id: str
    source_node_label: str
    source_node_type: str
    scope: str  # 'global', 'loop', 'task', 'node'
    path: str  # 访问路径，如 'context.user_id', 'loop_states.loop_1.count'
    description: Optional[str] = None
    value_type: Optional[str] = None  # 'string', 'number', 'boolean', 'object', 'array'


@dataclass
class VariableUsage:
    """变量使用信息。"""

    name: str
    used_in_node_id: str
    used_in_node_label: str
    used_in_node_type: str
    usage_type: str  # 'read', 'write', 'condition', 'mapping'
    expression: str  # 使用变量的表达式
    path: str  # 访问路径


@dataclass
class VariableInfo:
    """变量完整信息。"""

    name: str
    definitions: List[VariableDefinition]
    usages: List[VariableUsage]
    scope: str
    is_defined: bool
    is_used: bool


class StateVariableTracker:
    """状态变量追踪器。

    分析图中的节点配置，提取：
    1. 变量定义（哪些节点定义了哪些变量）
    2. 变量使用（哪些节点使用了哪些变量）
    3. 变量依赖关系
    """

    def __init__(self, nodes: List[GraphNode], edges: List[GraphEdge]):
        self.nodes = nodes
        self.edges = edges
        self.variable_definitions: Dict[str, List[VariableDefinition]] = {}
        self.variable_usages: Dict[str, List[VariableUsage]] = {}

    def analyze_graph(self) -> Dict[str, VariableInfo]:
        """分析整个图，返回所有变量的信息。

        Returns:
            Dict mapping variable_name -> VariableInfo
        """
        # 分析所有节点
        for node in self.nodes:
            self._analyze_node(node)

        # 构建变量信息
        all_variables: Set[str] = set()
        all_variables.update(self.variable_definitions.keys())
        all_variables.update(self.variable_usages.keys())

        result = {}
        for var_name in all_variables:
            definitions = self.variable_definitions.get(var_name, [])
            usages = self.variable_usages.get(var_name, [])

            # 确定作用域（优先使用定义的作用域）
            # VariableUsage doesn't have scope, only VariableDefinition does
            scope = definitions[0].scope if definitions else "global"

            result[var_name] = VariableInfo(
                name=var_name,
                definitions=definitions,
                usages=usages,
                scope=scope,
                is_defined=len(definitions) > 0,
                is_used=len(usages) > 0,
            )

        return result

    def _analyze_node(self, node: GraphNode) -> None:
        """分析单个节点的变量定义和使用。"""
        node_data = node.data or {}
        node_type = node_data.get("type", "agent")
        node_label = node_data.get("label", node.id)
        config = node_data.get("config", {})

        # 根据节点类型分析
        if node_type == "router_node":
            self._analyze_router_node(node, config, node_label)
        elif node_type == "condition":
            self._analyze_condition_node(node, config, node_label)
        elif node_type in ["loop_condition_node", "iteration"]:
            self._analyze_loop_condition_node(node, config, node_label)
        elif node_type == "tool_node":
            self._analyze_tool_node(node, config, node_label)
        elif node_type == "function_node":
            self._analyze_function_node(node, config, node_label)
        elif node_type == "agent":
            self._analyze_agent_node(node, config, node_label)
        elif node_type == "direct_reply":
            self._analyze_direct_reply_node(node, config, node_label)

    def _analyze_router_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Router 节点的变量使用。"""
        routes = config.get("routes", [])
        for rule in routes:
            condition = rule.get("condition", "")
            if condition:
                variables = self._extract_variables_from_expression(condition)
                for var_name, var_path in variables.items():
                    self._add_variable_usage(
                        var_name,
                        str(node.id),
                        node_label,
                        "router_node",
                        "condition",
                        condition,
                        var_path,
                    )

    def _analyze_condition_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Condition 节点的变量使用。"""
        expression = config.get("expression", "")
        if expression:
            variables = self._extract_variables_from_expression(expression)
            for var_name, var_path in variables.items():
                self._add_variable_usage(
                    var_name,
                    str(node.id),
                    node_label,
                    "condition",
                    "condition",
                    expression,
                    var_path,
                )

    def _analyze_loop_condition_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Loop Condition 节点的变量使用。"""
        conditionType = config.get("conditionType", "while")

        # For forEach, track listVariable usage
        if conditionType == "forEach":
            listVariable = config.get("listVariable", "items")
            if listVariable:
                # Track the list variable as a source
                self._add_variable_usage(
                    listVariable,
                    str(node.id),
                    node_label,
                    "loop_condition_node",
                    "listVariable",
                    f"forEach over {listVariable}",
                    listVariable,
                )
        else:
            # For while/doWhile, track condition expression
            condition = config.get("condition", "")
            if condition:
                variables = self._extract_variables_from_expression(condition)
                for var_name, var_path in variables.items():
                    self._add_variable_usage(
                        var_name,
                        str(node.id),
                        node_label,
                        "loop_condition_node",
                        "condition",
                        condition,
                        var_path,
                    )

        # Loop condition 节点定义 loop_count 变量
        self._add_variable_definition(
            f"loop_states.{node.id}.loop_count",
            str(node.id),
            node_label,
            "loop_condition_node",
            "loop",
            f"loop_states.{node.id}.loop_count",
            "Loop iteration count",
            "number",
        )

    def _analyze_tool_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Tool 节点的变量使用。"""
        input_mapping = config.get("input_mapping", {})
        for param_name, expression in input_mapping.items():
            if isinstance(expression, str):
                variables = self._extract_variables_from_expression(expression)
                for var_name, var_path in variables.items():
                    self._add_variable_usage(
                        var_name,
                        str(node.id),
                        node_label,
                        "tool_node",
                        "mapping",
                        expression,
                        var_path,
                    )

    def _analyze_function_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Function 节点的变量使用和定义。"""
        function_code = config.get("function_code", "")
        if function_code:
            # 提取使用的变量
            variables = self._extract_variables_from_expression(function_code)
            for var_name, var_path in variables.items():
                self._add_variable_usage(
                    var_name,
                    str(node.id),
                    node_label,
                    "function_node",
                    "read",
                    function_code,
                    var_path,
                )

            # 尝试提取定义的变量（从 result = {...} 中）
            defined_vars = self._extract_defined_variables(function_code)
            for var_name, var_path in defined_vars.items():
                self._add_variable_definition(
                    var_name,
                    str(node.id),
                    node_label,
                    "function_node",
                    "global",
                    var_path,
                    f"Defined by function node '{node_label}'",
                )

    def _analyze_agent_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Agent 节点的变量使用。

        Agent 节点可能通过 systemPrompt 或其他配置使用变量。
        """
        system_prompt = config.get("systemPrompt", "")
        if system_prompt:
            # 检查模板变量 {{variable}}
            import re

            template_vars = re.findall(r"\{\{(\w+)\}\}", system_prompt)
            for var_name in template_vars:
                self._add_variable_usage(
                    var_name,
                    str(node.id),
                    node_label,
                    "agent",
                    "template",
                    system_prompt,
                    f"context.{var_name}",
                )

    def _analyze_direct_reply_node(self, node: GraphNode, config: Dict[str, Any], node_label: str) -> None:
        """分析 Direct Reply 节点的变量使用。"""
        template = config.get("template", "")
        if template:
            # 检查模板变量 {{variable}}
            import re

            template_vars = re.findall(r"\{\{(\w+)\}\}", template)
            for var_name in template_vars:
                self._add_variable_usage(
                    var_name,
                    str(node.id),
                    node_label,
                    "direct_reply",
                    "template",
                    template,
                    f"context.{var_name}",
                )

    def _extract_variables_from_expression(self, expression: str) -> Dict[str, str]:
        """从表达式中提取变量。

        Returns:
            Dict mapping variable_name -> access_path
        """
        variables = {}

        # 匹配 state.get('key'), state.get("key"), state['key']
        import re

        patterns = [
            (r"state\.get\(['\"]([^'\"]+)['\"]", "state.{}"),
            (r"state\[['\"]([^'\"]+)['\"]", "state.{}"),
            (r"context\.get\(['\"]([^'\"]+)['\"]", "context.{}"),
            (r"context\[['\"]([^'\"]+)['\"]", "context.{}"),
            (r"loop_states\[['\"]([^'\"]+)['\"]", "loop_states.{}"),
            (r"loop_state\.get\(['\"]([^'\"]+)['\"]", "loop_state.{}"),
            (r"task_states\[['\"]([^'\"]+)['\"]", "task_states.{}"),
            (r"node_contexts\[['\"]([^'\"]+)['\"]", "node_contexts.{}"),
        ]

        for pattern, path_template in patterns:
            matches = re.finditer(pattern, expression)
            for match in matches:
                var_name = match.group(1)
                access_path = path_template.format(var_name)
                variables[var_name] = access_path

        # 匹配直接变量名（在表达式中）
        # 注意：这个可能不够精确，但可以捕获一些简单情况
        simple_vars = re.findall(r"\b([a-z_][a-z0-9_]*)\b", expression.lower())
        for var_name in simple_vars:
            if var_name not in ["state", "context", "true", "false", "none", "and", "or", "not", "in", "is"]:
                if var_name not in variables:
                    variables[var_name] = f"context.{var_name}"

        return variables

    def _extract_defined_variables(self, code: str) -> Dict[str, str]:
        """从代码中提取定义的变量。

        查找 result = {...} 或 context['key'] = value 等模式。
        """
        variables = {}
        import re

        # 匹配 result = {'key': value} 或 result = {"key": value}
        result_pattern = r"result\s*=\s*\{[^}]*['\"]([^'\"]+)['\"]"
        matches = re.finditer(result_pattern, code)
        for match in matches:
            var_name = match.group(1)
            variables[var_name] = f"context.{var_name}"

        # 匹配 context['key'] = value
        context_pattern = r"context\[['\"]([^'\"]+)['\"]\s*="
        matches = re.finditer(context_pattern, code)
        for match in matches:
            var_name = match.group(1)
            variables[var_name] = f"context.{var_name}"

        return variables

    def _add_variable_definition(
        self,
        var_name: str,
        source_node_id: str,
        source_node_label: str,
        source_node_type: str,
        scope: str,
        path: str,
        description: Optional[str] = None,
        value_type: Optional[str] = None,
    ) -> None:
        """添加变量定义。"""
        if var_name not in self.variable_definitions:
            self.variable_definitions[var_name] = []

        definition = VariableDefinition(
            name=var_name,
            source_node_id=source_node_id,
            source_node_label=source_node_label,
            source_node_type=source_node_type,
            scope=scope,
            path=path,
            description=description,
            value_type=value_type,
        )
        self.variable_definitions[var_name].append(definition)

    def _add_variable_usage(
        self,
        var_name: str,
        used_in_node_id: str,
        used_in_node_label: str,
        used_in_node_type: str,
        usage_type: str,
        expression: str,
        path: str,
    ) -> None:
        """添加变量使用。"""
        if var_name not in self.variable_usages:
            self.variable_usages[var_name] = []

        usage = VariableUsage(
            name=var_name,
            used_in_node_id=used_in_node_id,
            used_in_node_label=used_in_node_label,
            used_in_node_type=used_in_node_type,
            usage_type=usage_type,
            expression=expression,
            path=path,
        )
        self.variable_usages[var_name].append(usage)

    def get_available_variables_for_node(self, node_id: str, include_scoped: bool = True) -> List[Dict[str, Any]]:
        """获取节点可用的变量列表。

        Args:
            node_id: 节点 ID
            include_scoped: 是否包含作用域变量（loop_states, task_states 等）

        Returns:
            变量列表，每个变量包含 name, path, source, scope 等信息
        """
        # 找到节点在图中的位置（上游节点）
        upstream_nodes = self._get_upstream_nodes(node_id)

        available_vars = []

        # 全局变量（总是可用）
        global_vars = [
            {
                "name": "current_node",
                "path": "state.current_node",
                "source": "system",
                "scope": "global",
                "description": "Current executing node ID",
                "value_type": "string",
            },
            {
                "name": "route_decision",
                "path": "state.route_decision",
                "source": "system",
                "scope": "global",
                "description": "Latest route decision from router/condition nodes",
                "value_type": "string",
            },
            {
                "name": "loop_count",
                "path": "state.loop_count",
                "source": "system",
                "scope": "global",
                "description": "Global loop iteration count",
                "value_type": "number",
            },
            {
                "name": "messages",
                "path": "state.messages",
                "source": "system",
                "scope": "global",
                "description": "List of messages in the conversation",
                "value_type": "array",
            },
            {
                "name": "todos",
                "path": "state.todos",
                "source": "system",
                "scope": "global",
                "description": "List of todos/tasks",
                "value_type": "array",
            },
            {
                "name": "task_results",
                "path": "state.task_results",
                "source": "system",
                "scope": "global",
                "description": "Results from parallel task execution",
                "value_type": "array",
            },
            {
                "name": "parallel_results",
                "path": "state.parallel_results",
                "source": "system",
                "scope": "global",
                "description": "Generic parallel execution results",
                "value_type": "array",
            },
        ]
        available_vars.extend(global_vars)

        # 从上游节点收集定义的变量
        for upstream_node_id in upstream_nodes:
            for var_name, definitions in self.variable_definitions.items():
                for definition in definitions:
                    if definition.source_node_id == upstream_node_id:
                        available_vars.append(
                            {
                                "name": var_name,
                                "path": definition.path,
                                "source": definition.source_node_label,
                                "source_node_id": definition.source_node_id,
                                "scope": definition.scope,
                                "description": definition.description or "",
                                "value_type": definition.value_type or "",
                            }
                        )

        # 添加作用域变量（如果启用）
        if include_scoped:
            # 查找相关的循环节点
            loop_nodes = [n for n in self.nodes if (n.data or {}).get("type") == "loop_condition_node"]
            for loop_node in loop_nodes:
                available_vars.append(
                    {
                        "name": f"loop_count_{loop_node.id}",
                        "path": f"loop_states.{loop_node.id}.loop_count",
                        "source": (loop_node.data or {}).get("label", str(loop_node.id)),
                        "source_node_id": str(loop_node.id),
                        "scope": "loop",
                        "description": f"Loop count for loop '{loop_node.id}'",
                        "value_type": "number",
                    }
                )

        return available_vars

    def _get_upstream_nodes(self, node_id: str) -> List[str]:
        """获取节点的所有上游节点 ID。"""
        upstream = []
        visited = set()

        def traverse(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)

            for edge in self.edges:
                if str(edge.target_node_id) == node_id:
                    upstream.append(str(edge.source_node_id))
                    traverse(str(edge.source_node_id))

        traverse(node_id)
        return upstream

    def validate_variable_usage(self, node_id: str, expression: str) -> List[Dict[str, Any]]:
        """验证表达式中使用的变量是否可用。

        Returns:
            错误列表，每个错误包含 variable_name, error_message
        """
        errors = []
        available_vars = self.get_available_variables_for_node(node_id)
        available_var_names = {v["name"] for v in available_vars}
        available_var_paths = {v["path"] for v in available_vars}

        used_vars = self._extract_variables_from_expression(expression)

        for var_name, var_path in used_vars.items():
            # 检查变量名是否可用
            if var_name not in available_var_names:
                # 检查路径是否可用
                if var_path not in available_var_paths:
                    errors.append(
                        {
                            "variable_name": var_name,
                            "variable_path": var_path,
                            "error_message": f"Variable '{var_name}' is not available in this context",
                            "suggestion": f"Available variables: {', '.join(available_var_names)}",
                        }
                    )

        return errors
