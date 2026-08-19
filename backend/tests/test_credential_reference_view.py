import pytest

from app.joysafeter_application.credentials.reference_view import (
    ReferenceItem,
    build_reference_view,
    mappable_targets,
    resolve_reference_view,
)
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)

ARCHIVE = DependencyDisposition.BLOCK_RESOURCE_ARCHIVE
DELETE = DependencyDisposition.BLOCK_RESOURCE_DELETE
BLOCK_RESOURCE = frozenset({ARCHIVE, DELETE})
PROJECT = "project-a"
CRED = "cred-1"


def _dep(surface_id: str, source_id: str, dispositions=BLOCK_RESOURCE) -> CredentialDependency:
    return CredentialDependency(
        surface_id=surface_id,
        project_id=PROJECT,
        source_id=source_id,
        credential_id=CRED,
        group_id=None,
        dispositions=dispositions,
    )


def test_maps_four_live_surfaces_with_names():
    deps = [
        _dep("live_agent_model_binding", "agent-1"),
        _dep("trigger_webhook_auth_binding", "trigger-1"),
        _dep("live_environment_direct_injection", "env-1"),
        _dep("active_session_model_environment_snapshot", "session-1"),
    ]
    targets = mappable_targets(deps, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert set(targets) == {
        ("agent", "agent-1"),
        ("trigger", "trigger-1"),
        ("environment", "env-1"),
        ("session", "session-1"),
    }
    names = {
        ("agent", "agent-1"): "客服机器人",
        ("trigger", "trigger-1"): "GitHub Hook",
        ("environment", "env-1"): "prod",
        ("session", "session-1"): None,
    }
    view = build_reference_view(deps, names, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert ReferenceItem("agent_model_binding", "agent", "agent-1", "客服机器人") in view.references
    assert ReferenceItem("active_session_snapshot", "session", "session-1", None) in view.references
    assert view.other_count == 0
    assert view.can_archive is False
    assert view.can_delete is False


def test_two_environment_surfaces_dedupe_same_id():
    deps = [
        _dep("live_environment_direct_injection", "env-1"),
        _dep("live_environment_http_egress_binding", "env-1"),
    ]
    view = build_reference_view(
        deps, {("environment", "env-1"): "prod"}, archive_disp=ARCHIVE, delete_disp=DELETE
    )
    env_items = [item for item in view.references if item.resource_type == "environment"]
    assert env_items == [ReferenceItem("environment_injection", "environment", "env-1", "prod")]


def test_unmapped_blocking_surface_folds_into_other_count():
    deps = [
        _dep("live_agent_model_binding", "agent-1"),
        _dep("legacy_v0_v1_environment_snapshot", "env-legacy"),
    ]
    view = build_reference_view(
        deps, {("agent", "agent-1"): "A"}, archive_disp=ARCHIVE, delete_disp=DELETE
    )
    assert [item.resource_type for item in view.references] == ["agent"]
    assert view.other_count == 1
    assert view.can_archive is False


def test_non_blocking_dep_excluded():
    deps = [
        _dep(
            "agent_version_executable_snapshot",
            "version-1",
            dispositions=frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
        ),
    ]
    view = build_reference_view(deps, {}, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert view.references == []
    assert view.other_count == 0
    assert view.can_archive is True
    assert view.can_delete is True


@pytest.mark.asyncio
async def test_resolve_reference_view_uses_name_lookup():
    deps = [_dep("live_agent_model_binding", "agent-1")]

    async def fake_lookup(resource_type, ids):
        assert resource_type == "agent"
        return {"agent-1": "客服机器人"}

    view = await resolve_reference_view(deps, fake_lookup, archive_disp=ARCHIVE, delete_disp=DELETE)
    assert view.references == [ReferenceItem("agent_model_binding", "agent", "agent-1", "客服机器人")]
