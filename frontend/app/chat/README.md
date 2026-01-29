# Chat Module Architecture

## 概述

Chat 模块采用分层架构设计，实现了清晰的职责分离和良好的扩展性。

## 架构层次

```
┌─────────────────────────────────────┐
│   UI Layer (ChatHome.tsx)          │  纯展示组件，只负责渲染
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   State Layer (useChatSession)     │  统一状态管理
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Business Layer (ModeHandlers)    │  模式处理逻辑
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Service Layer                     │  服务抽象
│   - ChatModeService                 │
│   - GraphResolutionService          │
│   - CopilotRedirectService          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   API Layer                         │  API 调用
└─────────────────────────────────────┘
```

## 核心模块

### 1. 配置层 (Config)

**文件**: `config/modeConfig.ts`

- **职责**: 定义所有模式的配置（唯一数据源）
- **内容**: 模式 ID、翻译 key、图标、类型等
- **原则**: 配置是唯一数据源，避免重复定义

### 2. 处理器层 (Mode Handlers)

**目录**: `services/modeHandlers/`

- **职责**: 实现不同模式的业务逻辑
- **设计模式**: 策略模式（Strategy Pattern）
- **核心接口**: `ModeHandler`

#### 处理器类型

1. **DynamicModeHandler**: 处理 dynamic 类型（直接跳转）
2. **APKVulnerabilityHandler**: 处理 APK 漏洞检测（需要 Graph 创建）
3. **SimpleModeHandler**: 处理简单模式（仅设置模式）
4. **AgentModeHandler**: 处理 Agent 选择模式

#### 工厂模式

**文件**: `handlerFactory.ts`

- 从配置创建处理器，确保配置和处理器的一致性
- 特殊处理器（如 APK）有复杂逻辑，直接返回实例

### 3. 注册机制

**文件**: `registerHandlers.ts`

- 从配置统一注册所有处理器
- 确保配置和处理器一一对应

### 4. 服务层

#### ChatModeService

- 提供模式处理器的查询和管理
- 封装模式相关的业务逻辑

#### GraphResolutionService

- 统一 Graph ID 解析逻辑
- 实现不同策略（Mode、AutoRedirect、AgentSelection）

#### CopilotRedirectService

- 处理自动重定向到 Copilot 的逻辑
- 创建新 Graph 并跳转

### 5. 状态管理

**文件**: `hooks/useChatSession.ts`

- 使用 reducer 统一管理所有聊天相关状态
- 提供清晰的 action 接口

## 数据流

### 模式选择流程

```
用户点击模式卡片
    ↓
ChatHome.handleModeSelect()
    ↓
chatModeService.getHandler(modeId)
    ↓
handler.onSelect(context)
    ↓
更新状态（通过 useChatSession）
```

### 提交流程

```
用户提交
    ↓
ChatHome.handleSubmit()
    ↓
handler.validate() (验证)
    ↓
handler.onSubmit() (处理)
    ↓
graphResolutionService.resolve() (解析 Graph ID)
    ↓
copilotRedirectService.executeRedirect() (如果需要)
    ↓
onStartChat() (调用父组件回调)
```

## 扩展新模式

### 步骤

1. **在 `modeConfig.ts` 中添加配置**
   ```typescript
   {
     id: 'new-mode',
     labelKey: 'chat.newMode',
     descriptionKey: 'chat.newModeDescription',
     icon: SomeIcon,
     type: 'simple', // 或 'dynamic', 'template'
   }
   ```

2. **创建处理器**（如果需要特殊逻辑）
   ```typescript
   // 在相应的 handler 文件中实现
   export const newModeHandler: ModeHandler = {
     metadata: { ... },
     onSelect: async (context) => { ... },
     onSubmit: async (input, files, context) => { ... },
   }
   ```

3. **在 `handlerFactory.ts` 中处理**（如果是特殊处理器）
   ```typescript
   if (config.id === 'new-mode') {
     return newModeHandler
   }
   ```

4. **注册会自动完成**（通过 `registerHandlers.ts`）

## 设计原则

1. **单一数据源**: 配置是唯一数据源，避免重复定义
2. **职责分离**: UI、业务逻辑、服务层清晰分离
3. **扩展性**: 新增模式只需实现接口并配置
4. **一致性**: 通过工厂模式确保配置和处理器一致
5. **可测试性**: 各层可独立测试

## 注意事项

- 配置中的 `label` 和 `description` 使用翻译 key，实际文本通过 `t()` 函数获取
- 特殊处理器（如 APK）的 metadata 中的 label/description 也是翻译 key
- 所有模式必须先在 `modeConfig.ts` 中定义，然后才能注册处理器
- 使用 `modeConfigs` 作为 UI 渲染的数据源，确保一致性
