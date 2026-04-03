"""
模型供应商服务
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.model import get_factory
from app.repositories.model_credential import ModelCredentialRepository
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository

from .base import BaseService

# 内置供应商固定展示顺序
BUILTIN_PROVIDER_ORDER = ("openaiapicompatible", "anthropic", "gemini", "zhipu", "ollama", "custom")


def _provider_sort_key(provider_data: Dict[str, Any]) -> int:
    """用于按固定顺序排序供应商。内置供应商优先，custom 其次，其他放最后。"""
    name = provider_data.get("provider_name", "")
    try:
        return BUILTIN_PROVIDER_ORDER.index(name)
    except ValueError:
        return len(BUILTIN_PROVIDER_ORDER)


class ModelProviderService(BaseService):
    """模型供应商服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelProviderRepository(db)
        self.instance_repo = ModelInstanceRepository(db)
        self.factory = get_factory()

    async def sync_providers_from_factory(self) -> List[Dict[str, Any]]:
        """从工厂同步供应商到数据库（upsert：不存在则创建，存在则更新）"""
        from loguru import logger

        factory_providers = self.factory.get_all_providers()
        synced_providers: List[Dict[str, Any]] = []
        errors: List[str] = []

        for provider_info in factory_providers:
            provider_name = provider_info["provider_name"]
            try:
                existing = await self.repo.get_by_name(provider_name)
                config_schemas = provider_info.get("config_schemas", {})

                provider_data = {
                    "display_name": provider_info.get("display_name", provider_name),
                    "supported_model_types": provider_info.get("supported_model_types", []),
                    "credential_schema": provider_info.get("credential_schema", {}),
                    "config_schema": config_schemas,
                    "is_template": provider_info.get("is_template", False),
                    "provider_type": provider_info.get("provider_type", "system"),
                    "template_name": provider_info.get("template_name"),
                }

                if existing:
                    await self.repo.update(existing.id, provider_data)
                    db_provider = existing
                    logger.debug(f"已更新供应商: {provider_name}")
                else:
                    db_provider = await self.repo.create(
                        {
                            "name": provider_name,
                            "is_enabled": True,
                            **provider_data,
                        }
                    )
                    logger.info(f"已创建供应商: {provider_name}")

                synced_providers.append(
                    {
                        "id": str(db_provider.id),
                        "name": db_provider.name,
                        "display_name": db_provider.display_name,
                        "supported_model_types": db_provider.supported_model_types or [],
                        "credential_schema": db_provider.credential_schema or {},
                        "config_schema": db_provider.config_schema or {},
                        "is_enabled": db_provider.is_enabled,
                        "is_template": db_provider.is_template,
                        "provider_type": db_provider.provider_type,
                        "template_name": db_provider.template_name,
                    }
                )
            except Exception as e:
                error_msg = f"同步供应商 {provider_name} 失败: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

        if errors:
            logger.warning(f"同步过程中有 {len(errors)} 个供应商失败: {', '.join(errors)}")

        await self.commit()
        return synced_providers

    def _serialize_provider(self, db_provider: Any, factory_provider: Any, model_count: int) -> Dict[str, Any]:
        """将 DB provider + factory provider 序列化为 API 响应 dict。"""
        config_schemas: Dict[str, Any] = {}
        if factory_provider:
            for model_type in factory_provider.get_supported_model_types():
                schema = factory_provider.get_config_schema(model_type)
                if schema:
                    config_schemas[model_type.value] = schema

        data: Dict[str, Any] = {
            "provider_name": db_provider.name,
            "display_name": db_provider.display_name
            or (factory_provider.display_name if factory_provider else db_provider.name),
            "supported_model_types": db_provider.supported_model_types
            or ([mt.value for mt in factory_provider.get_supported_model_types()] if factory_provider else []),
            "credential_schema": db_provider.credential_schema
            or (factory_provider.get_credential_schema() if factory_provider else {}),
            "config_schemas": config_schemas if factory_provider else (db_provider.config_schema or {}),
            "model_count": model_count,
            "default_parameters": db_provider.default_parameters or {},
            "is_template": db_provider.is_template,
            "provider_type": db_provider.provider_type,
            "template_name": db_provider.template_name,
            "is_enabled": db_provider.is_enabled,
            "id": str(db_provider.id),
        }

        if db_provider.icon:
            data["icon"] = db_provider.icon
        if db_provider.description:
            data["description"] = db_provider.description

        return data

    async def get_all_providers(self) -> List[Dict[str, Any]]:
        """获取所有供应商信息（过滤掉 is_template=True 的模板 provider）"""
        db_providers = await self.repo.find()
        model_counts = await self.instance_repo.count_grouped_by_provider()

        result = []
        for db_provider in db_providers:
            if db_provider.is_template:
                continue

            factory_name = db_provider.template_name or db_provider.name
            factory_provider = self.factory.get_provider(factory_name)
            model_count = model_counts.get(db_provider.id, 0)
            result.append(self._serialize_provider(db_provider, factory_provider, model_count))

        result.sort(key=_provider_sort_key)
        return result

    async def get_provider(self, provider_name: str) -> Dict[str, Any] | None:
        """获取单个供应商信息（不过滤模板，允许查询 custom 等模板 provider）"""
        db_provider = await self.repo.get_by_name(provider_name)
        if not db_provider:
            return None

        factory_name = db_provider.template_name or db_provider.name
        factory_provider = self.factory.get_provider(factory_name)
        model_count = await self.instance_repo.count_by_provider(provider_id=db_provider.id)
        return self._serialize_provider(db_provider, factory_provider, model_count)

    async def update_provider_defaults(self, provider_name: str, default_parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新供应商的默认参数

        Args:
            provider_name: 供应商名称
            default_parameters: 默认参数字典

        Returns:
            更新后的供应商信息

        Raises:
            NotFoundException: 供应商不存在
        """
        db_provider = await self.repo.get_by_name(provider_name)
        if not db_provider:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        await self.repo.update_default_parameters(provider_name, default_parameters)
        await self.commit()

        result = await self.get_provider(provider_name)
        if not result:
            raise NotFoundException(f"供应商不存在: {provider_name}")
        return result

    async def _create_derived_provider(self, template: Any, name: str, display_name: str, template_name: str) -> Any:
        """从模板创建派生 Provider DB 记录。"""
        return await self.repo.create(
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

    async def add_custom_provider(
        self,
        user_id: str,
        credentials: Dict[str, Any],
        model_name: str,
        display_name: Optional[str] = None,
        model_parameters: Optional[Dict[str, Any]] = None,
        validate: bool = True,
    ) -> Dict[str, Any]:
        """一步添加自定义 provider：创建 provider + credential + model_instance。"""
        import time

        from app.core.model import validate_provider_credentials
        from app.core.model.utils import encrypt_credentials

        template = self.factory.get_provider("custom")
        if not template:
            raise NotFoundException("供应商不存在: custom")

        is_valid = False
        validation_error = None
        if validate:
            is_valid, validation_error = await validate_provider_credentials(
                "custom", credentials, model_name=model_name
            )

        new_name = f"custom-{int(time.time())}"
        display = (display_name or model_name).strip() or new_name
        db_provider = await self._create_derived_provider(
            template=template, name=new_name, display_name=display, template_name="custom"
        )

        from datetime import datetime, timezone

        credential_repo = ModelCredentialRepository(self.db)
        encrypted = encrypt_credentials(credentials)
        now = datetime.now(timezone.utc) if is_valid else None
        credential = await credential_repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": db_provider.id,
                "credentials": encrypted,
                "is_valid": is_valid,
                "last_validated_at": now,
                "validation_error": validation_error,
            }
        )

        await self.instance_repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": db_provider.id,
                "model_name": model_name,
                "model_parameters": model_parameters or {},
            }
        )

        await self.commit()

        return {
            "provider_name": new_name,
            "display_name": display,
            "credential_id": str(credential.id),
            "is_valid": is_valid,
            "validation_error": validation_error,
        }

    async def delete_provider(self, provider_name: str) -> None:
        """
        删除供应商。仅允许删除自定义供应商（provider_type='custom'）。
        由于数据库配置了级联删除，相关的凭据和模型实例会自动清理。
        """
        from loguru import logger

        provider = await self.repo.get_by_name(provider_name)
        if not provider:
            factory_provider = self.factory.get_provider(provider_name)
            if factory_provider:
                raise BadRequestException(f"内置供应商不允许删除: {provider_name}")
            raise NotFoundException(f"供应商不存在: {provider_name}")

        if provider.provider_type != "custom":
            raise BadRequestException(f"仅允许删除自定义供应商: {provider_name}")

        await self.repo.delete(provider.id)
        logger.info(f"已删除自定义供应商: {provider_name}")

        await self.commit()

    async def sync_all(self) -> Dict[str, Any]:
        """统一同步接口：同步供应商和模型到数据库"""
        from loguru import logger

        result: Dict[str, Any] = {
            "providers": 0,
            "models": 0,
            "credentials": 0,
            "errors": [],
        }

        try:
            synced_providers = await self.sync_providers_from_factory()
            result["providers"] = len(synced_providers)
            logger.info(f"同步供应商完成，共 {len(synced_providers)} 个")
        except Exception as e:
            error_msg = f"同步供应商失败: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

        try:
            models_count = await self._sync_models()
            result["models"] = models_count
            logger.info(f"同步模型完成，共 {models_count} 个")
        except Exception as e:
            error_msg = f"同步模型失败: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

        await self.commit()
        return result

    async def _ensure_model_instances_for_provider(self, provider: Any) -> int:
        """
        确保该 provider 的所有模型在 model_instance 表中存在全局记录。
        对于动态发现型 provider（如 Ollama），还会清理已不存在的过期模型实例。

        Returns:
            本次新创建的模型实例数量
        """
        from loguru import logger

        from app.core.model.utils import decrypt_credentials

        provider_instance = self.factory.get_provider(provider.template_name or provider.name)
        if not provider_instance:
            return 0

        # 获取该 provider 的解密凭据（动态发现型 provider 需要凭据来获取模型列表）
        credential_repo = ModelCredentialRepository(self.db)
        credential = await credential_repo.get_by_provider(provider.id)
        decrypted_creds = None
        if credential and credential.is_valid:
            try:
                decrypted_creds = decrypt_credentials(credential.credentials)
            except Exception:
                pass

        synced_count = 0
        for model_type in provider_instance.get_supported_model_types():
            try:
                models = provider_instance.get_model_list(model_type, decrypted_creds)
                current_model_names = {m["name"] for m in models}

                for model_info in models:
                    model_name = model_info["name"]
                    existing = await self.instance_repo.get_best_instance(
                        model_name=model_name, provider_id=provider.id
                    )
                    if not existing:
                        await self.instance_repo.create(
                            {
                                "user_id": None,
                                "workspace_id": None,
                                "provider_id": provider.id,
                                "model_name": model_name,
                                "model_parameters": {},
                            }
                        )
                        synced_count += 1
                        logger.debug(f"已自动创建模型实例: {provider.name}/{model_name}")

                # 清理过期模型实例（仅当有凭据且获取到模型列表时执行）
                if decrypted_creds and current_model_names:
                    existing_instances = await self.instance_repo.list_by_provider(provider_id=provider.id)
                    for inst in existing_instances:
                        if inst.user_id is None and inst.model_name not in current_model_names:
                            await self.instance_repo.delete(inst.id)
                            logger.debug(f"已删除过期模型实例: {provider.name}/{inst.model_name}")

            except Exception as e:
                logger.warning(f"自动创建模型实例失败 {provider.name}/{model_type.value}: {str(e)}")

        return synced_count

    async def _sync_models(self) -> int:
        """同步模型到 model_instance 表（全局记录，user_id 和 workspace_id 为 NULL）"""
        providers = await self.repo.find(filters={})
        synced_count = 0
        for provider in providers:
            synced_count += await self._ensure_model_instances_for_provider(provider)
        return synced_count
