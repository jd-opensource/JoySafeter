"""
模型凭据服务

简化原则：一个 provider 一条凭证，按 provider_id 查找。
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.core.model import validate_provider_credentials
from app.core.model.factory import get_factory
from app.core.model.utils import decrypt_credentials, encrypt_credentials
from app.repositories.model_credential import ModelCredentialRepository
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository

from .base import BaseService


class ModelCredentialService(BaseService):
    """模型凭据服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelCredentialRepository(db)
        self.provider_repo = ModelProviderRepository(db)
        self.instance_repo = ModelInstanceRepository(db)
        self.factory = get_factory()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_first_model_name_for_provider(self, provider_id: uuid.UUID) -> Optional[str]:
        """获取 Provider 下第一个模型实例的名称，用于自定义 Provider 凭证验证。"""
        instances = await self.instance_repo.list_by_provider(provider_id=provider_id)
        return instances[0].model_name if instances else None

    async def _create_derived_provider(self, template: Any, name: str, display_name: str, template_name: str) -> Any:
        """从模板创建派生 Provider DB 记录。"""
        return await self.provider_repo.create(
            {
                "name": name,
                "display_name": display_name,
                "supported_model_types": [mt.value for mt in template.get_supported_model_types()],
                "credential_schema": template.get_credential_schema(),
                "config_schema": None,
                "is_template": False,
                "provider_type": "custom",
                "template_name": template_name,
                "is_enabled": True,
            }
        )

    async def _upsert_credential(
        self,
        provider_id: uuid.UUID,
        encrypted: str,
        is_valid: bool,
        validation_error: Optional[str],
        user_id: Optional[str] = None,
    ) -> Any:
        """一个 provider 一条凭证。存在则更新，不存在则创建。"""
        existing = await self.repo.get_by_provider(provider_id)
        now = datetime.now(timezone.utc) if is_valid else None

        if existing:
            existing.credentials = encrypted
            existing.is_valid = is_valid
            existing.last_validated_at = now
            existing.validation_error = validation_error
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        return await self.repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": provider_id,
                "credentials": encrypted,
                "is_valid": is_valid,
                "last_validated_at": now,
                "validation_error": validation_error,
            }
        )

    async def _validate_for_provider(
        self, provider: Any, credentials: Dict[str, Any], provider_id: uuid.UUID
    ) -> tuple[bool, Optional[str]]:
        """验证凭证。自定义 Provider 用实际模型名验证。"""
        implementation_name = provider.template_name or provider.name
        model_name = None
        if provider.provider_type == "custom":
            model_name = await self._get_first_model_name_for_provider(provider_id=provider_id)
        return await validate_provider_credentials(implementation_name, credentials, model_name=model_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_or_update_credential(
        self,
        user_id: str,
        provider_name: str,
        credentials: Dict[str, Any],
        validate: bool = True,
        provider_display_name: Optional[str] = None,
        model_name: Optional[str] = None,
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        创建或更新凭据。
        - provider_name=custom + model_name → 一步添加自定义模型
        - 其他 → 按 provider_id upsert 凭证
        """
        import time

        # 一步添加自定义模型
        if provider_name == "custom" and model_name and model_name.strip():
            return await self._add_one_custom_model(
                user_id=user_id,
                credentials=credentials,
                validate=validate,
                model_name=model_name.strip(),
                model_parameters=model_parameters,
                display_name=provider_display_name,
            )

        # 查找 provider
        provider = await self.provider_repo.get_by_name(provider_name)
        template = self.factory.get_provider(provider_name)

        if template and provider_display_name:
            # 创建命名派生 provider
            new_name = f"{provider_name}-{int(time.time())}"
            provider = await self._create_derived_provider(
                template=template, name=new_name, display_name=provider_display_name, template_name=provider_name
            )
        elif not provider:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        # 验证
        is_valid = False
        validation_error = None
        if validate:
            is_valid, validation_error = await self._validate_for_provider(provider, credentials, provider.id)

        # Upsert 凭证
        encrypted = encrypt_credentials(credentials)
        credential = await self._upsert_credential(
            provider_id=provider.id,
            encrypted=encrypted,
            is_valid=is_valid,
            validation_error=validation_error,
            user_id=user_id,
        )

        # 确保模型实例存在
        await self._ensure_model_instances(provider)
        await self.commit()
        await self._update_default_model_cache_if_needed(provider.name)

        return {
            "id": str(credential.id),
            "provider_name": provider.name,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }

    async def _add_one_custom_model(
        self,
        user_id: str,
        credentials: Dict[str, Any],
        validate: bool,
        model_name: str,
        model_parameters: Optional[Dict[str, Any]],
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """一步添加自定义模型：创建 provider + 凭据 + model_instance。"""
        import time

        template = self.factory.get_provider("custom")
        if not template:
            raise NotFoundException("供应商不存在: custom")

        # 验证
        is_valid = False
        validation_error = None
        if validate:
            is_valid, validation_error = await validate_provider_credentials(
                "custom", credentials, model_name=model_name
            )

        # 创建 provider
        new_name = f"custom-{int(time.time())}"
        display = (display_name or model_name).strip() or new_name
        db_provider = await self._create_derived_provider(
            template=template, name=new_name, display_name=display, template_name="custom"
        )

        # 创建凭证
        encrypted = encrypt_credentials(credentials)
        credential = await self._upsert_credential(
            provider_id=db_provider.id,
            encrypted=encrypted,
            is_valid=is_valid,
            validation_error=validation_error,
            user_id=user_id,
        )

        # 创建模型实例
        await self.instance_repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": db_provider.id,
                "model_name": model_name,
                "model_parameters": model_parameters or {},
                "is_default": False,
            }
        )

        await self.commit()

        return {
            "id": str(credential.id),
            "provider_name": new_name,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }

    async def validate_credential(self, credential_id: uuid.UUID) -> Dict[str, Any]:
        """重新验证已有凭证。按 ID 查找，解密，调 API 验证。"""
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")
        if not credential.provider:
            raise NotFoundException("凭据关联的供应商不存在")

        decrypted = decrypt_credentials(credential.credentials)
        is_valid, error = await self._validate_for_provider(credential.provider, decrypted, credential.provider_id)

        credential.is_valid = is_valid
        credential.last_validated_at = datetime.now(timezone.utc) if is_valid else None
        credential.validation_error = error or ""
        await self.commit()

        return {
            "is_valid": is_valid,
            "error": error or "",
            "last_validated_at": credential.last_validated_at,
        }

    async def get_credential(self, credential_id: uuid.UUID, include_credentials: bool = False) -> Dict[str, Any]:
        """获取凭据详情。"""
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")

        pname = credential.provider.name if credential.provider else ""
        pdisplay = credential.provider.display_name if credential.provider else ""
        result: Dict[str, Any] = {
            "id": str(credential.id),
            "provider_name": pname,
            "provider_display_name": pdisplay,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }
        if include_credentials:
            result["credentials"] = decrypt_credentials(credential.credentials)
        return result

    async def list_credentials(self) -> List[Dict[str, Any]]:
        """获取凭据列表。"""
        credentials = await self.repo.list_all()
        return [
            {
                "id": str(c.id),
                "provider_name": c.provider.name if c.provider else "",
                "provider_display_name": c.provider.display_name if c.provider else "",
                "is_valid": c.is_valid,
                "last_validated_at": c.last_validated_at,
                "validation_error": c.validation_error,
            }
            for c in credentials
        ]

    async def delete_credential(self, credential_id: uuid.UUID) -> None:
        """删除凭据。自定义供应商的凭据会连同供应商一起删除。"""
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")

        if (
            credential.provider
            and credential.provider.provider_type == "custom"
            and not credential.provider.is_template
        ):
            # 自定义供应商：删 provider 级联删凭证+实例
            await self.provider_repo.delete(credential.provider.id)
        else:
            await self.repo.delete(credential_id)

        await self.commit()

    async def get_decrypted_credentials(
        self, provider_name: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """按 provider_name 获取解密凭证。"""
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            return None

        credential = await self.repo.get_by_provider(provider.id)
        if credential and credential.is_valid:
            return decrypt_credentials(credential.credentials)
        return None

    async def get_current_credentials(
        self,
        provider_name: str,
        model_type: Any,
        model_name: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取当前可用凭据（供 ModelService 调用）。"""
        return await self.get_decrypted_credentials(provider_name, user_id)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _update_default_model_cache(
        self,
        provider_name: str,
        model_name: str,
        model_type: str = "chat",
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """更新默认模型缓存。"""
        try:
            from app.core.settings import set_default_model_config

            credentials = await self.get_decrypted_credentials(provider_name)
            if credentials:
                params = model_parameters or {}
                set_default_model_config(
                    {
                        "model": model_name,
                        "api_key": credentials.get("api_key", ""),
                        "base_url": credentials.get("base_url"),
                        "timeout": params.get("timeout", 30),
                    }
                )
        except Exception as e:
            print(f"Warning: Failed to update default model cache: {e}")

    async def _update_default_model_cache_if_needed(self, provider_name: str) -> None:
        """如果当前默认模型属于该 provider，则刷新缓存。"""
        try:
            repo = ModelInstanceRepository(self.db)
            default_instance = await repo.get_default()
            if not default_instance or not default_instance.provider:
                return
            if default_instance.provider.name == provider_name:
                await self._update_default_model_cache(
                    provider_name=provider_name,
                    model_name=default_instance.model_name,
                    model_type="chat",
                    model_parameters=default_instance.model_parameters,
                )
        except Exception as e:
            print(f"Warning: Failed to update default model cache after credential change: {e}")

    async def _ensure_model_instances(self, provider: Any) -> None:
        """确保该 provider 的所有模型在 model_instance 表中存在。"""
        from app.services.model_provider_service import ModelProviderService

        await ModelProviderService(self.db)._ensure_model_instances_for_provider(provider)
