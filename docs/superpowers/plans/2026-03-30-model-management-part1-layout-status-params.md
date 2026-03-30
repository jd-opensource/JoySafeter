# 模型管理重构 Part 1：布局 + 状态 + 参数配置

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模型管理页面从纵向卡片列表重构为 Master-Detail 分栏布局，增加凭证健康状态展示、全局概览、模型参数配置（Provider 默认 + 模型覆盖）。

**Architecture:** 前端全部重写 settings/models 页面及组件，后端重构 repositories/services/API 层以支持参数配置、概览聚合、unavailable_reason。保留 core/model 层和 credential service 不动。

**Tech Stack:** Next.js 16 / React 19 / TypeScript / Tailwind / Radix UI (Tabs, Sheet) / React Query / FastAPI / SQLAlchemy async / Alembic

**Spec:** `docs/superpowers/specs/2026-03-30-model-management-refactor-design.md`

**子计划说明：** 本计划是 3 个子计划中的第 1 个。Part 2 = Playground，Part 3 = 使用量统计。

---

## File Structure

### 后端新增/修改

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `backend/app/models/model_provider.py` | 加 `default_parameters` 字段 |
| Create | `backend/alembic/versions/20260330_000000_add_provider_default_parameters.py` | 迁移脚本 |
| Rewrite | `backend/app/repositories/model_instance.py` | eager load、按 provider 过滤、简化优先级 |
| Rewrite | `backend/app/repositories/model_provider.py` | 加过滤、统计、默认参数更新 |
| Rewrite | `backend/app/services/model_provider_service.py` | 清理废弃代码、加 update_defaults、返回 default_parameters |
| Rewrite | `backend/app/services/model_service.py` | 加 update_instance、get_overview、unavailable_reason |
| Rewrite | `backend/app/api/v1/model_providers.py` | 恢复认证、加 PATCH defaults |
| Rewrite | `backend/app/api/v1/models.py` | 加 PATCH instances/{id}、GET overview |

### 前端新增/修改

| 操作 | 文件 | 职责 |
|------|------|------|
| Delete | `frontend/app/settings/models/components/*.tsx` (8 files) | 旧组件全部删除 |
| Rewrite | `frontend/app/settings/models/page.tsx` | Master-Detail 分栏入口 |
| Create | `frontend/app/settings/models/components/provider-sidebar/provider-sidebar.tsx` | 左侧面板容器 |
| Create | `frontend/app/settings/models/components/provider-sidebar/provider-item.tsx` | Provider 行 |
| Create | `frontend/app/settings/models/components/provider-sidebar/provider-search.tsx` | 搜索框 |
| Create | `frontend/app/settings/models/components/detail-panel/detail-panel.tsx` | 右侧面板 + Tab |
| Create | `frontend/app/settings/models/components/detail-panel/overview-dashboard.tsx` | 全局概览 |
| Create | `frontend/app/settings/models/components/detail-panel/provider-header.tsx` | Provider 头部 + 凭证状态 |
| Create | `frontend/app/settings/models/components/detail-panel/model-list-tab/model-list-tab.tsx` | 模型列表 Tab |
| Create | `frontend/app/settings/models/components/detail-panel/model-list-tab/model-row.tsx` | 模型行 |
| Create | `frontend/app/settings/models/components/detail-panel/model-list-tab/param-drawer.tsx` | 参数编辑抽屉 |
| Create | `frontend/app/settings/models/components/credential-dialog.tsx` | 凭证编辑弹窗（重写） |
| Create | `frontend/app/settings/models/components/add-custom-model-dialog.tsx` | 添加自定义模型弹窗（重写） |
| Modify | `frontend/hooks/queries/models.ts` | 新增 hooks |
| Modify | `frontend/types/models.ts` | 新增类型 |

### 测试文件

| 文件 | 覆盖 |
|------|------|
| `backend/tests/test_model_providers_api.py` | PATCH defaults、认证恢复 |
| `backend/tests/test_models_api.py` | PATCH instances、GET overview、unavailable_reason |
| `frontend/app/settings/models/__tests__/provider-sidebar.test.tsx` | 列表渲染、搜索、选中 |
| `frontend/app/settings/models/__tests__/detail-panel.test.tsx` | Tab 切换、概览 |
| `frontend/app/settings/models/__tests__/model-list-tab.test.tsx` | 模型行、默认模型、参数抽屉 |

---

## Task 1: Alembic 迁移 — model_provider 加 default_parameters 字段

**Files:**
- Modify: `backend/app/models/model_provider.py`
- Create: `backend/alembic/versions/20260330_000000_add_provider_default_parameters.py`

- [ ] **Step 1: 修改 ORM 模型**

在 `backend/app/models/model_provider.py` 的 `is_enabled` 字段后加：

```python
# Provider 级默认参数
default_parameters: Mapped[dict] = mapped_column(
    JSON, nullable=False, default=dict, server_default="{}", comment="Provider 级默认参数"
)
```

- [ ] **Step 2: 创建迁移脚本**

创建 `backend/alembic/versions/20260330_000000_add_provider_default_parameters.py`，down_revision 指向当前最新 `add_agent_name_column`。

- [ ] **Step 3: 运行迁移验证**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/model_provider.py backend/alembic/versions/20260330_000000_add_provider_default_parameters.py
git commit -m "feat: add default_parameters field to model_provider"
```

---

## Task 2: 重写 model_instance repository

**Files:**
- Rewrite: `backend/app/repositories/model_instance.py`

- [ ] **Step 1: 重写 repository**

关键改动：
- `list_all()` 加 `selectinload(ModelInstance.provider)` 解决 N+1
- `get_best_instance()` 加 `selectinload`，简化优先级（全局模式，去掉 user_id 优先级）
- 新增 `list_by_provider(provider_id, provider_name)` 按 provider 过滤
- 新增 `count_by_provider(provider_id, provider_name)` 统计数量

完整代码见 spec 中 repository 重写部分。所有 select 查询统一加 `options(selectinload(ModelInstance.provider))`。

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories/model_instance.py
git commit -m "refactor: rewrite model_instance repo with eager load and provider filtering"
```

---

## Task 3: 重写 model_provider repository

**Files:**
- Rewrite: `backend/app/repositories/model_provider.py`

- [ ] **Step 1: 重写 repository**

保留 `get_by_name`、`list_enabled`，新增：
- `list_by_type(provider_type: str)` 按类型过滤
- `count_all()` 统计总数
- `update_default_parameters(name, default_parameters)` 更新默认参数

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories/model_provider.py
git commit -m "refactor: rewrite model_provider repo with type filtering and defaults"
```

---

## Task 4: 重写 model_provider_service

**Files:**
- Rewrite: `backend/app/services/model_provider_service.py`

- [ ] **Step 1: 重写 service**

关键改动：
- 删除 `_sync_credentials` 废弃方法
- `get_all_providers` 和 `get_provider` 返回结构增加 `default_parameters` 字段
- `get_all_providers` 中 `model_count` 改为从 `instance_repo.count_by_provider` 获取实际数量
- 新增 `update_provider_defaults(provider_name, default_parameters)` 方法
- 保留 `sync_all`、`sync_providers_from_factory`、`_ensure_model_instances_for_provider`、`_sync_models`、`delete_provider`（这些是功能性代码，不是废弃代码）

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/model_provider_service.py
git commit -m "refactor: rewrite model_provider_service with defaults and cleanup"
```

---

## Task 5: 重写 model_service — update_instance + get_overview + unavailable_reason

**Files:**
- Rewrite: `backend/app/services/model_service.py`

- [ ] **Step 1: 重写 service**

关键改动：
- `get_available_models` 增加 `unavailable_reason` 逻辑：
  - 无凭证 → `no_credentials`
  - 凭证无效 → `invalid_credentials`（需要额外查 credential.is_valid）
  - 模型不在 provider model_list 中 → `model_not_found`
- 新增 `update_model_instance(instance_id, model_parameters, is_default)` 方法
- 新增 `get_overview()` 方法，返回 Provider 健康摘要、默认模型信息、最近凭证失败
- 提取公共方法 `_resolve_model(provider_name, model_name, user_id)` 减少重复代码
- 保留 `test_output`（Part 2 会改为流式，本阶段保持同步）
- 保留 `get_model_instance`、`get_runtime_model_by_name`、`create_model_instance_config`、`list_model_instances`、`update_model_instance_default`

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/model_service.py
git commit -m "refactor: rewrite model_service with overview, update_instance, unavailable_reason"
```

---

## Task 6: 重写 model_providers API

**Files:**
- Rewrite: `backend/app/api/v1/model_providers.py`
- Test: `backend/tests/test_model_providers_api.py`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_model_providers_api.py`，测试：
- `PATCH /v1/model-providers/{name}/defaults` 正常更新
- `PATCH /v1/model-providers/{name}/defaults` 不存在的 provider 返回 404
- 所有端点恢复认证（无 token 返回 401）

- [ ] **Step 2: 重写 API**

关键改动：
- 所有端点恢复 `current_user: User = Depends(get_current_user)`
- 新增 `PATCH /{provider_name}/defaults` 端点，请求体 `{ default_parameters: {} }`
- 保留 `GET /`、`GET /{name}`、`POST /sync`、`DELETE /{name}`

- [ ] **Step 3: 运行测试**

Run: `cd backend && python -m pytest tests/test_model_providers_api.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/model_providers.py backend/tests/test_model_providers_api.py
git commit -m "refactor: rewrite model_providers API with auth and defaults endpoint"
```

---

## Task 7: 重写 models API

**Files:**
- Rewrite: `backend/app/api/v1/models.py`
- Test: `backend/tests/test_models_api.py`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_models_api.py`，测试：
- `PATCH /v1/models/instances/{id}` 更新参数
- `PATCH /v1/models/instances/{id}` 不存在返回 404
- `GET /v1/models/overview` 返回正确结构
- `GET /v1/models` 响应包含 `unavailable_reason`

- [ ] **Step 2: 重写 API**

关键改动：
- 新增 `PATCH /instances/{id}` 端点，请求体 `ModelInstanceUpdate(model_parameters, is_default)`
- 新增 `GET /overview` 端点
- `GET /` 响应增加 `unavailable_reason` 字段
- 保留 `POST /instances`、`GET /instances`、`POST /test-output`、`PATCH /instances/default`

- [ ] **Step 3: 运行测试**

Run: `cd backend && python -m pytest tests/test_models_api.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/models.py backend/tests/test_models_api.py
git commit -m "refactor: rewrite models API with PATCH instance, overview, unavailable_reason"
```

---

## Task 8: 前端类型和 hooks 扩展

**Files:**
- Modify: `frontend/types/models.ts`
- Modify: `frontend/hooks/queries/models.ts`

- [ ] **Step 1: 扩展类型**

在 `frontend/types/models.ts` 中新增：

```typescript
// ==================== Provider Defaults ====================

export interface UpdateProviderDefaultsRequest {
  default_parameters: Record<string, unknown>
}

// ==================== Update Model Instance ====================

export interface UpdateModelInstanceRequest {
  model_parameters?: Record<string, unknown>
  is_default?: boolean
}

// ==================== Overview ====================

export interface DefaultModelInfo {
  provider_name: string
  provider_display_name: string
  model_name: string
  model_parameters: Record<string, unknown>
}

export interface CredentialFailureInfo {
  provider_name: string
  provider_display_name: string
  error: string
  failed_at?: string
}

export interface ModelsOverview {
  total_providers: number
  healthy_providers: number
  unhealthy_providers: number
  unconfigured_providers: number
  total_models: number
  available_models: number
  default_model?: DefaultModelInfo
  recent_credential_failure?: CredentialFailureInfo
}
```

在 `AvailableModel` 中增加：
```typescript
unavailable_reason?: 'no_credentials' | 'invalid_credentials' | 'model_not_found' | 'provider_error'
```

在 `ModelProvider` 中增加：
```typescript
default_parameters?: Record<string, unknown>
```

- [ ] **Step 2: 扩展 hooks**

在 `frontend/hooks/queries/models.ts` 中新增：

```typescript
// Query keys 扩展
overview: () => [...modelKeys.all, 'overview'] as const,

// Hooks
export function useModelsOverview() { ... }       // GET models/overview
export function useUpdateModelInstance() { ... }   // PATCH models/instances/{id}
export function useUpdateProviderDefaults() { ... } // PATCH model-providers/{name}/defaults
```

- [ ] **Step 3: Commit**

```bash
git add frontend/types/models.ts frontend/hooks/queries/models.ts
git commit -m "feat: extend frontend types and hooks for overview, instance update, provider defaults"
```

---

## Task 9: 删除旧前端组件

**Files:**
- Delete: `frontend/app/settings/models/components/provider-added-card.tsx`
- Delete: `frontend/app/settings/models/components/provider-card.tsx`
- Delete: `frontend/app/settings/models/components/credential-dialog.tsx`
- Delete: `frontend/app/settings/models/components/add-custom-model-dialog.tsx`
- Delete: `frontend/app/settings/models/components/model-list.tsx`
- Delete: `frontend/app/settings/models/components/model-list-item.tsx`
- Delete: `frontend/app/settings/models/components/credential-panel.tsx`
- Delete: `frontend/app/settings/models/components/provider-icon.tsx`

- [ ] **Step 1: 删除所有旧组件**

```bash
rm frontend/app/settings/models/components/*.tsx
```

- [ ] **Step 2: Commit**

```bash
git add -A frontend/app/settings/models/components/
git commit -m "chore: delete old model settings components for rewrite"
```

---

## Task 10: 创建 provider-sidebar 组件

**Files:**
- Create: `frontend/app/settings/models/components/provider-sidebar/provider-search.tsx`
- Create: `frontend/app/settings/models/components/provider-sidebar/provider-item.tsx`
- Create: `frontend/app/settings/models/components/provider-sidebar/provider-sidebar.tsx`

- [ ] **Step 1: 创建 provider-search.tsx**

简单的搜索输入框组件，接受 `value` 和 `onChange` props。使用 Lucide `Search` 图标 + `Input` 组件。

- [ ] **Step 2: 创建 provider-item.tsx**

单个 Provider 行组件，props：
- `provider: ModelProvider`
- `credential?: ModelCredential`
- `isSelected: boolean`
- `onClick: () => void`
- `modelCount: number`

展示：图标（首字母 fallback）、名称、状态指示灯（绿/红/灰，根据 credential.is_valid）、模型数量 badge。选中时高亮背景。

- [ ] **Step 3: 创建 provider-sidebar.tsx**

左侧面板容器，props：
- `selectedProvider: string | null`
- `onSelectProvider: (name: string | null) => void`

内部使用 `useModelProviders` + `useModelCredentials` + `useModelProvidersByConfig`。顶部搜索框 + "添加模型"按钮，下方按"系统内置"/"自定义"分组渲染 `ProviderItem` 列表。搜索过滤按 display_name 匹配。

- [ ] **Step 4: Commit**

```bash
git add frontend/app/settings/models/components/provider-sidebar/
git commit -m "feat: create provider-sidebar components"
```

---

## Task 11: 创建 detail-panel 骨架 + overview-dashboard

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/detail-panel.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/overview-dashboard.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/provider-header.tsx`

- [ ] **Step 1: 创建 overview-dashboard.tsx**

未选中 Provider 时的全局概览。使用 `useModelsOverview()` hook。展示：
- Provider 健康摘要卡片（正常/异常/未配置数量）
- 默认模型信息卡片
- 最近凭证失败告警（如果有）

- [ ] **Step 2: 创建 provider-header.tsx**

Provider 详情顶部，props：
- `provider: ModelProvider`
- `credential?: ModelCredential`

展示：Provider 图标 + 名称 + 凭证状态卡片（状态标签、最后验证时间、错误信息展开、重新验证按钮、编辑凭证按钮）。操作按钮：删除 Provider（仅自定义）。

- [ ] **Step 3: 创建 detail-panel.tsx**

右侧面板容器，props：
- `selectedProvider: string | null`

未选中时渲染 `OverviewDashboard`。选中时渲染 `ProviderHeader` + Radix `Tabs`（模型列表 / Playground / 统计）。Playground 和统计 Tab 暂时显示"Coming Soon"占位。

- [ ] **Step 4: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/
git commit -m "feat: create detail-panel skeleton with overview and provider header"
```

---

## Task 12: 创建 model-list-tab 组件

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/model-list-tab/model-row.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/model-list-tab/param-drawer.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/model-list-tab/model-list-tab.tsx`

- [ ] **Step 1: 创建 model-row.tsx**

单行模型组件，props：
- `model: AvailableModel & { model_parameters?: Record<string, unknown> }`
- `onEditParams: () => void`
- `onSetDefault: () => void`

展示：模型名称、可用性标签（含 unavailable_reason tooltip）、默认星标、参数摘要（折叠）、操作按钮。

- [ ] **Step 2: 创建 param-drawer.tsx**

参数编辑侧抽屉，使用 `Sheet` 组件（side="right"）。props：
- `open: boolean`
- `onOpenChange: (open: boolean) => void`
- `model: ModelInstance`
- `configSchema: Record<string, any> | null`
- `providerDefaults: Record<string, unknown>`

根据 configSchema 动态渲染参数表单。每个字段旁有"使用 Provider 默认"Switch，打开时显示 Provider 默认值（只读），关闭时可编辑。保存时调用 `useUpdateModelInstance`。

- [ ] **Step 3: 创建 model-list-tab.tsx**

模型列表 Tab 容器。使用 `useAvailableModels` + `useModelInstances` 获取数据，按当前选中 Provider 过滤。渲染 `ModelRow` 列表 + `ParamDrawer`。

- [ ] **Step 4: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/model-list-tab/
git commit -m "feat: create model-list-tab with param drawer"
```

---

## Task 13: 重写 credential-dialog 和 add-custom-model-dialog

**Files:**
- Create: `frontend/app/settings/models/components/credential-dialog.tsx`
- Create: `frontend/app/settings/models/components/add-custom-model-dialog.tsx`

- [ ] **Step 1: 重写 credential-dialog.tsx**

从旧版提取 schema 驱动表单逻辑，适配新的触发方式（从 provider-header 中触发）。保持 Dialog 组件，但简化样式与新设计一致。

- [ ] **Step 2: 重写 add-custom-model-dialog.tsx**

从旧版提取表单逻辑，适配新的触发方式（从 provider-sidebar 的"添加模型"按钮触发）。

- [ ] **Step 3: Commit**

```bash
git add frontend/app/settings/models/components/credential-dialog.tsx frontend/app/settings/models/components/add-custom-model-dialog.tsx
git commit -m "feat: rewrite credential and add-custom-model dialogs"
```

---

## Task 14: 重写 page.tsx — Master-Detail 入口

**Files:**
- Rewrite: `frontend/app/settings/models/page.tsx`

- [ ] **Step 1: 重写 page.tsx**

```typescript
'use client'

import { useState } from 'react'
import { ProviderSidebar } from './components/provider-sidebar/provider-sidebar'
import { DetailPanel } from './components/detail-panel/detail-panel'

export default function ModelsPage() {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  return (
    <div className="flex h-full bg-[var(--surface-elevated)]">
      <ProviderSidebar
        selectedProvider={selectedProvider}
        onSelectProvider={setSelectedProvider}
      />
      <DetailPanel selectedProvider={selectedProvider} />
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/settings/models/page.tsx
git commit -m "feat: rewrite models page with Master-Detail layout"
```

---

## Task 15: 前端测试

**Files:**
- Create: `frontend/app/settings/models/__tests__/provider-sidebar.test.tsx`
- Create: `frontend/app/settings/models/__tests__/detail-panel.test.tsx`
- Create: `frontend/app/settings/models/__tests__/model-list-tab.test.tsx`

- [ ] **Step 1: 写 provider-sidebar 测试**

测试：渲染 Provider 列表、搜索过滤、点击选中、状态灯颜色映射（绿/红/灰）。Mock `useModelProviders` 和 `useModelCredentials`。

- [ ] **Step 2: 写 detail-panel 测试**

测试：未选中时显示概览、选中后显示 Tab、Tab 切换。Mock `useModelsOverview`。

- [ ] **Step 3: 写 model-list-tab 测试**

测试：模型行渲染、设置默认模型、打开参数抽屉、参数表单渲染。Mock `useAvailableModels` 和 `useModelInstances`。

- [ ] **Step 4: 运行所有前端测试**

Run: `cd frontend && npx vitest run app/settings/models/__tests__/ --reporter=verbose`

- [ ] **Step 5: Commit**

```bash
git add frontend/app/settings/models/__tests__/
git commit -m "test: add frontend tests for model settings components"
```

---

## Task 16: 集成验证

- [ ] **Step 1: 运行后端全量测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`

- [ ] **Step 2: 运行前端构建检查**

Run: `cd frontend && npx next build`

- [ ] **Step 3: 修复发现的问题（如有）**

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "fix: resolve integration issues from model management refactor part 1"
```
