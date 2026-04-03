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
from app.core.model.utils import decrypt_credentials, encrypt_credentials
from app.repositories.model_credential import ModelCredentialRepository
from app.repositories.model_provider import ModelProviderRepository

from .base import BaseService


class ModelCredentialService(BaseService):
    """模型凭据服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelCredentialRepository(db)
        self.provider_repo = ModelProviderRepository(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
            from app.repositories.model_instance import ModelInstanceRepository

            instance_repo = ModelInstanceRepository(self.db)
            instances = await instance_repo.list_by_provider(provider_id=provider_id)
            model_name = instances[0].model_name if instances else None
        return await validate_provider_credentials(implementation_name, credentials, model_name=model_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upsert_credential(
        self,
        user_id: str,
        provider_name: str,
        credentials: Dict[str, Any],
        validate: bool = True,
    ) -> Dict[str, Any]:
        """
        创建或更新内置 provider 的凭据。
        一个 provider 一条凭证，按 provider_id upsert。
        """
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            raise NotFoundException(f"Provider not found: {provider_name}")

        is_valid = False
        validation_error = None
        if validate:
            is_valid, validation_error = await self._validate_for_provider(provider, credentials, provider.id)

        encrypted = encrypt_credentials(credentials)
        credential = await self._upsert_credential(
            provider_id=provider.id,
            encrypted=encrypted,
            is_valid=is_valid,
            validation_error=validation_error,
            user_id=user_id,
        )

        # 确保模型实例存在
        from app.services.model_provider_service import ModelProviderService

        provider_service = ModelProviderService(self.db)
        await provider_service._ensure_model_instances_for_provider(provider)

        await self.commit()

        return {
            "id": str(credential.id),
            "provider_name": provider.name,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }

    async def validate_credential(self, credential_id: uuid.UUID) -> Dict[str, Any]:
        """重新验证已有凭证。按 ID 查找，解密，调 API 验证。"""
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("Credential not found")
        if not credential.provider:
            raise NotFoundException("Credential's associated provider not found")

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
            raise NotFoundException("Credential not found")

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
        """删除内置 provider 的凭据记录。自定义 provider 的凭据不允许单独删除。"""
        from app.common.exceptions import BadRequestException

        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("Credential not found")

        if (
            credential.provider
            and credential.provider.provider_type == "custom"
            and not credential.provider.is_template
        ):
            raise BadRequestException(
                f"Cannot delete credentials for custom provider separately. Use DELETE /model-providers/{credential.provider.name} to remove the entire provider."
            )

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
