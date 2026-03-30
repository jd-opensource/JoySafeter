# 模型管理模块全面重构设计

## 概述

对 settings/models 模型管理模块进行前后端全面重构，核心目标：

- 页面布局从纵向卡片列表改为左右分栏 Master-Detail
- 新增模型测试 Playground（流式输出 + 性能指标）
- 新增 Provider 默认参数 + 模型级覆盖的参数配置体系
- 新增凭证健康状态、模型可用性实时状态的直观展示
- 新增使用量统计系统（采集、聚合、趋势图表）

### 新增前端依赖

- `recharts` — 使用量统计趋势图表（当前 package.json 中无图表库）

## 1. 页面整体布局

### 左侧面板（~280px 固定宽度）

- 顶部：搜索框 + "添加模型"按钮
- Provider 分组列表，按类型分组（系统内置 / 自定义）
- 每个 Provider 项显示：图标、名称、凭证状态指示灯（绿/红/灰）、模型数量 badge
- 点击 Provider 项选中，右侧展示详情
- 当前选中项高亮

### 右侧详情面板（flex-1 自适应）

- 顶部：Provider 名称 + 图标 + 操作按钮（编辑凭证、删除 Provider）
- 内容区域用 Tab 切换三个视图：
  - **模型列表** — 该 Provider 下所有模型实例，含状态、默认标记、参数概览
  - **Playground** — 模型测试交互区
  - **统计** — 使用量数据与趋势图

### 未选中状态

右侧显示全局概览卡片（总 Provider 数、总模型数、默认模型信息、凭证健康摘要）

### 数据流

左侧列表复用现有 `useModelProviders` + `useModelCredentials`，右侧详情按选中的 Provider 加载对应数据。

注意：当前 `useModelProviders` 返回的 `model_count` 来自 factory 预定义模型列表，自定义 Provider 的 `model_count` 为 0。需要修改后端 `get_all_providers` 和 `get_provider`，将 `model_count` 改为从 `model_instance` 表中按 provider 统计实际实例数量。

## 2. 模型列表与参数配置

### 模型列表 Tab

选中 Provider 后，右侧默认展示该 Provider 下的模型实例列表，每行显示：

- 模型名称 + 显示名称
- 可用性状态标签（可用 / 不可用）
- 默认模型标记（星标，点击可切换）
- 参数摘要（如 `temperature: 0.7, max_tokens: 2000`，折叠显示）
- 操作：编辑参数、测试（跳转 Playground 并预选该模型）、删除

### 参数配置交互

采用 Provider 默认 + 模型覆盖的两层模式：

- **Provider 级别**：在 Provider 详情顶部区域可设置默认参数（temperature、max_tokens、top_p、frequency_penalty、presence_penalty、timeout、max_retries）
- **模型级别**：点击模型行的"编辑参数"，弹出侧抽屉（Drawer），展示参数表单。每个字段旁有"使用 Provider 默认"开关，关闭后可自定义值
- 参数表单根据后端 `get_config_schema()` 动态渲染，不同 Provider 可能有不同的参数集

### 后端改动

- 移除 `GET /v1/model-providers/{name}/config-schema` — 现有 `GET /v1/model-providers/{name}` 已返回 `config_schemas`，前端直接从 provider 详情中提取即可，无需单独端点
- 新增 `PATCH /v1/models/instances/{id}` — 更新模型实例参数
- 新增 `PATCH /v1/model-providers/{name}/defaults` — 更新 Provider 级默认参数
- Provider 表新增 `default_parameters` 字段（JSON），存储 Provider 级默认参数

#### `PATCH /v1/models/instances/{id}` 请求/响应定义

```python
class ModelInstanceUpdate(BaseModel):
    """更新模型实例请求"""
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="模型参数覆盖值（仅包含用户显式设置的字段）")
    is_default: Optional[bool] = Field(default=None, description="是否为默认模型")

# 响应复用现有格式：
# { id, provider_name, model_name, model_type, model_parameters, is_default }
```

#### `PATCH /v1/model-providers/{name}/defaults` 请求/响应定义

```python
class ProviderDefaultsUpdate(BaseModel):
    """更新 Provider 默认参数请求"""
    default_parameters: Dict[str, Any] = Field(description="Provider 级默认参数，如 {temperature: 0.7, max_tokens: 2000}")

# 响应：更新后的 provider 完整信息（复用 get_provider 格式）
```

#### 参数合并语义

采用写时合并（write-time merge）：当用户保存模型实例参数时，前端将 Provider 默认值与用户覆盖值合并后提交。`model_parameters` 存储的是最终生效值。

这意味着修改 Provider 默认参数不会自动影响已有模型实例。如果需要批量更新，前端可提供"应用到所有模型"的可选操作（调用批量 PATCH）。

## 3. Playground 模型测试

### 交互设计

Playground Tab 分为上下两个区域：

**上方：输入区**
- 模型选择器（下拉，预选当前 Provider 下的模型，也可切换到其他 Provider 的模型）
- 参数调节面板（右侧折叠面板，可展开调整 temperature、max_tokens 等，默认继承该模型的已保存参数）
- Prompt 输入框（多行文本，支持 Shift+Enter 换行）
- 发送按钮 + 清空按钮

**下方：输出区**
- 模型响应内容（流式输出，逐字显示）
- 性能指标卡片组，横向排列：
  - 首 token 延迟（TTFT, Time To First Token）
  - 总响应时间
  - 输入 token 数
  - 输出 token 数
  - 输出速度（tokens/s）
- 历史记录：本次会话内的测试记录列表，可回看对比

### 后端改动

当前 `POST /v1/models/test-output` 只返回 `{ output: string }`，需要增强：

- 改为 SSE 流式响应（`text/event-stream`），支持逐 token 推送
- 请求体增加可选的 `model_parameters` 字段，允许临时覆盖参数（不持久化）
- 响应增加性能指标：

```python
class ModelTestMetrics(BaseModel):
    ttft_ms: float          # 首 token 延迟（毫秒）
    total_time_ms: float    # 总响应时间
    input_tokens: int       # 输入 token 数
    output_tokens: int      # 输出 token 数
    tokens_per_second: float # 输出速度
```

- SSE 事件类型：`token`（逐个 token）、`metrics`（最终性能数据）、`error`（错误信息）、`done`（完成信号）

#### SSE 认证方式

现有项目使用 Bearer token 认证（`apiGet`/`apiPost` 自动附加 Authorization header）。SSE 通过 `fetch` + `ReadableStream` 消费，`fetch` 支持自定义 headers，因此认证方式与普通 API 一致，无需特殊处理。

#### Playground 交互模式

每次测试独立，不支持多轮对话。请求体只接受单个 `input` 字符串，不接受 `messages` 数组。Playground 的定位是快速验证模型可用性和参数效果，不是完整的对话体验（对话体验在 chat 模块中）。

### 前端实现

- 使用 `fetch` + `ReadableStream` 消费 SSE，通过 Authorization header 传递 token
- 性能指标在流结束后渲染，TTFT 在收到第一个 token 时即时显示
- 测试历史存在组件本地 state，不持久化

## 4. 状态展示与凭证健康

### 凭证健康状态

左侧 Provider 列表中，每个 Provider 项右侧显示状态指示灯：
- 绿色圆点：凭证有效
- 红色圆点：凭证验证失败
- 灰色圆点：未配置凭证

右侧详情面板顶部展示凭证详细状态卡片：
- 状态标签（Valid / Invalid / Not Configured）
- 最后验证时间（相对时间，如"5 分钟前"）
- 验证失败时显示错误信息（可展开查看完整错误）
- "重新验证"按钮
- "编辑凭证"按钮

### 模型可用性实时状态

后端 `get_available_models` 响应增加 `unavailable_reason` 字段：
- `no_credentials` / `invalid_credentials` / `model_not_found` / `provider_error`
- 前端根据 reason 展示不同的提示文案和修复引导

前端 `AvailableModel` 类型同步更新：
```typescript
export interface AvailableModel {
  provider_name: string
  provider_display_name: string
  name: string
  display_name: string
  description: string
  is_available: boolean
  is_default?: boolean
  unavailable_reason?: 'no_credentials' | 'invalid_credentials' | 'model_not_found' | 'provider_error'
}
```

### 全局概览（未选中 Provider 时）

- Provider 健康摘要：X 个正常 / Y 个异常 / Z 个未配置
- 默认模型信息卡片（名称、Provider、当前参数）
- 最近一次凭证验证失败的告警（如果有）

### 后端改动

- 新增 `GET /v1/models/overview` — 返回聚合概览数据

#### `GET /v1/models/overview` 响应定义

```python
class ModelsOverview(BaseModel):
    """全局模型概览"""
    total_providers: int                    # 总 Provider 数
    healthy_providers: int                  # 凭证有效的 Provider 数
    unhealthy_providers: int                # 凭证无效的 Provider 数
    unconfigured_providers: int             # 未配置凭证的 Provider 数
    total_models: int                       # 总模型实例数
    available_models: int                   # 可用模型数
    default_model: Optional[DefaultModelInfo]  # 默认模型信息
    recent_credential_failure: Optional[CredentialFailureInfo]  # 最近一次凭证验证失败

class DefaultModelInfo(BaseModel):
    provider_name: str
    provider_display_name: str
    model_name: str
    model_parameters: Dict[str, Any]

class CredentialFailureInfo(BaseModel):
    provider_name: str
    provider_display_name: str
    error: str
    failed_at: Optional[datetime]
```

## 5. 使用量统计系统

### 数据采集

后端新增 `model_usage_log` 表（继承项目 `app.models.base.BaseModel`，自带 UUID 主键 + created_at + updated_at）：

```python
class ModelUsageLog(BaseModel):
    """模型调用日志表"""
    __tablename__ = "model_usage_log"

    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="供应商名称")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="模型名称")
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="模型类型")
    user_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="调用用户")
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0, comment="输入 token 数")
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0, comment="输出 token 数")
    total_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0, comment="总响应时间（毫秒）")
    ttft_ms: Mapped[Optional[float]] = mapped_column(nullable=True, comment="首 token 延迟（毫秒）")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success", comment="success / error")
    error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True, comment="错误信息")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", comment="调用来源：playground / chat / agent")

    __table_args__ = (
        Index("model_usage_log_created_at_idx", "created_at"),
        Index("model_usage_log_provider_model_idx", "provider_name", "model_name"),
        Index("model_usage_log_composite_idx", "created_at", "provider_name", "model_name"),
    )
```

采集点：在 `ModelService` 的模型调用方法（`get_model_instance`、`get_runtime_model_by_name`、`test_output`）返回前，通过 `ModelUsageService.log_usage()` 异步记录。不使用装饰器（避免侵入 `model_resolver.py`），而是在 service 层显式调用。agent 路径的采集通过在 `model_resolver.py` 调用 `ModelService` 时由 `ModelService` 内部记录，不需要修改 `model_resolver.py` 本身。

### 聚合 API

`GET /v1/models/usage/stats`，支持查询参数：
- `provider_name`（可选）
- `model_name`（可选）
- `period`：`24h` / `7d` / `30d`
- `granularity`：`hour` / `day`

返回 summary（总调用、总 token、平均响应时间、错误率）+ timeline（时序数据）+ by_model（按模型分组排行）。

### 前端统计 Tab

- 顶部：时间范围选择器（24h / 7d / 30d）
- 摘要卡片行：总调用次数、总 token 消耗、平均响应时间、错误率
- 趋势折线图（recharts）
- 模型维度表格

### 数据清理

默认保留 90 天明细日志。清理方式：在 `ModelUsageService` 中提供 `cleanup_old_logs(days=90)` 方法，通过 `DELETE FROM model_usage_log WHERE created_at < now() - interval '90 days'` 实现。由后端启动时注册的 FastAPI `on_startup` 事件触发一次清理，之后每 24 小时执行一次（使用 `asyncio.create_task` + `asyncio.sleep` 的简单循环，不引入额外调度框架）。

## 6. 前端组件架构

### 目录结构

```
frontend/app/settings/models/
├── page.tsx                          # Master-Detail 分栏入口
├── components/
│   ├── provider-sidebar/
│   │   ├── provider-sidebar.tsx
│   │   ├── provider-item.tsx
│   │   └── provider-search.tsx
│   ├── detail-panel/
│   │   ├── detail-panel.tsx
│   │   ├── overview-dashboard.tsx
│   │   ├── provider-header.tsx
│   │   ├── model-list-tab/
│   │   │   ├── model-list-tab.tsx
│   │   │   ├── model-row.tsx
│   │   │   └── param-drawer.tsx
│   │   ├── playground-tab/
│   │   │   ├── playground-tab.tsx
│   │   │   ├── prompt-input.tsx
│   │   │   ├── output-display.tsx
│   │   │   └── test-history.tsx
│   │   └── stats-tab/
│   │       ├── stats-tab.tsx
│   │       ├── summary-cards.tsx
│   │       └── usage-chart.tsx
│   ├── credential-dialog.tsx         # 全新重写
│   └── add-custom-model-dialog.tsx   # 全新重写
```

### 状态管理

- 选中的 Provider：`page.tsx` 中的 `useState<string | null>`，通过 props 传递
- 选中的 Tab：`detail-panel.tsx` 中的 `useState`
- Playground 状态：`playground-tab.tsx` 本地 state
- 服务端数据：React Query（`hooks/queries/models.ts` 扩展）

### 新增 hooks

```typescript
useModelsOverview()                       // GET /v1/models/overview
useModelUsageStats(params)                // GET /v1/models/usage/stats
useUpdateModelInstance()                  // PATCH /v1/models/instances/{id}
useUpdateProviderDefaults()              // PATCH /v1/model-providers/{name}/defaults
useTestModelStream()                      // POST /v1/models/test-output (SSE)
```

注意：移除了 `useProviderConfigSchema`，因为 config schema 已包含在现有 `useModelProvider(providerName)` 的响应中（`config_schemas` 字段），无需单独 hook。

### 旧组件处理

`frontend/app/settings/models/components/` 下所有现有组件全部删除重写：
- `provider-added-card.tsx` — 卡片展开模式与新设计不兼容，删除
- `provider-card.tsx` — 网格卡片与左侧列表不兼容，删除
- `credential-dialog.tsx` — 容器和触发方式完全不同，重写
- `add-custom-model-dialog.tsx` — 同上，重写
- `model-list.tsx` / `model-list-item.tsx` — 新设计中模型列表是独立 Tab 且功能更丰富，重写
- `credential-panel.tsx` — 凭证状态移至 Provider header，删除
- `provider-icon.tsx` — 融入新的 `provider-item.tsx`

`frontend/app/workspace/[workspaceId]/[agentId]/services/modelService.ts` — 保留不动。此文件被 `agentService.ts` 引用，属于 workspace 模块而非 settings/models 模块，不在本次重构范围内。（注意：`frontend/services/modelService.ts` 不存在，之前的描述有误。）

## 7. 后端变更清单

### 保留不动（代码质量 OK，与新设计兼容）

- `app/core/model/` 整个目录（factory、providers、base、utils）— Factory 模式干净，provider 注册/获取/创建模型实例的职责清晰
- `app/models/model_instance.py` — 字段结构匹配新设计需求
- `app/models/model_credential.py` — is_valid、last_validated_at、validation_error 正好是凭证健康状态需要的字段
- `app/repositories/model_credential.py` — get_best_valid_credential 优先级逻辑合理，list_all 带 eager load
- `app/services/model_credential_service.py` — 凭证创建/验证/解密/删除/自定义模型一步添加逻辑完整
- `app/api/v1/model_credentials.py` — 接口设计合理，CRUD + validate 完整
- `app/core/graph/deep_agents/model_resolver.py` — 运行时解析，不在本次重构范围

### 小改（加字段，不重写）

- `app/models/model_provider.py` — 加 `default_parameters: JSON` 字段：`Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="Provider 级默认参数")`。迁移脚本中对现有行 backfill 为 ``。

注意：`default_parameters` 和 `model_usage_log` 表应拆为两个独立的 Alembic 迁移脚本，避免耦合。

### 重构（结构性改动，大部分代码重写）

**`app/repositories/model_instance.py`** — 重写
- 问题：list_all() 没有 eager load provider 关系导致 N+1；缺少按 provider 过滤的查询；缺少按 ID 更新的便捷方法；get_best_instance 中 user_id/workspace_id 优先级逻辑是旧多租户遗留
- 改为：加 eager load、按 provider 过滤、按 ID 更新、简化优先级逻辑

**`app/repositories/model_provider.py`** — 重写
- 问题：太薄，只有 get_by_name 和 list_enabled
- 改为：加按 provider_type 过滤、default_parameters 更新、统计 Provider 数量

**`app/services/model_service.py`** — 重写
- 问题：test_output 同步返回（新设计要 SSE 流式 + 性能指标）；get_available_models 缺少 unavailable_reason；缺少 update_model_instance 和 get_overview；create_model_instance_config 不合并 Provider 默认参数；多个方法重复"获取 provider → instance → credentials → 创建模型"模式
- 改为：流式 test_output 生成器、update_model_instance、get_overview、unavailable_reason、参数合并逻辑、提取公共模型解析方法

**`app/services/model_provider_service.py`** — 重写
- 问题：_sync_credentials 废弃方法还留着；sync_all/_sync_models/_ensure_model_instances_for_provider 占大量代码但与新设计无关；缺少 get_config_schema 和 update_provider_defaults；get_all_providers/get_provider 返回结构缺少 default_parameters；大量注释和废弃逻辑
- 改为：清理废弃代码、加 get_config_schema、update_provider_defaults、返回结构增加 default_parameters

**`app/api/v1/models.py`** — 重写
- 问题：test-output 同步返回；缺少 PATCH instances、overview 端点；响应结构缺字段
- 改为：SSE test-output（StreamingResponse）、PATCH instances/{id}、GET overview、响应增加 unavailable_reason

**`app/api/v1/model_providers.py`** — 重写
- 问题：get_current_user 被注释掉（安全问题）；缺少 update defaults 端点
- 改为：恢复所有端点的认证（包括 sync 端点）、加 PATCH defaults

### 新增

- `app/models/model_usage_log.py` — 使用量日志 ORM
- `app/repositories/model_usage_log.py` — 使用量日志 Repository（含聚合查询）
- `app/services/model_usage_service.py` — 采集装饰器 + 聚合 Service
- `app/api/v1/model_usage.py` — 使用量统计 API
- Alembic 迁移脚本 1 — model_provider.default_parameters 字段（backfill 现有行为 `{}`）
- Alembic 迁移脚本 2 — model_usage_log 表创建（含索引）

## 8. 错误处理与边界情况

### Playground

- SSE 连接失败：错误提示卡片 + 重试按钮
- 流式输出中断：保留已接收内容，底部追加错误提示
- 模型调用超时：60s 超时，中断连接，显示超时提示
- 凭证无效时：模型选择器中不可用模型置灰不可选，tooltip 显示原因

### 参数配置

- Provider 默认参数为空：模型参数表单中"使用 Provider 默认"开关仍然显示，但开关打开时字段值显示为 schema 中定义的 `default` 值（如 temperature 的 schema default 为 1.0），placeholder 标注"schema 默认值"。如果 schema 也没有 default，则显示为空并标注"未设置"
- 参数 schema 缺失（Provider 未实现 `get_config_schema` 返回 None）：参数编辑入口隐藏，模型行不显示参数摘要
- 参数值越界：前端即时校验 + 后端二次校验

### 使用量统计

- 无数据：空状态插图 + 提示文案
- 数据量大：联合索引（created_at + provider_name + model_name），图表限制 720 数据点
- 采集失败：try/catch 包裹，只记 warning，不影响主流程

### 左侧面板

- Provider 数量为 0：空状态 + 添加引导
- 搜索无结果：提示文案
- 选中的 Provider 被删除：自动取消选中，回到全局概览

### 凭证状态

- 验证中：蓝色脉冲动画
- 验证完成：自动刷新状态灯
- 不做自动过期检测，依赖手动验证或 Playground 测试发现

## 9. 测试策略

### 前端（Vitest + Testing Library）

- `provider-sidebar` — 列表渲染、搜索过滤、选中切换、状态灯
- `detail-panel` — Tab 切换、未选中概览
- `model-list-tab` — 模型行渲染、默认模型、参数抽屉
- `param-drawer` — schema 动态表单、默认值继承、覆盖开关
- `playground-tab` — 模型选择、发送、流式输出、性能指标、错误状态
- `stats-tab` — 空状态、摘要卡片、时间范围切换
- `credential-dialog` — schema 表单、提交验证、错误提示
- SSE 测试：mock fetch + ReadableStream

### 后端（Pytest + httpx AsyncClient）

- `test_models_api.py` — SSE 流式、PATCH instances、overview、unavailable_reason
- `test_model_usage_api.py` — 统计查询、过滤、空数据
- `test_model_providers_api.py` — update defaults、404
- `test_model_usage_service.py` — 日志采集、聚合计算
- `test_model_service.py` — update_model_instance、流式 test_output、参数合并

### 不测的

- 现有不变的代码不新增测试
- 图表渲染细节不测，只测数据传入
