from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import ModelConfigError
from app.core.copilot.exceptions import CopilotAgentError
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

    assert exc_info.value.code == ModelConfigError.BUILD_COPILOT_MODEL_REQUIRED
    assert exc_info.value.message == "Build Copilot has no model configured. Select a model and try again."


def test_copilot_agent_error_uses_canonical_app_error_shape() -> None:
    err = CopilotAgentError("Failed to create Copilot agent", original_error=RuntimeError("boom"))

    assert err.to_payload() == {
        "code": "COPILOT_AGENT_ERROR",
        "message": "Failed to create Copilot agent",
        "data": {
            "error_type": "RuntimeError",
            "error_message": "boom",
        },
    }
