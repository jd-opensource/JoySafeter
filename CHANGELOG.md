# Changelog

All notable changes to JoySafeter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
