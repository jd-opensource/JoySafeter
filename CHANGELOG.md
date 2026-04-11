# Changelog

All notable changes to JoySafeter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## v0.3.2 — 2026-04-11



### Features

- 添加版本信息展示功能，并接入 bump-version.sh 版本管理体系 (#125)
- Agent 构建错误信息加入 graph_name 和 node_label 上下文，便于用户定位问题

### Bug Fixes

- 修复本地 Ollama 模型在 Agent 工作台报 401 无 API key 的问题 (#127)
- 修复 Skill 保存时使用 previewData 替代 fileTree 容器路径，并正确去除沙箱路径前缀
- 修复沙箱断连后自动重连，改善 Skill 名称冲突的错误提示
- 修复 preview_skill 读取时传入正确的 sandbox backend
- 修复 FileTrackingProxy 在 SkillSandboxLoader 中的 backend 检测
- 修复 CheckpointerManager 复用 Settings 获取数据库 URI，替代直接读取环境变量
- 修复 checkpointer 调用缺少 RunnableConfig 类型注解的问题
- 修复 credential_resolver 中未使用的 model_service 变量
- 修复 deep agent 创建时未传入 checkpointer 导致对话上下文丢失的问题
- 流式错误信息改为内联展示在 AI 消息中，而非仅弹出 toast
- 修复工作区下拉菜单遮罩层阻挡嵌套右键菜单点击的问题
- 修复 SidebarContextMenu 使用 fixed 定位时 portal 到 body
- 修复 Select/Popover 的 z-index 层级，确保在 Dialog/Sheet 之上正确渲染
- 修复侧边栏硬编码偏移量，改用 CSS 变量并增加视口安全边距
- 修复 Tailwind 透明度修饰符失效，改用 color-mix() 方案
- 补充 globals.css 中缺失的 CSS 变量定义
- 修复边框冲突并移除无用的 chart/border-tw 变量

### Refactoring

- 全局清理 Default Model 逻辑，消除模型使用歧义 (#126)
- 统一 WebSocket 错误处理（chat、skill creator、copilot）
- 统一 z-index 层级体系，清理无用 CSS 变量
- 统一排版系统，将 13 个自定义 fontSize token 精简为 8 个标准 Tailwind 覆盖
- 精简 surface 色阶，从 15 级收敛至 6 级
- 将 Agent 调色板从 CSS 变量迁移至 TypeScript 常量
- 移除冗余的品牌别名 CSS 变量、--divider 别名及零使用 CSS 变量
- 整理 globals.css 结构，添加清晰的分区注释
- 全局替换硬编码 Tailwind 颜色为 CSS 变量（UI 基础组件、工作区组件、copilot 组件等）
- 精简 skills 预加载逻辑，渲染 worker prompts，移除未使用的 max_tokens

---

## v0.3.1 — 2026-04-08

### 新功能

- Chat 与 Copilot 全面迁入 Run Center 架构，支持运行详情查看、会话恢复与事件回放
- 解锁深色模式，新增偏好设置面板并重新设计个人资料页面
- WebSocket 层统一重构：引入 BaseWsClient 基类，三端 WS 客户端统一生命周期与认证方式
- 新增 trace_id 全链路追踪传播
- 添加 Ollama 本地模型供应商一键集成
- 更新 OpenAI Compatible 供应商为官方标准模型列表
- 新增图模板自动应用功能（新建或空白图时）
- 技能协作者标签页展示用户名、邮箱及角色
- 增强快速启动脚本，支持交互式部署模式选择
- 新增 Artifacts 开关标签的中英文本地化

### 问题修复

- 修复默认主题为 system，确保 API 响应优先
- 修复侧边栏用户下拉菜单重复分隔线
- 修复通知 WebSocket Hook 的监听器泄漏问题
- 修复沙盒用户列展示 "Unknown" 的 schema 不匹配问题
- 修复非 Docker 环境（Colima 兼容）下的优雅降级
- 修复工作空间权限审计——关闭认证缺口，修正角色映射
- 修复多处 Alembic 迁移循环（重复 revision ID）
- 修复 Edge Runtime 下 crypto.randomUUID 不可用问题
- 完善 quick-start.sh 远程部署支持及后端远程 DB 端口识别
- 优化模型未配置时的错误提示，明确引导用户操作路径
- 将 OpenAI Compatible 供应商显示名称简化为 OpenAI
- 修复调试 trace 路由至 Logger 并在 UI 显示 missing-graph 错误
- 统一后端日志为 loguru
- 修正 buildin→builtin 拼写，提取硬编码 URL，统一 useToast 导入

### 重构

- 前端设计令牌统一——硬编码颜色、字号、圆角替换为 CSS 变量与 Tailwind token
- 统一对话框模式——新建 ConfirmDialog，6 个对话框迁移至 UnifiedDialog
- 引入 AgentListContext 消除 FolderItem 层层透传（27→10 props）
- 提取共享组件：InlineRenameInput、SidebarContextMenu、useInlineRename、useDropZone
- 移除 129 个未使用 SVG 图标（icons.tsx 4091→69 行）
- 移除聊天页模型选择器（保留 Copilot）
- 前端类型安全增强：`any`→`Record<string, unknown>`，引入 discriminated union
- i18n 全面推进：移除 defaultValue/fallback 模式、后端错误消息国际化、邮件模板迁移至 Jinja2、LLM 提示词外置为 Markdown
- 结构化错误码支持 i18n
- 移除硬编码默认模型，要求显式配置
- 沙盒系统重构——RAII 句柄、适配器 API 上传、安全加固
- 清理旧 Copilot 基础设施（Redis、WS handler、copilot_chats 表）
- 后端注释标准化及前后端注释/字符串统一为英文
- 后端目录命名修正与项目结构清理

### CI/CD

- Docker 构建流程优化：限制为仅构建，仅在 release 时推送镜像
- 新增 Docker Hub 双推送支持（ghcr.io + docker.io）
- 移除 MCP 镜像并跳过 openclaw 的 DockerHub 推送

### 其他

- 移除未使用依赖（axios、@remixicon/react）
- 移除 graph_tests 功能（待重新设计）
- 版本管理脚本与发布流程对齐

---

## v0.3.0 — 2026-04-08

### 新功能

- WebSocket 基础架构重构：新增 BaseWsClient 抽象类，统一三端 WebSocket 生命周期管理
- Chat 对话接入 Run Center：支持对话运行持久化、断线恢复、心跳保活及概览展示
- Copilot 接入 Run Center：支持事件持久化、页面刷新后实时事件回放
- 解锁深色模式，支持系统/浅色/深色三种主题切换
- 重新设计个人资料页面，新增偏好设置（语言、主题切换）
- 添加 Ollama 本地模型供应商一键集成
- 更新 OpenAI Compatible 供应商为官方标准模型列表
- 新增图模板自动应用功能（新建或空图时自动加载模板）
- 增强快速启动脚本，支持交互式部署模式选择
- 实现 trace_id 全链路传播（基于 contextvars）
- 技能协作者标签页显示用户名、邮箱和角色信息
- 版本管理脚本及发布工作流优化
- 新增 Artifacts 开关标签的中英文国际化
- 新增 toggle-group shadcn 组件

### 问题修复

- 修复调试追踪日志未经 Logger 输出的问题，向 UI 暴露缺失图错误
- 修复通知 WebSocket 连接的监听器泄漏
- 修复 Copilot 事件持久化及 handleStop 取消逻辑
- 修复 Alembic 数据库迁移版本冲突（重复 revision ID）
- 修复沙箱用户列显示 "Unknown" 的 schema 不匹配问题
- 修复工作空间权限审计——关闭认证漏洞、修正角色映射
- 修复 Docker 在非 Docker 代理环境下的优雅降级（兼容 Colima）
- 修复 tool_resolver 中 _NodeShim 缺少 id 属性
- 统一后端日志为 loguru，替换分散的 logging 调用
- 修复主题同步逻辑，保持 Zustand store 状态一致
- 修复侧边栏用户下拉菜单重复分隔线
- 修复 Chat reducer 消息 ID 校验、node_end 顺序及 node_name 匹配
- 修复 Edge Runtime 下 crypto.randomUUID 不可用问题
- 完善 quick-start.sh 远程部署支持及后端远程数据库端口识别
- 优化模型未配置时的错误提示，明确引导用户操作路径
- 将 OpenAI Compatible 供应商显示名称简化为 OpenAI
- 修复文件上传与 Agent Docker 沙箱文件系统的对齐
- 修复 CI 发布矩阵中引用不存在的 init.Dockerfile
- 移除遗留的 chat/resume/stop 帧类型别名及已废弃的 POST /copilot/actions 端点
- 修复前端 command.tsx 中 27 处重复的 @ts-nocheck 指令
- 修正 buildin→builtin 拼写错误，清理 console.log，提取硬编码 URL

### 重构

- **WebSocket 层统一**：Chat/Run/Notification 三个客户端迁移至 BaseWsClient，统一认证方式（ws-token），重命名 SSE 时代标识符，移除冗余重连常量
- **前端组件提取与统一**：创建 ConfirmDialog 和 UnifiedDialog（迁移 6 个对话框），提取 InlineRenameInput、SidebarContextMenu、useInlineRename、useDropZone 等共享组件
- 引入 AgentListContext 消除 FolderItem 属性穿透（27→10 props）
- 统一前端设计令牌：替换硬编码颜色、字号、圆角为 CSS 变量和 Tailwind 命名令牌
- **沙箱架构重构**：RAII 句柄管理、适配器 API 上传、安全加固
- **后端国际化**：提取邮件模板至 Jinja2、外置 LLM 提示词为 Markdown、结构化错误码支持 i18n
- 移除硬编码默认模型，改为要求显式配置
- 后端注释与字符串标准化为英文，清理死代码、补充 docstring
- 前端类型安全提升：替换 `any` 为 `Record<string, unknown>` 和判别联合类型
- 修正目录命名（midware→middleware、model/models→model/wrappers），合并重复目录
- 移除聊天页模型选择器（保留 Copilot）
- 精简 icons.tsx 未使用 SVG 图标（4091→69 行）
- i18n：移除 defaultValue/fallback 模式，补充缺失翻译键
- 后端错误处理改进：HTTPException→AppException、新增 5 个枚举替代魔法字符串、迁移 datetime.utcnow()

### 无障碍

- 为 20+ 组件的纯图标按钮添加 aria-label 属性（分两批完成）

### 样式

- 更新侧边栏链接排版、间距和图标尺寸，改善视觉层次
- 移除个人资料页面设置布局中的冗余空白

### CI/CD

- 新增 Docker Hub 双推送支持（ghcr.io + docker.io）

### 其他

- 移除未使用的依赖（axios、@remixicon/react）
- 移除 graph_tests 功能（待重新设计）
- 清理旧版 Copilot 基础设施（Redis、WS handler、copilot_chats 表及 Alembic 迁移）
- 移除 converted_skills.json 文件

---

## v0.2.0 — 2026-03-31

### Model Settings — Master-Detail Redesign

- **全新 Master-Detail 布局** — 左侧供应商列表 + 右侧详情面板，替代旧的平铺卡片式设计
- **Schema 驱动的动态表单** — 凭据对话框和参数抽屉均由 JSON Schema 自动生成，新增 Slider 组件
- **自定义模型一站式添加** — 新增 `POST /model-providers/custom` 端点，前端对话框支持协议、API Key、Base URL 等字段
- **模型用量统计** — 新增 `ModelUsageLog` 模型、API 端点、前端 StatsTab，可视化调用量与性能指标
- **SSE 测试流端点** — 新增 `/test-output-stream`，实时验证模型输出并返回性能指标

### Backend 架构重构

- **provider_id 外键统一** — 三阶段迁移：为工厂供应商创建 DB 记录 → 回填 provider_id → 移除废弃的 provider_name 列
- **服务层职责清晰化** — 缓存方法收归 `model_service`，提取 `_resolve_and_create_model`；`credential_service` 简化为一供应商一凭据
- **查询性能优化** — `get_available_models` 改用 dict 查找 + 工厂/模型列表缓存，消除全表扫描；减少前端不必要的 query invalidation
- **移除全局默认模型** — 删除 `is_default` 数据库列及相关配置，简化模型选择逻辑

### 前端体验改进

- **新建自定义供应商自动选中** — 创建后侧边栏自动聚焦到新供应商
- **删除/验证/设默认操作反馈** — 全面补齐 toast 提示，删除后自动清除选中态
- **z-index 层级修复** — Sheet 组件不再被 Settings 对话框遮挡
- **无障碍合规** — 参数抽屉补充 `SheetDescription` 消除 aria 警告

### 代码质量

- **mypy 类型安全** — 修复 6 处类型错误（含 BaseModel.validate 字段名冲突、BaseLanguageModel → BaseChatModel cast）
- **死代码清理** — 移除未使用的 import、冗余 revalidate、废弃 SchemaField 引用

---

## v0.1.0 — 2026-03

### Core Capabilities

- **Skill Versioning & Collaboration**
  - Publish, rollback, and browse skill version history
  - Invite collaborators with role-based permissions (owner / editor / viewer)
  - Ownership transfer with safety checks
  - Platform API tokens for CI/CD and programmatic access

- **Extensible Skill Protocol**
  - Established the `SKILL.md` standard with a "Progressive Disclosure" architecture
  - Dynamic loading of skill metadata, instructions, and resources to optimize context window usage

### System Architecture

- **Multi-Tenant Sandbox Engine**
  - Strict per-user isolation for code execution environments (OpenClaw)
  - Guarantees data sovereignty and prevents state leakage between concurrent sessions

- **Glass-Box Observability**
  - Deep Langfuse integration for real-time execution tracing
  - Visualize agent decision-making process and state transitions

### Enterprise & Infrastructure

- **Enterprise SSO Integration**
  - Built-in templates for GitHub, Google, and Microsoft
  - Configurable OIDC providers: Keycloak, Authentik, GitLab
  - JD SSO support
  - See `backend/config/oauth_providers.yaml` and `backend/config/README_OAUTH_LOCAL.md`

- **Secure Runtime Transition**
  - Deprecated legacy insecure execution paths
  - All dynamic code operations enforced through Sandbox architecture

- **DeepAgents Kernel v0.4.0**
  - Latest stability improvements and performance optimizations

- **Meta-Cognitive Superpowers**
  - Structured reasoning capabilities: Brainstorming, Strategic Planning, and Execution
  - Formalizes the "thinking process" into executable semantic skills
