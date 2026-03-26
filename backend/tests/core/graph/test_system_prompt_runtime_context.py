import importlib
import sys
import types
import uuid

import pytest

from app.models.graph import AgentGraph, GraphNode


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


graph_builder_factory = _import_with_optional_dependency_stubs("app.core.graph.graph_builder_factory")
_base_graph_builder = _import_with_optional_dependency_stubs("app.core.graph.base_graph_builder")
_deep_agents_node_config = _import_with_optional_dependency_stubs("app.core.graph.deep_agents.node_config")
_agent_executor = _import_with_optional_dependency_stubs("app.core.graph.executors.agent")

BaseGraphBuilder = _base_graph_builder.BaseGraphBuilder
AgentConfig = _deep_agents_node_config.AgentConfig
AgentNodeExecutor = _agent_executor.AgentNodeExecutor


def _make_graph() -> AgentGraph:
    return AgentGraph(
        id=uuid.uuid4(),
        name="Test Graph",
        user_id="user-1",
        variables={},
    )


def _make_node(graph: AgentGraph, *, use_deep_agents: bool, system_prompt: str) -> GraphNode:
    return GraphNode(
        id=uuid.uuid4(),
        graph_id=graph.id,
        type="agent",
        data={
            "label": "Agent",
            "config": {
                "useDeepAgents": use_deep_agents,
                "systemPrompt": system_prompt,
            },
        },
        position_x=0,
        position_y=0,
        width=0,
        height=0,
    )


class _CapturingBuilder:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.thread_id = kwargs.get("thread_id")


class _TestBaseGraphBuilder(BaseGraphBuilder):
    def build(self):  # type: ignore[override]
        raise NotImplementedError


@pytest.mark.parametrize(
    ("use_deep_agents", "builder_attr", "deepagents_available"),
    [
        (True, "DeepAgentsGraphBuilder", True),
        (False, "LanggraphModelBuilder", False),
    ],
)
def test_graph_builder_passes_thread_id_to_inner_builder(
    monkeypatch: pytest.MonkeyPatch,
    use_deep_agents: bool,
    builder_attr: str,
    deepagents_available: bool,
) -> None:
    graph = _make_graph()
    node = _make_node(graph, use_deep_agents=use_deep_agents, system_prompt="Hello {thread_id}")

    monkeypatch.setattr(graph_builder_factory, "DEEPAGENTS_AVAILABLE", deepagents_available)
    monkeypatch.setattr(graph_builder_factory, builder_attr, _CapturingBuilder)

    builder = graph_builder_factory.GraphBuilder(
        graph=graph,
        nodes=[node],
        edges=[],
        thread_id="thread-123",
    )

    inner_builder = builder._create_builder()

    assert inner_builder.thread_id == "thread-123"


def test_builder_runtime_context_includes_built_in_fields() -> None:
    graph = _make_graph()
    graph.workspace_id = uuid.uuid4()
    runtime_user_id = uuid.uuid4()

    builder = _TestBaseGraphBuilder(
        graph=graph,
        nodes=[],
        edges=[],
        user_id=runtime_user_id,
        thread_id="thread-123",
    )

    assert builder.runtime_prompt_context == {
        "thread_id": "thread-123",
        "user_id": str(runtime_user_id),
        "graph_id": str(graph.id),
        "workspace_id": str(graph.workspace_id),
        "graph_name": "Test Graph",
    }


def test_graph_variables_context_overrides_built_ins() -> None:
    graph = _make_graph()
    graph.workspace_id = uuid.uuid4()
    runtime_user_id = uuid.uuid4()
    graph.variables = {
        "context": {
            "thread_id": "override-thread",
            "graph_name": "Override Name",
            "custom_key": "custom-value",
        }
    }

    builder = _TestBaseGraphBuilder(
        graph=graph,
        nodes=[],
        edges=[],
        user_id=runtime_user_id,
        thread_id="thread-123",
    )

    assert builder.runtime_prompt_context["thread_id"] == "override-thread"
    assert builder.runtime_prompt_context["graph_name"] == "Override Name"
    assert builder.runtime_prompt_context["custom_key"] == "custom-value"


def test_builder_renders_prompt_using_runtime_prompt_context() -> None:
    graph = _make_graph()
    runtime_user_id = uuid.uuid4()
    graph.variables = {
        "context": {
            "thread_id": "override-thread",
            "project": "runtime-project",
        }
    }
    node = _make_node(
        graph,
        use_deep_agents=False,
        system_prompt=("T={thread_id} U={user_id} G={graph_name} W={workspace_id} P={project} M={missing_key}"),
    )

    builder = _TestBaseGraphBuilder(
        graph=graph,
        nodes=[node],
        edges=[],
        user_id=runtime_user_id,
        thread_id="thread-123",
    )

    assert (
        builder._get_system_prompt_from_node(node)
        == f"T=override-thread U={runtime_user_id} G=Test Graph W={{workspace_id}} "
        "P=runtime-project M={missing_key}"
    )


def test_agent_node_executor_uses_builder_rendered_system_prompt() -> None:
    graph = _make_graph()
    node = _make_node(graph, use_deep_agents=False, system_prompt="Hello {thread_id}")

    class _BuilderStub:
        def _get_system_prompt_from_node(self, graph_node: GraphNode) -> str:
            assert graph_node is node
            return "Hello thread-123"

    executor = AgentNodeExecutor(node=node, node_id="agent-1", builder=_BuilderStub())

    assert executor.system_prompt == "Hello thread-123"


def test_agent_node_executor_falls_back_to_raw_system_prompt_without_builder() -> None:
    graph = _make_graph()
    node = _make_node(graph, use_deep_agents=False, system_prompt="Hello {thread_id}")

    executor = AgentNodeExecutor(node=node, node_id="agent-1")

    assert executor.system_prompt == "Hello {thread_id}"


def test_agent_node_executor_fallback_reads_system_prompt_snake_case() -> None:
    graph = _make_graph()
    node = GraphNode(
        id=uuid.uuid4(),
        graph_id=graph.id,
        type="agent",
        data={
            "label": "Agent",
            "config": {
                "system_prompt": "Hello snake-case",
            },
        },
        position_x=0,
        position_y=0,
        width=0,
        height=0,
    )

    executor = AgentNodeExecutor(node=node, node_id="agent-1")

    assert executor.system_prompt == "Hello snake-case"


@pytest.mark.asyncio
async def test_deep_agents_agent_config_uses_builder_rendered_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _make_graph()
    node = _make_node(graph, use_deep_agents=True, system_prompt="Hello {thread_id}")

    async def _resolve_tools_for_node_stub(*args, **kwargs):
        return ["raw-tool"]

    import app.core.agent.node_tools as node_tools

    monkeypatch.setattr(node_tools, "resolve_tools_for_node", _resolve_tools_for_node_stub)

    class _BuilderStub:
        user_id = "runtime-user"

        def __init__(self) -> None:
            self.prompt_calls: list[GraphNode] = []

        def _get_node_name(self, graph_node: GraphNode) -> str:
            assert graph_node is node
            return "fallback-name"

        def get_backend(self):
            return None

        async def _resolve_tools_from_registry(self, raw_tools, *, user_id: str):
            assert raw_tools == ["raw-tool"]
            assert user_id == "runtime-user"
            return ["resolved-tool"]

        def has_valid_skills_config(self, skill_ids_raw) -> bool:
            assert skill_ids_raw is None
            return False

        async def preload_skills_to_backend(self, graph_node: GraphNode, backend) -> None:
            raise AssertionError("preload_skills_to_backend should not be called without valid skills")

        async def resolve_middleware_for_node_with_backend(self, graph_node: GraphNode, backend, *, user_id: str):
            assert graph_node is node
            assert backend is None
            assert user_id == "runtime-user"
            return ["middleware"]

        def get_skills_paths(self, has_skills: bool, backend):
            assert has_skills is False
            assert backend is None
            return None

        async def _resolve_node_llm(self, graph_node: GraphNode):
            assert graph_node is node
            return "resolved-model"

        def _get_system_prompt_from_node(self, graph_node: GraphNode) -> str:
            assert graph_node is node
            self.prompt_calls.append(graph_node)
            return "Hello thread-123"

    builder = _BuilderStub()
    config = await AgentConfig.from_node(node=node, builder=builder, node_id_to_name={})

    assert config.system_prompt == "Hello thread-123"
    assert config.system_prompt != "Hello {thread_id}"
    assert config.tools == ["resolved-tool"]
    assert builder.prompt_calls == [node]
