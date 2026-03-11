"""
模型服务
"""

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
        self.factory = get_factory()

    async def get_available_models(self, model_type: ModelType, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取可用模型列表（支持用户级或全局凭据）。
        """
        all_instances = await self.repo.list_all()
        providers = await self.provider_repo.find()
        provider_map = {p.id: p for p in providers}

        # 获取当前用户可用的凭据
        # 注意：list_credentials 返回的是简要信息，接下来我们需要为每个 provider 获取解密后的凭据（如果有效）

        credentials_dict = {}
        # 为了提高效率，我们只对 instances 中出现的 provider 进行查询
        relevant_providers = set()
        for instance in all_instances:
            relevant_providers.add(instance.resolved_provider_name)

        for pname in relevant_providers:
            decrypted = await self.credential_service.get_decrypted_credentials(pname, user_id=user_id)
            if decrypted:
                credentials_dict[pname] = decrypted

        models = []
        for instance in all_instances:
            if instance.provider_id is not None:
                provider = provider_map.get(instance.provider_id)
                if not provider:
                    continue
                pname = instance.resolved_provider_name
                pdisplay = provider.display_name
                impl_name = instance.resolved_implementation_name
                supported_types: List[str] = provider.supported_model_types or []
            else:
                if not instance.provider_name:
                    continue
                pname = instance.resolved_provider_name
                impl_name = instance.resolved_implementation_name
                prov = self.factory.get_provider(instance.provider_name)
                if not prov:
                    continue
                pdisplay = prov.display_name
                supported_types = [mt.value for mt in prov.get_supported_model_types()]

            if model_type.value not in supported_types:
                continue
            has_credentials = pname in credentials_dict
            display_name = instance.model_name
            description = ""
            prov_impl = self.factory.get_provider(impl_name)
            if prov_impl:
                provider_credentials = credentials_dict.get(pname)
                model_list = prov_impl.get_model_list(model_type, provider_credentials)
                matched = next((m for m in model_list if m.get("name") == instance.model_name), None)
                if matched:
                    display_name = matched.get("display_name", instance.model_name)
                    description = matched.get("description", "")

            models.append(
                {
                    "provider_name": pname,
                    "provider_display_name": pdisplay,
                    "name": instance.model_name,
                    "display_name": display_name,
                    "description": description,
                    "is_available": has_credentials,
                    "is_default": instance.is_default,
                }
            )
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
        创建模型实例配置（全局）。模板供应商以 Factory 为准；用户派生以 DB 为准。
        """
        provider = await self.provider_repo.get_by_name(provider_name)

        instance = await self.repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": provider.id if provider else None,
                "provider_name": provider_name if not provider else None,
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
        provider = await self.provider_repo.get_by_name(provider_name)

        provider_id = provider.id if provider else None

        instance = await self.repo.get_best_instance(
            model_name=model_name,
            provider_name=provider_name,
            provider_id=provider_id,
            user_id=user_id,
        )

        if not instance:
            raise NotFoundException(f"供应商不存在或模型实例不存在: {provider_name}/{model_name}")

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
        model_parameters: Dict[str, Any] = {}
        if not provider_name or not model_name:
            if use_default:
                default_instance = await self.repo.get_default()
                if default_instance:
                    provider_name = default_instance.resolved_provider_name
                    implementation_name = default_instance.resolved_implementation_name
                    model_name = default_instance.model_name
                    model_parameters = default_instance.model_parameters or {}
                else:
                    raise NotFoundException("未找到默认模型配置")
            else:
                raise BadRequestException("必须指定provider_name和model_name，或设置use_default=True")
        else:
            provider = await self.provider_repo.get_by_name(provider_name)
            provider_id = provider.id if provider else None

            instance = await self.repo.get_best_instance(
                model_name=model_name,
                provider_name=provider_name,
                provider_id=provider_id,
            )

            if not instance:
                raise NotFoundException(f"供应商不存在或模型实例不存在: {provider_name}/{model_name}")

            implementation_name = instance.resolved_implementation_name
            provider_name = instance.resolved_provider_name
            model_parameters = instance.model_parameters or {}

        # 确定模型类型（这里简化处理，假设是Chat模型）
        model_type = ModelType.CHAT

        assert provider_name is not None and model_name is not None
        assert implementation_name is not None

        # 获取凭据（按 DB 的 provider 名查找）
        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
            user_id=user_id,
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
        获取所有模型实例配置（全局）。支持模板（provider_name）与用户派生（provider）。
        """
        instances = await self.repo.list_all()
        out = []
        for i in instances:
            if i.provider:
                pname = i.provider.name
                pdisplay = i.provider.display_name
            else:
                pname = i.provider_name or ""
                p = self.factory.get_provider(i.provider_name) if i.provider_name else None
                pdisplay = p.display_name if p else pname
            out.append(
                {
                    "id": str(i.id),
                    "provider_name": pname,
                    "provider_display_name": pdisplay,
                    "model_name": i.model_name,
                    "model_parameters": i.model_parameters or {},
                    "is_default": i.is_default,
                }
            )
        return out

    async def get_runtime_model_by_name(self, model_name: str, user_id: Optional[str] = None) -> Any:
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

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name
        logger.debug(
            f"[ModelService.get_runtime_model_by_name] Found model instance | "
            f"model_name={instance.model_name} | provider={provider_name}"
        )

        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
            user_id=user_id,
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

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name
        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
            user_id=user_id,
        )

        if not credentials:
            raise NotFoundException(f"未找到模型 {provider_name}/{model_name} 的有效凭据")
        model = create_model_instance(
            implementation_name,
            model_name,
            model_type,
            credentials,
            instance.model_parameters or {},
        )

        # 调用模型进行测试
        response = await model.ainvoke(input_text)

        # 返回模型输出内容
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)
