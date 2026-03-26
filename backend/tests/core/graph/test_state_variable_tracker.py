import uuid
import importlib
import sys
import types

from app.models.graph import GraphNode


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


_state_variable_tracker = _import_with_optional_dependency_stubs("app.core.graph.state_variable_tracker")
StateVariableTracker = _state_variable_tracker.StateVariableTracker


def _make_node(*, node_type: str, config: dict) -> GraphNode:
    return GraphNode(
        id=uuid.uuid4(),
        graph_id=uuid.uuid4(),
        type=node_type,
        data={
            "type": node_type,
            "label": f"{node_type}-node",
            "config": config,
        },
        position_x=0,
        position_y=0,
        width=0,
        height=0,
    )


def test_agent_node_tracks_supported_runtime_prompt_variables() -> None:
    node = _make_node(
        node_type="agent",
        config={
            "systemPrompt": "T={thread_id} P={project} {{mustache}} {user.id} {vars['name']}",
        },
    )

    result = StateVariableTracker(nodes=[node], edges=[]).analyze_graph()

    assert set(result) == {"thread_id", "project"}
    assert result["thread_id"].usages[0].path == "context.thread_id"
    assert result["project"].usages[0].path == "context.project"


def test_direct_reply_node_keeps_existing_mustache_variable_tracking() -> None:
    node = _make_node(
        node_type="direct_reply",
        config={
            "template": "Hello {{name}}",
        },
    )

    result = StateVariableTracker(nodes=[node], edges=[]).analyze_graph()

    assert set(result) == {"name"}
    assert result["name"].usages[0].path == "context.name"
