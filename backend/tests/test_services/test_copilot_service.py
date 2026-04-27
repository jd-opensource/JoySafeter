from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.common.exceptions import ModelConfigError
from app.services.copilot_service import CopilotService


@pytest.mark.asyncio
async def test_resolve_model_requires_build_copilot_model_selection() -> None:
    service = CopilotService(
        user_id="user-123",
        provider_name=None,
        model_name=None,
        db=AsyncMock(),
    )

    with pytest.raises(ModelConfigError) as exc_info:
        await service._resolve_model()

    assert exc_info.value.error_code == ModelConfigError.BUILD_COPILOT_MODEL_REQUIRED
    assert "Build Copilot has no model configured" in str(exc_info.value.detail)
