"""
模型凭据服务
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

    async def create_or_update_credential(
        self,
        user_id: str,
        provider_name: str,
        credentials: Dict[str, Any],
        workspace_id: Optional[uuid.UUID] = None,
        validate: bool = True,
        provider_display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建或更新凭据

        Args:
            user_id: 用户ID
            provider_name: 供应商名称
            credentials: 凭据字典（明文）
            workspace_id: 工作空间ID（可选）
            validate: 是否验证凭据

        Returns:
            创建的凭据信息
        """
        # 验证供应商是否存在
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        # 如果提供了 provider_display_name 且是一个模板，则创建一个新的自定义供应商
        if provider_display_name and provider.is_template:
            # 生成唯一的供应商名称
            import time

            new_provider_name = f"{provider.name}-{int(time.time())}"

            # 创建新供应商
            provider = await self.provider_repo.create(
                {
                    "name": new_provider_name,
                    "display_name": provider_display_name,
                    "supported_model_types": provider.supported_model_types,
                    "credential_schema": provider.credential_schema,
                    "config_schema": provider.config_schema,
                    "is_template": False,
                    "provider_type": "custom",
                    "template_name": provider.name,
                    "is_enabled": True,
                }
            )
            provider_name = new_provider_name
            # 重新确保模型实例（新供应商需要同步模型）
            await self._ensure_model_instances(provider)

        # 验证凭据
        is_valid = False
        validation_error = None

        if validate:
            # 使用模板名称进行验证 if applicable，但 model_credential_service 已经处理了 template_name logic
            # 这里直接传递 provider_name (如果是新创建的，它有 template_name)
            is_valid, validation_error = await validate_provider_credentials(
                provider.template_name or provider.name,
                credentials,
            )

        # 加密凭据
        encrypted_credentials = encrypt_credentials(credentials)

        # 检查是否已存在
        existing = await self.repo.get_by_user_and_provider(
            user_id,
            provider.id,
            workspace_id,
        )

        if existing:
            # 更新现有凭据
            existing.credentials = encrypted_credentials
            existing.is_valid = is_valid
            existing.last_validated_at = datetime.now(timezone.utc) if is_valid else None
            existing.validation_error = validation_error
            await self.db.flush()
            await self.db.refresh(existing)
            credential = existing
        else:
            # 创建新凭据
            credential = await self.repo.create(
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "provider_id": provider.id,
                    "credentials": encrypted_credentials,
                    "is_valid": is_valid,
                    "last_validated_at": datetime.now(timezone.utc) if is_valid else None,
                    "validation_error": validation_error,
                }
            )

        # 创建凭据后，自动为该 provider 的所有模型创建全局模型实例记录（如果不存在）
        await self._ensure_model_instances(provider)

        await self.commit()

        # 检查是否需要更新默认模型缓存
        await self._update_default_model_cache_if_needed(provider_name)

        return {
            "id": str(credential.id),
            "provider_name": provider_name,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }

    async def _update_default_model_cache(
        self,
        provider_name: str,
        model_name: str,
        model_type: str = "chat",
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """根据当前凭据更新默认模型缓存，供本服务与 ModelService 复用。失败仅打日志。"""
        try:
            from app.core.settings import set_default_model_config

            credentials = await self.get_current_credentials(
                provider_name=provider_name,
                model_type=model_type,
                model_name=model_name,
            )
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
        """如果当前默认模型属于该 provider，则刷新默认模型缓存"""
        from app.repositories.model_instance import ModelInstanceRepository

        try:
            repo = ModelInstanceRepository(self.db)
            default_instance = await repo.get_default()
            if default_instance and default_instance.provider and default_instance.provider.name == provider_name:
                await self._update_default_model_cache(
                    provider_name=provider_name,
                    model_name=default_instance.model_name,
                    model_type="chat",
                    model_parameters=default_instance.model_parameters,
                )
        except Exception as e:
            print(f"Warning: Failed to update default model cache after credential change: {e}")

    async def _ensure_model_instances(self, provider) -> None:
        """确保该 provider 的所有模型在 model_instance 表中存在全局记录（委托给 ModelProviderService 复用逻辑）"""
        from app.services.model_provider_service import ModelProviderService

        await ModelProviderService(self.db)._ensure_model_instances_for_provider(provider)

    async def validate_credential(
        self,
        credential_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """
        验证凭据

        Args:
            credential_id: 凭据ID

        Returns:
            验证结果
        """
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")

        # 解密凭据
        decrypted_credentials = decrypt_credentials(credential.credentials)

        # 验证凭据
        provider_name_to_validate = credential.provider.template_name or credential.provider.name
        is_valid, error = await validate_provider_credentials(
            provider_name_to_validate,
            decrypted_credentials,
        )

        # 更新验证状态
        credential.is_valid = is_valid
        credential.last_validated_at = datetime.now(timezone.utc) if is_valid else None
        credential.validation_error = error

        await self.commit()

        return {
            "is_valid": is_valid,
            "error": error,
            "last_validated_at": credential.last_validated_at,
        }

    async def get_credential(
        self,
        credential_id: uuid.UUID,
        include_credentials: bool = False,
    ) -> Dict[str, Any]:
        """
        获取凭据信息

        Args:
            credential_id: 凭据ID
            include_credentials: 是否包含解密后的凭据（仅用于内部使用）

        Returns:
            凭据信息
        """
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")

        result = {
            "id": str(credential.id),
            "provider_name": credential.provider.name,
            "provider_display_name": credential.provider.display_name,
            "is_valid": credential.is_valid,
            "last_validated_at": credential.last_validated_at,
            "validation_error": credential.validation_error,
        }

        if include_credentials:
            result["credentials"] = decrypt_credentials(credential.credentials)

        return result

    async def list_credentials(
        self,
        user_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取所有凭据（所有用户和工作空间可见）

        Args:
            user_id: 用户ID（已废弃，当前未使用，保留用于向后兼容）
            workspace_id: 工作空间ID（已废弃，当前未使用，保留用于向后兼容）

        Returns:
            凭据列表
        """
        credentials = await self.repo.list_by_user(user_id, workspace_id)

        return [
            {
                "id": str(c.id),
                "provider_name": c.provider.name,
                "provider_display_name": c.provider.display_name,
                "is_valid": c.is_valid,
                "last_validated_at": c.last_validated_at,
                "validation_error": c.validation_error,
            }
            for c in credentials
        ]

    async def delete_credential(self, credential_id: uuid.UUID) -> None:
        """
        删除凭据

        Args:
            credential_id: 凭据ID
        """
        credential = await self.repo.get(credential_id)
        if not credential:
            raise NotFoundException("凭据不存在")

        await self.repo.delete(credential_id)
        await self.commit()

    async def get_current_credentials(
        self,
        provider_name: str,
        model_type: Any,
        model_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取当前凭据

        逻辑：
        1. 优先查找模型级别的凭据（如果有的话）
        2. 如果没有模型级别的凭据，使用 provider 级别的凭据

        Args:
            provider_name: 供应商名称
            model_type: 模型类型（ModelType 枚举）
            model_name: 模型名称

        Returns:
            解密后的凭据，如果不存在则返回None
        """
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            return None

        # TODO: 如果将来支持模型级别的凭据，在这里优先查找
        # 当前系统只支持 provider 级别的凭据，所以直接使用 provider 级别的凭据

        # 优先查找全局凭据（user_id 为 NULL）
        credential = await self.repo.get_by_provider(provider.id)

        # 如果没有全局凭据，查找任意有效凭据
        if not credential:
            credential = await self.repo.get_by_user_and_provider(
                None,
                provider.id,
                None,
            )

        if not credential or not credential.is_valid:
            return None

        return decrypt_credentials(credential.credentials)

    async def get_decrypted_credentials(
        self,
        provider_name: str,
        user_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取解密后的凭据（向后兼容方法，推荐使用 get_current_credentials）

        Args:
            provider_name: 供应商名称
            user_id: 用户ID（已废弃，当前未使用，保留用于向后兼容）
            workspace_id: 工作空间ID（已废弃，当前未使用，保留用于向后兼容）

        Returns:
            解密后的凭据，如果不存在则返回None
        """
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            return None

        # 优先查找全局凭据（user_id 为 NULL）
        credential = await self.repo.get_by_provider(provider.id)

        # 如果没有全局凭据，查找任意有效凭据
        if not credential:
            credential = await self.repo.get_by_user_and_provider(
                None,
                provider.id,
                None,
            )

        if not credential or not credential.is_valid:
            return None

        return decrypt_credentials(credential.credentials)
