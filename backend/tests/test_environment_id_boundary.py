import uuid

import pytest
from pydantic import ValidationError

from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_domain.schemas.joysafeter_agent import JoySafeterCreateAgentRequest
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    UpdateEnvironmentRequest,
)
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_domain.schemas.joysafeter_trigger import TriggerCreateRequest
from app.joysafeter_shared.ids import AgentId, EntityId, EnvironmentId, ProjectId

pytestmark = pytest.mark.no_db


def test_environment_request_names_accept_unambiguous_names() -> None:
    assert CreateEnvironmentRequest(name="development").name == "development"
    assert UpdateEnvironmentRequest(name="staging-2").name == "staging-2"


@pytest.mark.parametrize("request_type", [CreateEnvironmentRequest, UpdateEnvironmentRequest])
def test_environment_request_names_reject_uuid_shapes_and_registered_prefixes(request_type: type) -> None:
    entity_uuid = uuid.uuid4()
    registered_prefixes = [id_type.prefix for id_type in EntityId.__subclasses__()]

    for invalid_name in [str(entity_uuid), str(entity_uuid).upper()]:
        with pytest.raises(ValidationError):
            request_type(name=invalid_name)

    for prefix in registered_prefixes:
        with pytest.raises(ValidationError):
            request_type(name=f"{prefix}reserved-name")


@pytest.mark.parametrize(
    "invalid_id",
    [
        str(uuid.uuid4()),
        str(AgentId.new()),
        "development",
        "env_not-a-uuid",
    ],
)
def test_public_environment_id_fields_reject_names_bare_uuids_and_wrong_prefixes(
    invalid_id: str,
) -> None:
    requests = (
        lambda: JoySafeterCreateAgentRequest(name="agent", engine_kind="claude", environment_id=invalid_id),
        lambda: JoySafeterCreateTaskRequest(agent_id=AgentId.new(), prompt="run", environment_id=invalid_id),
        lambda: CreateSessionRequest(agent_id=AgentId.new(), environment_id=invalid_id),
        lambda: TriggerCreateRequest(
            name="trigger",
            type="manual",
            agent_id=AgentId.new(),
            prompt_template="run",
            environment_id=invalid_id,
        ),
    )
    for build_request in requests:
        with pytest.raises(ValidationError):
            build_request()


def test_public_environment_id_fields_accept_canonical_ids() -> None:
    environment_id = EnvironmentId.new()

    assert (
        JoySafeterCreateAgentRequest(name="agent", engine_kind="claude", environment_id=environment_id).environment_id
        == environment_id
    )
    assert (
        JoySafeterCreateTaskRequest(agent_id=AgentId.new(), prompt="run", environment_id=environment_id).environment_id
        == environment_id
    )
    assert CreateSessionRequest(agent_id=AgentId.new(), environment_id=environment_id).environment_id == environment_id
    assert (
        TriggerCreateRequest(
            name="trigger",
            type="manual",
            agent_id=AgentId.new(),
            prompt_template="run",
            environment_id=environment_id,
        ).environment_id
        == environment_id
    )


def test_snapshot_overlay_accepts_only_frozen_keys_and_deep_copies_inputs() -> None:
    overlay = {
        "type": "cloud",
        "packages": {"apt": ["git"]},
        "networking": {"mode": "limited"},
        "env_vars": {"MODE": "test"},
    }
    mounts = ({"name": "data", "volume_ref": "volume", "mount_path": "/workspace/data"},)
    command = CreateCredentialAwareSession(
        project_id=ProjectId.new(),
        agent_id=AgentId.new(),
        environment_config_overlay=overlay,
        environment_mount_resources=mounts,
    )

    overlay["packages"]["apt"].append("curl")
    mounts[0]["name"] = "mutated"

    assert command.environment_config_overlay["packages"] == {"apt": ["git"]}
    assert command.environment_mount_resources[0]["name"] == "data"


@pytest.mark.parametrize(
    "key",
    [
        "environment_credential_ids",
        "secret_refs",
        "service_credential_id",
        "egress_services",
        "mount_resources",
        "future_field",
    ],
)
def test_snapshot_overlay_rejects_credential_aliases_mounts_and_unknown_keys(key: str) -> None:
    with pytest.raises(ValueError, match="environment_config_overlay"):
        CreateCredentialAwareSession(
            project_id=ProjectId.new(),
            agent_id=AgentId.new(),
            environment_config_overlay={key: []},
        )
