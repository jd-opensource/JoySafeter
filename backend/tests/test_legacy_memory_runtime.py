from types import SimpleNamespace

from app.joysafeter_orchestrator.grpc import server
from app.joysafeter_orchestrator.kernel import legacy_memory


def _harness_input_with_memory():
    return SimpleNamespace(
        skill_archives=[],
        mcp_servers=[],
        custom_tools=[],
        memory_mounts=[
            {
                "store_id": "memstore_1",
                "mount_name": "legacy",
                "access": "read_write",
                "files": [{"path": "/note.md", "content": "old memory"}],
            }
        ],
        file_mounts=[],
        file_refs=[],
        env={},
        permission_mode="default",
        model="",
        memory_system_prompt="# Memory\nlegacy",
        allowed_tools=[],
        ask_tools=[],
        repos=[],
    )


def test_legacy_sandbox_memory_runtime_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JOYSAFETER_LEGACY_SANDBOX_MEMORY_ENABLED", raising=False)

    assert legacy_memory.legacy_sandbox_memory_enabled() is False


def test_legacy_sandbox_memory_runtime_can_be_enabled(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LEGACY_SANDBOX_MEMORY_ENABLED", "true")

    assert legacy_memory.legacy_sandbox_memory_enabled() is True


def test_setup_sandbox_omits_legacy_memory_when_disabled(monkeypatch):
    monkeypatch.delenv("JOYSAFETER_LEGACY_SANDBOX_MEMORY_ENABLED", raising=False)

    setup = server._build_setup_sandbox(
        _harness_input_with_memory(),
        agent=SimpleNamespace(engine_kind="claude"),
    )

    assert list(setup.memory_mounts) == []
    assert setup.memory_system_prompt == ""


def test_setup_sandbox_includes_legacy_memory_when_enabled(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LEGACY_SANDBOX_MEMORY_ENABLED", "1")

    setup = server._build_setup_sandbox(
        _harness_input_with_memory(),
        agent=SimpleNamespace(engine_kind="claude"),
    )

    assert len(setup.memory_mounts) == 1
    assert setup.memory_mounts[0].mount_name == "legacy"
    assert setup.memory_system_prompt == "# Memory\nlegacy"
