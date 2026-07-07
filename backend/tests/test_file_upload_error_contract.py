import io
import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import UploadFile

from app.joysafeter_api.api.v1.files import delete_file, download_file, get_file, upload_file
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id="test-project",
        role=JoySafeterRole.DEVELOPER,
    )


def _upload(filename: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.mark.asyncio
async def test_upload_file_empty_file_returns_structured_validation_error(db_session):
    with pytest.raises(AppError) as exc_info:
        await upload_file(_auth_ctx(), db_session, _upload("empty.txt", b""))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "FILE_EMPTY",
        "message": "File cannot be empty",
        "data": {"filename": "empty.txt"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_upload_file_unsupported_type_returns_structured_validation_error(db_session):
    with pytest.raises(AppError) as exc_info:
        await upload_file(_auth_ctx(), db_session, _upload("payload.exe", b"binary"))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "FILE_TYPE_UNSUPPORTED",
        "message": "File type .exe is not supported",
        "data": {"filename": "payload.exe", "extension": ".exe"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_upload_file_storage_failure_returns_structured_retryable_error(db_session, monkeypatch):
    class FailingFileService:
        async def upload(self, **kwargs):
            raise RuntimeError("storage offline")

    monkeypatch.setattr("app.joysafeter_api.api.v1.files._get_service", lambda: FailingFileService())

    with pytest.raises(AppError) as exc_info:
        await upload_file(_auth_ctx(), db_session, _upload("report.txt", b"body"))

    assert await handled_app_error_payload(exc_info.value, status_code=500) == {
        "code": "FILE_UPLOAD_FAILED",
        "message": "File upload failed",
        "data": {"filename": "report.txt"},
        "source": "internal",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_get_file_invalid_id_returns_structured_validation_error(db_session):
    with pytest.raises(AppError) as exc_info:
        await get_file("not-a-file-id", _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "FILE_ID_INVALID",
        "message": "Invalid file_id",
        "data": {"file_id": "not-a-file-id"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_get_file_missing_file_returns_structured_not_found_error(db_session, monkeypatch):
    class MissingFileService:
        async def get_metadata(self, *args, **kwargs):
            return None

    missing_file_id = f"file_{uuid.uuid4()}"
    monkeypatch.setattr("app.joysafeter_api.api.v1.files._get_service", lambda: MissingFileService())

    with pytest.raises(AppError) as exc_info:
        await get_file(missing_file_id, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "FILE_NOT_FOUND",
        "message": "File not found",
        "data": {"file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_download_file_missing_presign_record_returns_structured_not_found_error(db_session, monkeypatch):
    class MissingFileService:
        async def get_presign_url(self, *args, **kwargs):
            raise FileNotFoundError("File not found")

    missing_file_id = f"file_{uuid.uuid4()}"
    monkeypatch.setattr("app.joysafeter_api.api.v1.files._get_service", lambda: MissingFileService())

    with pytest.raises(AppError) as exc_info:
        await download_file(missing_file_id, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "FILE_NOT_FOUND",
        "message": "File not found",
        "data": {"file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_delete_file_missing_file_returns_structured_not_found_error(db_session, monkeypatch):
    class MissingFileService:
        async def delete(self, *args, **kwargs):
            return False

    missing_file_id = f"file_{uuid.uuid4()}"
    monkeypatch.setattr("app.joysafeter_api.api.v1.files._get_service", lambda: MissingFileService())

    with pytest.raises(AppError) as exc_info:
        await delete_file(missing_file_id, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "FILE_NOT_FOUND",
        "message": "File not found",
        "data": {"file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
