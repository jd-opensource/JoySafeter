import pytest

from app.joysafeter_domain.quickstart.engine_policy import (
    ConnectionInput,
    EngineInput,
    recommend_engine_options,
)

pytestmark = pytest.mark.no_db


def _engines():
    return [
        EngineInput("native", "Native", True),
        EngineInput("claude", "Claude Code", True),
        EngineInput("codex", "Codex", True),
    ]


def test_ready_engine_with_connection_ranks_first_and_is_recommended():
    conns = [ConnectionInput(("codex",), True, False)]
    options = recommend_engine_options(_engines(), conns, "just chat")
    assert options[0].engine_id == "codex"
    assert options[0].readiness == "ready"
    assert options[0].recommended is True


def test_coding_intent_prefers_claude_when_none_ready():
    options = recommend_engine_options(_engines(), [], "fix a bug in my python repo")
    ids = [o.engine_id for o in options]
    assert ids[0] == "claude"
    assert all(o.readiness == "setup_required" for o in options)
    assert options[0].recommended is True


def test_disabled_engine_is_unavailable_and_never_recommended():
    engines = [EngineInput("native", "Native", False), EngineInput("codex", "Codex", True)]
    options = recommend_engine_options(engines, [], "hello")
    native = next(o for o in options if o.engine_id == "native")
    assert native.readiness == "unavailable"
    assert native.recommended is False


def test_archived_connections_are_ignored():
    conns = [ConnectionInput(("codex",), True, True)]
    options = recommend_engine_options(_engines(), conns, "hi")
    codex = next(o for o in options if o.engine_id == "codex")
    assert codex.readiness == "setup_required"
    assert codex.compatible_connection_count == 0
