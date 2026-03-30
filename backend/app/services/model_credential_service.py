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

    async def _get_first_model_name_for_provider(
        self, provider_id: Optional[uuid.UUID] = None, provider_name: Optional[str] = None
    ) -> Optional[str]:
        """获取 Provider 下第一个模型实例的名称，用于自定义 Provider 凭证验证。"""
        instances = await self.instance_repo.list_by_provider(
            provider_id=provider_id, provider_name=provider_name
        )
        return instances[0].model_name if instances else None

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
        创建或更新凭据（全局）。当 provider_name=custom 且 model_name 非空时：以模型维度新增一条
        （创建 custom-xxx provider + 凭据 + model_instance），一步到位。
        """
        import time

        # 一步到位：添加一个自定义模型（凭据 + 模型名）→ 新建 custom-xxx + 凭据 + 实例
        if provider_name == "custom" and model_name and model_name.strip():
            return await self._add_one_custom_model(
                user_id=user_id,
                credentials=credentials,
                validate=validate,
                model_name=model_name.strip(),
                model_parameters=model_parameters,
                display_name=provider_display_name,
            )

        # 以下为原有逻辑：仅创建/更新凭据
        template = self.factory.get_provider(provider_name)
        provider = await self.provider_repo.get_by_name(provider_name)

        # After Phase 1, all factory providers have DB records (sync_providers_from_factory upserts).
        # We always prefer provider_id over provider_name for storage.
        if template and provider_display_name:
            # User wants a named derived provider (e.g. "My OpenAI") — create a new DB provider record
            new_provider_name = f"{provider_name}-{int(time.time())}"
            db_provider = await self.provider_repo.create(
                {
                    "name": new_provider_name,
                    "display_name": provider_display_name,
                    "supported_model_types": [mt.value for mt in template.get_supported_model_types()],
                    "credential_schema": template.get_credential_schema(),
                    "config_schema": None,
                    "is_template": False,
                    "provider_type": "custom",
                    "template_name": provider_name,
                    "is_enabled": True,
                }
            )
            provider_id_to_use = db_provider.id
            provider_name_to_store = None
            final_provider_name = new_provider_name
            implementation_name = provider_name
            db_provider_for_ensure = db_provider
        elif provider:
            # DB record exists (covers all factory providers after Phase 1 sync)
            provider_id_to_use = provider.id
            provider_name_to_store = None
            final_provider_name = provider_name
            implementation_name = provider.template_name or provider.name
            db_provider_for_ensure = provider
        elif template:
            # Factory provider exists but DB record missing (should not happen post-Phase 1,
            # kept as a safety fallback using deprecated provider_name storage)
            implementation_name = provider_name
            provider_id_to_use = None
            provider_name_to_store = provider_name
            final_provider_name = provider_name
            db_provider_for_ensure = None
        else:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        is_valid = False
        validation_error = None
        if validate:
            validate_model_name = None
            if provider and provider.provider_type == "custom" and provider_id_to_use:
                validate_model_name = await self._get_first_model_name_for_provider(provider_id=provider_id_to_use)
            is_valid, validation_error = await validate_provider_credentials(
                implementation_name, credentials, model_name=validate_model_name
            )

        encrypted_credentials = encrypt_credentials(credentials)

        existing = await self.repo.get_by_user_and_provider(
            provider_id=provider_id_to_use, provider_name=provider_name_to_store
        )
        if existing:
            existing.credentials = encrypted_credentials
            existing.is_valid = is_valid
            existing.last_validated_at = datetime.now(timezone.utc) if is_valid else None
            existing.validation_error = validation_error
            await self.db.flush()
            await self.db.refresh(existing)
            credential = existing
        else:
            credential = await self.repo.create(
                {
                    "user_id": user_id,
                    "workspace_id": None,
                    "provider_id": provider_id_to_use,
                    "provider_name": provider_name_to_store,
                    "credentials": encrypted_credentials,
                    "is_valid": is_valid,
                    "last_validated_at": datetime.now(timezone.utc) if is_valid else None,
                    "validation_error": validation_error,
                }
            )

        if db_provider_for_ensure:
            await self._ensure_model_instances(db_provider_for_ensure)

        await self.commit()
        await self._update_default_model_cache_if_needed(final_provider_name)

        return {
            "id": str(credential.id),
            "provider_name": final_provider_name,
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
        """以模型维度新增一个自定义模型：custom-xxx + 凭据 + model_instance，同一事务。"""
        import time

        template = self.factory.get_provider("custom")
        if not template:
            raise NotFoundException("供应商不存在: custom")

        is_valid = False
        validation_error = None
        if validate:
            is_valid, validation_error = await validate_provider_credentials(
                "custom", credentials, model_name=model_name
            )
        encrypted = encrypt_credentials(credentials)

        new_provider_name = f"custom-{int(time.time())}"
        display = (display_name or model_name).strip() or new_provider_name

        db_provider = await self.provider_repo.create(
            {
                "name": new_provider_name,
                "display_name": display,
                "supported_model_types": [mt.value for mt in template.get_supported_model_types()],
                "credential_schema": template.get_credential_schema(),
                "config_schema": None,
                "is_template": False,
                "provider_type": "custom",
                "template_name": "custom",
                "is_enabled": True,
            }
        )

        credential = await self.repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": db_provider.id,
                "provider_name": None,
                "credentials": encrypted,
                "is_valid": is_valid,
                "last_validated_at": datetime.now(timezone.utc) if is_valid else None,
                "validation_error": validation_error,
            }
        )

        await self.instance_repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": db_provider.id,
                "provider_name": None,
                "model_name": model_name,
                "model_parameters": model_parameters or {},
                "is_default": False,
            }
        )

        await self.commit()
        await self._update_default_model_cache_if_needed(new_provider_name)

        return {
            "id": str(credential.id),
            "provider_name": new_provider_name,
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
                user_id=None,  # Cache is global for now, but we search for global credentials
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
            effective_name = (
                (default_instance.provider.name if default_instance.provider else default_instance.provider_name)
                if default_instance
                else None
            )
            if default_instance and effective_name == provider_name:
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

        # 验证凭据（模板凭据无 provider 行，用 provider_name）
        provider_name_to_validate = (
            (credential.provider.template_name or credential.provider.name)
            if credential.provider
            else (credential.provider_name or "")
        )
        if not provider_name_to_validate:
            is_valid, error = False, "无法解析供应商"
        else:
            validate_model_name = None
            if credential.provider and credential.provider.provider_type == "custom":
                validate_model_name = await self._get_first_model_name_for_provider(provider_id=credential.provider.id)
            is_valid, error_to_store = await validate_provider_credentials(
                provider_name_to_validate,
                decrypted_credentials,
                model_name=validate_model_name,
            )
            error = error_to_store or ""

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

        pname = credential.provider.name if credential.provider else (credential.provider_name or "")
        if credential.provider:
            pdisplay = credential.provider.display_name
        elif credential.provider_name:
            p = self.factory.get_provider(credential.provider_name)
            pdisplay = p.display_name if p else credential.provider_name
        else:
            pdisplay = ""
        result = {
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
        """
        获取凭据列表（全局，与 workspace 无关）
        """
        credentials = await self.repo.list_all()

        out = []
        for c in credentials:
            pname = c.provider.name if c.provider else (c.provider_name or "")
            if c.provider:
                pdisplay = c.provider.display_name
            elif c.provider_name:
                p = self.factory.get_provider(c.provider_name)
                pdisplay = p.display_name if p else c.provider_name
            else:
                pdisplay = ""
            out.append(
                {
                    "id": str(c.id),
                    "provider_name": pname,
                    "provider_display_name": pdisplay,
                    "is_valid": c.is_valid,
                    "last_validated_at": c.last_validated_at,
                    "validation_error": c.validation_error,
                }
            )
        return out

    async def delete_credential(self, credential_id: uuid.UUID) -> None:
        """
        删除凭据。
        如果是自定义供应商的专用凭据（provider_type='custom' 且非模板），则连同供应商一并删除，以防残留。
        """
        credential = await self.repo.get(credential_id, relations=["provider"])
        if not credential:
            raise NotFoundException("凭据不存在")

        # 如果是专用自定义供应商，删除供应商（触发级联删除）
        if (
            credential.provider
            and credential.provider.provider_type == "custom"
            and not credential.provider.is_template
        ):
            from loguru import logger

            logger.info(f"正在删除专用自定义供应商及其凭据: {credential.provider.name}")
            await self.provider_repo.delete(credential.provider.id)
        else:
            # 否则仅删除凭据（如内置供应商的凭据）
            await self.repo.delete(credential_id)

        await self.commit()

    async def get_current_credentials(
        self,
        provider_name: str,
        model_type: Any,
        model_name: str,
        user_id: Optional[str] = None,
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
            user_id: 用户ID（可选）

        Returns:
            解 decrypted后的凭据，如果不存在则返回None
        """
        return await self.get_decrypted_credentials(provider_name, user_id)

    async def get_decrypted_credentials(
        self, provider_name: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取解密后的凭据（全局）。
        After Phase 1, all factory providers have DB records, so we look up by provider_id.
        Falls back to provider_name-only lookup for any legacy unbackfilled rows.

        Queries: get_by_name (1) + get_best_valid_credential by provider_id (1) = 2 total.
        """
        # Look up the DB provider record once
        provider = await self.provider_repo.get_by_name(provider_name)

        if provider:
            # Primary path: query by provider_id (all post-Phase-1 records)
            credential = await self.repo.get_best_valid_credential(
                provider_name=provider_name, provider_id=provider.id, user_id=user_id
            )
            if credential:
                return decrypt_credentials(credential.credentials)

        # Deprecated fallback: legacy rows where provider_id was not backfilled (provider_id IS NULL)
        credential = await self.repo.get_best_valid_credential(provider_name=provider_name, user_id=user_id)
        if credential:
            return decrypt_credentials(credential.credentials)

        return None
