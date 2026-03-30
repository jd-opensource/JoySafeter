"""
模型供应商服务
"""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.model import get_factory
from app.models.model_instance import ModelInstance
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository

from .base import BaseService

# 内置供应商固定展示顺序
BUILTIN_PROVIDER_ORDER = ("openaiapicompatible", "anthropic", "gemini", "zhipu", "custom")


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
        """从工厂同步供应商到数据库"""
        from loguru import logger

        factory_providers = self.factory.get_all_providers()
        synced_providers: List[Dict[str, Any]] = []
        errors: List[str] = []

        for provider_info in factory_providers:
            provider_name = provider_info["provider_name"]
            try:
                existing = await self.repo.get_by_name(provider_name)
                config_schemas = provider_info.get("config_schemas", {})

                if existing:
                    await self.repo.update(
                        existing.id,
                        {
                            "display_name": provider_info.get("display_name", existing.display_name),
                            "supported_model_types": provider_info.get("supported_model_types", []),
                            "credential_schema": provider_info.get("credential_schema", {}),
                            "config_schema": config_schemas,
                            "is_template": provider_info.get("is_template", False),
                            "provider_type": provider_info.get("provider_type", "system"),
                            "template_name": provider_info.get("template_name"),
                        },
                    )
                    synced_providers.append(
                        {
                            "id": str(existing.id),
                            "name": existing.name,
                            "display_name": existing.display_name,
                            "supported_model_types": existing.supported_model_types or [],
                            "credential_schema": existing.credential_schema or {},
                            "config_schema": existing.config_schema or {},
                            "is_enabled": existing.is_enabled,
                            "is_template": existing.is_template,
                            "provider_type": existing.provider_type,
                            "template_name": existing.template_name,
                        }
                    )
                    logger.debug(f"已更新供应商: {provider_name}")
            except Exception as e:
                error_msg = f"同步供应商 {provider_name} 失败: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

        if errors:
            logger.warning(f"同步过程中有 {len(errors)} 个供应商失败: {', '.join(errors)}")

        await self.commit()
        return synced_providers

    async def get_all_providers(self) -> List[Dict[str, Any]]:
        """获取所有供应商信息（工厂为主，数据库补充用户自定义元数据）"""
        factory_providers = self.factory.get_all_providers()

        db_providers = await self.repo.find()
        db_provider_map = {p.name: p for p in db_providers}

        result = []
        for provider_info in factory_providers:
            provider_name = provider_info["provider_name"]
            db_provider = db_provider_map.get(provider_name)

            model_count = (
                await self.instance_repo.count_by_provider(provider_id=db_provider.id)
                if db_provider
                else await self.instance_repo.count_by_provider(provider_name=provider_name)
            )

            provider_data = {
                "provider_name": provider_name,
                "display_name": provider_info["display_name"],
                "supported_model_types": provider_info["supported_model_types"],
                "credential_schema": provider_info["credential_schema"],
                "config_schemas": provider_info.get("config_schemas", {}),
                "model_count": model_count,
                "default_parameters": db_provider.default_parameters if db_provider else {},
                "is_template": provider_info.get("is_template", False),
                "provider_type": provider_info.get("provider_type", "system"),
                "template_name": provider_info.get("template_name"),
                "is_enabled": db_provider.is_enabled if db_provider else True,
            }

            if db_provider:
                provider_data["id"] = str(db_provider.id)
                if db_provider.icon:
                    provider_data["icon"] = db_provider.icon
                if db_provider.description:
                    provider_data["description"] = db_provider.description

            result.append(provider_data)

        # 处理仅在数据库中存在的自定义供应商
        for provider_name, db_provider in db_provider_map.items():
            if any(p["provider_name"] == provider_name for p in factory_providers):
                continue

            model_count = await self.instance_repo.count_by_provider(provider_id=db_provider.id)

            provider_data = {
                "provider_name": db_provider.name,
                "display_name": db_provider.display_name or db_provider.name,
                "supported_model_types": db_provider.supported_model_types or [],
                "credential_schema": db_provider.credential_schema or {},
                "config_schemas": db_provider.config_schema or {},
                "model_count": model_count,
                "default_parameters": db_provider.default_parameters if db_provider.default_parameters else {},
                "is_template": db_provider.is_template,
                "provider_type": db_provider.provider_type,
                "template_name": db_provider.template_name,
                "is_enabled": db_provider.is_enabled,
                "id": str(db_provider.id),
                "icon": db_provider.icon,
                "description": db_provider.description,
            }
            result.append(provider_data)

        result.sort(key=_provider_sort_key)
        return result

    async def get_provider(self, provider_name: str) -> Dict[str, Any] | None:
        """获取单个供应商信息"""
        provider = self.factory.get_provider(provider_name)
        db_provider = await self.repo.get_by_name(provider_name)

        if not provider:
            if not db_provider:
                return None

            implementation_info = {}
            if db_provider.template_name:
                template = self.factory.get_provider(db_provider.template_name)
                if template:
                    implementation_info = {
                        "supported_model_types": [mt.value for mt in template.get_supported_model_types()],
                        "credential_schema": template.get_credential_schema(),
                    }

            model_count = await self.instance_repo.count_by_provider(provider_id=db_provider.id)

            return {
                "provider_name": db_provider.name,
                "display_name": db_provider.display_name or db_provider.name,
                "supported_model_types": implementation_info.get(
                    "supported_model_types", db_provider.supported_model_types or []
                ),
                "credential_schema": implementation_info.get("credential_schema", db_provider.credential_schema or {}),
                "config_schemas": db_provider.config_schema or {},
                "model_count": model_count,
                "default_parameters": db_provider.default_parameters if db_provider.default_parameters else {},
                "is_template": db_provider.is_template,
                "provider_type": db_provider.provider_type,
                "template_name": db_provider.template_name,
                "is_enabled": db_provider.is_enabled,
                "id": str(db_provider.id),
                "icon": db_provider.icon,
                "description": db_provider.description,
            }

        model_count = (
            await self.instance_repo.count_by_provider(provider_id=db_provider.id)
            if db_provider
            else await self.instance_repo.count_by_provider(provider_name=provider_name)
        )

        config_schemas = {}
        for model_type in provider.get_supported_model_types():
            config_schema = provider.get_config_schema(model_type)
            if config_schema:
                config_schemas[model_type.value] = config_schema

        provider_info = {
            "provider_name": provider_name,
            "display_name": provider.display_name,
            "supported_model_types": [mt.value for mt in provider.get_supported_model_types()],
            "credential_schema": provider.get_credential_schema(),
            "config_schemas": config_schemas,
            "model_count": model_count,
            "default_parameters": db_provider.default_parameters if db_provider else {},
            "is_template": provider.is_template,
            "provider_type": provider.provider_type,
            "template_name": getattr(provider, "template_name", None),
            "is_enabled": db_provider.is_enabled if db_provider else True,
        }

        if db_provider:
            provider_info["id"] = str(db_provider.id)
            if db_provider.icon:
                provider_info["icon"] = db_provider.icon
            if db_provider.description:
                provider_info["description"] = db_provider.description

        return provider_info

    async def update_provider_defaults(
        self, provider_name: str, default_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
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

        return await self.get_provider(provider_name)

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

        default_instance = await self.instance_repo.get_default()
        needs_new_default = False
        if default_instance and default_instance.provider_id == provider.id:
            logger.info(
                f"正在删除包含默认模型({default_instance.model_name})的供应商({provider_name})，将重新分配默认模型"
            )
            needs_new_default = True

        await self.repo.delete(provider.id)
        logger.info(f"已删除自定义供应商: {provider_name}")

        if needs_new_default:
            query = (
                select(ModelInstance).where(ModelInstance.user_id.is_(None)).order_by(ModelInstance.created_at.asc())
            )
            result = await self.db.execute(query)
            remaining_models = list(result.scalars().all())
            if remaining_models:
                new_default = remaining_models[0]
                await self.instance_repo.update(new_default.id, {"is_default": True})
                logger.info(f"已自动重新分配默认模型: {new_default.model_name}")

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
        确保该 provider 的所有模型在 model_instance 表中存在全局记录；若无默认模型则设第一个为默认。

        Returns:
            本次新创建的模型实例数量
        """
        from loguru import logger

        provider_instance = self.factory.get_provider(provider.template_name or provider.name)
        if not provider_instance:
            return 0

        synced_count = 0
        for model_type in provider_instance.get_supported_model_types():
            try:
                models = provider_instance.get_model_list(model_type)
                for model_info in models:
                    model_name = model_info["name"]
                    existing = await self.instance_repo.get_best_instance(
                        model_name=model_name, provider_name=provider.name, provider_id=provider.id
                    )
                    if not existing:
                        await self.instance_repo.create(
                            {
                                "user_id": None,
                                "workspace_id": None,
                                "provider_id": provider.id,
                                "model_name": model_name,
                                "model_parameters": {},
                                "is_default": False,
                            }
                        )
                        synced_count += 1
                        logger.debug(f"已自动创建模型实例: {provider.name}/{model_name}")
            except Exception as e:
                logger.warning(f"自动创建模型实例失败 {provider.name}/{model_type.value}: {str(e)}")

        default_instance = await self.instance_repo.get_default()
        if not default_instance:
            query = (
                select(ModelInstance).where(ModelInstance.user_id.is_(None)).order_by(ModelInstance.created_at.asc())
            )
            result = await self.db.execute(query)
            global_models = list(result.scalars().all())
            if global_models:
                first_model = global_models[0]
                await self.instance_repo.update(first_model.id, {"is_default": True})
                logger.info(f"已自动设置默认模型: {first_model.model_name} (provider_id: {first_model.provider_id})")

        return synced_count

    async def _sync_models(self) -> int:
        """同步模型到 model_instance 表（全局记录，user_id 和 workspace_id 为 NULL）"""
        providers = await self.repo.find(filters={})
        synced_count = 0
        for provider in providers:
            synced_count += await self._ensure_model_instances_for_provider(provider)
        return synced_count
