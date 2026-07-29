import io
import uuid
import zipfile
from types import SimpleNamespace
from typing import Any

from app.joysafeter_orchestrator.kernel import harness_input_builder as hib
from app.joysafeter_orchestrator.sandbox.file_injection import (
    FileInjectionContext,
    HostMountStrategy,
    SessionFileRecord,
)


class _MemoryStorage:
    def __init__(self, data: bytes):
        self._data = data

    async def get(self, _key: str) -> bytes:
        return self._data


class _EverOSResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _EverOSClient:
    requests: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, json: dict[str, Any]):
        self.requests.append({"url": url, "json": json})
        return _EverOSResponse(self.responses.pop(0))


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("repo/README.md", "hello")
    return buf.getvalue()


def test_everos_base_url_defaults_to_sandbox_reachable_host(monkeypatch):
    monkeypatch.delenv("EVEROS_BASE_URL", raising=False)
    monkeypatch.delenv("EVEROS_MEMORY_PROXY_BASE_URL", raising=False)

    assert hib._resolve_everos_base_url() == "http://host.docker.internal:8000/api/v1/everos_memory"


def test_everos_base_url_ignores_bare_everos_runtime_url(monkeypatch):
    monkeypatch.setenv("EVEROS_BASE_URL", "http://host.docker.internal:8003")
    monkeypatch.delenv("EVEROS_MEMORY_PROXY_BASE_URL", raising=False)

    assert hib._resolve_everos_base_url() == "http://host.docker.internal:8000/api/v1/everos_memory"


def test_everos_proxy_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("EVEROS_MEMORY_PROXY_BASE_URL", "http://memory.local:18000/api/v1/everos_memory")

    assert hib._resolve_everos_base_url() == "http://memory.local:18000/api/v1/everos_memory"


def test_append_everos_system_prompt_adds_service_note():
    base = "You are a security assistant."
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-1",
        agent_id="agent-1",
    )
    out = hib._append_everos_system_prompt(base, "http://everos:8003", identity)

    assert "You are a security assistant." in out
    assert "EverOS memory service" in out
    assert "http://everos:8003" in out


def test_everos_identity_env_maps_joysafeter_ids():
    identity = hib._build_everos_identity_env(
        project_id="project-123",
        project_slug="test",
        session_id="session-456",
        user_name="huajie Sun",
        user_id="e7197065-b019-4f81-80a6-e66515074cba",
        agent_id="agent-789",
    )

    assert identity == {
        "EVEROS_APP_ID": "joysafeter",
        "EVEROS_PROJECT_ID": "test__project-123",
        "EVEROS_SESSION_ID": "session-456",
        "EVEROS_USER_ID": "huajie_Sun",
        "EVEROS_AGENT_ID": "agent-789",
    }


def test_everos_identity_env_sanitizes_path_ids():
    identity = hib._build_everos_identity_env(
        project_id="../unsafe project",
        session_id="session/value",
        user_name="huajie Sun",
        agent_id=".",
    )

    assert identity["EVEROS_PROJECT_ID"] == "unsafe_project"
    assert identity["EVEROS_SESSION_ID"] == "session_value"
    assert identity["EVEROS_USER_ID"] == "huajie_Sun"
    assert identity["EVEROS_AGENT_ID"] == "agent"


def test_append_everos_system_prompt_documents_identity_mapping():
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-1",
        user_name="huajie Sun",
        agent_id="agent-1",
    )
    out = hib._append_everos_system_prompt(None, "http://everos:8003", identity)

    assert "EVEROS_APP_ID" in out
    assert "EVEROS_PROJECT_ID" in out
    assert "EVEROS_SESSION_ID" in out
    assert "EVEROS_USER_ID" in out
    assert "EVEROS_AGENT_ID" in out
    assert "/get" in out
    assert "/search" in out
    assert "/api/v1/memory/get" not in out
    assert "/api/v1/memory/search" not in out
    assert "app_id" in out
    assert "project_id" in out
    assert "user_id" in out
    assert "agent_id" in out


async def test_fetch_everos_bootstrap_memories_loads_session_user_and_agent_memory(monkeypatch):
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-1",
        user_name="huajie Sun",
        agent_id="agent-1",
    )
    _EverOSClient.requests = []
    _EverOSClient.responses = [
        {"data": {"profiles": [{"id": "profile-1", "profile_data": {"summary": "User profile"}}]}},
        {
            "data": {
                "episodes": [
                    {
                        "id": "episode-1",
                        "entry_id": "ep-entry-1",
                        "parent_id": "memcell-1",
                        "subject": "Recent episode",
                    }
                ]
            }
        },
        {
            "data": {
                "atomic_facts": [
                    {"id": "fact-1", "parent_id": "ep-entry-1", "fact": "User wants concise memory loading."},
                    {"id": "fact-2", "parent_id": "unrelated-episode", "fact": "This should not attach."},
                ]
            }
        },
        {"data": {"agent_cases": [{"id": "case-1", "task_intent": "Debug issue"}]}},
        {"data": {"agent_skills": [{"id": "skill-1", "name": "Debugging skill"}]}},
    ]
    monkeypatch.setattr(hib.httpx, "AsyncClient", _EverOSClient)

    memories = await hib._fetch_everos_bootstrap_memories("http://everos-proxy", identity)

    assert memories["profiles"][0]["id"] == "profile-1"
    assert memories["episodes"][0]["id"] == "episode-1"
    assert memories["episodes"][0]["atomic_facts"] == [
        {"id": "fact-1", "parent_id": "ep-entry-1", "fact": "User wants concise memory loading."}
    ]
    assert memories["agent_cases"][0]["id"] == "case-1"
    assert memories["agent_skills"][0]["id"] == "skill-1"
    assert [req["json"]["memory_type"] for req in _EverOSClient.requests] == [
        "profile",
        "episode",
        "atomic_fact",
        "agent_case",
        "agent_skill",
    ]
    assert all(req["url"] == "http://everos-proxy/get" for req in _EverOSClient.requests)
    assert _EverOSClient.requests[0]["json"]["user_id"] == "huajie_Sun"
    assert _EverOSClient.requests[1]["json"]["page_size"] == 5
    assert _EverOSClient.requests[2]["json"]["user_id"] == "huajie_Sun"
    assert _EverOSClient.requests[2]["json"]["filters"] == {
        "parent_id": {"in": ["ep-entry-1", "memcell-1"]}
    }
    assert _EverOSClient.requests[3]["json"]["agent_id"] == "agent-1"
    assert _EverOSClient.requests[3]["json"]["page_size"] == 5
    assert _EverOSClient.requests[4]["json"]["agent_id"] == "agent-1"
    assert _EverOSClient.requests[4]["json"]["page_size"] == 5


async def test_fetch_everos_bootstrap_memories_filters_session_scoped_memory_to_active_sessions(monkeypatch):
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-current",
        user_name="huajie Sun",
        agent_id="agent-1",
    )
    _EverOSClient.requests = []
    _EverOSClient.responses = [
        {"data": {"profiles": []}},
        {"data": {"episodes": []}},
        {"data": {"agent_cases": []}},
        {"data": {"agent_skills": []}},
    ]
    monkeypatch.setattr(hib.httpx, "AsyncClient", _EverOSClient)

    await hib._fetch_everos_bootstrap_memories(
        "http://everos:8003",
        identity,
        active_session_ids=["session-current", "session-other-active"],
    )

    assert _EverOSClient.requests[0]["json"]["memory_type"] == "profile"
    assert "filters" not in _EverOSClient.requests[0]["json"]
    assert _EverOSClient.requests[1]["json"]["memory_type"] == "episode"
    assert _EverOSClient.requests[1]["json"]["filters"] == {
        "session_id": {"in": ["session-current", "session-other-active"]}
    }
    assert _EverOSClient.requests[2]["json"]["memory_type"] == "agent_case"
    assert _EverOSClient.requests[2]["json"]["filters"] == {
        "session_id": {"in": ["session-current", "session-other-active"]}
    }
    assert _EverOSClient.requests[3]["json"]["memory_type"] == "agent_skill"
    assert "filters" not in _EverOSClient.requests[3]["json"]


def test_format_everos_bootstrap_prompt_injects_metadata_and_full_load_instructions():
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-1",
        user_name="huajie Sun",
        agent_id="agent-1",
    )
    prompt = hib._format_everos_bootstrap_prompt(
        identity,
        {
            "profiles": [
                {
                    "id": "profile-1",
                    "profile_data": {
                        "summary": "User prefers concise answers.",
                        "explicit_info": {"language": "Chinese"},
                        "implicit_traits": {"style": "direct"},
                    },
                }
            ],
            "episodes": [
                {
                    "id": "episode-1",
                    "entry_id": "ep-entry-1",
                    "timestamp": "2026-07-20T01:00:00Z",
                    "subject": "Memory design",
                    "summary": "Discussed loading memories at session start.",
                    "episode": "Full episode body should not be injected into the bootstrap prompt.",
                    "atomic_facts": [
                        {"id": "fact-1", "fact": "User wants episode facts shown with the episode."}
                    ],
                }
            ],
            "agent_cases": [
                {
                    "id": "case-1",
                    "session_id": "case-session",
                    "task_intent": "Fix frontend filtering",
                    "approach": "Use owner agent id.",
                    "quality_score": 0.91,
                    "key_insight": "Skill selection maps to agent id.",
                }
            ],
            "agent_skills": [
                {
                    "id": "skill-1",
                    "name": "Memory UI filtering",
                    "description": "Filter related memories by owner id.",
                    "content": "Full skill content should not be injected into the bootstrap prompt.",
                    "confidence": 0.86,
                    "maturity_score": 0.65,
                    "source_case_ids": ["case-1"],
                }
            ],
        },
    )

    assert "EverOS Memory Bootstrap" in prompt
    assert "user_id: huajie_Sun" in prompt
    assert "agent_id: agent-1" in prompt
    assert "User prefers concise answers." in prompt
    assert "explicit_info" in prompt
    assert "implicit_traits" in prompt
    assert "Memory design" in prompt
    assert "Related Facts" in prompt
    assert "User wants episode facts shown with the episode." in prompt
    assert "Full episode body should not be injected" not in prompt
    assert "Fix frontend filtering" in prompt
    assert "Memory UI filtering" in prompt
    assert "Full skill content should not be injected" not in prompt
    assert "${EVEROS_BASE_URL}/get" in prompt
    assert "${EVEROS_BASE_URL}/search" in prompt
    assert "/api/v1/memory/get" not in prompt
    assert "/api/v1/memory/search" not in prompt
    assert '"memory_type": "episode"' in prompt
    assert '"memory_type": "atomic_fact"' in prompt
    assert '"memory_type": "agent_case"' in prompt
    assert '"memory_type": "agent_skill"' in prompt
    assert "progressive" in prompt


async def test_build_everos_bootstrap_prompt_returns_empty_when_everos_fails(monkeypatch):
    identity = hib._build_everos_identity_env(
        project_id="project-1",
        session_id="session-1",
        agent_id="agent-1",
    )

    class FailingClient(_EverOSClient):
        async def post(self, url: str, json: dict[str, Any]):
            raise RuntimeError("everos unavailable")

    monkeypatch.setattr(hib.httpx, "AsyncClient", FailingClient)

    prompt = await hib._build_everos_bootstrap_prompt("http://everos:8003", identity)

    assert prompt is None


def test_session_files_with_host_workspace_are_not_inlined_over_grpc():
    files = [SimpleNamespace(size_bytes=10)]

    assert hib._should_inline_session_file_mounts(files, workspace_path="/tmp/workspace") is False


def test_large_session_files_are_not_inlined_over_grpc():
    files = [
        SimpleNamespace(size_bytes=20 * 1024 * 1024),
        SimpleNamespace(size_bytes=20 * 1024 * 1024),
    ]

    assert hib._should_inline_session_file_mounts(files, workspace_path=None) is False


def test_small_session_files_without_host_workspace_can_be_inlined_over_grpc():
    files = [SimpleNamespace(size_bytes=1024)]

    assert hib._should_inline_session_file_mounts(files, workspace_path=None) is True


def test_claude_secret_model_is_left_to_container_environment():
    model = hib._resolve_harness_model(
        agent_model=None,
        engine_kind="claude",
        secrets={"ANTHROPIC_MODEL": "Claude-Opus-4.6"},
    )

    assert model is None


def test_codex_secret_model_is_passed_to_cli():
    model = hib._resolve_harness_model(
        agent_model=None,
        engine_kind="codex",
        secrets={"OPENAI_MODEL": "gpt-5"},
    )

    assert model == "gpt-5"


def test_explicit_agent_model_is_passed_to_cli():
    model = hib._resolve_harness_model(
        agent_model={"id": "Claude-Opus-4.6"},
        engine_kind="claude",
        secrets={"ANTHROPIC_MODEL": "Claude-Opus-4.6"},
    )

    assert model == "Claude-Opus-4.6"


async def test_host_mount_injects_archive_as_resource_without_auto_extracting(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_data = _zip_bytes()
    strategy = HostMountStrategy()
    ctx = FileInjectionContext(
        session_id=uuid.uuid4(),
        external_id="sandbox",
        workspace_path=str(workspace),
        provider=None,
        storage=_MemoryStorage(archive_data),
    )

    count = await strategy.inject(
        ctx,
        [
            SessionFileRecord(
                mount_path="/workspace/upload.zip",
                storage_key="files/upload.zip",
                filename="upload.zip",
                size_bytes=len(archive_data),
            )
        ],
    )

    assert count == 1
    assert (workspace / "upload.zip").read_bytes() == archive_data
    assert not (workspace / "upload").exists()
