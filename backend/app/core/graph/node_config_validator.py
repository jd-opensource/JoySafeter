"""
Node Configuration Validator - Unified validation using JSON schema.

This module now uses the unified validation system for consistency
between frontend and backend validation logic.
"""

from typing import Any, Dict, List

from loguru import logger

from .unified_validator import validate_node_config_as_strings


class NodeConfigValidator:
    """节点配置验证器 - 现在使用统一的验证系统"""

    @classmethod
    def validate_node_config(cls, node_type: str, config: Dict[str, Any]) -> List[str]:
        """验证节点配置。

        Args:
            node_type: 节点类型
            config: 节点配置字典

        Returns:
            错误列表，如果为空则表示配置正确
        """
        try:
            errors = validate_node_config_as_strings(node_type, config)

            if errors:
                logger.warning(f"Node config validation failed for '{node_type}': {', '.join(errors)}")

            return errors
        except Exception as e:
            logger.error(f"Validation error for node type '{node_type}': {e}")
            return [f"Validation system error: {str(e)}"]

    # 保持向后兼容的静态方法
    @staticmethod
    def validate_router_node(config: Dict[str, Any]) -> List[str]:
        """验证 Router 节点配置（向后兼容）"""
        return validate_node_config_as_strings("router_node", config)

    @staticmethod
    def validate_loop_condition_node(config: Dict[str, Any]) -> List[str]:
        """验证 Loop Condition 节点配置（向后兼容）"""
        return validate_node_config_as_strings("loop_condition_node", config)

    @staticmethod
    def validate_tool_node(config: Dict[str, Any]) -> List[str]:
        """验证 Tool 节点配置（向后兼容）"""
        return validate_node_config_as_strings("tool_node", config)

    @staticmethod
    def validate_function_node(config: Dict[str, Any]) -> List[str]:
        """验证 Function 节点配置（向后兼容）"""
        return validate_node_config_as_strings("function_node", config)

    @staticmethod
    def validate_aggregator_node(config: Dict[str, Any]) -> List[str]:
        """验证 Aggregator 节点配置（向后兼容）"""
        return validate_node_config_as_strings("aggregator_node", config)

    @staticmethod
    def validate_json_parser_node(config: Dict[str, Any]) -> List[str]:
        """验证 JSON Parser 节点配置（向后兼容）"""
        return validate_node_config_as_strings("json_parser_node", config)

    @staticmethod
    def validate_http_request_node(config: Dict[str, Any]) -> List[str]:
        """验证 HTTP Request 节点配置（向后兼容）"""
        return validate_node_config_as_strings("http_request_node", config)
