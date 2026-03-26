import sys
import types
import uuid
from pathlib import Path

from app.models.graph import AgentGraph


def _import_runtime_renderer():
    graph_package = "app.core.graph"
    root = Path(__file__).resolve().parents[3]
    stub = types.ModuleType(graph_package)
    stub.__path__ = [str(root / "app" / "core" / "graph")]
    tracker = {}
    tracker[graph_package] = sys.modules.get(graph_package)
    tracker[f"{graph_package}.runtime_prompt_template"] = sys.modules.get(f"{graph_package}.runtime_prompt_template")
    sys.modules[graph_package] = stub
    try:
        from app.core.graph.runtime_prompt_template import (
            build_runtime_prompt_context,
            extract_runtime_template_variables,
            get_prompt_text_from_config,
            render_runtime_template,
        )
    finally:
        for name, original in tracker.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return (
        render_runtime_template,
        get_prompt_text_from_config,
        extract_runtime_template_variables,
        build_runtime_prompt_context,
    )


(
    render_runtime_template,
    get_prompt_text_from_config,
    extract_runtime_template_variables,
    build_runtime_prompt_context,
) = _import_runtime_renderer()


def test_known_placeholders_are_replaced():
    rendered = render_runtime_template(
        "Thread {thread_id} repo {target_repo}",
        {"thread_id": 42, "target_repo": "main"},
    )
    assert rendered == "Thread 42 repo main"


def test_missing_placeholders_stay_literal():
    rendered = render_runtime_template(
        "Missing {nothing} still literal",
        {},
    )
    assert rendered == "Missing {nothing} still literal"


def test_non_string_values_converted_none_untouched():
    rendered = render_runtime_template(
        "Count {count} optional {optional}",
        {"count": 7, "optional": None},
    )
    assert rendered == "Count 7 optional {optional}"


def test_mustache_placeholders_remain_when_context_has_key():
    rendered = render_runtime_template(
        "{{mustache}}",
        {"mustache": "X"},
    )
    assert rendered == "{{mustache}}"


def test_unsupported_placeholder_shapes_ignored():
    rendered = render_runtime_template(
        "Shallow {user.id} {vars['name']} {vars[\"name\"]} {{mustache}}",
        {"user": "irrelevant", "vars": {"name": "ignored"}},
    )
    assert rendered == "Shallow {user.id} {vars['name']} {vars[\"name\"]} {{mustache}}"


def test_none_input_returns_none():
    assert render_runtime_template(None, {"anything": "value"}) is None


def test_get_prompt_text_from_config_prefers_supported_keys():
    assert get_prompt_text_from_config({"systemPrompt": "A", "prompt": "B"}) == "A"
    assert get_prompt_text_from_config({"system_prompt": "A", "prompt": "B"}) == "A"
    assert get_prompt_text_from_config({"prompt": "B"}) == "B"
    assert get_prompt_text_from_config({}) is None


def test_extract_runtime_template_variables_only_returns_supported_shapes():
    variables = extract_runtime_template_variables(
        "T={thread_id} P={project} {{mustache}} {user.id} {vars['name']} {missing_key}"
    )
    assert variables == {"thread_id", "project", "missing_key"}


def test_build_runtime_prompt_context_merges_built_ins_and_graph_context():
    graph = AgentGraph(
        id=uuid.uuid4(),
        name="Prompt Graph",
        user_id="owner-user",
        workspace_id=uuid.uuid4(),
        variables={"context": {"thread_id": "override-thread", "project": "alpha"}},
    )

    context = build_runtime_prompt_context(graph, user_id=uuid.uuid4(), thread_id="thread-123")

    assert context["thread_id"] == "override-thread"
    assert context["project"] == "alpha"
    assert context["graph_id"] == str(graph.id)
    assert context["workspace_id"] == str(graph.workspace_id)
    assert context["graph_name"] == "Prompt Graph"
