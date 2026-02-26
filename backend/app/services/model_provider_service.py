"""
模型供应商服务
"""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model import get_factory
from app.models.model_instance import ModelInstance
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository

from .base import BaseService


class ModelProviderService(BaseService):
    """模型供应商服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelProviderRepository(db)
        self.instance_repo = ModelInstanceRepository(db)
        # 注意：credential_repo 和 credential_service 已不再使用（凭据同步功能已移除）
        # 保留导入以避免破坏现有代码，但实际不再使用
        self.factory = get_factory()

    async def sync_providers_from_factory(self) -> List[Dict[str, Any]]:
        """
        从工厂同步供应商到数据库

        Returns:
            同步的供应商列表（包括新建和更新的）
        """
        from loguru import logger

        factory_providers = self.factory.get_all_providers()
        synced_providers: List[Dict[str, Any]] = []
        errors: List[str] = []

        for provider_info in factory_providers:
            provider_name = provider_info["provider_name"]
            try:
                # 检查是否已存在
                existing = await self.repo.get_by_name(provider_name)

                # 获取配置规则（工厂返回的是按模型类型组织的字典，存储时合并为一个字典）
                config_schemas = provider_info.get("config_schemas", {})

                if existing:
                    # 更新现有供应商
                    await self.repo.update(
                        existing.id,
                        {
                            "display_name": provider_info.get("display_name", existing.display_name),
                            "supported_model_types": provider_info.get("supported_model_types", []),
                            "credential_schema": provider_info.get("credential_schema", {}),
                            "config_schema": config_schemas,  # 注意：数据库字段是 config_schema（单数）
                        },
                    )
                    # Convert ModelProvider to dict
                    synced_providers.append(
                        {
                            "id": str(existing.id),
                            "name": existing.name,
                            "display_name": existing.display_name,
                            "supported_model_types": existing.supported_model_types or [],
                            "credential_schema": existing.credential_schema or {},
                            "config_schema": existing.config_schema or {},
                            "is_enabled": existing.is_enabled,
                        }
                    )
                    logger.debug(f"已更新供应商: {provider_name}")
                else:
                    # 创建新供应商
                    new_provider = await self.repo.create(
                        {
                            "name": provider_name,
                            "display_name": provider_info.get("display_name", provider_name),
                            "supported_model_types": provider_info.get("supported_model_types", []),
                            "credential_schema": provider_info.get("credential_schema", {}),
                            "config_schema": config_schemas,  # 注意：数据库字段是 config_schema（单数）
                            "is_enabled": True,
                        }
                    )
                    # Convert ModelProvider to dict
                    synced_providers.append(
                        {
                            "id": str(new_provider.id),
                            "name": new_provider.name,
                            "display_name": new_provider.display_name,
                            "supported_model_types": new_provider.supported_model_types or [],
                            "credential_schema": new_provider.credential_schema or {},
                            "config_schema": new_provider.config_schema or {},
                            "is_enabled": new_provider.is_enabled,
                        }
                    )
                    logger.debug(f"已创建供应商: {provider_name}")
            except Exception as e:
                error_msg = f"同步供应商 {provider_name} 失败: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

        if errors:
            logger.warning(f"同步过程中有 {len(errors)} 个供应商失败: {', '.join(errors)}")

        await self.commit()
        return synced_providers

    async def get_all_providers(self) -> List[Dict[str, Any]]:
        """
        获取所有供应商信息（直接从工厂获取，数据库仅用于用户自定义的元数据）

        改进：不再依赖数据库中的供应商记录，直接从代码加载。
        数据库仅用于存储用户自定义的元数据（图标、描述等），如果不存在则使用代码中的默认值。

        Returns:
            供应商信息列表
        """
        # 直接从工厂获取所有供应商（代码中定义）
        factory_providers = self.factory.get_all_providers()

        # 从数据库获取用户自定义的元数据（可选，用于覆盖默认值）
        db_providers = await self.repo.find()
        db_provider_map = {p.name: p for p in db_providers}

        # 合并信息（工厂为主，数据库为辅）
        result = []
        for provider_info in factory_providers:
            provider_name = provider_info["provider_name"]
            db_provider = db_provider_map.get(provider_name)

            # 主要信息从工厂获取（代码中定义）
            provider_data = {
                "provider_name": provider_name,
                "display_name": provider_info["display_name"],
                "supported_model_types": provider_info["supported_model_types"],
                "credential_schema": provider_info["credential_schema"],
                "config_schemas": provider_info.get("config_schemas", {}),
                "model_count": provider_info.get("model_count", 0),
                # 状态信息：数据库存在则使用数据库的值，否则默认为启用
                "is_enabled": db_provider.is_enabled if db_provider else True,
            }

            # 用户自定义的元数据（如果数据库中有，则覆盖默认值）
            if db_provider:
                provider_data["id"] = str(db_provider.id)
                # 图标和描述：优先使用数据库中的值（用户自定义），如果为空则使用代码中的默认值
                if db_provider.icon:
                    provider_data["icon"] = db_provider.icon
                if db_provider.description:
                    provider_data["description"] = db_provider.description

            result.append(provider_data)

        return result

    async def get_provider(self, provider_name: str) -> Dict[str, Any] | None:
        """
        获取单个供应商信息（直接从工厂获取，数据库仅用于用户自定义的元数据）

        Args:
            provider_name: 供应商名称

        Returns:
            供应商信息，如果不存在则返回None
        """
        # 直接从工厂获取供应商实例（代码中定义）
        provider = self.factory.get_provider(provider_name)
        if not provider:
            return None

        # 从数据库获取用户自定义的元数据（可选）
        db_provider = await self.repo.get_by_name(provider_name)

        model_count = 0
        for model_type in provider.get_supported_model_types():
            models = provider.get_model_list(model_type, None)
            model_count += len(models)

        # 主要信息从工厂获取（代码中定义）
        provider_info = {
            "provider_name": provider_name,
            "display_name": provider.display_name,
            "supported_model_types": [mt.value for mt in provider.get_supported_model_types()],
            "credential_schema": provider.get_credential_schema(),
            "model_count": model_count,
            # 状态信息：数据库存在则使用数据库的值，否则默认为启用
            "is_enabled": db_provider.is_enabled if db_provider else True,
        }

        # 添加配置规则（从代码中获取）
        config_schemas = {}
        for model_type in provider.get_supported_model_types():
            config_schema = provider.get_config_schema(model_type)
            if config_schema:
                config_schemas[model_type.value] = config_schema

        if config_schemas:
            provider_info["config_schemas"] = config_schemas

        # 用户自定义的元数据（如果数据库中有，则覆盖默认值）
        if db_provider:
            provider_info["id"] = str(db_provider.id)
            if db_provider.icon:
                provider_info["icon"] = db_provider.icon
            if db_provider.description:
                provider_info["description"] = db_provider.description

        return provider_info

    async def sync_all(self) -> Dict[str, Any]:
        """
        统一同步接口：同步供应商和模型到数据库

        注意：凭据不再通过此接口同步，请通过前端页面配置。
        所有凭据应通过前端页面配置，存储在 ModelCredential 表中。

        Returns:
            同步结果，包含：
            - providers: 同步的供应商数量
            - models: 同步的模型数量
            - credentials: 始终为 0（已移除环境变量同步功能）
        """
        from loguru import logger

        result: Dict[str, Any] = {
            "providers": 0,
            "models": 0,
            "credentials": 0,  # 已移除，始终为 0
            "errors": [],
        }

        # 1. 同步供应商元数据（用于存储用户自定义的图标、描述等）
        try:
            synced_providers = await self.sync_providers_from_factory()
            result["providers"] = len(synced_providers)
            logger.info(f"同步供应商完成，共 {len(synced_providers)} 个")
        except Exception as e:
            error_msg = f"同步供应商失败: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

        # 2. 同步模型到 model_instance 表（全局记录）
        try:
            models_count = await self._sync_models()
            result["models"] = models_count
            logger.info(f"同步模型完成，共 {models_count} 个")
        except Exception as e:
            error_msg = f"同步模型失败: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

        # 注意：凭据同步已移除，所有凭据应通过前端页面配置
        logger.info("凭据同步已移除，请通过前端页面配置凭据")

        await self.commit()
        return result

    async def _sync_models(self) -> int:
        """
        同步模型到 model_instance 表（全局记录，user_id 和 workspace_id 为 NULL）

        Returns:
            同步的模型数量
        """
        from loguru import logger

        synced_count = 0
        # 获取数据库中所有已同步的供应商（用于同步模型）
        providers = await self.repo.find(filters={})

        for provider in providers:
            provider_instance = self.factory.get_provider(provider.name)
            if not provider_instance:
                continue

            # 遍历所有支持的模型类型
            for model_type in provider_instance.get_supported_model_types():
                try:
                    # 从工厂获取模型列表
                    models = provider_instance.get_model_list(model_type)

                    for model_info in models:
                        model_name = model_info["name"]

                        # 检查是否已存在全局模型记录
                        existing = await self.instance_repo.get_by_provider_and_model(
                            provider.id,
                            model_name,
                        )

                        if existing:
                            # 更新现有记录
                            logger.debug(f"模型已存在: {provider.name}/{model_name}")
                        else:
                            # 创建新的全局模型记录
                            await self.instance_repo.create(
                                {
                                    "user_id": None,  # 全局记录
                                    "workspace_id": None,  # 全局记录
                                    "provider_id": provider.id,
                                    "model_name": model_name,
                                    "model_parameters": {},
                                    "is_default": False,
                                }
                            )
                            synced_count += 1
                            logger.debug(f"已创建模型: {provider.name}/{model_name}")
                except Exception as e:
                    logger.error(f"同步模型失败 {provider.name}/{model_type.value}: {str(e)}")

        # 检查是否存在默认模型，如果没有则选择第一个创建的全局模型作为默认
        default_instance = await self.instance_repo.get_default()
        if not default_instance:
            # 查询所有全局模型（user_id 为 None），按 created_at 升序排序
            query = (
                select(ModelInstance).where(ModelInstance.user_id.is_(None)).order_by(ModelInstance.created_at.asc())
            )
            result = await self.db.execute(query)
            global_models = list(result.scalars().all())

            if global_models:
                # 选择第一个创建的模型设置为默认
                first_model = global_models[0]
                await self.instance_repo.update(first_model.id, {"is_default": True})
                logger.info(f"已设置默认模型: {first_model.model_name} (provider_id: {first_model.provider_id})")

        return synced_count

    async def _sync_credentials(self) -> int:
        """
        [已废弃] 从环境变量同步凭据的功能已移除

        所有凭据应通过前端页面配置，存储在 ModelCredential 表中。
        此方法保留用于向后兼容，但不再执行任何操作。

        Returns:
            始终返回 0
        """
        from loguru import logger

        logger.warning("_sync_credentials() 已废弃，所有凭据应通过前端页面配置")
        return 0
