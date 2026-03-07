"""
模型服务
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.model import ModelType, create_model_instance
from app.core.model.factory import get_factory
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository
from app.services.model_credential_service import ModelCredentialService

from .base import BaseService


class ModelService(BaseService):
    """模型服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelInstanceRepository(db)
        self.provider_repo = ModelProviderRepository(db)
        self.credential_service = ModelCredentialService(db)

    async def get_available_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """
        获取可用模型列表（全局，与 workspace 无关）
        """
        all_instances = await self.repo.list_all()

        # 获取所有供应商
        providers = await self.provider_repo.find()
        provider_map = {p.id: p for p in providers}

        # 获取所有凭据
        credentials_list = await self.credential_service.list_credentials()
        credentials_dict = {}
        for cred in credentials_list:
            if cred["is_valid"]:
                decrypted = await self.credential_service.get_decrypted_credentials(
                    cred["provider_name"],
                )
                if decrypted:
                    credentials_dict[cred["provider_name"]] = decrypted

        # 获取 ModelFactory 实例
        factory = get_factory()

        # 过滤出指定类型的模型
        models = []
        for instance in all_instances:
            provider = provider_map.get(instance.provider_id)
            if not provider:
                continue

            # 检查供应商是否支持该模型类型
            supported_types: list[str] = provider.supported_model_types or []  # type: ignore[assignment]
            if model_type.value not in supported_types:
                continue

            # 检查是否有有效的凭据
            has_credentials = provider.name in credentials_dict

            # 从 ModelFactory 获取 provider 实例，并获取模型的 display_name 和 description
            display_name = instance.model_name  # 默认使用 model_name
            description = ""  # 默认描述为空

            provider_instance = factory.get_provider(provider.template_name or provider.name)
            if provider_instance:
                # 获取该 provider 的凭据（如果有）
                provider_credentials = credentials_dict.get(provider.name)

                # 获取模型列表
                model_list = provider_instance.get_model_list(model_type, provider_credentials)

                # 在模型列表中查找匹配的模型
                matched_model = next((m for m in model_list if m.get("name") == instance.model_name), None)

                if matched_model:
                    display_name = matched_model.get("display_name", instance.model_name)
                    description = matched_model.get("description", "")

            model_info = {
                "provider_name": provider.name,
                "provider_display_name": provider.display_name,
                "name": instance.model_name,
                "display_name": display_name,
                "description": description,
                "is_available": has_credentials,
                "is_default": instance.is_default,
            }
            models.append(model_info)

        return models

    async def create_model_instance_config(
        self,
        user_id: str,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        model_parameters: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
    ) -> Dict[str, Any]:
        """
        创建模型实例配置（全局，与 workspace 无关）
        """
        # 验证供应商是否存在
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        # 如果设置为默认，先取消其他默认模型
        if is_default:
            existing_default = await self.repo.get_default()
            if existing_default:
                existing_default.is_default = False
                await self.db.flush()

        # 创建模型实例配置（全局：workspace_id 固定为 None）
        instance = await self.repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": provider.id,
                "model_name": model_name,
                "model_parameters": model_parameters or {},
                "is_default": is_default,
            }
        )

        await self.commit()

        if is_default:
            await self.credential_service._update_default_model_cache(
                provider_name=provider_name,
                model_name=model_name,
                model_type=model_type.value,
                model_parameters=instance.model_parameters,
            )

        return {
            "id": str(instance.id),
            "provider_name": provider_name,
            "model_name": model_name,
            "model_type": model_type.value,
            "model_parameters": instance.model_parameters,
            "is_default": instance.is_default,
        }

    async def update_model_instance_default(
        self,
        provider_name: str,
        model_name: str,
        is_default: bool,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新模型实例的默认状态

        Args:
            provider_name: 供应商名称
            model_name: 模型名称
            is_default: 是否为默认模型
            user_id: 用户ID（可选，用于查找用户特定的模型实例）

        Returns:
            更新后的模型实例配置
        """
        # 验证供应商是否存在
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            raise NotFoundException(f"供应商不存在: {provider_name}")

        # 获取模型实例（优先全局，其次用户）
        instance = await self.repo.get_by_provider_and_model(provider.id, model_name, user_id)
        if not instance:
            raise NotFoundException(f"模型实例不存在: {provider_name}/{model_name}")

        # 如果设置为默认，先取消其他默认模型
        if is_default:
            existing_default = await self.repo.get_default()
            if existing_default and existing_default.id != instance.id:
                existing_default.is_default = False
                await self.db.flush()

        # 更新模型实例的默认状态
        instance.is_default = is_default
        await self.commit()

        if is_default:
            await self.credential_service._update_default_model_cache(
                provider_name=provider_name,
                model_name=model_name,
                model_type="chat",
                model_parameters=instance.model_parameters,
            )
        else:
            try:
                from app.core.settings import clear_default_model_config

                clear_default_model_config()
            except Exception as e:
                print(f"Warning: Failed to clear model cache: {e}")

        return {
            "id": str(instance.id),
            "provider_name": provider_name,
            "model_name": model_name,
            "model_type": "chat",  # 简化处理
            "model_parameters": instance.model_parameters,
            "is_default": instance.is_default,
        }

    async def get_model_instance(
        self,
        user_id: str,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        use_default: bool = True,
    ) -> Any:
        """
        获取模型实例（LangChain模型对象）。全局，与 workspace 无关。
        """
        # 如果未指定，使用默认模型
        implementation_name: Optional[str] = None
        if not provider_name or not model_name:
            if use_default:
                default_instance = await self.repo.get_default()
                if default_instance:
                    provider_name = default_instance.provider.name
                    implementation_name = default_instance.provider.template_name or default_instance.provider.name
                    model_name = default_instance.model_name
                    model_parameters = default_instance.model_parameters
                else:
                    raise NotFoundException("未找到默认模型配置")
            else:
                raise BadRequestException("必须指定provider_name和model_name，或设置use_default=True")
        else:
            provider = await self.provider_repo.get_by_name(provider_name)
            if not provider:
                raise NotFoundException(f"供应商不存在: {provider_name}")

            implementation_name = provider.template_name or provider.name
            instance = await self.repo.get_by_provider_and_model(provider.id, model_name)
            model_parameters = instance.model_parameters if instance else {}

        # 确定模型类型（这里简化处理，假设是Chat模型）
        model_type = ModelType.CHAT

        assert provider_name is not None and model_name is not None
        assert implementation_name is not None

        # 获取凭据（按 DB 的 provider 名查找）
        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
        )

        if not credentials:
            raise NotFoundException(f"未找到模型 {provider_name}/{model_name} 的有效凭据")

        # 创建模型实例（工厂按实现名 template_name 解析，如 custom、openaiapicompatible）
        model = create_model_instance(
            implementation_name,
            model_name,
            model_type,
            credentials,
            model_parameters,
        )

        return model

    async def list_model_instances(self) -> List[Dict[str, Any]]:
        """
        获取所有模型实例配置（全局，与 workspace 无关）
        """
        instances = await self.repo.list_all()

        return [
            {
                "id": str(i.id),
                "provider_name": i.provider.name,
                "provider_display_name": i.provider.display_name,
                "model_name": i.model_name,
                "model_parameters": i.model_parameters,
                "is_default": i.is_default,
            }
            for i in instances
        ]

    async def get_runtime_model_by_name(self, model_name: str) -> Any:
        """
        根据 model_name 获取运行时模型实例（LangChain 模型对象）。全局，与 workspace 无关。
        """
        from loguru import logger

        logger.debug(f"[ModelService.get_runtime_model_by_name] Looking up model | model_name={model_name}")

        instance = await self.repo.get_by_name(model_name)

        if not instance:
            # 列出所有可用的模型实例，帮助调试
            all_instances = await self.repo.list_all()
            available_model_names = [inst.model_name for inst in all_instances]
            logger.error(
                f"[ModelService.get_runtime_model_by_name] Model instance not found | "
                f"requested_model_name={model_name} | "
                f"available_model_names={available_model_names}"
            )
            raise NotFoundException(
                f"模型实例不存在: {model_name}。可用的模型: {', '.join(available_model_names[:10])}"
            )

        logger.debug(
            f"[ModelService.get_runtime_model_by_name] Found model instance | "
            f"model_name={instance.model_name} | provider={instance.provider.name}"
        )

        # 凭据按 DB 的 provider 名查找；工厂按实现名（template_name）创建实例
        provider_name = instance.provider.name
        implementation_name = instance.provider.template_name or instance.provider.name

        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
        )

        if not credentials:
            raise NotFoundException(f"未找到模型 {provider_name}/{model_name} 的有效凭据")

        model = create_model_instance(
            implementation_name,
            model_name,
            model_type,
            credentials,
            instance.model_parameters,
        )

        return model

    async def test_output(self, user_id: str, model_name: str, input_text: str) -> str:
        """
        测试模型输出（全局，与 workspace 无关）
        """
        instance = await self.repo.get_by_name(model_name)

        if not instance:
            raise NotFoundException(f"模型实例不存在: {model_name}")

        provider_name = instance.provider.name
        implementation_name = instance.provider.template_name or instance.provider.name
        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
        )

        if not credentials:
            raise NotFoundException(f"未找到模型 {provider_name}/{model_name} 的有效凭据")
        model = create_model_instance(
            implementation_name,
            model_name,
            model_type,
            credentials,
            instance.model_parameters,
        )

        # 调用模型进行测试
        response = await model.ainvoke(input_text)

        # 返回模型输出内容
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)
