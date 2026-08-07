import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.joysafeter_api.api.v1.sessions import _canonical_environment_ref
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    UpdateEnvironmentRequest,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import AgentId, EntityId, EnvironmentId

pytestmark = pytest.mark.no_db


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _NameLookupDb:
    def __init__(self, result: object) -> None:
        self.result = result
        self.execute_calls = 0

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_calls += 1
        return _ScalarResult(self.result)


class _NoLookupDb:
    async def execute(self, _statement: object) -> None:
        raise AssertionError("reserved environment references must be rejected before name lookup")


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


@pytest.mark.asyncio
async def test_environment_service_resolves_names_and_canonical_environment_ids() -> None:
    environment = object()
    name_db = _NameLookupDb(environment)
    service = EnvironmentService(name_db)  # type: ignore[arg-type]

    assert await service.get_environment_by_ref(" development ") is environment
    assert name_db.execute_calls == 1

    environment_id = EnvironmentId.new()
    get_environment = AsyncMock(return_value=environment)
    service = EnvironmentService(_NoLookupDb())  # type: ignore[arg-type]
    service.get_environment = get_environment

    assert await service.get_environment_by_ref(f" {environment_id} ") is environment
    get_environment.assert_awaited_once_with(environment_id, project_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_ref",
    [
        str(uuid.uuid4()),
        str(uuid.uuid4()).upper(),
        str(AgentId.new()),
        "env_not-a-uuid",
    ],
)
async def test_environment_service_rejects_ambiguous_or_invalid_entity_references_before_name_lookup(
    invalid_ref: str,
) -> None:
    service = EnvironmentService(_NoLookupDb())  # type: ignore[arg-type]

    assert await service.get_environment_by_ref(invalid_ref) is None


def test_session_environment_api_ingress_classifies_names_and_entity_references() -> None:
    environment_id = EnvironmentId.new()

    assert _canonical_environment_ref(" development ") == "development"
    assert _canonical_environment_ref(f" {environment_id} ") == str(environment_id)

    for invalid_ref in [
        str(environment_id.uuid),
        str(AgentId.new()),
        "env_not-a-uuid",
    ]:
        with pytest.raises(AppError) as exc_info:
            _canonical_environment_ref(invalid_ref)
        assert exc_info.value.code == "ENVIRONMENT_ID_INVALID"
