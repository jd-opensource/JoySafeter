<h1 align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter" width="80" /><br/>
  JoySafeter
</h1>

<p align="center">
  <strong>AI 原生安全智能体平台 —— 构建、编排、规模化运行安全 Agent。</strong><br/>
  <sub>从想法到生产级安全自动化，只需几分钟，而非数月。</sub>
</p>

<p align="center">
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.122+-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs&logoColor=white" alt="Next.js 16"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-Protocol-purple" alt="MCP Protocol"></a>
</p>

<p align="center">
  <a href="./README.md">English</a> | 简体中文
</p>

---

## 为什么选择 JoySafeter

传统安全工具有天花板：脚本脆弱易断、单 Agent 缺乏上下文、复杂场景需要 2–3 名工程师并行协作。JoySafeter 打破这个天花板。

| 挑战 | 传统方式 | JoySafeter |
|------|---------|------------|
| APK 漏洞分析 | 手动 MobSF + 工程师人工审查 | 自主 Agent：上传 → 分析 → 出报告 |
| 渗透测试 | 固定脚本、静态 Playbook | 自主 Agent 根据发现实时动态决策 |
| 工具集成 | 每个工具单独写胶水代码 | 通过 MCP 协议零胶水接入任意工具 |
| 规模扩展 | 人力线性增长 | Agent 团队倍增安全产能 |

> JoySafeter 定义了全新范式：**AI 驱动安全运营（AISecOps）** —— 用多智能体协作、认知记忆进化、场景化战力速配，取代人工协调，实现安全能力的规模化运营。

---

## 实战案例

### 案例一 —— APK 漏洞检测智能体

> 上传 APK，获得 OWASP Mobile Top 10 检测报告，全程无需人工干预。

<p align="center">
  <img src="docs/assets/APK-case.gif" alt="APK 漏洞检测演示" width="800" />
</p>

**运行流程：**

1. 用户上传 APK 文件
2. Agent 调用 MobSF 进行静态分析
3. 提取关键风险点 —— 权限滥用、硬编码密钥、不安全的网络配置等
4. 对高危项通过 Frida 动态插桩进行深度验证
5. 自动生成符合 OWASP Mobile Top 10 格式的结构化检测报告

整个流程从上传到出报告，零人工干预，覆盖了传统需要 2–3 名安全工程师协作完成的工作量。

---

### 案例二 —— 渗透测试智能体

> 给出目标和测试范围，Agent 自主规划、执行、动态调整，最终交付报告。

<p align="center">
  <img src="docs/assets/pentest-case.gif" alt="渗透测试智能体演示" width="800" />
</p>

**操作流程：**

1. 进入工作台，创建新 Agent
2. 选择执行引擎（Claude Code / Codex / native）→ 选择渗透测试相关 Skills
3. 输入经过授权的目标地址和测试要求
4. Agent 在隔离沙箱中自主运行 —— 若发现登录页面，自动触发认证绕过测试
5. 会话结束后下载完整报告

> **备注：** 需在沙箱设置中配置镜像 `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/ghcr.io/jd-opensource/joysafeter-sandbox:latest`。

这种根据侦察结果动态决定下一步的能力，是传统固定脚本无法实现的。

---

## 核心能力

<table>
<tr>
<td width="50%">

### Agent 构建器

- **一次配置，随处运行** —— 一个 Agent 打包了执行引擎、模型、系统提示词、工具、Skills 与 MCP 服务
- **Quickstart 快速上手** —— 用自然语言描述目标，分钟级生成可运行的 Agent
- **AI Skill 创作** —— LLM 辅助的 Skill 起草、代码编辑与版本 diff

</td>
<td width="50%">

### 安全工具开箱即用

- 预集成 **Nmap、Nuclei、Trivy** 等主流安全工具
- **MCP 协议** —— 通过模型上下文协议扩展任意工具
- **30+ 预置技能** —— 渗透测试、文档分析、规划/元技能等

</td>
</tr>
<tr>
<td width="50%">

### 多引擎执行

- **可插拔引擎** —— Claude Code CLI、Codex app-server 以及自研 `native`（`ccb`）引擎，按 Agent 选择
- **隔离沙箱** —— 每个会话运行在独立加固容器中；沙箱 Provider 包括 Docker（默认）、E2B、Daytona
- **技能体系** —— 版本化、可复用的能力包，带安全扫描与渐进式披露

</td>
<td width="50%">

### 企业级就绪

- **多租户** —— 基于角色的工作区隔离与访问控制
- **全链路审计** —— 每个会话的追加式事件日志 + 全链路追踪
- **SSO 集成** —— GitHub、Google、Microsoft、OIDC（Keycloak、Authentik、GitLab）、JD SSO
- **出站管控** —— 每个沙箱由 Envoy 代理执行默认拒绝的域名白名单

</td>
</tr>
</table>

---

## 快速开始

### Docker Compose 部署（推荐）

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# 通过 profile 选择 orchestrator 实现：
docker compose --profile python-orchestrator up -d --build
# 或使用 Rust 版 orchestrator：
# docker compose --profile rust-orchestrator up -d --build
```

访问地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

后端是同一份代码，通过 `JOYSAFETER_SERVICE_ROLE` 环境变量拆成三个服务，作为独立容器部署：

- `api`：REST `/api/v1/*`、SSE 事件流、通知 WebSocket、鉴权。
- `orchestrator`：任务调度、gRPC `AgentBridge`、sandbox 生命周期。
- `worker`：消费 Redis 事件流并将事件落库到 Postgres。

配套基础设施：PostgreSQL、Redis、Envoy（每沙箱出站代理）、skillspector（Skill 安全扫描服务）。

### 本地测试一键启动

```bash
cd deploy
./local-test.sh
```

### 常用部署命令

```bash
./deploy/local-test.sh                     # 本地测试一键启动
./deploy/deploy.sh build                   # 构建前后端镜像
./deploy/deploy.sh build --all             # 构建全部镜像
```

> **环境要求：** Docker + Docker Compose。部署细节请参考 [deploy/README.md](deploy/README.md)。

---

## 架构概览

<p align="center">
  <img src="docs/architecture-diagram.png" alt="JoySafeter 系统架构图" width="900" />
</p>

> 详细架构：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)

**核心设计原则：**

- **三服务、一份代码** —— `api`、`orchestrator`、`worker` 共享同一份代码，在启动时由 `JOYSAFETER_SERVICE_ROLE` 决定行为（`all` 表示单进程本地开发）
- **调度以 DB 为准** —— API 将任务推入 Redis list 作为唤醒信号；orchestrator 用 `FOR UPDATE SKIP LOCKED` 从 Postgres 认领待处理行
- **持久化与实时投递解耦** —— 两阶段事件总线分别扇出到 Redis Streams（持久，Worker 消费 → `joysafeter_session_events`）和 Redis Pub/Sub（临时，驱动 SSE 扇出到浏览器）
- **实时事件走 SSE** —— 浏览器订阅 `GET /api/v1/sessions/{id}/events/stream`（先按 `?after_seq` 从 DB 回放，再接实时）；WebSocket 仅用于 `/ws/notifications`
- **沙箱内 gRPC 执行** —— Agent 从不在 orchestrator 进程中运行；每会话容器内的 Rust `sandbox-runner` 通过 gRPC `AgentBridge` 协议回连 orchestrator
- **可插拔引擎** —— `claude`（Claude Code CLI）、`codex`（Codex app-server）、`native`（自研 `ccb` 二进制），按 Agent 的 `engine_kind` 选择
- **可插拔沙箱** —— Docker（默认，加固）、E2B、Daytona，统一的 `SandboxProvider` SPI
- **集中化状态机** —— Task、Session、Sandbox、Skill 生命周期均由受保护的 FSM 管理
- **规范化错误系统** —— `AppError` 输出规范的 `ErrorDescriptor`（`{code, message, data, source, retryable, user_action}`），HTTP 与流式路径一致消费
- **OTel 观测追踪** —— 全链路 `trace_id` 传播，span 落库
- **凭据加密** —— Provider API Key 存于 Secrets、MCP 凭据存于 Vaults，均 AES-256-GCM 加密，运行时注入沙箱
- **分层技能体系** —— Skills 是版本化能力包，使用前经安全扫描（fail-closed）

### 用户操作路径 —— 快速入门

> **登录** → **添加 Provider Key（Secrets）** → **配置 MCP 凭据（Vaults）** → **Skill 管理** → **构建 Agent** → **开启 Session** → **对话并实时观看事件** → **下载报告**

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16（App Router）, React 19, TypeScript | 服务端渲染，产品界面位于 `/managed/**` |
| **UI** | Radix UI, Tailwind CSS, Framer Motion | 无障碍、动画组件 |
| **状态管理** | Zustand, TanStack Query | 客户端与服务端状态 |
| **后端** | FastAPI 0.122+, Python 3.12+ | 异步 API + OpenAPI 文档，按 `JOYSAFETER_SERVICE_ROLE` 拆分为三服务 |
| **Agent 运行时** | Rust `sandbox-runner` + Claude Code / Codex / `ccb` harness | 每会话沙箱执行，经 gRPC `AgentBridge` |
| **MCP** | mcp 1.20+, fastmcp 2.14+ | 工具协议支持 |
| **数据库** | PostgreSQL, SQLAlchemy 2.0 | 异步 ORM，Alembic 迁移 |
| **事件总线/缓存** | Redis（Streams · Pub/Sub · list） | 持久事件流、实时 SSE 扇出、任务队列 |
| **出站管控** | Envoy | 每沙箱默认拒绝的域名白名单 |
| **可观测性** | OpenTelemetry, Loguru | 全链路追踪与结构化日志 |

---

## 最新动态

> 完整更新记录：[CHANGELOG.md](CHANGELOG.md)

| 标签 | 功能 | 一句话说明 |
|------|------|-----------|
| **NEW** | **三服务架构** | 单进程单体拆分为 `api` / `orchestrator` / `worker`，同一份代码由 `JOYSAFETER_SERVICE_ROLE` 选择，作为独立容器部署 |
| **NEW** | **Redis 事件总线** | 两阶段总线扇出到 Redis Streams（持久，Worker 消费）与 Redis Pub/Sub（实时 SSE），取代旧的进程内 WebSocket 总线 |
| **NEW** | **SSE 实时事件流** | 浏览器订阅 `GET /api/v1/sessions/{id}/events/stream`，支持 `?after_seq` 回放；WebSocket 仅用于通知 |
| **NEW** | **沙箱 gRPC 执行** | Rust `sandbox-runner` 在每会话容器内运行 harness，经 gRPC `AgentBridge` 协议回连 orchestrator |
| **NEW** | **可插拔引擎** | `claude`（Claude Code CLI）、`codex`（Codex app-server）、`native`（自研 `ccb`），按 Agent 选择 |
| **NEW** | **可插拔沙箱** | Docker（默认，加固）、E2B、Daytona，统一 SPI |
| **NEW** | **AI Skill 创作** | 工作区内 LLM 辅助的 Skill 起草、代码编辑与版本 diff |
| **NEW** | **Secrets 与 Vaults** | AES-256-GCM 加密的 Provider API Key（Secrets）与 MCP 凭据（Vaults），运行时注入沙箱 |
| **NEW** | **Skill 安全扫描** | fail-closed 的 skillspector 网关在每次 Skill 写入前扫描 |
| **NEW** | **每沙箱出站管控** | Envoy 代理对每个沙箱执行默认拒绝的域名白名单 |
| **NEW** | **trace_id 全链路追踪** | 基于 OpenTelemetry 的端到端请求追踪，实现完整可观测性 |

---

## 文档

### 快速上手
- [INSTALL_CN.md](INSTALL_CN.md) — 安装指南（Docker / 手动 / 预构建镜像）
- [DEVELOPMENT.md](DEVELOPMENT.md) — 本地开发
- [deploy/README.md](deploy/README.md) — Docker 部署

### 深入了解
- [docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md) — 架构总览
- [backend/README.md](backend/README.md) — 后端指南
- [frontend/README.md](frontend/README.md) — 前端指南

### 教程
参见 [docs/tutorials/](docs/tutorials/)，包含模型配置、MCP 集成、技能开发等逐步指南。

### 项目治理
- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献指南
- [SECURITY.md](SECURITY.md) — 安全策略
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — 行为准则

---

## 社区

如有问题或想与其他用户交流，欢迎扫码加入微信交流群：

<p align="center">
  <img src="docs/assets/wechat-group-3.png" alt="JoySafeter 用户交流群 3" width="280" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/assets/wechat-group-4.png" alt="JoySafeter 用户交流群 4" width="280" />
</p>

---

## 贡献指南

```bash
git clone https://github.com/jd-opensource/JoySafeter.git
git checkout -b feature/amazing-feature
git commit -m 'feat: add amazing feature'
git push origin feature/amazing-feature
```

详情请查看 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

Apache License 2.0 —— 详见 [LICENSE](LICENSE) 文件。

第三方组件许可证：[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

---

## 致谢

<table>
<tr>
<td align="center"><a href="https://fastapi.tiangolo.com/"><img src="https://fastapi.tiangolo.com/img/icon-white.svg" width="48"/><br/><sub>FastAPI</sub></a></td>
<td align="center"><a href="https://nextjs.org/"><img src="https://assets.vercel.com/image/upload/v1662130559/nextjs/Icon_dark_background.png" width="48"/><br/><sub>Next.js</sub></a></td>
<td align="center"><a href="https://www.radix-ui.com/"><img src="https://avatars.githubusercontent.com/u/75042455?s=64" width="48"/><br/><sub>Radix UI</sub></a></td>
<td align="center"><a href="https://www.envoyproxy.io/"><img src="https://avatars.githubusercontent.com/u/13843634?s=64" width="48"/><br/><sub>Envoy</sub></a></td>
<td align="center"><a href="https://opentelemetry.io/"><img src="https://avatars.githubusercontent.com/u/49998002?s=64" width="48"/><br/><sub>OpenTelemetry</sub></a></td>
</tr>
</table>

---

<p align="center">
  <sub>由 JoySafeter 团队用 ❤️ 打造</sub><br/>
  <sub>如需咨询商业方案，请联系京东科技解决方案团队：<a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
