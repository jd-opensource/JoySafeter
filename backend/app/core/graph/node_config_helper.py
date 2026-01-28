"""
Node Configuration Helper - Simplifies node configuration creation.

Provides helper functions to create node configurations with sensible defaults
and validation, making it easier for users to configure nodes.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.graph.node_config_validator import NodeConfigValidator


class NodeConfigHelper:
    """节点配置辅助工具，简化配置创建。"""

    @staticmethod
    def create_router_config(
        routes: List[Dict[str, Any]],
        defaultRoute: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建 Router 节点配置。

        Args:
            routes: 路由规则列表，每个规则包含 condition, targetEdgeKey, label, priority
            defaultRoute: 默认路由键（可选）

        Returns:
            配置字典

        Example:
            config = NodeConfigHelper.create_router_config([
                {
                    "id": "rule_1",
                    "condition": "state.get('value', 0) > 10",
                    "targetEdgeKey": "high",
                    "label": "High Score",
                    "priority": 0,
                },
                {
                    "id": "rule_2",
                    "condition": "state.get('value', 0) > 5",
                    "targetEdgeKey": "medium",
                    "label": "Medium Score",
                    "priority": 1,
                },
            ], defaultRoute="default")
        """
        config: Dict[str, Any] = {"routes": routes}

        if defaultRoute:
            config["defaultRoute"] = defaultRoute

        # 验证配置
        errors = NodeConfigValidator.validate_node_config("router_node", config)
        if errors:
            logger.warning(f"Router config validation errors: {errors}")

        return config

    @staticmethod
    def create_loop_condition_config(
        conditionType: str = "while",
        condition: Optional[str] = None,
        listVariable: Optional[str] = None,
        maxIterations: int = 5,
    ) -> Dict[str, Any]:
        """创建 Loop Condition 节点配置。

        Args:
            conditionType: 循环类型 ('forEach', 'while', 'doWhile')
            condition: 循环条件表达式（for while/doWhile）
            listVariable: 列表变量名（for forEach）
            maxIterations: 最大迭代次数（默认 5）

        Returns:
            配置字典

        Example:
            # While loop
            config = NodeConfigHelper.create_loop_condition_config(
                conditionType="while",
                condition="loop_count < 3 and state.get('has_error') == False",
                maxIterations=5,
            )

            # ForEach loop
            config = NodeConfigHelper.create_loop_condition_config(
                conditionType="forEach",
                listVariable="items",
                maxIterations=10,
            )
        """
        config = {
            "conditionType": conditionType,
            "maxIterations": maxIterations,
        }

        if conditionType == "forEach":
            if not listVariable:
                raise ValueError("'listVariable' is required for forEach conditionType")
            config["listVariable"] = listVariable
        else:
            if not condition:
                raise ValueError("'condition' is required for while/doWhile conditionType")
            config["condition"] = condition

        # 验证配置
        errors = NodeConfigValidator.validate_node_config("loop_condition_node", config)
        if errors:
            logger.warning(f"Loop condition config validation errors: {errors}")

        return config

    @staticmethod
    def create_tool_config(
        tool_name: str,
        input_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """创建 Tool 节点配置。

        Args:
            tool_name: 工具名称
            input_mapping: 输入映射（可选）

        Returns:
            配置字典

        Example:
            config = NodeConfigHelper.create_tool_config(
                tool_name="search_google",
                input_mapping={"query": "state.context.get('user_query')"},
            )
        """
        config = {
            "tool_name": tool_name,
            "input_mapping": input_mapping or {},
        }

        # 验证配置
        errors = NodeConfigValidator.validate_node_config("tool_node", config)
        if errors:
            logger.warning(f"Tool config validation errors: {errors}")

        return config

    @staticmethod
    def create_function_config(
        function_name: Optional[str] = None,
        function_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建 Function 节点配置。

        Args:
            function_name: 预定义函数名称（可选）
            function_code: 自定义代码（可选）

        Returns:
            配置字典

        Example:
            # 使用预定义函数
            config = NodeConfigHelper.create_function_config(
                function_name="math_add",
            )

            # 使用自定义代码
            config = NodeConfigHelper.create_function_config(
                function_code="result = {'output': state.get('value', 0) * 2}",
            )
        """
        config = {}

        if function_name:
            config["function_name"] = function_name
        elif function_code:
            config["function_code"] = function_code
        else:
            raise ValueError("Either 'function_name' or 'function_code' must be provided")

        # 验证配置
        errors = NodeConfigValidator.validate_function_node(config)
        if errors:
            logger.warning(f"Function config validation errors: {errors}")

        return config

    @staticmethod
    def create_aggregator_config(
        error_strategy: str = "best_effort",
    ) -> Dict[str, Any]:
        """创建 Aggregator 节点配置。

        Args:
            error_strategy: 错误处理策略（'fail_fast' 或 'best_effort'）

        Returns:
            配置字典
        """
        config = {"error_strategy": error_strategy}

        # 验证配置
        errors = NodeConfigValidator.validate_aggregator_node(config)
        if errors:
            logger.warning(f"Aggregator config validation errors: {errors}")

        return config

    @staticmethod
    def create_json_parser_config(
        jsonpath_query: Optional[str] = None,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建 JSON Parser 节点配置。

        Args:
            jsonpath_query: JSONPath 查询表达式（可选）
            json_schema: JSON Schema（可选）

        Returns:
            配置字典
        """
        config: Dict[str, Any] = {}

        if jsonpath_query:
            config["jsonpath_query"] = jsonpath_query
        if json_schema:
            config["json_schema"] = json_schema

        if not config:
            raise ValueError("Either 'jsonpath_query' or 'json_schema' must be provided")

        # 验证配置
        errors = NodeConfigValidator.validate_json_parser_node(config)
        if errors:
            logger.warning(f"JSON parser config validation errors: {errors}")

        return config

    @staticmethod
    def create_http_request_config(
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        auth: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """创建 HTTP Request 节点配置。

        Args:
            url: 请求 URL
            method: HTTP 方法（默认 GET）
            headers: HTTP 头（可选）
            auth: 认证配置（可选）
            max_retries: 最大重试次数（默认 3）
            timeout: 超时时间（秒，默认 30.0）

        Returns:
            配置字典
        """
        config = {
            "method": method,
            "url": url,
            "headers": headers or {},
            "auth": auth or {"type": "none"},
            "max_retries": max_retries,
            "timeout": timeout,
        }

        # 验证配置
        errors = NodeConfigValidator.validate_http_request_node(config)
        if errors:
            logger.warning(f"HTTP request config validation errors: {errors}")

        return config
