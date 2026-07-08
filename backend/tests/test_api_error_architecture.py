import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

API_V1_FILES = sorted(Path("backend/app/joysafeter_api/api/v1").glob("*.py"))
SCHEDULER_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs")
GRPC_SERVER_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")
PY_ASYNC_BOUNDARY_ROOTS = (
    Path("backend/app/joysafeter_api"),
    Path("backend/app/joysafeter_domain/services"),
    Path("backend/app/joysafeter_shared/orchestrator_bridge"),
    Path("backend/app/joysafeter_worker"),
)
LOGGER_FAILURE_METHODS = {"warning", "error", "exception"}
EXCEPTION_ARG_NAMES = {"e", "exc", "err", "error", "result"}
HIGH_SIGNAL_BOUNDARY_TERMS = (
    "failed",
    "redis",
    "oidc",
    "token exchange",
    "orphan",
    "cleanup",
    "scan",
    "provision",
    "destroy",
    "lease",
    "wakeup",
    "sync",
    "oauth",
    "vaultcipher",
    "decryption",
    "inject",
    "dispatch task",
    "memory sync",
    "down",
    "timeout",
    "cancelled",
    "deadline",
)
STATE_BOUNDARY_TERMS = HIGH_SIGNAL_BOUNDARY_TERMS + (
    "sandbox",
    "setupsandbox",
    "rejecting",
    "stale",
    "cas conflict",
    "terminal",
    "not running",
    "unexpected status",
    "no external_id",
    "failure threshold",
    "idle before result",
    "incomplete",
    "requeued",
)

OLD_ORCHESTRATOR_MODULE = "app." + "joysafeter_orchestrator"
PRODUCTION_PY_ROOTS = (
    Path("backend/app/joysafeter_api"),
    Path("backend/app/joysafeter_domain"),
    Path("backend/app/joysafeter_shared"),
    Path("backend/app/joysafeter_worker"),
)
REQUIRED_BRIDGE_EXPORTS = {
    "ensure_session_broadcaster",
    "get_bridge_registry",
    "get_envoy_manager",
    "get_image_builder",
    "get_memory_subscribers",
    "get_redis_coordinator",
    "get_sandbox_provider",
    "get_sandbox_resolver",
    "get_scheduler",
    "get_session_broadcaster",
    "set_bridge_registry",
    "set_envoy_manager",
    "set_image_builder",
    "set_memory_subscribers",
    "set_redis_coordinator",
    "set_sandbox_provider",
    "set_sandbox_resolver",
    "set_scheduler",
    "set_session_broadcaster",
}


def _logger_failure_method(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in LOGGER_FAILURE_METHODS:
        return func.attr
    return None


def _literal_log_message(call: ast.Call) -> str:
    if not call.args:
        return ""
    first_arg = call.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    if isinstance(first_arg, ast.JoinedStr):
        return "".join(
            value.value
            for value in first_arg.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return ""


def _dict_has_error_key(node: ast.AST) -> bool:
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "error" for key in node.keys
    )


def _call_has_extra_error(call: ast.Call) -> bool:
    return any(keyword.arg == "extra" and _dict_has_error_key(keyword.value) for keyword in call.keywords)


def _expression_binds_error(node: ast.AST) -> bool:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            if current.func.attr == "bind" and any(keyword.arg == "error" for keyword in current.keywords):
                return True
            stack.append(current.func.value)
        elif isinstance(current, ast.Attribute):
            stack.append(current.value)
    return False


def _call_has_bound_error(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and _expression_binds_error(call.func.value)


def _call_has_truthy_exception_keyword(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg not in {"exc_info", "exception"}:
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value in {False, None}:
            continue
        return True
    return False


def _call_passes_exception_like_arg(call: ast.Call) -> bool:
    return any(isinstance(arg, ast.Name) and arg.id in EXCEPTION_ARG_NAMES for arg in call.args[1:])


def _is_high_signal_boundary_log(call: ast.Call, method: str) -> bool:
    message = _literal_log_message(call).lower()
    if method == "exception":
        return True
    if _call_has_truthy_exception_keyword(call):
        return True
    return _call_passes_exception_like_arg(call) and any(term in message for term in HIGH_SIGNAL_BOUNDARY_TERMS)


def _is_state_boundary_log(call: ast.Call) -> bool:
    message = _literal_log_message(call).lower()
    return any(term in message for term in STATE_BOUNDARY_TERMS)


def _has_structured_error_payload(call: ast.Call) -> bool:
    return _call_has_extra_error(call) or _call_has_bound_error(call)


def test_api_error_descriptors_use_semantic_app_errors():
    offenders: list[str] = []
    manual_detail_pattern = re.compile(r"detail\s*=\s*\{[^}]*[\"']code[\"']", re.DOTALL)
    raw_conflict_pattern = re.compile(r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?409\b")
    raw_runtime_failure_pattern = re.compile(r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?5\d\d\b")
    raw_client_error_pattern = re.compile(r"raise\s+HTTPException\s*\(\s*(?:status_code\s*=\s*)?[34]\d\d\b")
    stringified_exception_pattern = re.compile(
        r"HTTPException\s*\([^)]*(?:str\((?:e|exc)\)|detail\s*=\s*str\((?:e|exc)\))"
    )
    raw_config_dependency_pattern = re.compile(
        r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?(?:400|422)\b[^)]*(?:"
        r"Secret not found|Environment not found|"
        r"Secret missing|Invalid OPENAI_BASE_URL|Invalid ANTHROPIC_BASE_URL|"
        r"MCP server URL must use HTTPS|Duplicate MCP server name|Tool references undeclared MCP server|"
        r"not compatible with engine_kind"
        r")"
    )
    raw_resource_reference_pattern = re.compile(
        r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?(?:400|404)\b[^)]*(?:"
        r"Agent not found|Session not found|Invalid agent id|Agent version .* not found|"
        r"Invalid ID|"
        r"Invalid file_id|File not found|Memory store not found|Invalid vault_id|Vault not found|Credential not found|"
        r"Secret not found|Environment not found|Sandbox not found|Task not found|Memory not found|"
        r"Memory version not found|"
        r"Organization not found|Member not found|Project not found|API key not found|"
        r"No default project found|User not found with the given email|"
        r"Skill file not found|"
        r"Request body must be an object|Invalid file resource|Invalid repo resource|Unsupported resource type|"
        r"Repo url is required|repo resource url is required|Invalid resource_id|Resource not found|"
        r"Repo resource not found|Too many file resources|Too many repo resources|Too many memory_store resources|"
        r"mount_path must be under /workspace/|mount_path must not contain"
        r")"
    )
    raw_input_validation_pattern = re.compile(
        r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?(?:400|422)\b[^)]*(?:"
        r"Metadata exceeds maximum|Metadata keys must be strings|Metadata key length must|"
        r"Metadata values must be strings|Metadata value exceeds|Path must start with|Path exceeds|"
        r"Path must not contain|Content exceeds|order_by must be one of|order must be|"
        r"Each content block must be an object|Content blocks must have type|"
        r"Content blocks array must not be empty|content must be a string|No events provided|"
        r"user\\.message requires content|Invalid member role|Cannot transfer ownership to yourself|"
        r"Cannot remove the owner|Cannot archive the default project|Organization name is required"
        r")"
    )
    raw_permission_pattern = re.compile(
        r"HTTPException\s*\(\s*(?:status_code\s*=\s*)?403\b[^)]*(?:"
        r"Cannot grant a role higher than your own|Cannot change the owner's role|"
        r"Cannot modify or grant a role higher than your own|"
        r"User is not a member of the target organization|"
        r"Only organization owners can assign owner role|No access to organization|"
        r"Insufficient permission|Only the organization owner can delete it|"
        r"Only the organization owner can transfer ownership|"
        r"Cannot remove a member with a higher role than your own|"
        r"不能授予高于自身权限的角色|无法修改所有者的角色|不能修改或授予高于自身权限的角色"
        r")"
    )

    for file_path in API_V1_FILES:
        text = file_path.read_text()
        if "http_error" in text or "http_errors" in text:
            offenders.append(f"{file_path}: parallel http_error helper instead of semantic AppError")
        if re.search(r"def\s+_session_[a-zA-Z0-9_]*_error\s*\(", text):
            offenders.append(f"{file_path}: local _session_*_error factory instead of semantic AppError")
        if "_api_error_detail" in text:
            offenders.append(f"{file_path}: local _api_error_detail helper")
        if manual_detail_pattern.search(text):
            offenders.append(f"{file_path}: manual structured HTTPException detail")
        if raw_client_error_pattern.search(text):
            offenders.append(f"{file_path}: raw HTTPException client error instead of semantic AppError")
        if raw_conflict_pattern.search(text):
            offenders.append(f"{file_path}: raw HTTPException 409 instead of semantic AppError")
        if raw_runtime_failure_pattern.search(text):
            offenders.append(f"{file_path}: raw HTTPException 5xx instead of semantic AppError")
        if stringified_exception_pattern.search(text):
            offenders.append(f"{file_path}: stringified exception passed directly to HTTPException")
        if raw_config_dependency_pattern.search(text):
            offenders.append(f"{file_path}: raw configuration dependency error instead of semantic AppError")
        if raw_resource_reference_pattern.search(text):
            offenders.append(f"{file_path}: raw resource reference error instead of semantic AppError")
        if raw_input_validation_pattern.search(text):
            offenders.append(f"{file_path}: raw input validation error instead of semantic AppError")
        if raw_permission_pattern.search(text):
            offenders.append(f"{file_path}: raw permission error instead of semantic AppError")

    assert offenders == []


def test_parallel_error_helper_modules_are_not_reintroduced():
    assert not Path("backend/app/joysafeter_shared/common/http_errors.py").exists()
    assert not Path("backend/app/joysafeter_api/api/v1/boundary_errors.py").exists()
    assert not Path("backend/app/joysafeter_domain/services/boundary_errors.py").exists()


def test_python_orchestrator_source_is_not_reintroduced():
    source_files = [
        path
        for path in Path("backend/app/joysafeter_orchestrator").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert source_files == []


def test_python_services_do_not_import_removed_orchestrator_package():
    offenders: list[str] = []

    for root in PRODUCTION_PY_ROOTS:
        for file_path in sorted(root.rglob("*.py")):
            tree = ast.parse(file_path.read_text(), filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == OLD_ORCHESTRATOR_MODULE or node.module.startswith(f"{OLD_ORCHESTRATOR_MODULE}."):
                        offenders.append(f"{file_path}:{node.lineno}: from {node.module} import ...")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == OLD_ORCHESTRATOR_MODULE or alias.name.startswith(f"{OLD_ORCHESTRATOR_MODULE}."):
                            offenders.append(f"{file_path}:{node.lineno}: import {alias.name}")

    assert offenders == []


def test_tests_do_not_target_removed_python_orchestrator_package():
    offenders: list[str] = []
    this_file = Path(__file__).resolve()

    for file_path in sorted(Path("backend/tests").rglob("*.py")):
        if file_path.resolve() == this_file:
            continue
        text = file_path.read_text()
        if OLD_ORCHESTRATOR_MODULE in text:
            offenders.append(str(file_path))

    assert offenders == []


def test_orchestrator_bridge_exports_runtime_boundary_contract():
    from app.joysafeter_shared import orchestrator_bridge

    missing = sorted(name for name in REQUIRED_BRIDGE_EXPORTS if not hasattr(orchestrator_bridge, name))
    assert missing == []


def test_api_v1_async_error_boundaries_use_shared_contract_builders():
    offenders: list[str] = []
    raw_websocket_error_pattern = re.compile(
        r"send_json\s*\(\s*\{\s*[\"']type[\"']\s*:\s*[\"']error[\"']",
        re.DOTALL,
    )
    raw_stop_reason_pattern = re.compile(
        r"stop_reason\s*=\s*\{\s*[\"']type[\"']\s*:\s*[\"']error[\"']",
        re.DOTALL,
    )

    for file_path in API_V1_FILES:
        text = file_path.read_text()
        if raw_websocket_error_pattern.search(text):
            offenders.append(f"{file_path}: raw WebSocket error payload instead of async_error_payload")
        if raw_stop_reason_pattern.search(text):
            offenders.append(f"{file_path}: raw error stop_reason instead of async_error_payload")
    scheduler_text = SCHEDULER_FILE.read_text()
    if re.search(r"\{\s*[\"']type[\"']\s*:\s*[\"']error[\"']\s*,\s*[\"']message[\"']", scheduler_text, re.DOTALL):
        offenders.append(f"{SCHEDULER_FILE}: raw scheduler error event instead of async_error_payload")
    grpc_text = GRPC_SERVER_FILE.read_text()
    if re.search(
        r"(?:stop_reason\s*=|return)\s*\{\s*[\"']type[\"']\s*:\s*[\"']error[\"']\s*,\s*[\"'](?:message|error)[\"']",
        grpc_text,
        re.DOTALL,
    ):
        offenders.append(f"{GRPC_SERVER_FILE}: raw gRPC error stop_reason/event instead of async_error_payload")

    assert offenders == []


def test_high_signal_async_boundary_logs_include_structured_error_payload():
    offenders: list[str] = []

    for root in PY_ASYNC_BOUNDARY_ROOTS:
        for file_path in sorted(root.rglob("*.py")):
            if file_path.name == "boundary_errors.py":
                continue
            tree = ast.parse(file_path.read_text(), filename=str(file_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                method = _logger_failure_method(node)
                if method is None:
                    continue
                if not _is_high_signal_boundary_log(node, method):
                    continue
                if _has_structured_error_payload(node):
                    continue
                offenders.append(f"{file_path}:{node.lineno}: {method} {_literal_log_message(node)!r}")

    assert offenders == []


def test_state_boundary_logs_include_structured_error_payload():
    offenders: list[str] = []

    for root in PY_ASYNC_BOUNDARY_ROOTS:
        for file_path in sorted(root.rglob("*.py")):
            if file_path.name == "boundary_errors.py":
                continue
            tree = ast.parse(file_path.read_text(), filename=str(file_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                method = _logger_failure_method(node)
                if method is None:
                    continue
                if not _is_state_boundary_log(node):
                    continue
                if _has_structured_error_payload(node):
                    continue
                offenders.append(f"{file_path}:{node.lineno}: {method} {_literal_log_message(node)!r}")

    assert offenders == []
