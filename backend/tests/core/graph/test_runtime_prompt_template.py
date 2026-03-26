import sys
import types
from pathlib import Path


def _import_runtime_renderer():
    graph_package = "app.core.graph"
    root = Path(__file__).resolve().parents[3]
    stub = types.ModuleType(graph_package)
    stub.__path__ = [str(root / "app" / "core" / "graph")]
    tracker = {}
    tracker[graph_package] = sys.modules.get(graph_package)
    tracker[f"{graph_package}.runtime_prompt_template"] = sys.modules.get(
        f"{graph_package}.runtime_prompt_template"
    )
    sys.modules[graph_package] = stub
    try:
        from app.core.graph.runtime_prompt_template import render_runtime_template
    finally:
        for name, original in tracker.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return render_runtime_template


render_runtime_template = _import_runtime_renderer()


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
