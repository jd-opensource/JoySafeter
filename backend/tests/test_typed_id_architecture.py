import ast
import re
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

ENTITY_ID_CLASS_NAMES = (
    "AgentId",
    "AgentVersionId",
    "ApiKeyId",
    "SessionId",
    "TaskId",
    "EnvironmentId",
    "TriggerId",
    "MemoryStoreId",
    "MemoryId",
    "MemoryVersionId",
    "SandboxId",
    "CredentialId",
    "CredentialGroupId",
    "SkillId",
    "SkillFileId",
    "SkillSecurityScanId",
    "SkillVersionId",
    "SkillVersionFileId",
    "SkillUsageId",
    "EventId",
    "FileId",
    "SessionResourceId",
    "StorageVolumeId",
    "StorageGrantId",
    "StorageMountAuditId",
)

ENTITY_ID_PREFIXES = (
    "agent_",
    "agentver_",
    "apikey_",
    "sess_",
    "task_",
    "env_",
    "trig_",
    "memstore_",
    "mem_",
    "memver_",
    "sbx_",
    "cred_",
    "credgrp_",
    "skill_",
    "sklfile_",
    "sklscan_",
    "sklver_",
    "sklvfile_",
    "skluse_",
    "evt_",
    "file_",
    "sesrsc_",
    "vol_",
    "stgrant_",
    "staudit_",
)

ENTITY_MODEL_CLASS_NAMES = {
    "JoySafeterAgent",
    "JoySafeterAgentVersion",
    "JoySafeterApiKey",
    "JoySafeterCredential",
    "JoySafeterCredentialGroup",
    "JoySafeterEnvironment",
    "JoySafeterFile",
    "JoySafeterMemoryStore",
    "JoySafeterMemory",
    "JoySafeterMemoryVersion",
    "JoySafeterSandbox",
    "JoySafeterSession",
    "JoySafeterSessionEvent",
    "JoySafeterSessionFile",
    "JoySafeterSessionMemoryStore",
    "JoySafeterSessionRepo",
    "JoySafeterSkill",
    "JoySafeterSkillFile",
    "JoySafeterSkillSecurityScan",
    "JoySafeterSkillVersion",
    "JoySafeterSkillVersionFile",
    "JoySafeterSkillUsageLog",
    "JoySafeterStorageVolume",
    "JoySafeterStorageProjectGrant",
    "JoySafeterStorageOrganizationGrant",
    "JoySafeterSessionStorageMount",
    "JoySafeterStorageMountAudit",
    "JoySafeterTask",
    "JoySafeterTrigger",
    "AuthUser",
    "AuthSession",
    "Organization",
    "Member",
    "Project",
    "ProjectMember",
    "OAuthAccount",
    "JoySafeterCredentialAccessAudit",
    "SecurityAuditLog",
    "JoySafeterSandboxNetworkPolicy",
}

REVIEWED_ADAPTER_CATEGORIES = {
    "typed_id_codec": "EntityId public/native codecs and ORM hydration",
    "strict_validation_probe": "native UUID parse used only to reject a bare public reference",
    "sql_uuid_bind_result": "native PostgreSQL UUID bind/result conversion",
    "advisory_locks": "UUID bytes used to derive PostgreSQL advisory-lock keys",
    "redis_queue_channel_payloads": "Redis keys, channels, queue members, and payload fields",
    "runner_protobuf_fields": "runner/orchestrator wire fields defined as UUID strings",
    "object_storage_keys": "object-store keys derived from FileId",
    "physical_resource_naming": "provider labels, env vars, pod/container, and Envoy names",
    "derived_non_identity_value": "UUID bits used for deterministic jitter, not as an ID contract",
    "third_party_uuid_contracts": "external APIs that independently require a UUID value",
}

# Each key is emitted by the scanner below. Values are (reviewed categories, exact count).
# A new call, parse, file, function, or count is therefore unclassified and fails the guard.
REVIEWED_ENTITY_UUID_ADAPTERS = {
    "rust:app/joysafeter_orchestrator_rs/src/kernel/ha/redis_impl.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        8,
    ),
    "python:app/joysafeter_api/api/v1/memory_stores.py::_broadcast_memory_update::as_uuid_call": (
        ("sql_uuid_bind_result", "redis_queue_channel_payloads"),
        2,
    ),
    "python:app/joysafeter_api/api/v1/tasks.py::_stream_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_identity/providers/jd.py::cleanup_agent_identity::uuid_attr": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_domain/services/joysafeter_file_service.py::_make_storage_key::as_uuid_call": (
        ("object_storage_keys",),
        1,
    ),
    "python:app/joysafeter_domain/schemas/joysafeter_environment.py::_validate_environment_name::uuid_parse": (
        ("strict_validation_probe",),
        1,
    ),
    "python:app/joysafeter_domain/services/joysafeter_session_service.py::SessionService::task_has_agent_output::as_uuid_call": (
        ("sql_uuid_bind_result",),
        1,
    ),
    "python:app/joysafeter_domain/services/joysafeter_session_service.py::publish_session_event_realtime::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_domain/services/joysafeter_task_service.py::JoySafeterTaskService::append_task_output::as_uuid_call": (
        ("sql_uuid_bind_result",),
        1,
    ),
    "python:app/joysafeter_shared/ids.py::EntityId::_coerce::uuid_attr": (("typed_id_codec",), 1),
    "python:app/joysafeter_shared/ids.py::EntityId::from_public::uuid_parse": (("typed_id_codec",), 1),
    "python:app/joysafeter_shared/ids.py::EntityId::new::uuid_parse": (("typed_id_codec",), 1),
    "python:app/joysafeter_shared/sqlalchemy_ids.py::EntityIdType::process_bind_param::uuid_attr": (
        ("typed_id_codec", "sql_uuid_bind_result"),
        1,
    ),
    "python:app/joysafeter_shared/ids.py::as_uuid::uuid_attr": (("typed_id_codec",), 1),
    "python:app/joysafeter_shared/orchestrator_bridge/enqueue.py::enqueue_joysafeter_task::uuid_attr": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::publish_to_sandbox_owner_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::publish_to_sandbox_owners_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::relay_environment_image_build_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads", "runner_protobuf_fields"),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::relay_sandbox_command_payload_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::relay_sandbox_command_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/runtime_commands.py::relay_sandbox_destroy_via_redis::as_uuid_call": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/session_broadcaster.py::SessionBroadcaster::_redis_subscriber::uuid_attr": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/orchestrator_bridge/session_broadcaster.py::SessionBroadcaster::send::uuid_attr": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "python:app/joysafeter_shared/retry.py::compute_retry_delay::uuid_attr": (
        ("derived_non_identity_value",),
        1,
    ),
    "python:app/joysafeter_shared/utils/locks.py::session_advisory_lock_key::uuid_attr": (
        ("advisory_locks",),
        1,
    ),
    "python:app/joysafeter_worker/events/stream_consumer.py::EventStreamWorker::_decode_event::uuid_parse": (
        ("redis_queue_channel_payloads",),
        2,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/db/queries/session.rs::as_uuid": (("advisory_locks",), 1),
    "rust:app/joysafeter_orchestrator_rs/src/db/queries/task.rs::as_uuid": (("sql_uuid_bind_result",), 1),
    "rust:app/joysafeter_orchestrator_rs/src/events/persist.rs::as_uuid": (("advisory_locks",), 1),
    "rust:app/joysafeter_orchestrator_rs/src/events/realtime.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/events/session_state.rs::as_uuid": (
        ("advisory_locks", "sql_uuid_bind_result"),
        2,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/events/stream_publisher.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        2,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs::uuid_parse": (
        ("redis_queue_channel_payloads", "runner_protobuf_fields"),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs::as_uuid": (
        ("sql_uuid_bind_result", "runner_protobuf_fields"),
        2,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/queue.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        5,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/redis_coordinator.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        9,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/sandbox_controller.rs::uuid_parse": (
        ("physical_resource_naming",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs::as_uuid": (
        ("physical_resource_naming", "third_party_uuid_contracts"),
        24,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/session_broadcaster.rs::as_uuid": (
        ("redis_queue_channel_payloads",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/artifacts.rs::as_uuid": (("object_storage_keys",), 1),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/daytona.rs::as_uuid": (
        ("physical_resource_naming",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/docker.rs::as_uuid": (
        ("physical_resource_naming",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/e2b.rs::as_uuid": (
        ("physical_resource_naming",),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs::as_uuid": (
        ("physical_resource_naming",),
        8,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs::as_uuid": (
        ("physical_resource_naming",),
        2,
    ),
}

PUBLIC_PARAMETER_FACTORIES = {"Body", "Cookie", "Header", "Path", "Query"}
BARE_UUID_GUIDANCE = re.compile(
    r"(?:bare\s+uuid|raw\s+uuid|uuid\s+without\s+(?:an?\s+)?prefix|"
    r"(?:prefixed|canonical|<uuid>|_xxx).*\bor\b.*\buuid)",
    re.IGNORECASE,
)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _string_literals(node: ast.AST) -> str:
    return " ".join(
        child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


ID_PREFIX_BY_CLASS = dict(zip(ENTITY_ID_CLASS_NAMES, ENTITY_ID_PREFIXES, strict=True))


def _new_bindings() -> dict[str, object]:
    return {
        "id_aliases": {},
        "id_modules": set(),
        "fastapi_factories": {},
        "fastapi_modules": {"fastapi"},
        "as_uuid_aliases": {"as_uuid"},
        "uuid_modules": {"uuid"},
        "uuid_classes": set(),
        "prefix_constants": {},
        "string_constants": {},
    }


def _copy_bindings(bindings: dict[str, object]) -> dict[str, object]:
    return {key: value.copy() if isinstance(value, (dict, set)) else value for key, value in bindings.items()}


def _resolved_id_class(node: ast.AST, bindings: dict[str, object]) -> str | None:
    aliases = bindings["id_aliases"]
    modules = bindings["id_modules"]
    assert isinstance(aliases, dict) and isinstance(modules, set)
    if isinstance(node, ast.Name):
        if node.id in ENTITY_ID_CLASS_NAMES:
            return node.id
        return aliases.get(node.id)
    if (
        isinstance(node, ast.Attribute)
        and node.attr in ENTITY_ID_CLASS_NAMES
        and isinstance(node.value, ast.Name)
        and node.value.id in modules
    ):
        return node.attr
    return None


def _resolved_prefix(node: ast.AST, bindings: dict[str, object]) -> str | None:
    constants = bindings["prefix_constants"]
    assert isinstance(constants, dict)
    if isinstance(node, ast.Constant) and node.value in ENTITY_ID_PREFIXES:
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Attribute) and node.attr == "prefix":
        id_class = _resolved_id_class(node.value, bindings)
        return ID_PREFIX_BY_CLASS.get(id_class) if id_class else None
    return None


def _resolved_string(node: ast.AST, bindings: dict[str, object]) -> str | None:
    constants = bindings["string_constants"]
    assert isinstance(constants, dict)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


class _ScopedBindingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.binding_stack = [_new_bindings()]
        self.scope: list[str] = []

    @property
    def bindings(self) -> dict[str, object]:
        return self.binding_stack[-1]

    def _clear_binding(self, name: str) -> None:
        for key in (
            "id_aliases",
            "fastapi_factories",
            "prefix_constants",
            "string_constants",
        ):
            values = self.bindings[key]
            assert isinstance(values, dict)
            values.pop(name, None)
        for key in (
            "id_modules",
            "fastapi_modules",
            "as_uuid_aliases",
            "uuid_modules",
            "uuid_classes",
        ):
            values = self.bindings[key]
            assert isinstance(values, set)
            values.discard(name)

    def _bind_alias(self, name: str, value: ast.AST) -> None:
        resolved_id = _resolved_id_class(value, self.bindings)
        resolved_prefix = _resolved_prefix(value, self.bindings)
        resolved_string = _resolved_string(value, self.bindings)
        source_name = value.id if isinstance(value, ast.Name) else None
        self._clear_binding(name)

        if resolved_id:
            aliases = self.bindings["id_aliases"]
            assert isinstance(aliases, dict)
            aliases[name] = resolved_id
        if resolved_prefix:
            prefixes = self.bindings["prefix_constants"]
            assert isinstance(prefixes, dict)
            prefixes[name] = resolved_prefix
        if resolved_string:
            strings = self.bindings["string_constants"]
            assert isinstance(strings, dict)
            strings[name] = resolved_string

        if source_name:
            for key in ("id_modules", "fastapi_modules", "as_uuid_aliases", "uuid_modules", "uuid_classes"):
                values = self.bindings[key]
                assert isinstance(values, set)
                if source_name in values:
                    values.add(name)
            factories = self.bindings["fastapi_factories"]
            assert isinstance(factories, dict)
            if source_name in factories:
                factories[name] = factories[source_name]
        elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
            id_modules = self.bindings["id_modules"]
            uuid_modules = self.bindings["uuid_modules"]
            assert isinstance(id_modules, set) and isinstance(uuid_modules, set)
            if value.value.id in id_modules and value.attr == "as_uuid":
                aliases = self.bindings["as_uuid_aliases"]
                assert isinstance(aliases, set)
                aliases.add(name)
            elif value.value.id in uuid_modules and value.attr == "UUID":
                constructors = self.bindings["uuid_classes"]
                assert isinstance(constructors, set)
                constructors.add(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            bound = imported.asname or imported.name
            self._clear_binding(bound)
            if node.module == "app.joysafeter_shared.ids":
                if imported.name in ENTITY_ID_CLASS_NAMES:
                    aliases = self.bindings["id_aliases"]
                    assert isinstance(aliases, dict)
                    aliases[bound] = imported.name
                elif imported.name == "as_uuid":
                    aliases = self.bindings["as_uuid_aliases"]
                    assert isinstance(aliases, set)
                    aliases.add(bound)
            elif node.module == "app.joysafeter_shared" and imported.name == "ids":
                modules = self.bindings["id_modules"]
                assert isinstance(modules, set)
                modules.add(bound)
            elif node.module == "fastapi" and imported.name in PUBLIC_PARAMETER_FACTORIES:
                factories = self.bindings["fastapi_factories"]
                assert isinstance(factories, dict)
                factories[bound] = imported.name
            elif node.module == "uuid" and imported.name == "UUID":
                constructors = self.bindings["uuid_classes"]
                assert isinstance(constructors, set)
                constructors.add(bound)

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            bound = imported.asname or imported.name.split(".")[0]
            self._clear_binding(bound)
            if imported.name == "app.joysafeter_shared.ids" and imported.asname:
                modules = self.bindings["id_modules"]
                assert isinstance(modules, set)
                modules.add(bound)
            elif imported.name == "fastapi":
                modules = self.bindings["fastapi_modules"]
                assert isinstance(modules, set)
                modules.add(bound)
            elif imported.name == "uuid":
                modules = self.bindings["uuid_modules"]
                assert isinstance(modules, set)
                modules.add(bound)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._bind_alias(target.id, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            if isinstance(node.target, ast.Name):
                self._bind_alias(node.target.id, node.value)

    def _visit_scoped_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
        else:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
        self.binding_stack.append(_copy_bindings(self.bindings))
        self.scope.append(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            if node.args.vararg:
                arguments.append(node.args.vararg)
            if node.args.kwarg:
                arguments.append(node.args.kwarg)
            for argument in arguments:
                self._clear_binding(argument.arg)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()
        self.binding_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped_body(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped_body(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped_body(node)


class _BackendGuardVisitor(_ScopedBindingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.direct_constructors: list[int] = []
        self.prefix_removals: list[int] = []
        self.bare_descriptions: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _resolved_id_class(node.func, self.bindings) is not None:
            self.direct_constructors.append(node.lineno)

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "removeprefix"
            and node.args
            and _resolved_prefix(node.args[0], self.bindings)
        ):
            self.prefix_removals.append(node.lineno)

        factories = self.bindings["fastapi_factories"]
        modules = self.bindings["fastapi_modules"]
        assert isinstance(factories, dict) and isinstance(modules, set)
        factory = None
        if isinstance(node.func, ast.Name):
            factory = factories.get(node.func.id, node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in modules
        ):
            factory = node.func.attr
        if factory in PUBLIC_PARAMETER_FACTORIES:
            description = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "description"),
                None,
            )
            if description is not None:
                text = _resolved_string(description, self.bindings) or _string_literals(description)
                if BARE_UUID_GUIDANCE.search(text):
                    self.bare_descriptions.append(node.lineno)

        self.generic_visit(node)


def _backend_guard_visitor(source: str) -> _BackendGuardVisitor:
    visitor = _BackendGuardVisitor()
    visitor.visit(ast.parse(source))
    return visitor


def _find_direct_id_constructor_calls(source: str) -> list[int]:
    return _backend_guard_visitor(source).direct_constructors


def _find_entity_prefix_removals(source: str) -> list[int]:
    return _backend_guard_visitor(source).prefix_removals


def _find_bare_uuid_parameter_descriptions(source: str) -> list[int]:
    return _backend_guard_visitor(source).bare_descriptions


def _rust_production_source(source: str) -> str:
    return re.split(r"\n#\[cfg\(test\)\]\s*\nmod tests\s*\{", source, maxsplit=1)[0]


class _PythonUuidScanner(_ScopedBindingVisitor):
    def __init__(self, relative_path: str) -> None:
        super().__init__()
        self.relative_path = relative_path
        self.counts: Counter[str] = Counter()

    def key(self, operation: str) -> str:
        qualified = "::".join(self.scope) or "<module>"
        return f"python:{self.relative_path}::{qualified}::{operation}"

    def visit_Call(self, node: ast.Call) -> None:
        as_uuid_aliases = self.bindings["as_uuid_aliases"]
        id_modules = self.bindings["id_modules"]
        uuid_modules = self.bindings["uuid_modules"]
        uuid_classes = self.bindings["uuid_classes"]
        assert isinstance(as_uuid_aliases, set)
        assert isinstance(id_modules, set)
        assert isinstance(uuid_modules, set)
        assert isinstance(uuid_classes, set)

        direct_as_uuid = isinstance(node.func, ast.Name) and node.func.id in as_uuid_aliases
        module_as_uuid = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "as_uuid"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in id_modules
        )
        if direct_as_uuid or module_as_uuid:
            self.counts[self.key("as_uuid_call")] += 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "as_uuid":
            self.counts[self.key("as_uuid_method")] += 1

        direct_uuid = isinstance(node.func, ast.Name) and node.func.id in uuid_classes
        module_uuid = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "UUID"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in uuid_modules
        )
        if direct_uuid or module_uuid:
            self.counts[self.key("uuid_parse")] += 1

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "uuid":
            self.counts[self.key("uuid_attr")] += 1
        self.generic_visit(node)


def _scan_python_uuid_source(source: str, relative_path: str) -> Counter[str]:
    scanner = _PythonUuidScanner(relative_path)
    scanner.visit(ast.parse(source))
    return scanner.counts


def _scan_entity_uuid_adapters() -> Counter[str]:
    counts: Counter[str] = Counter()
    app_root = BACKEND_ROOT / "app"

    for path in app_root.rglob("*.py"):
        relative_path = str(path.relative_to(BACKEND_ROOT))
        counts.update(_scan_python_uuid_source(path.read_text(), relative_path))

    rust_root = app_root / "joysafeter_orchestrator_rs/src"
    for path in rust_root.rglob("*.rs"):
        relative_path = str(path.relative_to(BACKEND_ROOT))
        source = _rust_production_source(path.read_text())
        as_uuid_count = len(re.findall(r"\.as_uuid\(\)", source))
        if as_uuid_count:
            counts[f"rust:{relative_path}::as_uuid"] = as_uuid_count
        parse_count = 0
        for match in re.finditer(r"\bUuid::(?:parse_str|from_str)\(", source):
            window = source[max(0, match.start() - 180) : match.end() + 180]
            if relative_path.endswith("/ids.rs") or re.search(r"(?:[A-Z][A-Za-z]+Id::from_uuid|\b\w+_id\b)", window):
                parse_count += 1
        if parse_count:
            counts[f"rust:{relative_path}::uuid_parse"] = parse_count

    return counts


def test_python_application_has_no_bare_entity_annotations():
    app_root = BACKEND_ROOT / "app"
    forbidden = re.compile(
        r"\b(?P<field>(?:(?:[A-Za-z0-9]+_)?(?:agent|agent_version|api_key|session|task|sandbox|sandbox_network_policy|trigger|environment|secret|vault|credential|credential_group|credential_access_audit|memory_store|memory|memory_version|skill|skill_file|skill_security_scan|skill_version|skill_version_file|skill_usage|file|session_resource|event|storage_volume|storage_grant|storage_mount_audit|volume|user|organization|organization_member|project|project_member|oauth_account|auth_session|security_audit)_id|store_id|env_id|cred_id|resource_id|scan_id|version_id))\s*:\s*"
        r"(?:(?:Optional|Union)\[)?(?:uuid\.UUID|UUID|str|Any)"
    )
    matches = []
    for path in app_root.rglob("*.py"):
        relative_path = str(path.relative_to(BACKEND_ROOT))
        violations = [
            match.group("field")
            for match in forbidden.finditer(path.read_text())
            if match.group("field") not in {"harness_session_id", "source_event_id"}
        ]
        if violations:
            matches.append(relative_path)

    assert matches == []


def test_python_application_has_no_direct_concrete_entity_id_construction():
    app_root = BACKEND_ROOT / "app"
    id_module = app_root / "joysafeter_shared/ids.py"
    matches = []
    for path in app_root.rglob("*.py"):
        if path == id_module:
            continue
        for line in _find_direct_id_constructor_calls(path.read_text()):
            matches.append(f"{path.relative_to(BACKEND_ROOT)}:{line}")

    assert matches == []


def test_python_application_has_no_entity_prefix_removeprefix_calls():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        for line in _find_entity_prefix_removals(path.read_text()):
            matches.append(f"{path.relative_to(BACKEND_ROOT)}:{line}")

    assert matches == []


def test_public_parameter_descriptions_do_not_advertise_bare_entity_uuids():
    api_root = BACKEND_ROOT / "app/joysafeter_api"
    matches = []
    for path in api_root.rglob("*.py"):
        for line in _find_bare_uuid_parameter_descriptions(path.read_text()):
            matches.append(f"{path.relative_to(BACKEND_ROOT)}:{line}")

    assert matches == []


def test_backend_ast_guards_resolve_aliases_prefix_attributes_and_description_constants():
    source = """
import app.joysafeter_shared.ids as entity_ids
from app.joysafeter_shared.ids import AgentId as AId
from fastapi import Query as ApiQuery

BARE_ID_HELP = "Canonical agent_<uuid> or bare UUID"

AId(value)
entity_ids.SessionId(value)
value.removeprefix(AId.prefix)
value.removeprefix(entity_ids.SessionId.prefix)
ApiQuery(None, description=BARE_ID_HELP)
"""

    assert _find_direct_id_constructor_calls(source) == [8, 9]
    assert _find_entity_prefix_removals(source) == [10, 11]
    assert _find_bare_uuid_parameter_descriptions(source) == [12]


def test_backend_ast_guards_resolve_transitive_and_function_scoped_bypass_probes():
    source = """
from app.joysafeter_shared.ids import AgentId
from fastapi import Query as ApiQuery

Alias = AgentId
PREFIX = AgentId.prefix

def probe(value):
    LocalAlias = Alias
    LOCAL_PREFIX = PREFIX
    HELP = "Canonical agent_<uuid> or bare UUID"
    LocalAlias(value)
    value.removeprefix(LOCAL_PREFIX)
    ApiQuery(None, description=HELP)
"""

    assert _find_direct_id_constructor_calls(source) == [12]
    assert _find_entity_prefix_removals(source) == [13]
    assert _find_bare_uuid_parameter_descriptions(source) == [14]


def test_python_uuid_scanner_is_exhaustive_and_name_independent():
    source = """
import uuid as native_uuid
from uuid import UUID as NativeUuid
from app.joysafeter_shared.ids import as_uuid as unwrap_uuid

UuidAlias = native_uuid.UUID
TransitiveUuidAlias = UuidAlias

def probe(session_id, task, sid, adapter):
    unwrap_uuid(session_id)
    adapter.as_uuid()
    task.id.uuid
    sid.uuid
    native_uuid.UUID(str(session_id))
    NativeUuid(str(session_id))
    UuidAlias(str(session_id))
    TransitiveUuidAlias(str(session_id))
"""

    assert _scan_python_uuid_source(source, "app/probe.py") == Counter(
        {
            "python:app/probe.py::probe::as_uuid_call": 1,
            "python:app/probe.py::probe::as_uuid_method": 1,
            "python:app/probe.py::probe::uuid_attr": 2,
            "python:app/probe.py::probe::uuid_parse": 4,
        }
    )


def test_retained_python_entity_uuid_adapters_match_reviewed_allowlist():
    reviewed_counts = {
        key: count for key, (_, count) in REVIEWED_ENTITY_UUID_ADAPTERS.items() if key.startswith("python:")
    }
    reviewed_categories = {
        category for categories, _ in REVIEWED_ENTITY_UUID_ADAPTERS.values() for category in categories
    }

    assert reviewed_categories <= set(REVIEWED_ADAPTER_CATEGORIES)
    actual_counts = Counter(
        {key: count for key, count in _scan_entity_uuid_adapters().items() if key.startswith("python:")}
    )
    assert actual_counts == Counter(reviewed_counts)


def test_python_application_does_not_reprefix_typed_entity_rows():
    app_root = BACKEND_ROOT / "app"
    forbidden = re.compile(
        r"f[\"'](?:agent_|sess_|task_|sbx_|trig_|env_|secret_|vault_|cred_|file_|sesrsc_|evt_|vol_|stgrant_|staudit_)\{[^}]+\.id\}"
    )
    matches = []
    for path in app_root.rglob("*.py"):
        if forbidden.search(path.read_text()):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_registered_entity_ids_have_one_python_definition():
    canonical_path = BACKEND_ROOT / "app/joysafeter_shared/ids.py"
    duplicates: list[str] = []

    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if path == canonical_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in ENTITY_ID_CLASS_NAMES:
                duplicates.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}:{node.name}")
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            function_name = value.func.id if isinstance(value.func, ast.Name) else None
            if function_name != "NewType":
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ENTITY_ID_CLASS_NAMES:
                    duplicates.append(f"{path.relative_to(BACKEND_ROOT)}:{target.lineno}:{target.id}")

    assert duplicates == []


def test_entity_ids_are_created_by_lifecycle_owners_not_orm_defaults():
    models_root = BACKEND_ROOT / "app/joysafeter_domain/models"
    implicit_default = re.compile(r"\bdefault\s*=\s*[A-Z][A-Za-z0-9]+Id\.new\b")
    violations: list[str] = []

    for path in sorted(models_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in implicit_default.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(BACKEND_ROOT)}:{line}:{match.group(0)}")

    assert violations == []


def test_production_entity_constructors_supply_explicit_typed_ids():
    violations: list[str] = []

    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if "joysafeter_domain/models" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in ENTITY_MODEL_CLASS_NAMES:
                continue
            if not any(keyword.arg == "id" for keyword in node.keywords):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}:{node.func.id}")

    assert violations == []


def test_test_entity_constructors_supply_explicit_typed_ids():
    violations: list[str] = []

    for path in sorted((BACKEND_ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in ENTITY_MODEL_CLASS_NAMES:
                continue
            if not any(keyword.arg == "id" for keyword in node.keywords):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}:{node.func.id}")

    assert violations == []


def test_tests_do_not_restore_implicit_orm_id_generation():
    conftest_source = (BACKEND_ROOT / "tests/conftest.py").read_text(encoding="utf-8")

    assert "_install_test_entity_id_factories" not in conftest_source
    assert 'event.listen(model, "init"' not in conftest_source


def test_json_boundaries_do_not_use_permissive_serialization_fallbacks():
    production_roots = (
        BACKEND_ROOT / "app/joysafeter_api",
        BACKEND_ROOT / "app/joysafeter_application",
        BACKEND_ROOT / "app/joysafeter_domain",
        BACKEND_ROOT / "app/joysafeter_shared/common",
        BACKEND_ROOT / "app/joysafeter_shared/json_boundary.py",
        BACKEND_ROOT / "app/joysafeter_worker",
    )
    offenders: list[str] = []
    for root in production_roots:
        for path in root.rglob("*.py"):
            source = path.read_text()
            if "default=str" in source:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: default=str")
            if "custom_encoder={EntityId: str}" in source:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: EntityId custom_encoder")

    assert offenders == []


def test_network_policy_api_keeps_project_identity_typed():
    paths = (
        "app/joysafeter_api/api/v1/network_policies.py",
        "app/joysafeter_api/api/v1/network_policy_refresh.py",
    )

    for relative_path in paths:
        source = (BACKEND_ROOT / relative_path).read_text()
        assert "project_id: Optional[str]" not in source, relative_path
