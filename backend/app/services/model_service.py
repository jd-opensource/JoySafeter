"""
模型服务
"""

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, ModelConfigError, NotFoundException
from app.core.model import ModelType, create_model_instance
from app.core.model.factory import get_factory
from app.repositories.model_credential import ModelCredentialRepository
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_provider import ModelProviderRepository
from app.services.model_credential_service import ModelCredentialService

from .base import BaseService
from .model_usage_service import ModelUsageService


# Error code constants — shared with frontend i18n keys
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
MODEL_NO_CREDENTIALS = "MODEL_NO_CREDENTIALS"
PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
MODEL_NAME_REQUIRED = "MODEL_NAME_REQUIRED"


def _raise_model_error(
    code: str,
    message: str,
    *,
    model_name: str | None = None,
    provider_name: str | None = None,
    available: list[str] | None = None,
) -> None:
    params: dict[str, str] = {"model": model_name or "", "provider": provider_name or ""}
    if available is not None:
        params["available"] = ", ".join(available[:10])
    raise ModelConfigError(code, message, params=params)


class ModelService(BaseService):
    """模型服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelInstanceRepository(db)
        self.provider_repo = ModelProviderRepository(db)
        self.credential_repo = ModelCredentialRepository(db)
        self.credential_service = ModelCredentialService(db)
        self.usage_service = ModelUsageService(db)
        self.factory = get_factory()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _build_provider_credentials_context(self, provider_ids: set) -> Dict[Any, Dict[str, Any]]:
        """一次性构建 provider 凭证上下文。Keyed by provider_id。"""
        from app.core.model.utils import decrypt_credentials

        credentials = await self.credential_repo.list_by_provider_ids(provider_ids)

        cred_by_id: Dict[Any, Any] = {}
        for c in credentials:
            pid = c.provider_id
            if pid not in cred_by_id:
                cred_by_id[pid] = c

        result: Dict[Any, Dict[str, Any]] = {}
        for pid in provider_ids:
            cred = cred_by_id.get(pid)
            if cred is None:
                result[pid] = {"decrypted": None, "is_valid": False, "error": "no_credentials"}
            elif not cred.is_valid:
                result[pid] = {
                    "decrypted": None,
                    "is_valid": False,
                    "error": cred.validation_error or "invalid_credentials",
                }
            else:
                try:
                    decrypted = decrypt_credentials(cred.credentials)
                    result[pid] = {"decrypted": decrypted, "is_valid": True, "error": None}
                except Exception:
                    result[pid] = {"decrypted": None, "is_valid": False, "error": "decrypt_failed"}

        return result

    async def _resolve_and_create_model(self, model_name: str, user_id: Optional[str] = None) -> tuple:
        """
        统一 resolve provider -> get credential -> create model 逻辑。
        返回 (model, provider_name, implementation_name, instance)。
        """
        instance = await self.repo.get_by_name(model_name)
        if not instance:
            _raise_model_error(MODEL_NOT_FOUND, f'Model "{model_name}" is not registered.', model_name=model_name)

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)
        if not credentials:
            _raise_model_error(MODEL_NO_CREDENTIALS, f'No valid API key for provider "{provider_name}".', model_name=model_name, provider_name=provider_name)

        model = create_model_instance(
            implementation_name,
            model_name,
            ModelType.CHAT,
            credentials,
            instance.model_parameters or {},
        )

        return model, provider_name, implementation_name, instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_available_models(self, model_type: ModelType, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取可用模型列表，含 unavailable_reason。"""
        all_instances = await self.repo.list_all()

        # Collect provider_ids for all instances that have one
        relevant_provider_ids: set = {i.provider_id for i in all_instances if i.provider_id is not None}
        cred_ctx = await self._build_provider_credentials_context(relevant_provider_ids)

        # Cache factory provider and model_list per impl_name to avoid repeated lookups
        _factory_cache: Dict[str, Any] = {}  # impl_name -> factory provider (or None)
        _model_list_cache: Dict[str, List[Dict[str, Any]]] = {}  # impl_name -> model list
        _model_map_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}  # impl_name -> {name: model_info}

        def _get_factory_provider(impl_name: str):
            if impl_name not in _factory_cache:
                _factory_cache[impl_name] = self.factory.get_provider(impl_name)
            return _factory_cache[impl_name]

        def _get_model_map(impl_name: str, prov_impl: Any, credentials: Any) -> Dict[str, Dict[str, Any]]:
            if impl_name not in _model_map_cache:
                model_list = prov_impl.get_model_list(model_type, credentials)
                _model_map_cache[impl_name] = {m["name"]: m for m in model_list if "name" in m}
            return _model_map_cache[impl_name]

        models = []
        for instance in all_instances:
            if not instance.provider_id or not instance.provider:
                continue  # Skip orphaned records without a provider FK

            provider = instance.provider  # Already eager-loaded via selectin
            pname = provider.name
            pdisplay = provider.display_name
            impl_name = provider.template_name or provider.name
            supported_types: List[str] = provider.supported_model_types or []

            if model_type.value not in supported_types:
                continue

            ctx = cred_ctx.get(instance.provider_id, {"decrypted": None, "is_valid": False, "error": "no_credentials"})

            display_name = instance.model_name
            description = ""
            model_found_in_list = True

            prov_impl = _get_factory_provider(impl_name)
            if prov_impl and not prov_impl.is_template:
                provider_credentials = ctx["decrypted"]
                model_map = _get_model_map(impl_name, prov_impl, provider_credentials)
                matched = model_map.get(instance.model_name)
                if matched:
                    display_name = matched.get("display_name", instance.model_name)
                    description = matched.get("description", "")
                else:
                    model_found_in_list = False

            # 统一判断 unavailable_reason
            unavailable_reason: Optional[str] = None
            if ctx["error"] == "no_credentials":
                unavailable_reason = "no_credentials"
            elif not ctx["is_valid"]:
                unavailable_reason = "invalid_credentials"
            elif not model_found_in_list:
                unavailable_reason = "model_not_found"

            entry: Dict[str, Any] = {
                "instance_id": str(instance.id),
                "provider_name": pname,
                "provider_display_name": pdisplay,
                "name": instance.model_name,
                "display_name": display_name,
                "description": description,
                "is_available": ctx["is_valid"] and unavailable_reason is None,
                "model_parameters": instance.model_parameters or {},
            }
            if unavailable_reason:
                entry["unavailable_reason"] = unavailable_reason

            models.append(entry)
        return models

    async def get_overview(self) -> Dict[str, Any]:
        """返回全局模型概览：Provider 健康摘要、最近凭证失败。"""
        all_providers = await self.provider_repo.find()
        all_instances = await self.repo.list_all()

        # Build cred_ctx keyed by provider_id
        provider_ids = {p.id for p in all_providers}
        cred_ctx = await self._build_provider_credentials_context(provider_ids)

        healthy = 0
        unhealthy = 0
        unconfigured = 0
        recent_failure: Optional[Dict[str, Any]] = None

        for p in all_providers:
            ctx = cred_ctx.get(p.id, {"is_valid": False, "error": "no_credentials"})
            if ctx["error"] == "no_credentials":
                unconfigured += 1
            elif ctx["is_valid"]:
                healthy += 1
            else:
                unhealthy += 1
                if recent_failure is None:
                    recent_failure = {
                        "provider_name": p.name,
                        "provider_display_name": p.display_name or p.name,
                        "error": ctx["error"] or "unknown error",
                        "failed_at": None,
                    }

        total_models = len(all_instances)
        available_models = 0
        for instance in all_instances:
            if instance.provider_id is not None:
                ctx = cred_ctx.get(instance.provider_id, {"is_valid": False})
                if ctx["is_valid"]:
                    available_models += 1

        return {
            "total_providers": len(all_providers),
            "healthy_providers": healthy,
            "unhealthy_providers": unhealthy,
            "unconfigured_providers": unconfigured,
            "total_models": total_models,
            "available_models": available_models,
            "recent_credential_failure": recent_failure,
        }

    async def update_model_instance(
        self,
        instance_id: uuid.UUID,
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """更新模型实例参数。"""
        instance = await self.repo.get(instance_id)
        if not instance:
            raise NotFoundException(f"模型实例不存在: {instance_id}")

        updates: Dict[str, Any] = {}
        if model_parameters is not None:
            updates["model_parameters"] = model_parameters

        if updates:
            await self.repo.update(instance_id, updates)

        await self.commit()
        await self.db.refresh(instance)

        pname = instance.resolved_provider_name

        return {
            "id": str(instance.id),
            "provider_name": pname,
            "model_name": instance.model_name,
            "model_type": ModelType.CHAT.value,
            "model_parameters": instance.model_parameters or {},
        }

    async def create_model_instance_config(
        self,
        user_id: str,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建模型实例配置（全局）。"""
        provider = await self.provider_repo.get_by_name(provider_name)

        instance = await self.repo.create(
            {
                "user_id": user_id,
                "workspace_id": None,
                "provider_id": provider.id if provider else None,
                "model_name": model_name,
                "model_parameters": model_parameters or {},
            }
        )

        await self.commit()

        return {
            "id": str(instance.id),
            "provider_name": provider_name,
            "model_name": model_name,
            "model_type": ModelType.CHAT.value,
            "model_parameters": instance.model_parameters,
        }

    async def get_model_instance(
        self,
        user_id: str,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Any:
        """获取模型实例（LangChain 模型对象）。需要显式传入 provider_name 和 model_name。"""
        implementation_name: Optional[str] = None
        model_parameters: Dict[str, Any] = {}
        if not provider_name or not model_name:
            raise BadRequestException("必须指定 provider_name 和 model_name")

        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            _raise_model_error(PROVIDER_NOT_FOUND, f'Provider "{provider_name}" is not registered.', model_name=model_name, provider_name=provider_name)

        instance = await self.repo.get_best_instance(
            model_name=model_name,
            provider_id=provider.id,
        )

        if not instance:
            _raise_model_error(MODEL_NOT_FOUND, f'Model "{model_name}" is not registered.', model_name=model_name, provider_name=provider_name)

        implementation_name = instance.resolved_implementation_name
        provider_name = instance.resolved_provider_name
        model_parameters = instance.model_parameters or {}

        model_type = ModelType.CHAT

        assert provider_name is not None and model_name is not None
        assert implementation_name is not None

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)

        if not credentials:
            _raise_model_error(MODEL_NO_CREDENTIALS, f'No valid API key for provider "{provider_name}".', model_name=model_name, provider_name=provider_name)

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
            pname = i.provider.name if i.provider else ""
            pdisplay = i.provider.display_name if i.provider else ""
            out.append(
                {
                    "id": str(i.id),
                    "provider_name": pname,
                    "provider_display_name": pdisplay,
                    "model_name": i.model_name,
                    "model_parameters": i.model_parameters or {},
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
            _raise_model_error(MODEL_NOT_FOUND, f'Model "{model_name}" is not registered.', model_name=model_name, available=available_model_names)

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name
        logger.debug(
            f"[ModelService.get_runtime_model_by_name] Found model instance | "
            f"model_name={instance.model_name} | provider={provider_name}"
        )

        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)

        if not credentials:
            _raise_model_error(MODEL_NO_CREDENTIALS, f'No valid API key for provider "{provider_name}".', model_name=model_name, provider_name=provider_name)

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
            _raise_model_error(MODEL_NOT_FOUND, f'Model "{model_name}" is not registered.', model_name=model_name)

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name
        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)

        if not credentials:
            _raise_model_error(MODEL_NO_CREDENTIALS, f'No valid API key for provider "{provider_name}".', model_name=model_name, provider_name=provider_name)

        model = create_model_instance(
            implementation_name,
            model_name,
            model_type,
            credentials,
            instance.model_parameters or {},
        )

        start_time = time.monotonic()
        try:
            response = await model.ainvoke(input_text)
            total_time_ms = round((time.monotonic() - start_time) * 1000, 1)

            content = response.content if hasattr(response, "content") else str(response)
            if isinstance(content, list):
                content = " ".join(str(item) for item in content)
            else:
                content = str(content)

            await self.usage_service.log_usage(
                provider_name=provider_name,
                model_name=model_name,
                input_tokens=max(1, len(input_text) // 4),
                output_tokens=max(1, len(content) // 4),
                total_time_ms=total_time_ms,
                status="success",
                user_id=user_id,
                source="playground",
            )
            return content
        except Exception as e:
            total_time_ms = round((time.monotonic() - start_time) * 1000, 1)
            await self.usage_service.log_usage(
                provider_name=provider_name,
                model_name=model_name,
                total_time_ms=total_time_ms,
                status="error",
                error_message=str(e)[:2000],
                user_id=user_id,
                source="playground",
            )
            raise

    async def test_output_stream(
        self,
        user_id: str,
        model_name: str,
        input_text: str,
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式测试模型输出，yield SSE 格式事件。
        事件类型：token, metrics, error, done
        """
        instance = await self.repo.get_by_name(model_name)
        if not instance:
            err_data = {"error_code": MODEL_NOT_FOUND, "message": f"Model \"{model_name}\" is not registered.", "params": {"model": model_name or ""}}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
            return

        provider_name = instance.resolved_provider_name
        implementation_name = instance.resolved_implementation_name
        model_type = ModelType.CHAT

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)

        if not credentials:
            err_data = {"error_code": MODEL_NO_CREDENTIALS, "message": f"No valid API key for provider \"{provider_name}\".", "params": {"model": model_name or "", "provider": provider_name or ""}}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
            return

        effective_params = {**(instance.model_parameters or {})}
        if model_parameters:
            effective_params.update(model_parameters)

        try:
            model = create_model_instance(
                implementation_name,
                model_name,
                model_type,
                credentials,
                effective_params,
            )
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': f'创建模型实例失败: {str(e)}'})}\n\n"
            return

        start_time = time.monotonic()
        first_token_time = None
        output_tokens = 0

        try:
            async for chunk in model.astream(input_text):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if isinstance(token, list):
                    token = "".join(str(t) for t in token)
                if not token:
                    continue

                if first_token_time is None:
                    first_token_time = time.monotonic()

                output_tokens += 1
                yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"

            total_time = time.monotonic() - start_time
            ttft = (first_token_time - start_time) if first_token_time else total_time
            input_tokens_est = max(1, len(input_text) // 4)

            metrics = {
                "ttft_ms": round(ttft * 1000, 1),
                "total_time_ms": round(total_time * 1000, 1),
                "input_tokens": input_tokens_est,
                "output_tokens": output_tokens,
                "tokens_per_second": round(output_tokens / total_time, 1) if total_time > 0 else 0,
            }
            await self.usage_service.log_usage(
                provider_name=provider_name,
                model_name=model_name,
                input_tokens=input_tokens_est,
                output_tokens=output_tokens,
                total_time_ms=round(total_time * 1000, 1),
                ttft_ms=round(ttft * 1000, 1),
                status="success",
                user_id=user_id,
                source="playground",
            )
            yield f"event: metrics\ndata: {json.dumps(metrics)}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

        except Exception as e:
            total_time = time.monotonic() - start_time
            await self.usage_service.log_usage(
                provider_name=provider_name,
                model_name=model_name,
                total_time_ms=round(total_time * 1000, 1),
                status="error",
                error_message=str(e)[:2000],
                user_id=user_id,
                source="playground",
            )
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
