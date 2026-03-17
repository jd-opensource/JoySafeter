"""
Tests for SandboxManagerService
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import configure_mappers

# Import models to ensure mappers are registered
from app.services.sandbox_manager import SandboxManagerService

# Ensure mappers are configured
configure_mappers()


@pytest.mark.asyncio
async def test_create_sandbox_record():
    # Setup mock db
    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    mock_db_session.refresh = AsyncMock()

    # Mock execute result for get_user_sandbox_record (returning None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    service = SandboxManagerService(mock_db_session)
    user_id = "test_user_1"

    # Run
    # We mock UserSandbox constructor to avoid mapper issues if they persist
    # But usually importing AuthUser should fix it.

    sandbox = await service.create_sandbox_record(user_id)

    # Verify
    assert sandbox.user_id == user_id
    assert sandbox.status == "pending"
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_sandbox_running_new():
    # Setup mocks
    mock_db_session = AsyncMock()
    mock_result = MagicMock()
    # Return a mock record
    mock_record = MagicMock()
    mock_record.id = "sandbox-123"
    mock_record.image = "python:3.12-slim"
    mock_record.idle_timeout = 3600
    mock_record.status = "pending"
    mock_result.scalar_one_or_none.return_value = mock_record
    mock_db_session.execute.return_value = mock_result

    with (
        patch("app.services.sandbox_manager._sandbox_pool") as mock_pool,
        patch("app.services.sandbox_manager.PydanticSandboxAdapter") as mock_adapter_cls,
        patch("os.makedirs") as mock_makedirs,
    ):
        # Configure mocks
        mock_pool.get = AsyncMock(return_value=None)
        mock_pool.put = AsyncMock()

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.is_started.return_value = True
        mock_adapter_cls.return_value = mock_adapter_instance

        service = SandboxManagerService(mock_db_session)
        user_id = "user-123"

        # Run
        adapter = await service.ensure_sandbox_running(user_id)

        # Validations
        assert adapter is not None
        mock_adapter_cls.assert_called_once()
        mock_pool.put.assert_called_once()

        # Verify volume creation
        expected_dir = f"/tmp/sandboxes/{user_id}"
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

        # Verify adapter called with volumes and auto_remove=False for user sandbox
        call_args = mock_adapter_cls.call_args
        assert call_args.kwargs["volumes"] == {expected_dir: "/workspace"}
        assert call_args.kwargs.get("auto_remove") is False

        # DB updates should happen
        assert mock_db_session.execute.call_count >= 1


@pytest.mark.asyncio
async def test_stop_sandbox():
    # Setup mocks
    mock_db_session = AsyncMock()
    mock_result = MagicMock()
    # Configure rowcount for the update result
    mock_result.rowcount = 1
    mock_db_session.execute.return_value = mock_result
    mock_db_session.commit = AsyncMock()

    with patch("app.services.sandbox_manager._sandbox_pool") as mock_pool:
        mock_pool.stop = AsyncMock()

        service = SandboxManagerService(mock_db_session)
        sandbox_id = str(uuid.uuid4())

        # Run
        success = await service.stop_sandbox(sandbox_id)

        # Validations: stop_sandbox only stops container, does not remove from pool
        assert success is True
        mock_pool.stop.assert_called_once_with(sandbox_id)
        mock_db_session.execute.assert_called()
        mock_db_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_cleanup_idle_sandboxes():
    # Setup mocks
    mock_db_session = AsyncMock()
    mock_db_session.execute = AsyncMock()
    mock_db_session.commit = AsyncMock()

    with patch("app.services.sandbox_manager._sandbox_pool") as mock_pool:
        # Mock cleanup returning list of IDs
        evicted_ids = ["sandbox-1", "sandbox-2"]
        mock_pool.cleanup_idle = AsyncMock(return_value=evicted_ids)

        service = SandboxManagerService(mock_db_session)

        # Run
        count = await service.cleanup_idle_sandboxes()

        # Verify
        assert count == 2
        mock_pool.cleanup_idle.assert_called_once()
        # Verify DB update called
        mock_db_session.execute.assert_called_once()
        mock_db_session.commit.assert_awaited_once()
