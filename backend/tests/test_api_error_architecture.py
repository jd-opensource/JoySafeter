import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

API_V1_FILES = sorted(Path("backend/app/joysafeter_api/api/v1").glob("*.py"))
SCHEDULER_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs")
RUNTIME_QUEUE_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/kernel/queue.rs")
ORCHESTRATOR_MAIN_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/main.rs")
REDIS_COORDINATOR_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/kernel/redis_coordinator.rs")
RUST_ORCHESTRATOR_SRC = Path("backend/app/joysafeter_orchestrator_rs/src")
GRPC_SERVER_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs")
DB_QUERIES_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/db/queries.rs")
SANDBOX_RESOLVER_FILE = Path("backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs")
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
DOMAIN_REPOSITORY_ROOT = Path("backend/app/joysafeter_domain/repositories")
DOMAIN_PAGINATION_FILE = Path("backend/app/joysafeter_domain/pagination.py")
SECRET_SERVICE_FILE = Path("backend/app/joysafeter_domain/services/joysafeter_secret_service.py")
REQUIRED_BRIDGE_EXPORTS = {
    "ensure_session_broadcaster",
    "get_session_broadcaster",
    "set_session_broadcaster",
}
REMOVED_BRIDGE_EXPORTS = {
    "get_bridge_registry",
    "get_envoy_manager",
    "get_image_builder",
    "get_memory_subscribers",
    "get_redis_coordinator",
    "get_sandbox_provider",
    "get_sandbox_resolver",
    "get_scheduler",
    "set_bridge_registry",
    "set_envoy_manager",
    "set_image_builder",
    "set_memory_subscribers",
    "set_redis_coordinator",
    "set_sandbox_provider",
    "set_sandbox_resolver",
    "set_scheduler",
    "ImageBuilder",
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


def test_non_api_layers_do_not_import_api_layer():
    offenders: list[str] = []
    roots = (
        Path("backend/app/joysafeter_domain"),
        Path("backend/app/joysafeter_shared"),
        Path("backend/app/joysafeter_worker"),
    )

    for file_path in sorted(path for root in roots for path in root.rglob("*.py")):
        tree = ast.parse(file_path.read_text())
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = [node.module]

            for module in imported_modules:
                if module == "app.joysafeter_api" or module.startswith("app.joysafeter_api."):
                    offenders.append(f"{file_path}:{node.lineno}: {module}")

    assert offenders == []


def test_domain_services_do_not_import_auth_dependency_package():
    offenders: list[str] = []

    for file_path in sorted(Path("backend/app/joysafeter_domain/services").rglob("*.py")):
        tree = ast.parse(file_path.read_text(), filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module == "app.joysafeter_shared.common.joysafeter_auth":
                offenders.append(f"{file_path}:{node.lineno}: import auth context from .joysafeter_auth.context")

    assert offenders == []


def test_auth_context_import_does_not_eagerly_load_dependency_layer():
    text = Path("backend/app/joysafeter_shared/common/joysafeter_auth/__init__.py").read_text()

    assert "from .dependencies import" not in text
    assert "def __getattr__" in text


def test_orchestrator_bridge_does_not_expose_removed_runtime_singletons():
    from app.joysafeter_shared import orchestrator_bridge

    exposed = sorted(name for name in REMOVED_BRIDGE_EXPORTS if hasattr(orchestrator_bridge, name))
    assert exposed == []
    assert not Path("backend/app/joysafeter_shared/orchestrator_bridge/image_builder.py").exists()


def test_removed_python_monolith_entrypoint_is_not_reintroduced():
    assert not Path("backend/app/main.py").exists()


def test_python_service_roles_stay_explicit_api_or_worker_only():
    from app.joysafeter_shared.config.service_role import ServiceRole

    assert {role.value for role in ServiceRole} == {"api", "worker"}


def test_orchestrator_bridge_does_not_expose_removed_python_event_bus():
    from app.joysafeter_shared import orchestrator_bridge

    assert not hasattr(orchestrator_bridge, "get_event_bus")
    assert not hasattr(orchestrator_bridge, "get_event_buffer")


def test_environment_api_does_not_use_python_image_builder_boundary():
    text = Path("backend/app/joysafeter_api/api/v1/environments.py").read_text()

    assert "get_image_builder" not in text
    assert "ImageBuilder" not in text


def test_auth_project_archive_lifecycle_stays_in_project_service():
    auth_text = Path("backend/app/joysafeter_api/api/v1/auth.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_project_service.py").read_text()

    assert "_cleanup_project_sessions_for_archive" not in auth_text
    assert "PROJECT_ARCHIVE_REDIS_DESTROY_FAILED" not in auth_text
    assert "PROJECT_SLUG_CONFLICT" not in auth_text
    assert "count_active_tasks_for_project" not in auth_text
    assert "pause_for_project_archive" not in auth_text
    assert "project.name =" not in auth_text
    assert "project.slug =" not in auth_text
    assert "async def archive_project" in service_text
    assert "async def update_project" in service_text
    assert "normalize_slug" in service_text
    assert "PROJECT_SLUG_CONFLICT" in service_text
    assert "PROJECT_ARCHIVE_REDIS_DESTROY_FAILED" in service_text
    assert "count_active_tasks_for_project" in service_text
    assert "pause_for_project_archive" in service_text


def test_organization_member_lifecycle_stays_in_domain_services():
    route_text = "\n".join(
        Path(path).read_text()
        for path in (
            "backend/app/joysafeter_api/api/v1/auth.py",
            "backend/app/joysafeter_api/api/v1/organizations.py",
        )
    )
    member_service_text = Path(
        "backend/app/joysafeter_domain/services/joysafeter_organization_member_service.py"
    ).read_text()
    org_service_text = Path("backend/app/joysafeter_domain/services/joysafeter_organization_service.py").read_text()
    project_service_text = Path("backend/app/joysafeter_domain/services/joysafeter_project_service.py").read_text()

    for forbidden in (
        "ORGANIZATION_MEMBER_ROLE_INVALID",
        "ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN",
        "ORGANIZATION_ROLE_MODIFY_FORBIDDEN",
        "db.add(member)",
        "Member(",
        "delete(Member)",
        "delete(Project)",
        "ProjectMember(",
        "member.role =",
        "lower().replace",
        "re.sub",
    ):
        assert forbidden not in route_text

    assert "normalize_slug" in org_service_text
    assert "PROJECT_RESOURCE_BLOCKERS" in org_service_text
    assert "ORGANIZATION_PROJECT_RESOURCES_EXIST" in org_service_text
    assert "grant_project_membership" in project_service_text
    assert "grant_default_project_membership" in project_service_text
    assert "revoke_org_project_memberships" in project_service_text
    assert "list_accessible_projects" in project_service_text
    assert "ORGANIZATION_MEMBER_ROLE_INVALID" in member_service_text
    assert "ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN" in member_service_text
    assert "ORGANIZATION_ROLE_MODIFY_FORBIDDEN" in member_service_text
    assert "async def add_member" in member_service_text
    assert "async def transfer_ownership" in member_service_text
    assert "async def create_with_owner_and_default_project" in org_service_text
    assert "async def delete_organization" in org_service_text


def test_memory_store_api_does_not_expose_removed_python_subscriber_stream():
    text = Path("backend/app/joysafeter_api/api/v1/memory_stores.py").read_text()

    assert 'events/stream' not in text
    assert "memory_store_event_stream" not in text
    assert "StreamingResponse" not in text


def test_rust_runtime_queue_has_no_process_local_task_fallback():
    text = RUNTIME_QUEUE_FILE.read_text()
    coordinator_text = REDIS_COORDINATOR_FILE.read_text()

    assert "redis_client: Option<redis::Client>" not in text
    assert "pub fn with_redis" not in text
    assert "Redis unavailable; runtime queue is not configured" not in text
    assert "VecDeque" not in text
    assert "global_notify" not in text
    assert "InMemoryRedisQueueBackend" not in text
    assert "falling back to local" not in text
    assert "rpush::<_, _, ()>(GLOBAL_QUEUE_KEY" in text
    assert "BLPOP" in text
    assert "LPOP" in text
    assert "push_to_global_queue" not in coordinator_text
    assert "pop_from_global_queue" not in coordinator_text
    assert "push_to_sandbox_queue" not in coordinator_text
    assert "pop_from_sandbox_queue" not in coordinator_text


def test_rust_scheduler_consumes_redis_queue_before_db_repair_sweep():
    text = SCHEDULER_FILE.read_text()

    assert "queue.pop_from_global" in text
    assert "queue.try_pop_from_global" in text
    assert "claim_pending_task_by_id" in text
    assert "DB_REPAIR_SWEEP_INTERVAL" in text
    assert "claim_pending_tasks(&pool, available_slots as i64)" in text


def test_rust_orchestrator_requires_redis_runtime_queue():
    text = ORCHESTRATOR_MAIN_FILE.read_text()

    assert "REDIS_URL is required for the Rust orchestrator runtime queue" in text
    assert "Redis not configured, HA coordination disabled" not in text
    assert "TaskQueue::new()" not in text
    assert "TaskQueue::new(redis_client.clone())" in text
    assert "if let Some(ref client) = redis_client" not in text
    assert "runtime queue" in text


def test_rust_orchestrator_does_not_keep_removed_compatibility_shims():
    db_queries_text = DB_QUERIES_FILE.read_text()
    sandbox_resolver_text = SANDBOX_RESOLVER_FILE.read_text()
    main_text = ORCHESTRATOR_MAIN_FILE.read_text()
    rust_sources = "\n".join(path.read_text() for path in sorted(RUST_ORCHESTRATOR_SRC.rglob("*.rs")))

    assert "try_advisory_lock" not in db_queries_text
    assert "release_advisory_lock" not in db_queries_text
    assert "pg_try_advisory_lock" not in db_queries_text
    assert not re.search(r"pub\s+fn\s+image_for_provider\s*\(", sandbox_resolver_text)
    assert "redis_client: Option<redis::Client>" not in rust_sources
    assert not any((RUST_ORCHESTRATOR_SRC / "runtime").glob("*.rs"))
    assert "mod runtime;" not in main_text
    assert "OrchestratorError" not in rust_sources
    assert "new_noop" not in rust_sources
    assert "publish_batch" not in rust_sources
    assert "redis_subscriber_loop" not in rust_sources
    assert "dispatch_cancel" not in rust_sources
    assert "dispatch_input" not in rust_sources
    assert "provider_name" not in rust_sources
    assert "event_batch_enabled" not in rust_sources
    assert "task_default_max_retries" not in rust_sources


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


def test_domain_repositories_do_not_import_services_layer():
    offenders: list[str] = []

    for file_path in sorted(DOMAIN_REPOSITORY_ROOT.rglob("*.py")):
        text = file_path.read_text()
        if "app.joysafeter_domain.services" in text:
            offenders.append(f"{file_path}: repository imports services layer")

    assert offenders == []


def test_after_id_keyset_pagination_uses_shared_domain_helpers():
    offenders: list[str] = []
    raw_after_id_pattern = re.compile(r"\b(?:\w+\.)?id\s*<\s*after_id")
    partial_cursor_pattern = re.compile(r"created_at\s*<\s*cursor_created_at")
    allowed_files = {DOMAIN_PAGINATION_FILE, SECRET_SERVICE_FILE}

    for root in (Path("backend/app/joysafeter_domain/services"), DOMAIN_REPOSITORY_ROOT):
        for file_path in sorted(root.rglob("*.py")):
            if file_path in allowed_files:
                continue
            text = file_path.read_text()
            if raw_after_id_pattern.search(text) or partial_cursor_pattern.search(text):
                offenders.append(f"{file_path}: hand-rolled after_id pagination")

    assert offenders == []


def test_sensitive_resource_routes_keep_project_and_parent_boundaries_in_services():
    secret_route_text = Path("backend/app/joysafeter_api/api/v1/secrets.py").read_text()
    vault_route_text = Path("backend/app/joysafeter_api/api/v1/vaults.py").read_text()
    session_route_text = Path("backend/app/joysafeter_api/api/v1/sessions.py").read_text()
    secret_service_text = Path(
        "backend/app/joysafeter_domain/services/joysafeter_secret_service.py"
    ).read_text()
    vault_service_text = Path("backend/app/joysafeter_domain/services/joysafeter_vault_service.py").read_text()
    secret_model_text = Path("backend/app/joysafeter_domain/models/joysafeter_secret.py").read_text()
    vault_model_text = Path("backend/app/joysafeter_domain/models/joysafeter_vault.py").read_text()

    assert "svc.get_secret(secret_id, project_id=auth_ctx.project_id)" in secret_route_text
    assert "svc.update_secret(secret_id, req, project_id=auth_ctx.project_id)" in secret_route_text
    assert "svc.delete_secret(secret_id, project_id=auth_ctx.project_id)" in secret_route_text
    assert "svc.hard_delete_secret(secret_id, project_id=auth_ctx.project_id)" in secret_route_text
    assert "svc.set_default_secret(secret_id, project_id=auth_ctx.project_id)" in secret_route_text

    assert "svc.get_vault(vault_id, project_id=project_id)" in vault_route_text
    assert "svc.update_vault(" in vault_route_text
    assert "project_id=auth_ctx.project_id" in vault_route_text
    assert "svc.delete_vault(vault_id, project_id=auth_ctx.project_id)" in vault_route_text
    assert "svc.archive_vault(vault_id, project_id=auth_ctx.project_id)" in vault_route_text
    assert "svc.get_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)" in vault_route_text
    assert "svc.list_credentials(" in vault_route_text
    assert "project_id=auth_ctx.project_id" in vault_route_text
    assert "svc.update_credential(" in vault_route_text
    assert "vault_id=vault_id" in vault_route_text
    assert "svc.archive_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)" in vault_route_text
    assert "svc.delete_credential(cred_id, vault_id=vault_id, project_id=auth_ctx.project_id)" in vault_route_text

    assert "vault_svc.get_vault(vid_uuid, project_id=auth_ctx.project_id)" in session_route_text
    assert "vault_svc.get_vault(vid_uuid)" not in session_route_text

    assert "secret = await self.get_secret(secret_id, project_id=project_id)" in secret_service_text
    assert "await self.clear_default_secret(project_id=project_id)" in secret_service_text
    assert "JoySafeterSecret.project_id == project_id" in secret_service_text
    assert "JoySafeterSecret.project_id.is_(None)" in secret_service_text
    assert 'UniqueConstraint("name"' not in secret_model_text
    assert "uq_joysafeter_secrets_project_name" in secret_model_text

    assert "vault = await self.get_vault(vault_id, project_id=project_id)" in vault_service_text
    assert "cred = await self.get_credential(cred_id, vault_id=vault_id, project_id=project_id)" in vault_service_text
    assert "vault = await self.get_vault(vid, project_id=project_id)" in vault_service_text
    assert "await self.list_credentials(vid, limit=500, include_archived=False, project_id=project_id)" in vault_service_text
    assert "JoySafeterVault.project_id == project_id" in vault_service_text
    assert "JoySafeterVault.project_id.is_(None)" in vault_service_text
    assert 'UniqueConstraint("name"' not in vault_model_text
    assert "uq_joysafeter_vaults_project_name" in vault_model_text


def test_project_scoped_named_runtime_resources_use_project_scoped_name_constraints():
    agent_model_text = Path("backend/app/joysafeter_domain/models/joysafeter_agent.py").read_text()
    environment_model_text = Path("backend/app/joysafeter_domain/models/joysafeter_environment.py").read_text()
    agent_service_text = Path("backend/app/joysafeter_domain/services/joysafeter_agent_service.py").read_text()
    environment_service_text = Path(
        "backend/app/joysafeter_domain/services/joysafeter_environment_service.py"
    ).read_text()
    agent_route_text = Path("backend/app/joysafeter_api/api/v1/agents.py").read_text()

    assert 'UniqueConstraint("name"' not in agent_model_text
    assert "mapped_column(Text, unique=True" not in environment_model_text
    assert "uq_joysafeter_agents_project_name" in agent_model_text
    assert "uq_joysafeter_environments_project_name" in environment_model_text
    assert "deleted_at IS NULL" in agent_model_text
    assert "deleted_at IS NULL" in environment_model_text

    assert "async def hard_delete_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None)" in agent_service_text
    assert "agent = await self.get_agent(agent_id, project_id=project_id)" in agent_service_text
    assert "svc.hard_delete_agent(agent_id, project_id=auth_ctx.project_id)" in agent_route_text
    assert "svc.hard_delete_agent(agent_id)" not in agent_route_text
    assert "agent.project_id != auth_ctx.project_id" not in agent_route_text

    assert "JoySafeterEnvironment.project_id == project_id" in environment_service_text
    assert "JoySafeterEnvironment.project_id.is_(None)" in environment_service_text


def test_agent_child_resources_keep_parent_project_boundary_in_service_calls():
    agent_route_text = Path("backend/app/joysafeter_api/api/v1/agents.py").read_text()
    session_route_text = Path("backend/app/joysafeter_api/api/v1/sessions.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_agent_service.py").read_text()
    sandbox_service_text = Path("backend/app/joysafeter_domain/services/joysafeter_sandbox_service.py").read_text()

    for signature in (
        "async def list_versions(",
        "async def get_agent_version_snapshot(",
        "async def list_active_tasks_for_agent(",
        "async def archive_sessions_for_agent(",
    ):
        assert signature in service_text
    assert "not await self.get_agent(agent_id, project_id=project_id)" in service_text
    assert "project_id: Optional[str] = None" in service_text

    for call in (
        "svc.list_active_tasks_for_agent(agent_id, project_id=auth_ctx.project_id)",
        "svc.list_versions(agent_id, limit, before_version, project_id=auth_ctx.project_id)",
        "svc.archive_sessions_for_agent(agent_id, project_id=project_id)",
    ):
        assert call in agent_route_text
    # Formatting-tolerant: assert the call threads the parent project boundary,
    # regardless of whether the formatter keeps the args on one line or wraps them.
    assert "get_agent_version_snapshot(" in session_route_text
    assert "agent.id, pinned_version, project_id=auth_ctx.project_id" in session_route_text
    assert "sandbox_svc.find_by_session(task.chat_session_id, project_id=project_id)" in agent_route_text
    assert "sandbox_svc.list_active_for_agent(agent_id, project_id=project_id)" in agent_route_text
    assert "JoySafeterSandbox" not in agent_route_text
    assert "select(" not in agent_route_text
    assert "async def list_active_for_agent(" in sandbox_service_text
    assert "JoySafeterSession.agent_id == agent_id" in sandbox_service_text
    assert "JoySafeterSession.project_id == project_id" in sandbox_service_text


def test_memory_child_resources_keep_parent_project_boundary_in_service_calls():
    route_text = Path("backend/app/joysafeter_api/api/v1/memory_stores.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_memory_service.py").read_text()

    for call in (
        "svc.get_memory_by_path(store_id, normalized_path, project_id=auth_ctx.project_id)",
        "svc.create_memory(store_id, normalized_path, req.content, project_id=auth_ctx.project_id)",
        "svc.get_memory(store_id, memory_id, project_id=auth_ctx.project_id)",
        "svc.delete_memory(store_id, memory_id, project_id=auth_ctx.project_id)",
        "svc.get_version(store_id, version_id, project_id=auth_ctx.project_id)",
        "svc.is_live_version(store_id, version_id, project_id=auth_ctx.project_id)",
        "svc.redact_version(store_id, version_id, project_id=auth_ctx.project_id)",
    ):
        assert call in route_text
    assert "project_id=auth_ctx.project_id" in route_text

    for signature in (
        "async def create_memory(",
        "async def get_memory(",
        "async def get_memory_by_path(",
        "async def update_memory(",
        "async def delete_memory(",
        "async def list_versions(",
        "async def get_version(",
        "async def redact_version(",
    ):
        assert signature in service_text
    assert "store = await self.get_store(store_id, project_id=project_id" in service_text


def test_schedule_target_project_boundary_lives_in_domain_service():
    route_text = Path("backend/app/joysafeter_api/api/v1/schedules.py").read_text()
    service_text = Path(
        "backend/app/joysafeter_domain/services/joysafeter_schedule_service.py"
    ).read_text()

    assert "async def resolve_runnable_target(" in service_text
    assert "JoySafeterAgent.project_id == project_id" in service_text
    assert "get_environment_by_ref(" in service_text
    assert "project_id=project_id" in service_text
    assert "await self.resolve_runnable_target(" in service_text
    assert "updated = await JoySafeterScheduleService(db).update(" in route_text
    assert "resolve_runnable_target(" in route_text
    assert "JoySafeterAgentService" not in route_text
    assert "EnvironmentService" not in route_text
    assert "async def list_runs(" in service_text
    assert "not await self.get(schedule_id, project_id=project_id)" in service_text
    assert "JoySafeterTask.schedule_id == schedule_id" in service_text
    assert "JoySafeterTask" not in route_text
    assert "list_runs(" in route_text


def test_sandbox_routes_keep_project_boundary_in_domain_service_calls():
    route_text = Path("backend/app/joysafeter_api/api/v1/sandboxes.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_sandbox_service.py").read_text()

    assert "async def get_sandbox(" in service_text
    assert "project_id: Optional[str] = None" in service_text
    assert "JoySafeterSandbox.project_id == project_id" in service_text
    assert "await svc.get_sandbox(sandbox_id, project_id=auth_ctx.project_id)" in route_text
    assert "await svc.stop_sandbox(sandbox_id, project_id=auth_ctx.project_id)" in route_text
    assert "sandbox.project_id != auth_ctx.project_id" not in route_text


def test_file_session_scope_keeps_parent_project_boundary_in_service():
    route_text = Path("backend/app/joysafeter_api/api/v1/files.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_file_service.py").read_text()

    assert 'code="SESSION_ID_INVALID"' in route_text
    assert "JoySafeterSession.id == session_id" in service_text
    assert "JoySafeterSession.project_id == project_id" in service_text
    assert "JoySafeterFile.session_id == session_id" in service_text


def test_session_routes_keep_project_boundary_in_domain_service_calls():
    route_text = Path("backend/app/joysafeter_api/api/v1/sessions.py").read_text()
    task_route_text = Path("backend/app/joysafeter_api/api/v1/tasks.py").read_text()
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_session_service.py").read_text()

    assert "async def get_session(" in service_text
    assert "async def delete_session(self, session_id: uuid.UUID, project_id: Optional[str] = None)" in service_text
    assert "async def archive_session(self, session_id: uuid.UUID, project_id: Optional[str] = None)" in service_text
    assert "project_id: Optional[str] = None" in service_text
    assert "JoySafeterSession.project_id == project_id" in service_text
    assert "await svc.get_session(session_id, project_id=auth_ctx.project_id)" in route_text
    assert "await svc.delete_session(session_id, project_id=auth_ctx.project_id)" in route_text
    assert "await svc.archive_session(session_id, project_id=auth_ctx.project_id)" in route_text
    assert "project_id=auth_ctx.project_id" in task_route_text
    assert "sandbox_svc.find_by_session(session_id, project_id=auth_ctx.project_id)" in route_text
    assert "sandbox_svc.find_by_session(session_id)" not in route_text
    assert "session.project_id != auth_ctx.project_id" not in route_text
    assert "existing_session.project_id != auth_ctx.project_id" not in task_route_text
    assert "async def find_user_message_event_by_idempotency_key(" in service_text
    assert "async def find_status_running_event_for_task(" in service_text
    assert "find_user_message_event_by_idempotency_key(" in route_text
    assert "find_status_running_event_for_task(" in route_text
    assert "JoySafeterSessionEvent" not in route_text
    assert "payload->>" not in route_text


def test_session_resource_children_keep_parent_project_boundary_in_service():
    route_text = Path("backend/app/joysafeter_api/api/v1/sessions.py").read_text()
    service_text = Path(
        "backend/app/joysafeter_domain/services/joysafeter_session_resource_service.py"
    ).read_text()

    assert "self._session_svc.get_session(session_id, project_id=project_id)" in service_text
    assert "JoySafeterSession.project_id == project_id" in service_text
    assert "async def list_resource_payloads(self, session_id: uuid.UUID, project_id: Optional[str] = None)" in service_text
    assert "async def delete_resource(" in service_text
    assert "project_id: Optional[str] = None" in service_text
    assert "async def rotate_repo_token(" in service_text
    assert "project_id=auth_ctx.project_id" in route_text
    assert "list_resource_payloads(session_id, project_id=auth_ctx.project_id)" in route_text
    assert "delete_resource(session_id, resource_id, project_id=auth_ctx.project_id)" in route_text


def test_task_agent_helpers_accept_project_scope_for_domain_boundaries():
    service_text = Path("backend/app/joysafeter_domain/services/joysafeter_task_service.py").read_text()

    assert "async def list_tasks_by_agent(" in service_text
    assert "async def agent_has_active_tasks(" in service_text
    assert "project_id: Optional[str] = None" in service_text
    assert "JoySafeterTask.project_id == project_id" in service_text
