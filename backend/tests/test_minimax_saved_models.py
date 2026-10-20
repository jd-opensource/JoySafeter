"""Check the real model-list service with its persistence collaborators mocked."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_minimax_provider import _load_providers


@pytest.fixture
def service_module(monkeypatch):
    base, _ = _load_providers()

    def module(name, **attributes):
        stub = types.ModuleType(name)
        stub.__path__ = []
        stub.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, stub)

    for name in ["app", "app.common", "app.core", "app.models", "app.repositories", "app.services"]:
        module(name)
    error = type(
        "ModelConfigError",
        (Exception,),
        {
            name: name
            for name in ["MODEL_NOT_FOUND", "MODEL_NO_CREDENTIALS", "PROVIDER_NOT_FOUND", "MODEL_NAME_REQUIRED"]
        },
    )
    module("sqlalchemy.ext.asyncio", AsyncSession=object)
    module("app.common.exceptions", BadRequestException=Exception, ModelConfigError=error, NotFoundException=Exception)
    module("app.core.model", ModelType=base.ModelType, create_model_instance=None, get_factory=None)
    module("app.core.model.utils", decrypt_credentials=lambda value: value)
    module("loguru", logger=types.SimpleNamespace(debug=lambda *a, **k: None, warning=lambda *a, **k: None))
    module("app.core.model.factory", get_factory=None)
    module("app.models.enums", ModelUsageSource=object)
    for path, attribute in [
        ("repositories.model_credential", "ModelCredentialRepository"),
        ("repositories.model_instance", "ModelInstanceRepository"),
        ("repositories.model_provider", "ModelProviderRepository"),
        ("services.model_credential_service", "ModelCredentialService"),
        ("services.model_usage_service", "ModelUsageService"),
        ("services.base", "BaseService"),
    ]:
        module("app." + path, **{attribute: object})
    path = Path(__file__).resolve().parents[1] / "app/services/model_service.py"
    spec = importlib.util.spec_from_file_location("app.services.model_service", path)
    loaded = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, loaded)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize("model_name", ["MiniMax-M2.7", "saved-custom-id"])
@pytest.mark.parametrize("credentials_valid", [True, False])
async def test_saved_minimax_models_remain_available(service_module, model_name, credentials_valid):
    base, module = _load_providers()
    provider = module.MiniMaxProvider()
    service = service_module.ModelService.__new__(service_module.ModelService)
    persisted_provider = types.SimpleNamespace(
        name="minimax", display_name="MiniMax", template_name=None, supported_model_types=["chat"]
    )
    instance = types.SimpleNamespace(
        id="saved", provider_id="provider", provider=persisted_provider, model_name=model_name, model_parameters={}
    )
    service.repo = types.SimpleNamespace(list_all=AsyncMock(return_value=[instance]))
    service.factory = types.SimpleNamespace(get_provider=lambda name: provider)
    service._build_provider_credentials_context = AsyncMock(
        return_value={
            "provider": {
                "decrypted": {},
                "is_valid": credentials_valid,
                "error": None if credentials_valid else "invalid_credentials",
            }
        }
    )
    models = await service.get_available_models(base.ModelType.CHAT)
    assert models[0]["name"] == model_name
    assert models[0]["is_available"] is credentials_valid
    if credentials_valid:
        assert "unavailable_reason" not in models[0]
    else:
        assert models[0]["unavailable_reason"] == "invalid_credentials"
    # The special case must not change catalog validation for unrelated providers.
    provider.provider_name = "unrelated"
    models = await service.get_available_models(base.ModelType.CHAT)
    assert models[0]["is_available"] is False
    if credentials_valid:
        assert models[0]["unavailable_reason"] == "model_not_found"


async def test_catalog_sync_preserves_saved_instances(service_module, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "app/services/model_provider_service.py"
    spec = importlib.util.spec_from_file_location("app.services.model_provider_service", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    _, providers = _load_providers()
    provider = providers.MiniMaxProvider()
    service = module.ModelProviderService.__new__(module.ModelProviderService)
    service.db = None
    service.factory = types.SimpleNamespace(get_provider=lambda name: provider)
    service.instance_repo = types.SimpleNamespace(
        get_best_instance=AsyncMock(return_value=None),
        create=AsyncMock(),
        delete=AsyncMock(),
        list_by_provider=AsyncMock(
            return_value=[
                types.SimpleNamespace(id="legacy", user_id=None, model_name="MiniMax-M2.7"),
                types.SimpleNamespace(id="custom", user_id=None, model_name="saved-custom-id"),
            ]
        ),
    )
    credential_repo = types.SimpleNamespace(
        get_by_provider=AsyncMock(
            return_value=types.SimpleNamespace(
                is_valid=True,
                credentials={"api_key": "offline"},
            )
        )
    )
    monkeypatch.setattr(module, "ModelCredentialRepository", lambda db: credential_repo)
    persisted = types.SimpleNamespace(id="provider", name="minimax", template_name=None)
    assert await service._ensure_model_instances_for_provider(persisted) == 2
    assert [call.args[0]["model_name"] for call in service.instance_repo.create.await_args_list] == [
        "MiniMax-M3.1-Flash",
        "MiniMax-M3",
    ]
    service.instance_repo.delete.assert_not_awaited()
    provider.provider_name = "unrelated"
    await service._ensure_model_instances_for_provider(persisted)
    assert service.instance_repo.delete.await_count == 2
