import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.joysafeter_api.api.v1 import storage_volumes as storage_api
from app.joysafeter_domain.schemas.joysafeter_storage_mount import StorageMountAuditResponse
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    EnvironmentId,
    OrganizationId,
    ProjectId,
    SessionId,
    StorageMountAuditId,
    StorageVolumeId,
    UserId,
)

pytestmark = pytest.mark.no_db


class _StorageServiceStub:
    def __init__(self) -> None:
        now = datetime(2026, 8, 7, tzinfo=UTC)
        self.user_id = UserId.new()
        self.org_id = OrganizationId.new()
        self.project_id = ProjectId.new()
        self.volume = SimpleNamespace(
            id=StorageVolumeId.new(),
            volume_ref="datasets",
            backend_type="generic",
            display_name="Datasets",
            description="",
            max_access="read_only",
            allowed_prefixes=[],
            docker={"host_path": "/tmp/datasets"},
            k8s={},
            quota_bytes=None,
            used_bytes=0,
            enabled=True,
            metadata_={},
            created_at=now,
            updated_at=now,
        )
        self.audit = SimpleNamespace(
            id=StorageMountAuditId.new(),
            volume_id=self.volume.id,
            project_id=self.project_id,
            session_id=SessionId.new(),
            environment_id=EnvironmentId.new(),
            user_id=self.user_id,
            action="mount",
            volume_ref=self.volume.volume_ref,
            mount_path="/workspace/data",
            sub_path="",
            access="read_only",
            bytes_used=None,
            result="success",
            detail={},
            created_at=now,
        )
        self.audit_filters: tuple[StorageVolumeId | None, StorageMountAuditId | None] | None = None

    async def get_volume(self, volume_id: StorageVolumeId) -> object | None:
        return self.volume if volume_id == self.volume.id else None

    async def list_organization_grants(self, _volume_id: StorageVolumeId) -> list[object]:
        return []

    async def list_grants(self, _volume_id: StorageVolumeId) -> list[object]:
        return []

    async def list_audit_page(
        self,
        *,
        volume_id: StorageVolumeId | None = None,
        after_id: StorageMountAuditId | None = None,
        **_filters: object,
    ) -> tuple[list[object], bool]:
        self.audit_filters = (volume_id, after_id)
        return [self.audit], False


def _client(monkeypatch: pytest.MonkeyPatch, service: _StorageServiceStub) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(storage_api.router, prefix="/storage-volumes")
    app.dependency_overrides[storage_api.get_db] = lambda: object()
    app.dependency_overrides[storage_api.require_joysafeter_user_admin] = lambda: JoySafeterAuthContext(
        user_id=service.user_id,
        org_id=service.org_id,
        project_id=service.project_id,
        role=JoySafeterRole.ADMIN,
        project_role="admin",
        is_super_user=True,
    )
    monkeypatch.setattr(storage_api, "StorageMountService", lambda _db: service)
    return TestClient(app)


def _audit_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(StorageMountAuditId.new()),
        "volume_id": str(StorageVolumeId.new()),
        "project_id": str(ProjectId.new()),
        "session_id": str(SessionId.new()),
        "environment_id": str(EnvironmentId.new()),
        "user_id": str(UserId.new()),
        "action": "mount",
        "result": "success",
        "created_at": "2026-08-07T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_storage_response_model_serializes_canonical_ids_and_rejects_noncanonical_strings() -> None:
    response = StorageMountAuditResponse.model_validate(_audit_payload())
    serialized = response.model_dump(mode="json")

    assert serialized["id"].startswith("staudit_")
    assert serialized["volume_id"].startswith("vol_")
    assert serialized["project_id"].startswith("proj_")
    assert serialized["session_id"].startswith("sess_")
    assert serialized["environment_id"].startswith("env_")
    assert serialized["user_id"].startswith("user_")

    for field, invalid_value in [
        ("id", str(uuid.uuid4())),
        ("id", str(StorageVolumeId.new())),
        ("volume_id", str(uuid.uuid4())),
        ("volume_id", str(StorageMountAuditId.new())),
        ("project_id", str(uuid.uuid4())),
        ("project_id", str(UserId.new())),
        ("user_id", str(uuid.uuid4())),
        ("user_id", str(ProjectId.new())),
    ]:
        with pytest.raises(ValidationError):
            StorageMountAuditResponse.model_validate(_audit_payload(**{field: invalid_value}))


def test_storage_path_and_audit_filters_require_canonical_entity_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _StorageServiceStub()
    client = _client(monkeypatch, service)

    response = client.get(f"/storage-volumes/{service.volume.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(service.volume.id)

    response = client.get(
        "/storage-volumes/audit/logs",
        params={"volume_id": str(service.volume.id), "after_id": str(service.audit.id)},
    )
    assert response.status_code == 200
    assert service.audit_filters == (service.volume.id, service.audit.id)
    assert response.json()["data"][0]["id"] == str(service.audit.id)
    assert response.json()["first_id"] == str(service.audit.id)
    assert response.json()["last_id"] == str(service.audit.id)

    invalid_requests = [
        f"/storage-volumes/{service.volume.id.uuid}",
        f"/storage-volumes/{SessionId.new()}",
        f"/storage-volumes/audit/logs?volume_id={service.volume.id.uuid}",
        f"/storage-volumes/audit/logs?volume_id={SessionId.new()}",
        f"/storage-volumes/audit/logs?after_id={service.audit.id.uuid}",
        f"/storage-volumes/audit/logs?after_id={service.volume.id}",
    ]
    for path in invalid_requests:
        invalid_response = client.get(path)
        assert invalid_response.status_code == 400
