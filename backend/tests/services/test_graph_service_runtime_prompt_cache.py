import importlib
import sys
import types
import uuid
from datetime import datetime, timezone

from app.models.graph import AgentGraph


def _import_with_optional_dependency_stubs(module_name: str):
    module_names = ("langchain_google_genai", "pydantic_ai_backends")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    modules_before_import = set(sys.modules)

    for name in module_names:
        sys.modules.pop(name, None)

    try:
        genai_stub = types.ModuleType("langchain_google_genai")

        class _ChatGoogleGenerativeAI:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        genai_stub.ChatGoogleGenerativeAI = _ChatGoogleGenerativeAI
        sys.modules["langchain_google_genai"] = genai_stub

        backends_stub = types.ModuleType("pydantic_ai_backends")

        class _DockerSandbox:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class _RuntimeConfig:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        backends_stub.DockerSandbox = _DockerSandbox
        backends_stub.RuntimeConfig = _RuntimeConfig
        sys.modules["pydantic_ai_backends"] = backends_stub

        imported_module = importlib.import_module(module_name)
        return imported_module
    finally:
        new_modules = set(sys.modules) - modules_before_import
        for name in new_modules:
            if name.startswith("app."):
                sys.modules.pop(name, None)
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


_graph_service = _import_with_optional_dependency_stubs("app.services.graph_service")
_build_runtime_aware_compile_cache_key = _graph_service._build_runtime_aware_compile_cache_key


def _make_graph(*, graph_id: uuid.UUID, context: dict) -> AgentGraph:
    graph = AgentGraph(
        id=graph_id,
        name="Runtime Cache Graph",
        user_id="owner-user",
        variables={"context": context},
    )
    graph.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return graph


def test_cache_key_changes_when_thread_id_changes() -> None:
    graph = _make_graph(graph_id=uuid.uuid4(), context={})

    key1 = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-1")
    key2 = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-2")

    assert key1 != key2


def test_cache_key_changes_when_graph_context_override_changes() -> None:
    graph_id = uuid.uuid4()
    graph1 = _make_graph(graph_id=graph_id, context={"thread_id": "override-1"})
    graph2 = _make_graph(graph_id=graph_id, context={"thread_id": "override-2"})

    key1 = _build_runtime_aware_compile_cache_key(graph1, user_id="user-1", thread_id="thread-raw")
    key2 = _build_runtime_aware_compile_cache_key(graph2, user_id="user-1", thread_id="thread-raw")

    assert key1 != key2


def test_cache_key_stable_for_equivalent_context_ordering() -> None:
    graph_id = uuid.uuid4()
    graph1 = _make_graph(
        graph_id=graph_id,
        context={
            "project": "x",
            "meta": {"alpha": 1, "beta": 2},
        },
    )
    graph2 = _make_graph(
        graph_id=graph_id,
        context={
            "meta": {"beta": 2, "alpha": 1},
            "project": "x",
        },
    )

    key1 = _build_runtime_aware_compile_cache_key(graph1, user_id="user-1", thread_id="thread-raw")
    key2 = _build_runtime_aware_compile_cache_key(graph2, user_id="user-1", thread_id="thread-raw")

    assert key1 == key2


def test_cache_key_repeated_execution_safe_for_runtime_context_changes() -> None:
    graph = _make_graph(graph_id=uuid.uuid4(), context={})

    first_key = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-raw")
    repeated_same_key = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-raw")
    assert repeated_same_key == first_key

    graph.variables = {"context": {"project": "alpha"}}
    changed_context_key = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-raw")
    assert changed_context_key != first_key

    graph.variables = {"context": {"project": "beta"}}
    changed_context_key_again = _build_runtime_aware_compile_cache_key(graph, user_id="user-1", thread_id="thread-raw")
    assert changed_context_key_again != changed_context_key
