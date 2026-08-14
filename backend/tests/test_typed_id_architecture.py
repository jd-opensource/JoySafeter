import ast
import re
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


BACKEND_ROOT = Path(__file__).resolve().parents[1]

ENTITY_ID_CLASS_NAMES = (
    "AgentId",
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

REVIEWED_ADAPTER_CATEGORIES = {
    "typed_id_codec": "EntityId public/native codecs and ORM hydration",
    "strict_validation_probe": "native UUID parse used only to reject a bare public reference",
    "sql_uuid_bind_result": "native PostgreSQL UUID bind/result conversion",
    "advisory_locks": "UUID bytes used to derive PostgreSQL advisory-lock keys",
    "redis_queue_channel_payloads": "Redis keys, channels, queue members, and payload fields",
    "runner_protobuf_fields": "runner/orchestrator wire fields defined as UUID strings",
    "telemetry_identities": "OpenTelemetry observation identities, not public entity IDs",
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
    "python:app/joysafeter_api/api/v1/sessions.py::_canonical_environment_ref::uuid_parse": (
        ("strict_validation_probe",),
        1,
    ),
    "python:app/joysafeter_api/api/v1/tasks.py::_stream_via_redis::as_uuid_call": (
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
    "python:app/joysafeter_domain/services/joysafeter_environment_service.py::EnvironmentService::get_environment_by_ref::uuid_parse": (
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
    "python:app/joysafeter_shared/ids.py::EntityIdType::process_bind_param::uuid_attr": (
        ("typed_id_codec", "sql_uuid_bind_result"),
        1,
    ),
    "python:app/joysafeter_shared/ids.py::as_uuid::uuid_attr": (("typed_id_codec",), 1),
    "python:app/joysafeter_shared/observation/otel/persistence_processor.py::_ExecutionBucket::on_end::uuid_parse": (
        ("telemetry_identities",),
        1,
    ),
    "python:app/joysafeter_shared/observation/otel/persistence_processor.py::_ExecutionBucket::on_start::uuid_parse": (
        ("telemetry_identities",),
        1,
    ),
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
    "rust:app/joysafeter_orchestrator_rs/src/ids.rs::uuid_parse": (("typed_id_codec",), 1),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs::uuid_parse": (
        ("redis_queue_channel_payloads", "runner_protobuf_fields"),
        1,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs::as_uuid": (
        ("sql_uuid_bind_result", "runner_protobuf_fields"),
        4,
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
        ("physical_resource_naming",),
        14,
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
        4,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs::as_uuid": (
        ("physical_resource_naming",),
        2,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs::as_uuid": (
        ("physical_resource_naming",),
        4,
    ),
    "rust:app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs::uuid_parse": (
        ("physical_resource_naming",),
        1,
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


CORE_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/agents.py",
    "app/joysafeter_api/api/v1/analytics.py",
    "app/joysafeter_api/api/v1/environments.py",
    "app/joysafeter_api/api/v1/files.py",
    "app/joysafeter_api/api/v1/credentials.py",
    "app/joysafeter_api/api/v1/credential_groups.py",
    "app/joysafeter_api/api/v1/sandboxes.py",
    "app/joysafeter_api/api/v1/sessions.py",
    "app/joysafeter_api/api/v1/tasks.py",
    "app/joysafeter_api/api/v1/triggers.py",
    "app/joysafeter_domain/services/agent_trigger_execution.py",
    "app/joysafeter_domain/services/analytics_service.py",
    "app/joysafeter_domain/services/joysafeter_agent_service.py",
    "app/joysafeter_domain/services/joysafeter_credential_service.py",
    "app/joysafeter_domain/services/joysafeter_credential_group_service.py",
    "app/joysafeter_domain/services/joysafeter_file_service.py",
    "app/joysafeter_domain/services/joysafeter_sandbox_service.py",
    "app/joysafeter_domain/services/joysafeter_session_resource_service.py",
    "app/joysafeter_domain/services/joysafeter_session_service.py",
    "app/joysafeter_domain/services/joysafeter_task_service.py",
    "app/joysafeter_domain/services/joysafeter_task_state_machine.py",
    "app/joysafeter_domain/services/joysafeter_trigger_fire_service.py",
    "app/joysafeter_domain/services/joysafeter_trigger_runtime_gate.py",
    "app/joysafeter_domain/services/joysafeter_trigger_service.py",
    "app/joysafeter_domain/services/task_submission_service.py",
)

SKILL_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/skills.py",
    "app/joysafeter_api/api/v1/skills_ai_authoring.py",
    "app/joysafeter_domain/repositories/joysafeter_skill.py",
    "app/joysafeter_domain/repositories/joysafeter_skill_version.py",
    "app/joysafeter_domain/services/joysafeter_skill_security.py",
    "app/joysafeter_domain/services/joysafeter_skill_service.py",
)

STORAGE_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/storage_volumes.py",
    "app/joysafeter_domain/schemas/joysafeter_storage_mount.py",
    "app/joysafeter_domain/schemas/joysafeter_session.py",
    "app/joysafeter_domain/services/joysafeter_storage_mount_service.py",
)


@pytest.mark.parametrize("relative_path", CORE_TYPED_ID_FILES)
def test_core_execution_graph_has_no_bare_uuid_entity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(
        r"\b(agent_id|session_id|task_id|sandbox_id|trigger_id|environment_id|env_id|secret_id|vault_id|cred_id|credential_id|file_id|resource_id|event_id)\s*:\s*(?:Optional\[)?uuid\.UUID"
    )

    assert forbidden.search(source) is None, relative_path


def test_agent_legacy_helpers_are_removed_from_application_code():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if "parse_agent_id" in source or "format_agent_id" in source:
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_python_application_has_no_bare_core_entity_annotations():
    app_root = BACKEND_ROOT / "app"
    forbidden = re.compile(
        r"\b(?P<field>(?:(?:[A-Za-z0-9]+_)?(?:agent|session|task|sandbox|trigger|environment|secret|vault|credential|memory_store|memory|memory_version|file|session_resource|event|storage_volume|storage_grant|storage_mount_audit|volume)_id|store_id|env_id|cred_id|resource_id))\s*:\s*"
        r"(?:(?:Optional|Union)\[)?(?:uuid\.UUID|UUID|str|Any)"
    )
    matches = []
    for path in app_root.rglob("*.py"):
        relative_path = str(path.relative_to(BACKEND_ROOT))
        violations = [
            match.group("field")
            for match in forbidden.finditer(path.read_text())
            if match.group("field") not in {"harness_session_id", "source_event_id"}
            and not (
                relative_path == "app/joysafeter_domain/schemas/joysafeter_session.py"
                and match.group("field") == "environment_id"
            )
        ]
        if violations:
            matches.append(relative_path)

    assert matches == []


def test_core_legacy_formatters_are_removed():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if "format_session_id" in source or "format_task_id" in source or "format_sandbox_id" in source:
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_core_legacy_parsers_are_removed():
    app_root = BACKEND_ROOT / "app"
    forbidden = (
        "parse_agent_id",
        "parse_session_id",
        "parse_task_id",
        "parse_task_after_id",
        "parse_sandbox_id",
        "parse_trigger_id",
        "parse_env_id",
        "parse_secret_id",
        "parse_vault_id",
        "parse_cred_id",
        "parse_skill_id",
        "parse_skill_file_id",
        "parse_skill_security_scan_id",
        "parse_file_id",
        "parse_resource_id",
        "parse_event_id",
    )
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if any(name in source for name in forbidden):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


@pytest.mark.parametrize("relative_path", SKILL_TYPED_ID_FILES)
def test_skill_execution_graph_has_no_bare_uuid_entity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(r"\b(skill_id|file_id|scan_id|version_id)\s*:\s*(?:Optional\[)?(?:uuid\.UUID|UUID|str|Any)")

    assert forbidden.search(source) is None, relative_path


@pytest.mark.parametrize("relative_path", STORAGE_TYPED_ID_FILES)
def test_storage_execution_graph_has_no_bare_identity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(r"\b(volume_id|after_id)\s*:\s*(?:Optional\[)?(?:uuid\.UUID|UUID|str|Any)")

    assert forbidden.search(source) is None, relative_path


def test_same_id_compatibility_helper_is_removed():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        if "same_id" in path.read_text():
            matches.append(str(path.relative_to(BACKEND_ROOT)))

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


def test_retained_entity_uuid_adapters_match_reviewed_allowlist():
    reviewed_counts = {key: count for key, (_, count) in REVIEWED_ENTITY_UUID_ADAPTERS.items()}
    reviewed_categories = {
        category for categories, _ in REVIEWED_ENTITY_UUID_ADAPTERS.values() for category in categories
    }

    assert reviewed_categories <= set(REVIEWED_ADAPTER_CATEGORIES)
    assert _scan_entity_uuid_adapters() == Counter(reviewed_counts)


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


def test_analytics_schemas_keep_agent_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/analytics.py").read_text()

    assert re.search(r"class AgentMetricsResponse.*?agent_id:\s*AgentId", source, re.S)
    assert re.search(r"class AlertItem.*?agent_id:\s*Optional\[AgentId\]", source, re.S)
    assert re.search(r"class AgentRankingItem.*?agent_id:\s*AgentId", source, re.S)


def test_trigger_models_keep_trigger_identity_typed():
    trigger_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_trigger.py").read_text()
    task_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_task.py").read_text()

    assert re.search(r"\bid:\s*Mapped\[TriggerId\].*?EntityIdType\(TriggerId\)", trigger_source, re.S)
    assert re.search(
        r"\btrigger_id:\s*Mapped\[Optional\[TriggerId\]\].*?EntityIdType\(TriggerId\)",
        task_source,
        re.S,
    )


def test_environment_models_keep_environment_identity_typed():
    environment_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_environment.py").read_text()
    audit_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_storage_mount.py").read_text()

    assert re.search(
        r"\bid:\s*Mapped\[EnvironmentId\].*?EntityIdType\(EnvironmentId\)",
        environment_source,
        re.S,
    )
    assert re.search(
        r"\benvironment_id:\s*Mapped\[Optional\[EnvironmentId\]\].*?EntityIdType\(EnvironmentId\)",
        audit_source,
        re.S,
    )


def test_credential_models_keep_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_credential.py").read_text()

    assert re.search(
        r"class JoySafeterCredential\b.*?\bid:\s*Mapped\[CredentialId\].*?EntityIdType\(CredentialId\)",
        source,
        re.S,
    )
    assert re.search(
        r"\bgroup_id:\s*Mapped\[Optional\[CredentialGroupId\]\].*?EntityIdType\(CredentialGroupId\)",
        source,
        re.S,
    )
    assert re.search(
        r"class JoySafeterCredentialGroup\b.*?\bid:\s*Mapped\[CredentialGroupId\].*?EntityIdType\(CredentialGroupId\)",
        source,
        re.S,
    )
    assert re.search(
        r"\bcredential_group_id:\s*Mapped\[CredentialGroupId\].*?EntityIdType\(CredentialGroupId\)",
        source,
        re.S,
    )


def test_sandbox_models_keep_sandbox_identity_typed():
    sandbox_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_sandbox.py").read_text()
    task_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_task.py").read_text()
    session_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session.py").read_text()
    policy_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_sandbox_network_policy.py").read_text()

    assert re.search(r"\bid:\s*Mapped\[SandboxId\].*?EntityIdType\(SandboxId\)", sandbox_source, re.S)
    assert re.search(
        r"\bsandbox_id:\s*Mapped\[Optional\[SandboxId\]\].*?EntityIdType\(SandboxId\)",
        task_source,
        re.S,
    )
    assert re.search(
        r"\blast_sandbox_id:\s*Mapped\[Optional\[SandboxId\]\].*?EntityIdType\(SandboxId\)",
        session_source,
        re.S,
    )
    assert re.search(r"\bsandbox_id:\s*Mapped\[SandboxId\].*?EntityIdType\(SandboxId\)", policy_source, re.S)


def test_memory_models_keep_memory_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_memory.py").read_text()

    assert re.search(r"class JoySafeterMemoryStore.*?\bid:\s*Mapped\[MemoryStoreId\]", source, re.S)
    assert re.search(r"class JoySafeterMemory.*?\bid:\s*Mapped\[MemoryId\]", source, re.S)
    assert re.search(r"\bstore_id:\s*Mapped\[MemoryStoreId\]", source)
    assert re.search(r"\bcurrent_version_id:\s*Mapped\[Optional\[MemoryVersionId\]\]", source)
    assert re.search(r"class JoySafeterMemoryVersion.*?\bid:\s*Mapped\[MemoryVersionId\]", source, re.S)


def test_skill_models_keep_skill_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_skill.py").read_text()

    expected = (
        ("JoySafeterSkill", "SkillId"),
        ("JoySafeterSkillFile", "SkillFileId"),
        ("JoySafeterSkillSecurityScan", "SkillSecurityScanId"),
        ("JoySafeterSkillVersion", "SkillVersionId"),
        ("JoySafeterSkillVersionFile", "SkillVersionFileId"),
        ("JoySafeterSkillUsageLog", "SkillUsageId"),
    )
    for model, id_type in expected:
        assert re.search(rf"class {model}.*?\bid:\s*Mapped\[{id_type}\]", source, re.S)


def test_file_and_session_resource_models_keep_identity_typed():
    file_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_file.py").read_text()
    session_file_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session_file.py").read_text()
    session_repo_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session_repo.py").read_text()

    assert re.search(r"\bid:\s*Mapped\[FileId\].*?EntityIdType\(FileId\)", file_source, re.S)
    assert re.search(
        r"\bid:\s*Mapped\[SessionResourceId\].*?EntityIdType\(SessionResourceId\)",
        session_file_source,
        re.S,
    )
    assert re.search(
        r"\bfile_id:\s*Mapped\[FileId\].*?EntityIdType\(FileId\)",
        session_file_source,
        re.S,
    )
    assert re.search(
        r"\bid:\s*Mapped\[SessionResourceId\].*?EntityIdType\(SessionResourceId\)",
        session_repo_source,
        re.S,
    )


def test_storage_models_keep_resource_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_storage_mount.py").read_text()

    expected = (
        ("JoySafeterStorageVolume", "StorageVolumeId"),
        ("JoySafeterStorageProjectGrant", "StorageGrantId"),
        ("JoySafeterStorageOrganizationGrant", "StorageGrantId"),
        ("JoySafeterSessionStorageMount", "SessionResourceId"),
        ("JoySafeterStorageMountAudit", "StorageMountAuditId"),
    )
    for model, id_type in expected:
        assert re.search(
            rf"class {model}.*?\bid:\s*Mapped\[{id_type}\].*?EntityIdType\({id_type}\)",
            source,
            re.S,
        )
    assert source.count("volume_id: Mapped[StorageVolumeId]") == 3
    assert "volume_id: Mapped[Optional[StorageVolumeId]]" in source


def test_storage_response_schemas_keep_resource_identity_typed():
    storage_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_storage_mount.py").read_text()
    session_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_session.py").read_text()

    assert re.search(r"class StorageVolumeResponse.*?\bid:\s*StorageVolumeId", storage_source, re.S)
    assert storage_source.count("id: StorageGrantId") == 2
    assert storage_source.count("volume_id: StorageVolumeId") == 2
    assert re.search(
        r"class StorageMountAuditResponse.*?\bid:\s*StorageMountAuditId.*?"
        r"volume_id:\s*Optional\[StorageVolumeId\]",
        storage_source,
        re.S,
    )
    assert re.search(
        r"class SessionStorageMountResponse.*?\bid:\s*SessionResourceId.*?"
        r"volume_id:\s*StorageVolumeId",
        session_source,
        re.S,
    )


def test_session_event_model_keeps_event_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session.py").read_text()
    assert re.search(
        r"class JoySafeterSessionEvent.*?\bid:\s*Mapped\[EventId\].*?EntityIdType\(EventId\)",
        source,
        re.S,
    )


def test_session_credential_groups_are_typed_not_jsonb():
    """Sessions bind credential GROUPS via the typed association table, not a
    ``vault_ids`` JSONB list. The schema carries ``list[CredentialGroupId]`` (on
    both request + response) and the service persists typed
    ``JoySafeterSessionCredentialGroup`` rows — so ids stay typed end to end and
    the legacy JSONB column is gone.
    """
    schema_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_session.py").read_text()
    service_source = (BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_session_service.py").read_text()

    assert "vault_ids" not in schema_source
    assert "vault_ids" not in service_source
    assert schema_source.count("credential_group_ids: list[CredentialGroupId]") == 2
    assert "JoySafeterSessionCredentialGroup(" in service_source


def test_rust_orchestrator_has_no_bare_core_entity_uuid_annotations():
    rust_root = BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src"
    forbidden = re.compile(
        r"\b(?:(?:[A-Za-z0-9]+_)?(?:agent|session|task|environment|vault|credential|sandbox|memory_store|memory|memory_version|skill|file|session_resource|event)_id|store_id|resource_id)\s*:\s*(?:Option<)?Uuid"
    )
    matches = []
    for path in rust_root.rglob("*.rs"):
        if forbidden.search(path.read_text()):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_rust_entity_ids_cannot_implicitly_deref_to_uuid():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()

    assert "impl std::ops::Deref" not in rust_ids


def test_rust_environment_and_credential_identity_boundaries_are_typed():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_scheduler = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs").read_text()
    rust_harness = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs").read_text()
    rust_resolver = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs").read_text()

    assert 'entity_id!(EnvironmentId, "env_");' in rust_ids
    assert 'entity_id!(CredentialId, "cred_");' in rust_ids
    assert 'entity_id!(CredentialGroupId, "credgrp_");' in rust_ids
    assert "id: EnvironmentId" in rust_scheduler
    assert "EnvironmentId::from_public(normalized)" in rust_scheduler
    assert 'strip_prefix("env_").unwrap_or(normalized)' not in rust_scheduler
    assert "let group_ids: Vec<CredentialGroupId>" in rust_harness
    assert "id: CredentialId" in rust_harness
    assert "let group_ids: Vec<CredentialGroupId>" in rust_resolver


def test_rust_orchestrator_models_use_core_entity_ids():
    source = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/models.rs").read_text()

    def struct_body(name: str) -> str:
        match = re.search(rf"pub struct {name}\s*\{{(?P<body>.*?)\n\}}", source, re.S)
        assert match is not None, name
        return match.group("body")

    agent_model = struct_body("JoySafeterAgent")
    task_model = struct_body("JoySafeterTask")
    session_model = struct_body("JoySafeterSession")
    sandbox_model = struct_body("JoySafeterSandbox")

    assert re.search(r"\bpub id:\s*AgentId\b", agent_model)
    assert re.search(r"\bpub id:\s*TaskId\b", task_model)
    assert re.search(r"\bpub session_id:\s*Option<SessionId>", task_model)
    assert re.search(r"\bpub sandbox_id:\s*Option<SandboxId>", task_model)
    assert re.search(r"\bpub id:\s*SessionId\b", session_model)
    assert re.search(r"\bpub id:\s*SandboxId\b", sandbox_model)
    assert re.search(r"\bpub chat_session_id:\s*Option<SessionId>", sandbox_model)


def test_sandbox_physical_boundaries_explicitly_unwrap_typed_ids():
    python_runtime = (BACKEND_ROOT / "app/joysafeter_shared/orchestrator_bridge/runtime_commands.py").read_text()
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_redis = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/redis_coordinator.rs").read_text()
    rust_commands = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs").read_text()
    rust_k8s = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs").read_text()

    assert 'entity_id!(SandboxId, "sbx_");' in rust_ids
    assert "sandbox_id_str = str(as_uuid(sandbox_id))" in python_runtime
    assert 'format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid())' in rust_redis
    assert "sandbox_id.as_uuid().to_string()" in rust_redis
    assert "SandboxId::from_uuid(id)" in rust_commands
    assert '"sandbox_id": sandbox_id.as_uuid().to_string()' in rust_commands
    assert 'format!("joysafeter-{}", sandbox_id.as_uuid())' in rust_k8s
    assert "let sandbox_uuid = config.sandbox_id.as_uuid();" in rust_k8s


def test_memory_physical_boundaries_explicitly_unwrap_typed_ids():
    python_memory_api = (BACKEND_ROOT / "app/joysafeter_api/api/v1/memory_stores.py").read_text()
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_harness = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs").read_text()
    rust_commands = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs").read_text()

    assert 'entity_id!(MemoryStoreId, "memstore_");' in rust_ids
    assert 'entity_id!(MemoryId, "mem_");' in rust_ids
    assert 'entity_id!(MemoryVersionId, "memver_");' in rust_ids
    assert '"store_id": str(as_uuid(store_id))' in python_memory_api
    assert "store_id: store.store_id.as_uuid().to_string()" in rust_harness
    assert ".map(MemoryStoreId::from_uuid)" in rust_commands
    assert ".notify_store_peers(" in rust_commands


def test_skill_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_harness = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs").read_text()

    for declaration in (
        'entity_id!(SkillId, "skill_");',
        'entity_id!(SkillFileId, "sklfile_");',
        'entity_id!(SkillSecurityScanId, "sklscan_");',
        'entity_id!(SkillVersionId, "sklver_");',
        'entity_id!(SkillVersionFileId, "sklvfile_");',
        'entity_id!(SkillUsageId, "skluse_");',
    ):
        assert declaration in rust_ids
    assert "SkillId::from_public(skill_id)" in rust_harness
    assert ".bind(SkillUsageId::from_uuid(Uuid::now_v7()))" in rust_harness


def test_file_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_query = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/queries/file.rs").read_text()
    rust_artifacts = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/sandbox/artifacts.rs").read_text()
    python_file_service = (BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_file_service.py").read_text()

    assert 'entity_id!(FileId, "file_");' in rust_ids
    assert 'entity_id!(SessionResourceId, "sesrsc_");' in rust_ids
    assert "id: FileId" in rust_query
    assert "Option<FileId>" in rust_artifacts
    assert "let raw_file_id = file_id.as_uuid();" in rust_artifacts
    assert "as_uuid(file_id)" in python_file_service


def test_event_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_envelope = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/events/envelope.rs").read_text()
    rust_realtime = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/events/realtime.rs").read_text()
    python_session = (BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_session_service.py").read_text()

    assert 'entity_id!(EventId, "evt_");' in rust_ids
    assert "pub event_id: Option<EventId>" in rust_envelope
    assert "id.to_public()" in rust_realtime
    assert 'event["id"] = str(event_id)' in python_session


def test_credential_group_id_roundtrip():
    from app.joysafeter_shared.ids import CredentialGroupId

    cid = CredentialGroupId.new()
    assert str(cid).startswith("credgrp_")
    assert CredentialGroupId.from_public(str(cid)) == cid


def test_secret_and_vault_ids_removed():
    import app.joysafeter_shared.ids as ids

    assert not hasattr(ids, "SecretId")
    assert not hasattr(ids, "VaultId")
