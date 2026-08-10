# 新建密钥页面交互调整：移除引擎选择器 + Auth Token 收进高级

日期：2026-08-10

## 背景

新建密钥（Secret）对话框的 LLM 页签由共享组件 `LlmSecretConfigurator`
渲染，其中包含两处让用户困惑的交互：

1. **"引擎"选择器**：一个可选下拉框（默认"所有引擎"），仅用于过滤下面的
   提供商/协议列表。用户不清楚它是必填还是可选、有什么用。
2. **API Key 与 Auth Token 同时显示**：Anthropic 提供商的凭据档案
   （`anthropic_standard`）同时展示 `ANTHROPIC_API_KEY` 和
   `ANTHROPIC_AUTH_TOKEN` 两个字段，靠 `required_any_of` 约束二选一，
   但用户不知道该填哪个、为什么有两个。

目标：简化新建密钥的交互——移除引擎选择器，并把偏门的 Auth Token 收进
"高级"折叠区，让常见的官方 API Key 场景只看到一个密钥输入框。

## 现状事实（决定改动范围）

- 引擎选择器只在 `LlmSecretConfigurator` 的 `lockEngine=false` 分支渲染
  （`llm-secret-configurator.tsx:247-268`）。
- 三个调用方：
  - `create-agent-dialog.tsx:446` —— `lockEngine`（选择器隐藏，引擎用于过滤）
  - `quickstart-llm-step.tsx:28` —— `lockEngine`（同上）
  - `create-secret-dialog.tsx:138` —— 唯一 `lockEngine=false`，即本次要改的新建密钥页
- 新建密钥的 `initialEngineId` 来自 URL 深链 `?create=llm&engine=<id>`
  （`secrets/page.tsx:72-79`）。实际代码库中**没有任何链接带 `&engine=`**
  （仅有 `?create=llm` 和 `?create=custom`），所以该参数在此路径上是死代码。
- 组件已内建"显示高级/隐藏高级"机制：`visibleFields` 会按 `field.advanced`
  过滤，`advanced` 字段默认隐藏，点按钮才展开。
- 后端 `test_llm_catalog.py` 使用内联 fixture 目录，不校验真实
  `llm_catalog.yaml` 的 advanced 标志。

## 改动 A：移除新建密钥流程中的"引擎"选择器

由于唯一显示选择器的入口被移除，`lockEngine` prop 随之失去意义，一并删除。

- **`frontend/components/managed/llm/llm-secret-configurator.tsx`**
  - 删除引擎 `<select>` 整块（`:247-268`）。
  - 删除 `lockEngine` prop。
  - `engineId` 由 `useState` 改为派生常量 `const engineId = initialEngineId ?? ''`，
    并移除 `setEngineId` 的使用。锁定引擎的调用方（Agent/Quickstart）继续按
    `initialEngineId` 过滤提供商；新建密钥不传 → 显示全部提供商。
- **`frontend/app/managed/secrets/components/create-secret-dialog.tsx`**
  - 移除 `initialEngineId` prop 及其向配置器的透传。
- **`frontend/app/managed/secrets/page.tsx`**
  - 移除 `initialEngineId` state、`searchParams.get('engine')` 读取、以及传参。
  - 保留 `?create=llm|generic|custom` 处理。
- **`frontend/app/managed/agents/components/create-agent-dialog.tsx`** 和
  **`frontend/app/managed/quickstart/components/quickstart-llm-step.tsx`**
  - 去掉现已成为空操作的 `lockEngine`，保留 `initialEngineId`；行为不变。
- **i18n**：删除未再使用的 key `managed.llm.engine`、`managed.llm.allEngines`、
  `managed.llm.engineFilterHint`（所有语言文件）。
- **测试**：
  - `llm-secret-configurator.test.tsx`：改写依赖引擎选择器的用例
    （用例 1 目前通过切换引擎下拉框验证协议显隐，改成不带引擎、直接切换提供商
    anthropic→openai 来覆盖同一逻辑）。
  - `create-secret-dialog.test.tsx`：移除 `initialEngineId="codex"` 及
    `engine:codex` 断言。

## 改动 B：把 Anthropic 的 Auth Token 收进"高级"区

- **`backend/config/llm_catalog.yaml`**：给 `ANTHROPIC_AUTH_TOKEN` 字段
  （`:39-42`）新增一行 `advanced: true`。
- 前端无需改动：配置器的 `visibleFields`/高级折叠机制会自动把该字段收进
  高级区。改完后 Anthropic 默认可见字段为 API Key + Model，展开高级后可见
  Auth Token + Base URL（网关场景通常需同时配 Base URL 与 Bearer token）。
- `required_any_of: [[ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN]]` 保持不变：
  常见官方场景填可见的 API Key 即可通过校验；走兼容网关的用户展开高级填
  Auth Token。两个字段均非单独 `required`，校验逻辑不受影响。
- 后端测试无需改动（fixture 内联，不断言真实 yaml 的 advanced 标志）。

## 已知取舍

- 改动 B 后，若用户 API Key、Auth Token 均未填且未展开高级，校验提示为
  "请填写以下之一：API Key / Auth Token"，会提及被折叠的 Auth Token。视为
  善意提示（暗示存在高级选项），保持不动。

## 不做的事（YAGNI）

- 不改 Auth Token 的鉴权/运行时行为（`x-api-key` vs `Bearer` 逻辑保持原样）。
- 不重构新建密钥对话框的整体布局或校验反馈。
- 不改动编辑/详情页（`secrets/[secretId]/page.tsx`）。
- 不为其他提供商（OpenAI/DeepSeek）新增或调整字段。
