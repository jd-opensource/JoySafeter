# 模型管理功能重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构模型管理系统，划清 service 职责边界，清理垃圾逻辑，统一 API 语义，前后端对齐。

**Architecture:** provider_service 管 provider 生命周期（含自定义 provider 创建），credential_service 只管认证 CRUD，model_service 管模型实例和运行时。API 层对应调整：自定义 provider 创建移到 provider 端点，credential 端点简化。前端同步更新 hooks/types/组件。

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), TypeScript/React/Next.js/TanStack Query (frontend)

**Spec:** `docs/superpowers/specs/2026-03-31-model-management-refactor-design.md`

---

## File Structure

### Backend — Modified
- `backend/app/services/model_provider_service.py` — 新增 add_custom_provider，简化 get_all_providers/get_provider
- `backend/app/services/model_credential_service.py` — 大幅简化，删除越界方法
- `backend/app/services/model_service.py` — 提取 _resolve_and_create_model，移入缓存方法
- `backend/app/api/v1/model_providers.py` — 新增 POST /custom 端点
- `backend/app/api/v1/model_credentials.py` — 简化 schema，增加 DELETE 校验
- `backend/app/main.py` — 替换 get_current_credentials 调用
- `backend/app/core/model/utils/credential_resolver.py` — 替换 get_current_credentials 调用
- `backend/app/api/v1/conversations.py` — 替换 get_current_credentials 调用

### Frontend — Modified
- `frontend/types/models.ts` — 新增 CreateCustomProviderRequest/Response，简化 CreateCredentialRequest
- `frontend/hooks/queries/models.ts` — 新增 useCreateCustomProvider，简化 useCreateCredential
- `frontend/components/settings/models/add-custom-model-dialog.tsx` — 改用 useCreateCustomProvider
- `frontend/components/settings/models/credential-dialog.tsx` — 增加清除认证按钮
- `frontend/components/settings/models/provider-sidebar/provider-sidebar.tsx` — 防御性过滤 is_template
- `frontend/components/settings/models-page.tsx` — 改用 useModelProvider('custom')

---

### Task 1: 重构 ModelProviderService — 新增 add_custom_provider + 简化查询方法

**Files:**
- Modify: `backend/app/services/model_provider_service.py`

- [ ] **Step 1: 新增 _create_derived_provider 和 add_custom_provider 方法**

在 `ModelProviderService` 类中，在 `delete_provider` 方法之前，添加从 credential_service 移入的方法：

```python
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

async def _get_first_model_name_for_provider(self, provider_id: uuid.UUID) -> Optional[str]:
    """获取 Provider 下第一个模型实例的名称，用于自定义 Provider 凭证验证。"""
    instances = await self.instance_repo.list_by_provider(provider_id=provider_id)
    return instances[0].model_name if instances else None

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
    from app.repositories.model_credential import ModelCredentialRepository

    template = self.factory.get_provider("custom")
    if not template:
        from app.common.exceptions import NotFoundException
        raise NotFoundException("供应商不存在: custom")

    # 验证
    is_valid = False
    validation_error = None
    if validate:
        is_valid, validation_error = await validate_provider_credentials(
            "custom", credentials, model_name=model_name
        )

    # 创建 provider
    new_name = f"custom-{int(time.time())}"
    display = (display_name or model_name).strip() or new_name
    db_provider = await self._create_derived_provider(
        template=template, name=new_name, display_name=display, template_name="custom"
    )

    # 创建凭证
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

    # 创建模型实例
    await self.instance_repo.create(
        {
            "user_id": user_id,
            "workspace_id": None,
            "provider_id": db_provider.id,
            "model_name": model_name,
            "model_parameters": model_parameters or {},
            "is_default": False,
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
```

需要在文件顶部添加 `import uuid` 和 `from typing import Optional`。

- [ ] **Step 2: 简化 get_all_providers — 合并两个分支 + 过滤 is_template**

将 `get_all_providers` 方法替换为：

```python
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

        # 构建 config_schemas
        config_schemas: Dict[str, Any] = {}
        if factory_provider:
            for model_type in factory_provider.get_supported_model_types():
                schema = factory_provider.get_config_schema(model_type)
                if schema:
                    config_schemas[model_type.value] = schema

        provider_data: Dict[str, Any] = {
            "provider_name": db_provider.name,
            "display_name": db_provider.display_name or (factory_provider.display_name if factory_provider else db_provider.name),
            "supported_model_types": db_provider.supported_model_types or (
                [mt.value for mt in factory_provider.get_supported_model_types()] if factory_provider else []
            ),
            "credential_schema": db_provider.credential_schema or (
                factory_provider.get_credential_schema() if factory_provider else {}
            ),
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
            provider_data["icon"] = db_provider.icon
        if db_provider.description:
            provider_data["description"] = db_provider.description

        result.append(provider_data)

    result.sort(key=_provider_sort_key)
    return result
```

- [ ] **Step 3: 简化 get_provider — 两段式逻辑**

将 `get_provider` 方法替换为：

```python
async def get_provider(self, provider_name: str) -> Dict[str, Any] | None:
    """获取单个供应商信息（不过滤模板，允许查询 custom 等模板 provider）"""
    db_provider = await self.repo.get_by_name(provider_name)
    if not db_provider:
        return None

    factory_name = db_provider.template_name or db_provider.name
    factory_provider = self.factory.get_provider(factory_name)
    model_count = await self.instance_repo.count_by_provider(provider_id=db_provider.id)

    config_schemas: Dict[str, Any] = {}
    if factory_provider:
        for model_type in factory_provider.get_supported_model_types():
            schema = factory_provider.get_config_schema(model_type)
            if schema:
                config_schemas[model_type.value] = schema

    provider_info: Dict[str, Any] = {
        "provider_name": db_provider.name,
        "display_name": db_provider.display_name or (factory_provider.display_name if factory_provider else db_provider.name),
        "supported_model_types": db_provider.supported_model_types or (
            [mt.value for mt in factory_provider.get_supported_model_types()] if factory_provider else []
        ),
        "credential_schema": db_provider.credential_schema or (
            factory_provider.get_credential_schema() if factory_provider else {}
        ),
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
        provider_info["icon"] = db_provider.icon
    if db_provider.description:
        provider_info["description"] = db_provider.description

    return provider_info
```

- [ ] **Step 4: 更新 delete_provider — 增加缓存清理**

在 `delete_provider` 方法的 `if needs_new_default:` 分支末尾，增加缓存更新逻辑：

在 `logger.info(f"已自动重新分配默认模型: {new_default.model_name}")` 之后添加：
```python
# 刷新默认模型缓存
try:
    from app.core.settings import set_default_model_config
    from app.core.model.utils import decrypt_credentials
    cred_repo = ModelCredentialRepository(self.db)
    cred = await cred_repo.get_by_provider(new_default.provider_id)
    if cred and cred.is_valid:
        decrypted = decrypt_credentials(cred.credentials)
        params = new_default.model_parameters or {}
        set_default_model_config({
            "model": new_default.model_name,
            "api_key": decrypted.get("api_key", ""),
            "base_url": decrypted.get("base_url"),
            "timeout": params.get("timeout", 30),
        })
except Exception as e:
    logger.warning(f"更新默认模型缓存失败: {e}")
```

在 `if needs_new_default:` 分支的 `else`（没有剩余模型时），添加：
```python
else:
    try:
        from app.core.settings import clear_default_model_config
        clear_default_model_config()
    except Exception:
        pass
```

需要在文件顶部添加 `from app.repositories.model_credential import ModelCredentialRepository`。

- [ ] **Step 5: 验证语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; ast.parse(open('app/services/model_provider_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/model_provider_service.py
git commit -m "refactor: add add_custom_provider to provider_service, simplify get_all_providers/get_provider"
```

---

### Task 2: 重构 ModelCredentialService — 大幅简化，删除越界方法

**Files:**
- Modify: `backend/app/services/model_credential_service.py`

- [ ] **Step 1: 删除越界的内部方法**

删除以下方法（整个方法体）：
- `_get_first_model_name_for_provider`（~L38-41）— 已移到 provider_service
- `_create_derived_provider`（~L43-57）— 已移到 provider_service
- `_add_one_custom_model`（~L176-237）— 已移到 provider_service
- `_ensure_model_instances`（~L383-387）— 不再需要
- `_update_default_model_cache`（~L341-365）— 将移到 model_service
- `_update_default_model_cache_if_needed`（~L366-381）— 将移到 model_service
- `get_current_credentials`（~L327-335）— 是 get_decrypted_credentials 的透传

- [ ] **Step 2: 简化 create_or_update_credential → upsert_credential**

将 `create_or_update_credential` 方法替换为简化版本：

```python
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
        raise NotFoundException(f"供应商不存在: {provider_name}")

    # 验证
    is_valid = False
    validation_error = None
    if validate:
        is_valid, validation_error = await self._validate_for_provider(provider, credentials, provider.id)

    # Upsert 凭证
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
    await ModelProviderService(self.db)._ensure_model_instances_for_provider(provider)

    await self.commit()

    # 如果当前默认模型属于该 provider，刷新缓存
    await self._refresh_cache_if_default(provider.name)

    return {
        "id": str(credential.id),
        "provider_name": provider.name,
        "is_valid": credential.is_valid,
        "last_validated_at": credential.last_validated_at,
        "validation_error": credential.validation_error,
    }
```

- [ ] **Step 3: 添加 _refresh_cache_if_default 辅助方法**

在 `_validate_for_provider` 方法之后添加：

```python
async def _refresh_cache_if_default(self, provider_name: str) -> None:
    """如果当前默认模型属于该 provider，则刷新默认模型缓存。"""
    try:
        from app.core.settings import set_default_model_config
        from app.core.model.utils import decrypt_credentials as _decrypt

        repo = ModelInstanceRepository(self.db)
        default_instance = await repo.get_default()
        if not default_instance or not default_instance.provider:
            return
        if default_instance.provider.name != provider_name:
            return

        creds = await self.get_decrypted_credentials(provider_name)
        if creds:
            params = default_instance.model_parameters or {}
            set_default_model_config({
                "model": default_instance.model_name,
                "api_key": creds.get("api_key", ""),
                "base_url": creds.get("base_url"),
                "timeout": params.get("timeout", 30),
            })
    except Exception as e:
        print(f"Warning: Failed to update default model cache after credential change: {e}")
```

- [ ] **Step 4: 修改 delete_credential — 拒绝自定义 provider + 清除缓存**

将 `delete_credential` 方法替换为：

```python
async def delete_credential(self, credential_id: uuid.UUID) -> None:
    """删除内置 provider 的凭据记录。自定义 provider 的凭据不允许单独删除。"""
    from app.common.exceptions import BadRequestException

    credential = await self.repo.get(credential_id, relations=["provider"])
    if not credential:
        raise NotFoundException("凭据不存在")

    # 自定义 provider 的 credential 不允许单独删除
    if (
        credential.provider
        and credential.provider.provider_type == "custom"
        and not credential.provider.is_template
    ):
        raise BadRequestException(
            f"自定义供应商的凭据不能单独删除，请通过 DELETE /model-providers/{credential.provider.name} 删除整个供应商"
        )

    provider_name = credential.provider.name if credential.provider else None
    provider_id = credential.provider_id

    await self.repo.delete(credential_id)

    # 如果默认模型属于该 provider，清除缓存
    if provider_id:
        try:
            from app.core.settings import clear_default_model_config
            repo = ModelInstanceRepository(self.db)
            default_instance = await repo.get_default()
            if default_instance and default_instance.provider_id == provider_id:
                clear_default_model_config()
        except Exception:
            pass

    await self.commit()
```

- [ ] **Step 5: 清理不再需要的 import**

删除文件顶部不再使用的 import（如果有的话）。确保保留：
- `uuid`, `datetime`, `timezone`
- `Dict, List, Optional` from typing
- `AsyncSession`
- `NotFoundException`
- `validate_provider_credentials`
- `decrypt_credentials`, `encrypt_credentials`
- `ModelCredentialRepository`, `ModelInstanceRepository`, `ModelProviderRepository`
- `BaseService`

删除 `get_factory` 的 import（如果 `_validate_for_provider` 不再需要 factory）。
注意：`_validate_for_provider` 仍然通过 `provider.template_name or provider.name` 调用 `validate_provider_credentials`，不需要 factory。但检查是否有其他地方用到 `self.factory`，如果没有则删除 `__init__` 中的 `self.factory = get_factory()` 和对应 import。

- [ ] **Step 6: 验证语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; ast.parse(open('app/services/model_credential_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/model_credential_service.py
git commit -m "refactor: simplify credential_service — remove cross-cutting methods, add delete guard"
```

---

### Task 3: 重构 ModelService — 提取 _resolve_and_create_model + 移入缓存方法

**Files:**
- Modify: `backend/app/services/model_service.py`

- [ ] **Step 1: 添加 _update_default_model_cache 和 _update_default_model_cache_if_needed**

在 `_build_provider_credentials_context` 方法之后，添加从 credential_service 移入的缓存方法：

```python
async def _update_default_model_cache(
    self,
    provider_name: str,
    model_name: str,
    model_type: str = "chat",
    model_parameters: Optional[Dict[str, Any]] = None,
) -> None:
    """更新默认模型缓存。"""
    try:
        from app.core.settings import set_default_model_config

        credentials = await self.credential_service.get_decrypted_credentials(provider_name)
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
```

- [ ] **Step 2: 添加 _resolve_and_create_model 统一方法**

在 `_update_default_model_cache` 之后添加：

```python
async def _resolve_and_create_model(self, model_name: str, user_id: Optional[str] = None) -> tuple:
    """
    统一 resolve provider → get credential → create model 逻辑。
    返回 (model, provider_name, implementation_name, instance)。
    """
    instance = await self.repo.get_by_name(model_name)
    if not instance:
        raise NotFoundException(f"模型实例不存在: {model_name}")

    provider_name = instance.resolved_provider_name
    implementation_name = instance.resolved_implementation_name
    model_type = ModelType.CHAT

    credentials = await self.credential_service.get_decrypted_credentials(provider_name)
    if not credentials:
        raise NotFoundException(f"未找到模型 {provider_name}/{model_name} 的有效凭据")

    model = create_model_instance(
        implementation_name,
        model_name,
        model_type,
        credentials,
        instance.model_parameters or {},
    )

    return model, provider_name, implementation_name, instance
```

- [ ] **Step 3: 简化 get_runtime_model_by_name**

替换为：

```python
async def get_runtime_model_by_name(self, model_name: str, user_id: Optional[str] = None) -> Any:
    """根据 model_name 获取运行时模型实例（LangChain 模型对象）。"""
    model, _, _, _ = await self._resolve_and_create_model(model_name, user_id)
    return model
```

- [ ] **Step 4: 简化 test_output**

替换为：

```python
async def test_output(self, user_id: str, model_name: str, input_text: str) -> str:
    """测试模型输出"""
    model, provider_name, _, _ = await self._resolve_and_create_model(model_name, user_id)

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
```

- [ ] **Step 5: 简化 test_output_stream**

替换 test_output_stream 方法中获取 instance/credentials/创建 model 的部分。将方法开头到 `try: model = create_model_instance(...)` 替换为：

```python
async def test_output_stream(
    self,
    user_id: str,
    model_name: str,
    input_text: str,
    model_parameters: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """流式测试模型输出，yield SSE 格式事件。"""
    try:
        base_model, provider_name, implementation_name, instance = await self._resolve_and_create_model(model_name, user_id)
    except NotFoundException as e:
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return

    # 如果有临时参数覆盖，重新创建 model
    if model_parameters:
        effective_params = {**(instance.model_parameters or {}), **model_parameters}
        credentials = await self.credential_service.get_decrypted_credentials(provider_name)
        if not credentials:
            yield f"event: error\ndata: {json.dumps({'error': f'未找到有效凭据: {provider_name}/{model_name}'})}\n\n"
            return
        try:
            model = create_model_instance(
                implementation_name, model_name, ModelType.CHAT, credentials, effective_params,
            )
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': f'创建模型实例失败: {str(e)}'})}\n\n"
            return
    else:
        model = base_model

    # 以下 streaming 逻辑保持不变（从 start_time = time.monotonic() 开始）
```

streaming 部分（从 `start_time = time.monotonic()` 到方法结束）保持不变。

- [ ] **Step 6: 替换所有 credential_service._update_default_model_cache 调用**

在 `update_model_instance` 方法中（~L254）：
```python
# 之前
await self.credential_service._update_default_model_cache(...)
# 之后
await self._update_default_model_cache(...)
```

在 `create_model_instance_config` 方法中（~L303）：
```python
# 之前
await self.credential_service._update_default_model_cache(...)
# 之后
await self._update_default_model_cache(...)
```

在 `update_model_instance_default` 方法中（~L347）：
```python
# 之前
await self.credential_service._update_default_model_cache(...)
# 之后
await self._update_default_model_cache(...)
```

- [ ] **Step 7: 替换所有 credential_service.get_current_credentials 调用**

在 `get_model_instance` 方法中（~L414）：
```python
# 之前
credentials = await self.credential_service.get_current_credentials(
    provider_name=provider_name,
    model_type=model_type,
    model_name=model_name,
    user_id=user_id,
)
# 之后
credentials = await self.credential_service.get_decrypted_credentials(provider_name)
```

- [ ] **Step 8: 简化 _build_provider_credentials_context**

删除 global vs user-scoped 优先级判断，简化为直接取第一个匹配的 credential：

```python
async def _build_provider_credentials_context(self, provider_ids: set) -> Dict[Any, Dict[str, Any]]:
    """一次性构建 provider 凭证上下文。Keyed by provider_id。"""
    from app.core.model.utils import decrypt_credentials

    all_credentials = await self.credential_repo.list_all()

    # 按 provider_id 取第一个匹配的 credential
    best_cred_by_id: Dict[Any, Any] = {}
    for c in all_credentials:
        pid = c.provider_id
        if pid is None or pid not in provider_ids:
            continue
        if pid not in best_cred_by_id:
            best_cred_by_id[pid] = c

    result: Dict[Any, Dict[str, Any]] = {}
    for pid in provider_ids:
        cred = best_cred_by_id.get(pid)
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
```

- [ ] **Step 9: 验证语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; ast.parse(open('app/services/model_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/model_service.py
git commit -m "refactor: extract _resolve_and_create_model, move cache methods into model_service"
```

---

### Task 4: 更新周边文件 — main.py, credential_resolver.py, conversations.py

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/model/utils/credential_resolver.py`
- Modify: `backend/app/api/v1/conversations.py`

- [ ] **Step 1: 更新 main.py**

在 `main.py` 的 lifespan 函数中（~L193），替换：

```python
# 之前
credentials = await credential_service.get_current_credentials(
    provider_name=default_provider_name,
    model_type="chat",
    model_name=default_instance.model_name,
)

# 之后
credentials = await credential_service.get_decrypted_credentials(default_provider_name)
```

- [ ] **Step 2: 更新 credential_resolver.py — 第一处调用**

在 `credential_resolver.py` 的 `get_credentials` 方法中（~L68），替换：

```python
# 之前
credentials = await credential_service.get_current_credentials(
    provider_name=provider_name or "",
    model_type=model_type,
    model_name=model_name or "",
    user_id=user_id,
)

# 之后
credentials = await credential_service.get_decrypted_credentials(provider_name or "")
```

- [ ] **Step 3: 更新 credential_resolver.py — 第二处调用**

在同一方法中（~L95），替换：

```python
# 之前
credentials = await credential_service.get_current_credentials(
    provider_name=provider_name or provider_name_from_cred,
    model_type=model_type,
    model_name=model_name or "",
    user_id=user_id,
)

# 之后
credentials = await credential_service.get_decrypted_credentials(provider_name_from_cred)
```

- [ ] **Step 4: 更新 conversations.py — 两处调用**

在 `conversations.py` 中找到两处 `credential_service.get_current_credentials(...)` 调用（~L104, ~L128），分别替换为：

第一处（~L104）：
```python
credentials = await credential_service.get_decrypted_credentials(str(provider_name))
```

第二处（~L128）：
```python
credentials = await credential_service.get_decrypted_credentials(provider_name_from_cred)
```

注意：需要检查 `conversations.py` 中 `provider_name_from_cred` 变量名是否与实际代码一致，可能是 `provider_name` 或其他名称。按实际代码中的变量名替换。

- [ ] **Step 5: 验证三个文件语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; [ast.parse(open(f).read()) for f in ['app/main.py', 'app/core/model/utils/credential_resolver.py', 'app/api/v1/conversations.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/core/model/utils/credential_resolver.py backend/app/api/v1/conversations.py
git commit -m "refactor: replace get_current_credentials with get_decrypted_credentials in peripheral files"
```

---

### Task 5: 重构后端 API 层 — model_providers.py 新增 POST /custom

**Files:**
- Modify: `backend/app/api/v1/model_providers.py`

- [ ] **Step 1: 新增 CustomProviderCreate schema 和 POST /custom 端点**

在 `ProviderDefaultsUpdate` class 之后，添加新的 schema：

```python
class CustomProviderCreate(BaseModel):
    """添加自定义 Provider 请求"""

    model_name: str = Field(description="模型名称", examples=["gpt-4o"])
    credentials: Dict[str, Any] = Field(description="凭据字典（明文）")
    display_name: Optional[str] = Field(default=None, description="自定义显示名称")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="模型参数")
    validate: bool = Field(default=True, description="是否验证凭据")
```

需要在文件顶部添加 `from typing import Optional`。

在 `sync_providers` 端点之前，添加新端点：

```python
@router.post("/custom")
async def add_custom_provider(
    payload: CustomProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加自定义 Provider（一步创建 provider + credential + model_instance）"""
    service = ModelProviderService(db)
    result = await service.add_custom_provider(
        user_id=current_user.id,
        credentials=payload.credentials,
        model_name=payload.model_name,
        display_name=payload.display_name,
        model_parameters=payload.model_parameters,
        validate=payload.validate,
    )
    return success_response(data=result, message="添加自定义供应商成功")
```

注意：`POST /custom` 必须放在 `GET /{provider_name}` 之前，否则 FastAPI 会把 `custom` 当作 path parameter。检查路由顺序，确保 `/custom` 在 `/{provider_name}` 之前注册。

- [ ] **Step 2: 验证语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; ast.parse(open('app/api/v1/model_providers.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/model_providers.py
git commit -m "feat: add POST /model-providers/custom endpoint for custom provider creation"
```

---

### Task 6: 重构后端 API 层 — model_credentials.py 简化 schema + DELETE 校验

**Files:**
- Modify: `backend/app/api/v1/model_credentials.py`

- [ ] **Step 1: 简化 CredentialCreate schema**

将 `CredentialCreate` class 替换为：

```python
class CredentialCreate(BaseModel):
    """创建/更新凭据请求（仅限内置 provider）"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    credentials: Dict[str, Any] = Field(..., description="凭据字典（明文）")
    should_validate: bool = Field(default=True, alias="validate", description="是否验证凭据")
```

删除字段：`provider_display_name`、`model_name`、`model_parameters`。

- [ ] **Step 2: 更新 create_or_update_credential 端点**

将端点处理函数简化为：

```python
@router.post("")
async def create_or_update_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建或更新内置 provider 的凭据"""
    service = ModelCredentialService(db)
    credential = await service.upsert_credential(
        user_id=current_user.id,
        provider_name=payload.provider_name,
        credentials=payload.credentials,
        validate=payload.should_validate,
    )
    return success_response(data=credential, message="创建/更新凭据成功")
```

- [ ] **Step 3: 清理不再需要的 import**

删除 `Optional` 的 import（如果不再使用）。保留 `uuid`, `Dict`, `Any`。

- [ ] **Step 4: 验证语法**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "import ast; ast.parse(open('app/api/v1/model_credentials.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/model_credentials.py
git commit -m "refactor: simplify credential API schema, add delete guard for custom providers"
```

---

### Task 7: 前端重构 — types + hooks

**Files:**
- Modify: `frontend/types/models.ts`
- Modify: `frontend/hooks/queries/models.ts`

- [ ] **Step 1: 更新 types/models.ts — 简化 CreateCredentialRequest**

将 `CreateCredentialRequest` 替换为：

```typescript
export interface CreateCredentialRequest {
  provider_name: string
  credentials: Record<string, any>
  validate?: boolean
}
```

删除 `providerDisplayName`、`model_name`、`model_parameters` 字段。

- [ ] **Step 2: 更新 types/models.ts — 新增 CreateCustomProviderRequest/Response**

在 `CreateCredentialRequest` 之后添加：

```typescript
/**
 * Create custom provider request (one-shot: provider + credential + model instance)
 */
export interface CreateCustomProviderRequest {
  model_name: string
  credentials: Record<string, any>
  display_name?: string
  model_parameters?: Record<string, unknown>
  validate?: boolean
}

/**
 * Create custom provider response
 */
export interface CreateCustomProviderResponse {
  provider_name: string
  display_name: string
  credential_id: string
  is_valid: boolean
  validation_error?: string
}
```

- [ ] **Step 3: 更新 hooks/queries/models.ts — 简化 useCreateCredential**

将 `useCreateCredential` 替换为：

```typescript
export function useCreateCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateCredentialRequest) => {
      const data = await apiPost<ModelCredential>(MODEL_CREDENTIALS_PATH, {
        provider_name: request.provider_name,
        credentials: request.credentials,
        validate: request.validate !== false,
      })
      logger.info(`Created credential for provider: ${request.provider_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: [...modelKeys.all, 'available'] })
    },
  })
}
```

- [ ] **Step 4: 更新 hooks/queries/models.ts — 新增 useCreateCustomProvider**

在 `useCreateCredential` 之后添加：

```typescript
export function useCreateCustomProvider() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateCustomProviderRequest) => {
      const data = await apiPost<CreateCustomProviderResponse>(
        `${MODEL_PROVIDERS_PATH}/custom`,
        request,
      )
      logger.info(`Created custom provider with model: ${request.model_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
      queryClient.invalidateQueries({ queryKey: [...modelKeys.all, 'available'] })
    },
  })
}
```

需要在文件顶部的 import 中添加 `CreateCustomProviderRequest` 和 `CreateCustomProviderResponse`。

- [ ] **Step 5: 更新 hooks/queries/models.ts — 简化 useModelProvidersByConfig**

在 `useModelProvidersByConfig` 中：

1. 从 `ModelProvidersByConfigResult` interface 中删除 `templateProviders` 字段
2. 在 `useMemo` 中删除 `templates` 数组和相关逻辑
3. 简化 provider 分类：只分 configured 和 notConfigured

替换 `useModelProvidersByConfig` 为：

```typescript
export interface ModelProvidersByConfigResult {
  credentialsByProvider: Map<string, ModelCredential>
  configuredProviders: ModelProvider[]
  notConfiguredProviders: ModelProvider[]
  noValidCredential: boolean
}

export function useModelProvidersByConfig(
  providers: ModelProvider[],
  credentials: ModelCredential[],
): ModelProvidersByConfigResult {
  const credentialsByProvider = useMemo(
    () => buildCredentialsByProvider(credentials),
    [credentials],
  )

  const [configuredProviders, notConfiguredProviders] = useMemo(() => {
    const configured: ModelProvider[] = []
    const notConfigured: ModelProvider[] = []

    for (const provider of providers) {
      if (provider.is_template) continue // 过滤模板 provider
      if (credentialsByProvider.has(provider.provider_name)) {
        configured.push(provider)
      } else {
        notConfigured.push(provider)
      }
    }

    const sortProviders = (a: ModelProvider, b: ModelProvider) => {
      if (a.provider_type !== b.provider_type) return a.provider_type === 'custom' ? 1 : -1
      return a.display_name.localeCompare(b.display_name)
    }

    configured.sort(sortProviders)
    notConfigured.sort(sortProviders)

    return [configured, notConfigured]
  }, [providers, credentialsByProvider])

  const noValidCredential =
    configuredProviders.length === 0 ||
    configuredProviders.every((p) => !credentialsByProvider.get(p.provider_name)?.is_valid)

  return {
    credentialsByProvider,
    configuredProviders,
    notConfiguredProviders,
    noValidCredential,
  }
}
```

- [ ] **Step 6: 更新 re-export 列表**

在文件顶部的 `import type` 和 `export type` 中添加 `CreateCustomProviderRequest` 和 `CreateCustomProviderResponse`。

- [ ] **Step 7: Commit**

```bash
git add frontend/types/models.ts frontend/hooks/queries/models.ts
git commit -m "refactor: simplify frontend types/hooks — add useCreateCustomProvider, remove template logic"
```

---

### Task 8: 前端重构 — 组件更新

**Files:**
- Modify: `frontend/components/settings/models/add-custom-model-dialog.tsx`
- Modify: `frontend/components/settings/models/credential-dialog.tsx`
- Modify: `frontend/components/settings/models/provider-sidebar/provider-sidebar.tsx`
- Modify: `frontend/components/settings/models-page.tsx`

- [ ] **Step 1: 更新 add-custom-model-dialog.tsx — 改用 useCreateCustomProvider**

1. 将 import 从 `useCreateCredential` 改为 `useCreateCustomProvider`：
```typescript
import { useCreateCustomProvider } from '@/hooks/queries/models'
```

2. 修改 props interface — 接收 credential_schema 而非整个 provider：
```typescript
interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  credentialSchema?: Record<string, any>
}
```

3. 将 `const createCredential = useCreateCredential()` 改为 `const createCustomProvider = useCreateCustomProvider()`

4. 将 `formFields` 的 useMemo 改为使用 `credentialSchema` prop：
```typescript
const formFields = useMemo(
  () => parseJsonSchema(credentialSchema),
  [credentialSchema],
)
```

5. 将 `handleAdd` 中的 `createCredential.mutateAsync` 调用改为：
```typescript
await createCustomProvider.mutateAsync({
  model_name: modelName.trim(),
  credentials,
  validate: true,
})
```

6. 将模板中所有 `createCredential.isPending` 改为 `createCustomProvider.isPending`

7. 删除 `import type { ModelProvider } from '@/types/models'`（如果不再使用）

- [ ] **Step 2: 更新 credential-dialog.tsx — 增加清除认证按钮**

1. 添加 import：
```typescript
import { useCreateCredential, useValidateCredential, useDeleteCredential } from '@/hooks/queries/models'
```

2. 在组件内添加 `deleteCredential` mutation：
```typescript
const deleteCredential = useDeleteCredential()
```

3. 添加清除认证处理函数（在 `handleValidate` 之后）：
```typescript
const handleClearCredential = async () => {
  if (!existingCredential) return
  try {
    await deleteCredential.mutateAsync(existingCredential.id)
    toast({ title: '凭证已清除' })
    onOpenChange(false)
  } catch (err) {
    toast({
      variant: 'destructive',
      title: '清除凭证失败',
      description: err instanceof Error ? err.message : '请稍后重试',
    })
  }
}
```

4. 在 DialogFooter 中，在"重新验证"按钮旁边添加"清除认证"按钮（只在内置 provider 且有 credential 时显示）：
```tsx
{existingCredential && provider.provider_type !== 'custom' && (
  <Button
    variant="outline"
    onClick={handleClearCredential}
    disabled={deleteCredential.isPending}
    className="mr-auto text-red-600 hover:text-red-700"
  >
    {deleteCredential.isPending ? '清除中...' : '清除认证'}
  </Button>
)}
```

注意：如果已有"重新验证"按钮也在 `mr-auto` 位置，需要把两个按钮包在一个 `div` 里：
```tsx
<div className="mr-auto flex gap-2">
  {existingCredential && (
    <Button
      variant="outline"
      onClick={handleValidate}
      disabled={validating || isDirty}
    >
      {validating ? '验证中...' : '重新验证'}
    </Button>
  )}
  {existingCredential && provider.provider_type !== 'custom' && (
    <Button
      variant="outline"
      onClick={handleClearCredential}
      disabled={deleteCredential.isPending}
      className="text-red-600 hover:text-red-700"
    >
      {deleteCredential.isPending ? '清除中...' : '清除认证'}
    </Button>
  )}
</div>
```

- [ ] **Step 3: 更新 models-page.tsx — 改用 useModelProvider('custom')**

将文件内容替换为：

```typescript
import { useState } from 'react'

import { AddCustomModelDialog } from '@/components/settings/models/add-custom-model-dialog'
import { DetailPanel } from '@/components/settings/models/detail-panel/detail-panel'
import { ProviderSidebar } from '@/components/settings/models/provider-sidebar/provider-sidebar'
import { useModelProvider } from '@/hooks/queries/models'

export function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const { data: customTemplate } = useModelProvider('custom')

  return (
    <div className="flex h-full overflow-hidden">
      <ProviderSidebar
        selectedProvider={selectedProvider}
        onSelectProvider={setSelectedProvider}
        onAddCustomModel={() => setShowAddCustomModel(true)}
      />

      <DetailPanel selectedProvider={selectedProvider} />

      <AddCustomModelDialog
        open={showAddCustomModel}
        onOpenChange={setShowAddCustomModel}
        credentialSchema={customTemplate?.credential_schema}
      />
    </div>
  )
}
```

注意：不再需要 `useModelProviders` import，改为 `useModelProvider`。

- [ ] **Step 4: 检查 provider-sidebar.tsx 是否需要更新**

当前 `provider-sidebar.tsx` 已经在 L34 过滤了 `!p.is_template`：
```typescript
const systemProviders = filtered.filter((p) => p.provider_type !== 'custom' && !p.is_template)
```

由于后端 `get_all_providers` 现在也过滤了 `is_template=True`，前端这个过滤是防御性的，保留即可。不需要修改。

但需要检查是否有引用 `templateProviders` 的地方。如果 `useModelProvidersByConfig` 的返回类型已经删除了 `templateProviders`，而 sidebar 没有使用它，则不需要改动。

- [ ] **Step 5: 检查 app/settings/models/page.tsx 是否需要同步更新**

检查 `frontend/app/settings/models/page.tsx` 是否也有类似 `models-page.tsx` 的逻辑需要同步。如果它只是 import 并渲染 `ModelsPage` 组件，则不需要改动。

- [ ] **Step 6: Commit**

```bash
git add frontend/components/settings/models/add-custom-model-dialog.tsx \
       frontend/components/settings/models/credential-dialog.tsx \
       frontend/components/settings/models-page.tsx
git commit -m "refactor: update frontend components — custom provider dialog, credential clear button, template filtering"
```

---

### Task 9: 端到端验证

- [ ] **Step 1: 后端语法验证**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "
import ast
files = [
    'app/services/model_provider_service.py',
    'app/services/model_credential_service.py',
    'app/services/model_service.py',
    'app/api/v1/model_providers.py',
    'app/api/v1/model_credentials.py',
    'app/main.py',
    'app/core/model/utils/credential_resolver.py',
    'app/api/v1/conversations.py',
]
for f in files:
    ast.parse(open(f).read())
    print(f'  OK: {f}')
print('All files parsed successfully')
"`

Expected: All files OK

- [ ] **Step 2: 后端 import 验证**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "
from app.services.model_provider_service import ModelProviderService
from app.services.model_credential_service import ModelCredentialService
from app.services.model_service import ModelService
print('All service imports OK')
"`

Expected: `All service imports OK`

- [ ] **Step 3: 确认 get_current_credentials 已完全移除**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter && grep -rn "get_current_credentials" backend/app/ --include="*.py"`

Expected: 无输出（或只在注释/文档中出现）

- [ ] **Step 4: 确认 _add_one_custom_model 已从 credential_service 移除**

Run: `grep -n "_add_one_custom_model\|_create_derived_provider\|_ensure_model_instances\|_update_default_model_cache" backend/app/services/model_credential_service.py`

Expected: 无输出（这些方法应该已经从 credential_service 中删除）

- [ ] **Step 5: 前端类型检查**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/frontend && npx tsc --noEmit 2>&1 | head -30`

Expected: 无类型错误（或只有与本次重构无关的已有错误）

- [ ] **Step 6: 运行已有后端测试**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_models_api.py tests/test_model_providers_api.py -v 2>&1 | tail -20`

Expected: 测试通过（可能需要根据 API 变更更新 mock）

- [ ] **Step 7: 最终 Commit（如果有修复）**

如果验证过程中发现问题并修复了，做一个最终 commit：

```bash
git add -A
git commit -m "fix: address issues found during end-to-end verification"
```
