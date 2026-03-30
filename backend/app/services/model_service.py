"""
模型服务
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.model import ModelType, create_model_instance
from app.core.model.factory import get_factory
from app.repositories.model_credential import ModelCredentialRepository
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
        self.credential_repo = ModelCredentialRepository(db)
        self.credential_service = ModelCredentialService(db)
        self.factory = get_factory()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _build_credentials_map(self, provider_names: set) -> Dict[str, Any]:
        """Build a map of provider_name -> decrypted credentials for a set of providers."""
        credentials_dict: Dict[str, Any] = {}
        for pname in provider_names:
            decrypted = await self.credential_service.get_decrypted_credentials(pname, user_id=None)
            if decrypted:
                credentials_dict[pname] = decrypted
        return credentials_dict

    async def _build_credentials_validity_map(self, provider_names: set) -> Dict[str, Optional[str]]:
        """
        Build a map of provider_name -> None (valid) or error string (invalid/missing).
        None means valid credentials exist; a string means invalid or no credentials.
        """
        all_credentials = await self.credential_repo.list_all()
        cred_by_provider: Dict[str, Any] = {}
        for c in all_credentials:
            pname = c.provider.name if c.provider else (c.provider_name or "")
            if pname and pname not in cred_by_provider:
                cred_by_provider[pname] = c

        result: Dict[str, Optional[str]] = {}
        for pname in provider_names:
            cred = cred_by_provider.get(pname)
            if cred is None:
                result[pname] = "no_credentials"
            elif not cred.is_valid:
                result[pname] = cred.validation_error or "invalid_credentials"
            else:
                result[pname] = None
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_available_models(self, model_type: ModelType, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取可用模型列表，含 unavailable_reason。"""
        all_instances = await self.repo.list_all()
        providers = await self.provider_repo.find()
        provider_map = {p.id: p for p in providers}

        relevant_providers: set = set()
        for instance in all_instances:
            relevant_providers.add(instance.resolved_provider_name)

        credentials_dict = await self._build_credentials_map(relevant_providers)
        validity_map = await self._build_credentials_validity_map(relevant_providers)

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
            validity_error = validity_map.get(pname)

            display_name = instance.model_name
            description = ""
            model_found_in_list = True

            prov_impl = self.factory.get_provider(impl_name)
            if prov_impl:
                provider_credentials = credentials_dict.get(pname)
                model_list = prov_impl.get_model_list(model_type, provider_credentials)
                matched = next((m for m in model_list if m.get("name") == instance.model_name), None)
                if matched:
                    display_name = matched.get("display_name", instance.model_name)
                    description = matched.get("description", "")
                else:
                    model_found_in_list = False

            # Determine unavailable_reason
            unavailable_reason: Optional[str] = None
            if validity_error == "no_credentials":
                unavailable_reason = "no_credentials"
            elif validity_error is not None:
                unavailable_reason = "invalid_credentials"
            elif not model_found_in_list:
                unavailable_reason = "model_not_found"

            entry: Dict[str, Any] = {
                "provider_name": pname,
                "provider_display_name": pdisplay,
                "name": instance.model_name,
                "display_name": display_name,
                "description": description,
                "is_available": has_credentials and unavailable_reason is None,
                "is_default": instance.is_default,
            }
            if unavailable_reason:
                entry["unavailable_reason"] = unavailable_reason

            models.append(entry)
        return models

    async def get_overview(self) -> Dict[str, Any]:
        """返回全局模型概览：Provider 健康摘要、默认模型、最近凭证失败。"""
        all_providers = await self.provider_repo.find()
        all_credentials = await self.credential_repo.list_all()

        cred_by_provider: Dict[str, Any] = {}
        for c in all_credentials:
            pname = c.provider.name if c.provider else (c.provider_name or "")
            if pname and pname not in cred_by_provider:
                cred_by_provider[pname] = c

        healthy = 0
        unhealthy = 0
        unconfigured = 0
        recent_failure: Optional[Dict[str, Any]] = None

        for p in all_providers:
            cred = cred_by_provider.get(p.name)
            if cred is None:
                unconfigured += 1
            elif cred.is_valid:
                healthy += 1
            else:
                unhealthy += 1
                if recent_failure is None:
                    recent_failure = {
                        "provider_name": p.name,
                        "provider_display_name": p.display_name or p.name,
                        "error": cred.validation_error or "unknown error",
                        "failed_at": cred.last_validated_at,
                    }

        total_models = await self.repo.count_by_provider()
        available_models = 0
        all_instances = await self.repo.list_all()
        relevant_providers: set = {i.resolved_provider_name for i in all_instances}
        credentials_dict = await self._build_credentials_map(relevant_providers)
        for instance in all_instances:
            pname = instance.resolved_provider_name
            if pname in credentials_dict:
                available_models += 1

        default_instance = await self.repo.get_default()
        default_model_info: Optional[Dict[str, Any]] = None
        if default_instance:
            pname = default_instance.resolved_provider_name
            if default_instance.provider_id is not None:
                provider = next((p for p in all_providers if p.id == default_instance.provider_id), None)
                pdisplay = provider.display_name if provider else pname
            else:
                prov = self.factory.get_provider(pname)
                pdisplay = prov.display_name if prov else pname
            default_model_info = {
                "provider_name": pname,
                "provider_display_name": pdisplay,
                "model_name": default_instance.model_name,
                "model_parameters": default_instance.model_parameters or {},
            }

        return {
            "total_providers": len(all_providers),
            "healthy_providers": healthy,
            "unhealthy_providers": unhealthy,
            "unconfigured_providers": unconfigured,
            "total_models": total_models,
            "available_models": available_models,
            "default_model": default_model_info,
            "recent_credential_failure": recent_failure,
        }

    async def update_model_instance(
        self,
        instance_id: uuid.UUID,
        model_parameters: Optional[Dict[str, Any]] = None,
        is_default: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """更新模型实例参数和/或默认状态。"""
        instance = await self.repo.get(instance_id)
        if not instance:
            raise NotFoundException(f"模型实例不存在: {instance_id}")

        updates: Dict[str, Any] = {}
        if model_parameters is not None:
            updates["model_parameters"] = model_parameters
        if is_default is not None:
            updates["is_default"] = is_default

        if is_default:
            existing_default = await self.repo.get_default()
            if existing_default and existing_default.id != instance_id:
                existing_default.is_default = False
                await self.db.flush()

        if updates:
            await self.repo.update(instance_id, updates)

        await self.commit()

        # Refresh
        instance = await self.repo.get(instance_id)
        pname = instance.resolved_provider_name

        if is_default:
            await self.credential_service._update_default_model_cache(
                provider_name=pname,
                model_name=instance.model_name,
                model_type="chat",
                model_parameters=instance.model_parameters,
            )

        return {
            "id": str(instance.id),
            "provider_name": pname,
            "model_name": instance.model_name,
            "model_type": "chat",
            "model_parameters": instance.model_parameters or {},
            "is_default": instance.is_default,
        }

    async def create_model_instance_config(
        self,
        user_id: str,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        model_parameters: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
    ) -> Dict[str, Any]:
        """创建模型实例配置（全局）。"""
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
        """更新模型实例的默认状态。"""
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

        if is_default:
            existing_default = await self.repo.get_default()
            if existing_default and existing_default.id != instance.id:
                existing_default.is_default = False
                await self.db.flush()

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
            "model_type": "chat",
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
        """获取模型实例（LangChain 模型对象）。"""
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

        model_type = ModelType.CHAT

        assert provider_name is not None and model_name is not None
        assert implementation_name is not None

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
            model_parameters,
        )

        return model

    async def list_model_instances(self) -> List[Dict[str, Any]]:
        """获取所有模型实例配置（全局）。"""
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
        """根据 model_name 获取运行时模型实例（LangChain 模型对象）。"""
        from loguru import logger

        logger.debug(f"[ModelService.get_runtime_model_by_name] Looking up model | model_name={model_name}")

        instance = await self.repo.get_by_name(model_name)

        if not instance:
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
        """测试模型输出（全局，与 workspace 无关）"""
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

        response = await model.ainvoke(input_text)

        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)
