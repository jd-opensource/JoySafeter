"""
Unified Node Configuration Validator

Provides unified validation logic for both frontend and backend.
Uses JSON schema-based validation rules to ensure consistency.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class ValidationError:
    """统一验证错误结构"""

    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "message": self.message, "severity": self.severity}


class UnifiedValidator:
    """统一的节点配置验证器"""

    def __init__(self):
        self.rules = {}
        self._validation_cache = {}
        self._cache_max_size = 100
        self._load_rules()

    def _load_rules(self):
        """加载验证规则"""
        rules_path = Path(__file__).parent / "node_validation_rules.json"
        if not rules_path.exists():
            raise FileNotFoundError(f"Validation rules file not found: {rules_path}")

        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.rules = data.get("rules", {})

    def _validate_field(
        self, field_name: str, field_config: Dict[str, Any], value: Any, config: Dict[str, Any]
    ) -> List[ValidationError]:
        """验证单个字段"""
        errors = []

        # 检查必需性
        if field_config.get("required", False) and (value is None or value == ""):
            errors.append(
                ValidationError(field_name, field_config["errorMessages"].get("required", f"{field_name} is required"))
            )
            return errors  # 如果必需字段为空，后续验证无意义

        # 如果值为空且非必需，跳过验证
        if value is None or value == "":
            return errors

        # 类型检查
        expected_types = field_config["type"]
        if isinstance(expected_types, str):
            expected_types = [expected_types]

        if not any(self._check_type(value, t) for t in expected_types):
            errors.append(
                ValidationError(field_name, field_config["errorMessages"].get("type", f"{field_name} has invalid type"))
            )
            return errors

        # 数值范围检查
        if field_config.get("type") in ["number", ["number"]]:
            if "minimum" in field_config and value < field_config["minimum"]:
                errors.append(
                    ValidationError(
                        field_name, field_config["errorMessages"].get("minimum", f"{field_name} is too small")
                    )
                )
            if "maximum" in field_config and value > field_config["maximum"]:
                errors.append(
                    ValidationError(
                        field_name, field_config["errorMessages"].get("maximum", f"{field_name} is too large")
                    )
                )

        # 字符串长度检查
        if field_config.get("type") in ["string", ["string"]]:
            if "minLength" in field_config and len(str(value)) < field_config["minLength"]:
                errors.append(
                    ValidationError(
                        field_name, field_config["errorMessages"].get("minLength", f"{field_name} is too short")
                    )
                )

        # 枚举值检查
        if "enum" in field_config and value not in field_config["enum"]:
            errors.append(
                ValidationError(
                    field_name, field_config["errorMessages"].get("enum", f"{field_name} has invalid value")
                )
            )

        # 正则表达式检查
        if "pattern" in field_config:
            import re

            if not re.match(field_config["pattern"], str(value)):
                errors.append(
                    ValidationError(
                        field_name, field_config["errorMessages"].get("pattern", f"{field_name} format is invalid")
                    )
                )

        # 数组检查
        if field_config.get("type") in ["array", ["array"]]:
            if "minLength" in field_config and len(value) < field_config["minLength"]:
                errors.append(
                    ValidationError(
                        field_name, field_config["errorMessages"].get("minLength", f"{field_name} needs more items")
                    )
                )

            # 验证数组项
            if "items" in field_config and isinstance(value, list):
                item_schema = field_config["items"]
                for i, item in enumerate(value):
                    item_errors = self._validate_field(f"{field_name}[{i}]", item_schema, item, config)
                    errors.extend(item_errors)

        # 对象字段检查
        if field_config.get("type") in ["object", ["object"]] and "fields" in field_config:
            if isinstance(value, dict):
                for sub_field_name, sub_field_config in field_config["fields"].items():
                    sub_value = value.get(sub_field_name)
                    sub_errors = self._validate_field(
                        f"{field_name}.{sub_field_name}", sub_field_config, sub_value, config
                    )
                    errors.extend(sub_errors)

        return errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值类型"""
        type_checks = {
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)),
            "boolean": lambda v: isinstance(v, bool),
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
        }

        check_func = type_checks.get(expected_type)
        return check_func(value) if check_func else False

    def _validate_conditional_required(
        self, field_name: str, field_config: Dict[str, Any], config: Dict[str, Any]
    ) -> List[ValidationError]:
        """验证条件必需字段"""
        errors = []

        if "conditionalRequired" in field_config:
            condition_config = field_config["conditionalRequired"]
            condition_expr = condition_config["condition"]

            # 简单条件评估 (可以扩展为更复杂的表达式)
            should_be_required = self._evaluate_simple_condition(condition_expr, config)

            if should_be_required:
                value = config.get(field_name)
                if value is None or value == "":
                    errors.append(ValidationError(field_name, condition_config["errorMessage"]))

        return errors

    def _evaluate_simple_condition(self, condition: str, config: Dict[str, Any]) -> bool:
        """评估简单条件表达式"""
        # 这是一个简化的条件评估器
        # 可以扩展为支持更复杂的表达式

        if condition == "conditionType in ['while', 'doWhile'] or conditionType is null":
            condition_type = config.get("conditionType")
            return condition_type in ["while", "doWhile"] or condition_type is None

        elif condition == "conditionType == 'forEach'":
            return config.get("conditionType") == "forEach"

        elif condition == "function_name or function_code":
            return bool(config.get("function_name") or config.get("function_code"))

        elif condition == "jsonpath_query or json_schema":
            return bool(config.get("jsonpath_query") or config.get("json_schema"))

        return False

    def _validate_exclusive_fields(
        self, field_name: str, field_config: Dict[str, Any], config: Dict[str, Any]
    ) -> List[ValidationError]:
        """验证互斥字段"""
        errors = []

        if "exclusiveWith" in field_config:
            exclusive_fields = field_config["exclusiveWith"]
            current_value = config.get(field_name)

            if current_value is not None:
                for exclusive_field in exclusive_fields:
                    if config.get(exclusive_field) is not None:
                        errors.append(
                            ValidationError(field_name, f"Cannot specify both {field_name} and {exclusive_field}")
                        )
                        break

        return errors

    def _validate_custom_rules(self, node_type: str, config: Dict[str, Any]) -> List[ValidationError]:
        """验证自定义规则"""
        errors = []
        node_rule = self.rules.get(node_type, {})

        if "customValidation" in node_rule:
            custom_config = node_rule["customValidation"]

            # Handle both old format (single condition) and new format (rules array)
            if "rules" in custom_config:
                # New format with multiple rules
                for rule in custom_config["rules"]:
                    rule_name = rule["name"]
                    condition = rule["condition"]
                    error_message = rule["errorMessage"]

                    try:
                        if not self._evaluate_complex_condition(condition, config):
                            errors.append(
                                ValidationError(
                                    f"config.{rule_name}",
                                    error_message,
                                    "warning",  # Custom rules are usually warnings
                                )
                            )
                    except Exception as e:
                        logger.warning(f"[UnifiedValidator] Error evaluating custom rule '{rule_name}': {e}")
            elif "condition" in custom_config:
                # Old format for backward compatibility
                condition = custom_config["condition"]
                if not self._evaluate_simple_condition(condition, config):
                    errors.append(ValidationError("config", custom_config["message"]))

        return errors

    def _evaluate_complex_condition(self, condition: str, config: Dict[str, Any]) -> bool:
        """
        Evaluate complex conditions that involve list comprehensions and set operations.

        This is a more powerful condition evaluator for custom validation rules.
        """
        try:
            # Create a safe evaluation context
            eval_context = {
                "config": config,
                "len": len,
                "set": set,
                "list": list,
                "dict": dict,
                "str": str,
                "int": int,
                "bool": bool,
                "all": all,
                "any": any,
            }

            # Add config keys as variables for easier access
            for key, value in config.items():
                if isinstance(key, str) and key.isidentifier():
                    eval_context[key] = value

            result = eval(condition, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            logger.warning(f"[UnifiedValidator] Error evaluating complex condition '{condition}': {e}")
            return False

    def validate_node_config(self, node_type: str, config: Dict[str, Any]) -> List[ValidationError]:
        """验证节点配置"""
        errors: List[ValidationError] = []

        if node_type not in self.rules:
            # 对于未知节点类型，不进行验证
            return errors

        # Generate cache key from node_type and config hash
        config_str = json.dumps(config, sort_keys=True, default=str)
        cache_key = f"{node_type}:{hash(config_str)}"

        # Check cache first
        if cache_key in self._validation_cache:
            cached = self._validation_cache[cache_key]
            if isinstance(cached, list):
                return cached.copy()
            return []

        # Perform validation

        node_rule = self.rules[node_type]
        fields_config = node_rule.get("fields", {})

        # 验证每个字段
        for field_name, field_config in fields_config.items():
            value = config.get(field_name)

            # 基础字段验证
            field_errors = self._validate_field(field_name, field_config, value, config)
            errors.extend(field_errors)

            # 条件必需验证
            conditional_errors = self._validate_conditional_required(field_name, field_config, config)
            errors.extend(conditional_errors)

            # 互斥字段验证
            exclusive_errors = self._validate_exclusive_fields(field_name, field_config, config)
            errors.extend(exclusive_errors)

        # 自定义验证规则
        custom_errors = self._validate_custom_rules(node_type, config)
        errors.extend(custom_errors)

        # Cache the results (only if no errors, or cache with short TTL for errors)
        if len(self._validation_cache) < self._cache_max_size:
            self._validation_cache[cache_key] = errors.copy()

        return errors


# 全局验证器实例
_validator_instance = None


def get_validator() -> UnifiedValidator:
    """获取全局验证器实例"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = UnifiedValidator()
        return _validator_instance

    def clear_cache(self):
        """Clear validation cache"""
        self._validation_cache.clear()

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return {
            "cache_size": len(self._validation_cache),
            "max_size": self._cache_max_size,
            "utilization_percent": int(len(self._validation_cache) / self._cache_max_size * 100),
        }


def validate_node_config(node_type: str, config: Dict[str, Any]) -> List[ValidationError]:
    """验证节点配置的便捷函数"""
    validator = get_validator()
    return validator.validate_node_config(node_type, config)


def validate_node_config_as_strings(node_type: str, config: Dict[str, Any]) -> List[str]:
    """验证节点配置，返回字符串列表（向后兼容）"""
    errors = validate_node_config(node_type, config)
    return [error.message for error in errors]


def validate_node_config_as_dicts(node_type: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """验证节点配置，返回字典列表（前端格式）"""
    errors = validate_node_config(node_type, config)
    return [error.to_dict() for error in errors]


def format_validation_errors_for_frontend(errors: List[ValidationError]) -> Dict[str, Any]:
    """
    Format validation errors for frontend consumption with categorization, suggestions, and examples.

    Args:
        errors: List of validation errors

    Returns:
        Dict with categorized errors, suggestions, and examples
    """
    categorized: Dict[str, List[Any]] = {
        "critical": [],  # Blocking errors
        "warnings": [],  # Non-blocking issues
        "suggestions": [],  # Improvement suggestions
    }

    for error in errors:
        formatted_error = {
            "field": error.field,
            "message": error.message,
            "severity": error.severity,
            "category": _categorize_error_field(error.field),
            "fixSuggestion": _suggest_fix_for_error(error),
            "example": _provide_error_example(error),
            "relatedFields": _find_related_fields(error.field),
        }

        if error.severity == "error":
            categorized["critical"].append(formatted_error)
        elif error.severity == "warning":
            categorized["warnings"].append(formatted_error)
        else:
            categorized["suggestions"].append(formatted_error)

    return {
        "totalErrors": len(errors),
        "criticalCount": len(categorized["critical"]),
        "warningCount": len(categorized["warnings"]),
        "suggestionCount": len(categorized["suggestions"]),
        "errors": categorized,
        "canDeploy": len(categorized["critical"]) == 0,
        "summary": _generate_validation_summary(categorized),
    }


def _categorize_error_field(field: str) -> str:
    """Categorize error field for better UX"""
    if field.startswith("routes"):
        return "routing"
    elif field.startswith("condition"):
        return "logic"
    elif field in ["tool_name", "function_name", "model"]:
        return "configuration"
    elif "loop" in field.lower():
        return "flow_control"
    else:
        return "general"


def _suggest_fix_for_error(error: ValidationError) -> Optional[str]:
    """Provide intelligent fix suggestions for common errors"""
    field = error.field.lower()
    message = error.message.lower()

    # Field-specific suggestions
    field_suggestions = {
        "routes": "Add route rules in the node configuration panel. Each route needs: condition, targetEdgeKey, and label.",
        "routes.condition": "Write a Python expression like: state.get('value', 0) > 10",
        "routes.targetedgekey": "Use a descriptive name like 'high_score' or 'approved'",
        "routes.label": "Provide a human-readable label like 'High Score' or 'Approved'",
        "condition": "Use expressions like: len(state.get('messages', [])) > 0 or state.get('status') == 'ready'",
        "conditiontype": "Choose 'while' for condition-based loops, 'forEach' for list iteration",
        "listvariable": "Specify the state key containing your list, e.g., 'items' or 'messages'",
        "maxiterations": "Set between 1-100. For safety, avoid very high numbers.",
        "tool_name": "Select from available tools like 'search_google' or 'calculate_sum'",
        "function_name": "Choose predefined functions or leave empty for custom code",
        "function_code": "Write Python code that assigns result to a 'result' variable",
        "model": "Select a model like 'DeepSeek-Chat' or 'gpt-4'",
        "prompt": "Write clear instructions, reference variables with {{variable_name}}",
        "jsonpath_query": "Use expressions like '$.data.items[*].name' to extract data",
        "json_schema": "Provide a JSON Schema object for validation",
        "url": "Must start with http:// or https://",
        "instruction": "Describe what you want the AI to decide, e.g., 'Route based on sentiment'",
        "options": "Provide 2+ options as strings, e.g., ['positive', 'negative', 'neutral']",
    }

    # Check for exact field matches first
    if field in field_suggestions:
        return field_suggestions[field]

    # Check for partial matches
    for key, suggestion in field_suggestions.items():
        if key in field or key in message:
            return suggestion

    # Pattern-based suggestions
    if "required" in message:
        return "This field cannot be empty. Please provide a value."
    elif "invalid" in message or "not allowed" in message:
        return "Check the format and allowed values for this field."
    elif "duplicate" in message:
        return "Ensure all values in this field are unique."
    elif "maximum" in message or "too large" in message:
        return "Reduce the value to be within the allowed range."
    elif "minimum" in message or "too small" in message:
        return "Increase the value to meet the minimum requirement."

    return "Check the field documentation for correct format and values."


def _provide_error_example(error: ValidationError) -> Optional[str]:
    """Provide concrete examples for fixing errors"""
    field = error.field.lower()

    examples = {
        "routes.condition": "state.get('score', 0) > 80",
        "routes.targetedgekey": "high_score",
        "condition": "state.get('status') == 'completed' and len(state.get('items', [])) > 0",
        "conditiontype": "while",
        "listvariable": "items",
        "maxiterations": "5",
        "tool_name": "search_web",
        "function_name": "math_add",
        "model": "DeepSeek-Chat",
        "prompt": "Analyze the sentiment of: {{user_message}}",
        "jsonpath_query": "$.response.data[*].title",
        "url": "https://api.example.com/data",
        "instruction": "Analyze the user's message and route to: positive, negative, or neutral",
        "options": '["positive", "negative", "neutral"]',
    }

    return examples.get(field)


def _find_related_fields(field: str) -> List[str]:
    """Find fields that are related to the error field"""
    field_relations = {
        "routes": ["routes.condition", "routes.targetEdgeKey", "routes.label", "defaultRoute"],
        "condition": ["conditionType", "listVariable", "maxIterations"],
        "tool_name": ["input_mapping"],
        "function_name": ["function_code"],
        "model": ["prompt"],
        "jsonpath_query": ["json_schema"],
        "url": ["method", "headers", "max_retries", "timeout"],
        "instruction": ["options"],
    }

    for key, related in field_relations.items():
        if key in field or field in related:
            return related

    return []


def _generate_validation_summary(categorized: Dict[str, List]) -> str:
    """Generate a human-readable validation summary"""
    total = len(categorized["critical"]) + len(categorized["warnings"]) + len(categorized["suggestions"])

    if total == 0:
        return "Configuration is valid and ready for deployment."

    parts = []
    if categorized["critical"]:
        parts.append(f"{len(categorized['critical'])} critical issue(s)")
    if categorized["warnings"]:
        parts.append(f"{len(categorized['warnings'])} warning(s)")
    if categorized["suggestions"]:
        parts.append(f"{len(categorized['suggestions'])} suggestion(s)")

    summary = f"Found {', '.join(parts)}."

    if categorized["critical"]:
        summary += " Fix critical issues before deployment."
    elif categorized["warnings"]:
        summary += " Consider addressing warnings for better reliability."

    return summary
