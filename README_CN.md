<h1 align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter" width="80" /><br/>
  JoySafeter
</h1>

<p align="center">
  <strong>开源、可自托管的安全托管智能体（Managed Agent）平台。</strong><br/>
  <sub>你只需声明 Agent 的工具、技能与护栏，JoySafeter 便在你自己的加固、可观测的基础设施上托管运行它。从想法到生产级安全自动化，只需几分钟，而非数月。</sub>
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

托管智能体运行模型对自主工作是正确选择。但对**安全**而言 —— 你在客户系统上、
在 NDA 之下运行具攻击性的工具 —— Agent *在哪里、以何种方式*运行才是决定性的。
JoySafeter 把这套模型交到你**自己的基础设施**上：

- **数据与目标绝不出你的基础设施。** 完全自托管：提示词、发现、抓取的流量、目标细节都留在你的
  网络内。任何第三方都不会看到本次工作。
- **网络受限执行。** 每个会话跑在 `NetworkMode=none` 沙箱里，前置一个 Envoy 代理，
  **默认全拒的出口白名单** —— 攻击性工具无法回连外部或横向进入你的网络，除非你显式放行。
- **运行时 fail-closed 的技能供应链管控。** 技能是会在你环境里执行的代码；skillspector 负责扫描，
  运行时打包会拦截未审批、未成功扫描、blocked、failed、scanning 或与上次扫描发生漂移的技能。
- **引擎无关。** Claude Code、Codex、或自研 `ccb` 引擎，统一在一个 gRPC 契约之后 —— 不锁定单一
  厂商或模型。

| | 云托管智能体 | 自建 | **JoySafeter** |
|---|---|---|---|
| 数据 / 目标驻留 | 厂商云 | 你的 | **你的 —— 完全自托管** |
| 引擎 / 模型 | 单一厂商 | 自行拼装 | **Claude Code / Codex / native，按 Agent 选** |
| 网络隔离 | 厂商托管 | 自行搭建 | **每沙箱 Envoy 全拒出口** |
| 技能与工具安全 | 厂商托管 | 自行搭建 | **SkillSpector 扫描 + 运行时 fail-closed 闸门** |
| 上生产时间 | 数天 | 数月 | **数天，在你自己的硬件上** |

> JoySafeter 将其定义为 **AI 驱动安全运营（AISecOps）**：把托管智能体模型 —— 多步自主、
> 沙箱化工具、会话、全链路可观测 —— 面向安全场景专门化，并完全运行在你的掌控之下。

---

## 实战案例

### 案例一 —— APK 漏洞检测智能体

> 上传 APK，获得 OWASP Mobile Top 10 检测报告，全程无需人工干预。

<p align="center">
  <img src="docs/assets/APK-case.gif" alt="APK 漏洞检测演示" width="800" />
</p>

> **这是一个演示流程，而非内置集成。** 该 Agent 配置了 `pentest-mobile-app` 技能，
> 并使用装有移动端分析工具的沙箱镜像 —— 工具由你自行选配。

**运行流程：**

1. 用户上传 APK 文件
2. Agent 用沙箱内的移动端工具做静态分析（例如 MobSF）
3. 提取关键风险点 —— 权限滥用、硬编码密钥、不安全的网络配置等
4. 对高危项通过动态插桩做深度验证（例如 Frida）
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

## 核心能力 —— 托管智能体的构建块

你只需声明一个 Agent —— 引擎、模型、系统提示词、工具、Skills、MCP 服务、护栏 —— JoySafeter
就用与 Claude Managed Agents 背后同一套**托管智能体构建块**端到端地运行它，只不过是
**自托管、面向安全场景**的：

<table>
<tr>
<td width="50%">

### 🧠 托管 harness 与编排

- **Orchestrator** + gRPC `AgentBridge` + 沙箱内 Rust `sandbox-runner` 负责决定何时调用工具、管理上下文、从错误中恢复
- **以 DB 为准的调度** —— 用 `FOR UPDATE SKIP LOCKED` 从 Postgres 认领任务，带重试与超时
- **引擎无关** —— Claude Code CLI、Codex app-server、自研 `native`（`ccb`）harness，按 Agent 选择

</td>
<td width="50%">

### 📦 沙箱执行

- 每个会话运行在**独立加固容器**中 —— 丢弃能力、非 root、no-new-privileges
- **可插拔 Provider** —— Docker（默认）、E2B（Firecracker）、Daytona，统一 SPI
- **出站管控** —— 每沙箱 Envoy 代理，默认拒绝的域名白名单

</td>
</tr>
<tr>
<td width="50%">

### 🔧 工具、自定义工具与 MCP

- 每个 Agent 可挂载**内置工具**、**自定义工具**（名称 + JSON Schema）与 **MCP 服务**
- MCP 配置 + Vault 凭据在运行时解析，经 gRPC 下发到沙箱
- **安全技能包**在沙箱镜像内驱动 **Nmap / Nuclei / Trivy** 等工具；任意外部工具经 **MCP 协议**接入

</td>
<td width="50%">

### 📚 Skills

- **30 个版本化能力包** —— 渗透测试、文档分析、规划/元技能
- **SkillSpector 安全扫描** + 运行时 `is_skill_usable` 闸门（approved + `passed` / `warning` 扫描 + 内容未漂移）
- **AI Skill 创作** —— LLM 辅助的起草、编辑、版本化与 diff

</td>
</tr>
<tr>
<td width="50%">

### 💾 会话、记忆与恢复

- **Session** 是持久对话，带**追加式、按 seq 排序的事件日志**
- **记忆库** —— 版本化、Agent 可写的 KV 存储，与沙箱双向同步
- **可恢复** —— 重连时重新挂接会话的 harness 与工作目录

</td>
<td width="50%">

### 🛡️ 作用域权限与护栏

- **每工具授权** —— `always_ask` / `always_allow`，高危工具触发人工确认（HITL）
- **凭据加密** —— Provider Key 存 Secrets、MCP 凭据存 Vaults，AES-256-GCM，作为沙箱 env 注入
- **SSRF 守卫** —— 拦截云元数据端点；可选私网段加固

</td>
</tr>
<tr>
<td width="50%">

### 🔎 全链路可观测

- **实时 SSE 事件流** —— 每条消息、思考步、工具调用、工具结果、模型请求
- **OpenTelemetry** traces + `observations`，带 token/成本聚合，`trace_id` 端到端传播
- 追加式会话事件日志天然充当完整**审计轨迹**

</td>
<td width="50%">

### 🏢 多租户与访问控制

- **组织 / 项目 / RBAC** —— 工作区隔离 + 基于角色的访问控制
- **SSO** —— GitHub、Google、Microsoft、OIDC（Keycloak、Authentik、GitLab）、JD SSO
- **Quickstart** —— 用自然语言描述目标，分钟级生成可运行的 Agent

</td>
</tr>
</table>

> 这些构建块与 Claude Managed Agents 特性集的逐项对照、以及路线图，见
> [与 Claude Managed Agents 的能力对齐与路线图](#与-claude-managed-agents-的能力对齐与路线图)。

---

## 快速开始

### Docker Compose 部署（推荐）

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` 只做本地环境预检，不启动容器。`local` 会创建缺失的 `.env`，
按 Docker daemon 的 CPU 架构自动选择 `linux/arm64` 或 `linux/amd64`，
配置多架构基础镜像，准备 SkillSpector 源码，执行数据库迁移，然后启动完整本地栈。

访问地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

后端由两个 Python 服务和 Rust orchestrator 组成，作为独立容器部署：

- `api`：REST `/api/v1/*`、SSE 事件流、通知 WebSocket、鉴权。
- `orchestrator-rs`：任务调度、gRPC `AgentBridge`、sandbox 生命周期。
- `worker`：消费 Redis 事件流并将事件落库到 Postgres。

配套基础设施：PostgreSQL、Redis、Envoy（每沙箱出站代理）、skillspector（Skill 安全扫描服务）。
内置 Redis 服务由 `local-redis` profile 控制；如果使用云 Redis，不启用该 profile，改 `deploy/.env`
里的 `REDIS_URL` 即可。
Python orchestrator 已移除；本地和容器化部署都使用 `rust-orchestrator` profile。

运行时协同：

| 参与方 | 职责 |
|------|------|
| 前端 | 产品 UI、REST 命令、SSE 订阅 |
| API | Auth/RBAC、CRUD、任务创建、SkillSpector 写入时扫描、SSE 回放/实时桥接 |
| Rust `orchestrator-rs` | DB 权威调度、任务租约、沙箱生命周期、runner gRPC、事件发射 |
| Sandbox runner | 容器内 Claude/Codex/native harness 执行，通过 `AgentBridge` 回连 |
| Worker | Redis Stream 消费、事件 `seq` 分配、可靠事件落库 |
| PostgreSQL / Redis | PostgreSQL 是调度/状态权威；Redis 提供唤醒、Streams、Pub/Sub 和命令中继 |

主数据流：浏览器命令 → API → PostgreSQL task 行 + Redis 唤醒 → Rust orchestrator 认领 →
sandbox runner 执行 → Redis Stream/PubSub 事件 → Worker 可靠落库 + API SSE 投递 → 浏览器。
完整拓扑、职责所有权和故障归属见 [docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)。

### 本地测试一键启动

```bash
cd deploy
./local-test.sh
```

仅当你希望 Python/Node 进程直接跑在宿主机、Docker 只提供 PostgreSQL/Redis 时使用它。
普通容器化本地部署请使用 `./deploy.sh local`。

### 常用部署命令

```bash
cd deploy
./deploy.sh doctor                         # 本地 Docker/Compose/env 预检
./deploy.sh local                          # 完整本地 Docker Compose 部署
./deploy.sh local --arch arm64             # 强制目标平台
./deploy.sh build                          # 构建核心部署镜像
./deploy.sh build --all                    # 构建核心 + agent runtime 镜像
```

> **环境要求：** Docker + Docker Compose。部署细节请参考 [deploy/README.md](deploy/README.md)。

---

## 架构概览

![JoySafeter 托管智能体架构](docs/architecture-diagram.png)

<sub>总览信息图 —— ① 控制面（REST · CLI）→ ② Agent Harness（沙箱内）→ ③ Session 状态层。交互版：[`docs/architecture-diagram.html`](docs/architecture-diagram.html)。</sub>

```mermaid
flowchart LR
    FE["浏览器"] -->|"REST · SSE"| API["API 服务"]
    API -->|"rpush task"| RLIST[("Redis list<br/>global_queue")]
    RLIST -.->|"唤醒"| SCHED["Orchestrator<br/>调度器（DB 权威）"]
    SCHED -->|"认领 / provision"| SBX["沙箱（NetworkMode=none）<br/>Rust runner + harness"]
    SBX <-->|"gRPC AgentBridge"| ENVOY["Envoy<br/>唯一网络出入口"]
    ENVOY <--> GRPC["Orchestrator gRPC :9090"]
    ENVOY -->|"出口白名单"| EXT["模型 API · MCP · 目标"]
    GRPC -->|"harness 事件"| BUS["两相事件总线"]
    BUS -->|"① 持久化 XADD"| RSTREAM[("Redis stream")]
    BUS -->|"② 广播 PUBLISH"| RPUB[("Redis pub/sub")]
    RSTREAM -->|"XREADGROUP"| WK["Worker → 落库"]
    WK --> PG[("PostgreSQL")]
    WK -.->|"再发布"| RPUB
    RPUB -->|"SessionBroadcaster"| API
    API -->|"SSE 事件流"| FE
```

> **托管智能体总览信息图：** [docs/architecture-diagram.html](docs/architecture-diagram.html) —— 在浏览器打开（① 控制面 REST·CLI → ② Agent Harness → ③ Session 状态层）。
>
> 完整架构（部署拓扑、gRPC 契约、引擎、沙箱、事件模型、领域 FSM）：
> **[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)** · 分层视图：
> [docs/architecture-unified-event-model.mmd](docs/architecture-unified-event-model.mmd)

**核心设计原则：**

- **显式服务边界** —— Python 只承载 `api` / `worker` 两个服务；调度、gRPC `AgentBridge` 与沙箱生命周期由 Rust `orchestrator-rs` 服务负责
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
- **分层技能体系** —— Skills 是版本化能力包；运行时只打包已审批、扫描状态允许且内容未漂移的技能

### 用户操作路径 —— 快速入门

> **登录** → **添加 Provider Key（Secrets）** → **配置 MCP 凭据（Vaults）** → **Skill 管理** → **构建 Agent** → **开启 Session** → **对话并实时观看事件** → **下载报告**

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16（App Router）, React 19, TypeScript | 服务端渲染，产品界面位于 `/managed/**` |
| **UI** | Radix UI, Tailwind CSS | 无障碍组件基元 |
| **状态管理** | Zustand, TanStack Query | 客户端与服务端状态 |
| **后端** | FastAPI 0.122+, Python 3.12+ | 异步 API 与 worker 服务；调度由 Rust `orchestrator-rs` 服务负责 |
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
| **NEW** | **拆分运行时架构** | 单进程单体拆分为 Python `api` / `worker` 与 Rust `orchestrator-rs`，作为独立容器部署 |
| **NEW** | **Redis 事件总线** | 两阶段总线扇出到 Redis Streams（持久，Worker 消费）与 Redis Pub/Sub（实时 SSE），取代旧的进程内 WebSocket 总线 |
| **NEW** | **SSE 实时事件流** | 浏览器订阅 `GET /api/v1/sessions/{id}/events/stream`，支持 `?after_seq` 回放；WebSocket 仅用于通知 |
| **NEW** | **沙箱 gRPC 执行** | Rust `sandbox-runner` 在每会话容器内运行 harness，经 gRPC `AgentBridge` 协议回连 orchestrator |
| **NEW** | **可插拔引擎** | `claude`（Claude Code CLI）、`codex`（Codex app-server）、`native`（自研 `ccb`），按 Agent 选择 |
| **NEW** | **可插拔沙箱** | Docker（默认，加固）、E2B、Daytona，统一 SPI |
| **NEW** | **AI Skill 创作** | 工作区内 LLM 辅助的 Skill 起草、代码编辑与版本 diff |
| **NEW** | **Secrets 与 Vaults** | AES-256-GCM 加密的 Provider API Key（Secrets）与 MCP 凭据（Vaults），运行时注入沙箱 |
| **NEW** | **Skill 安全扫描** | SkillSpector 扫描技能内容；运行时拦截未审批、未扫描、failed、blocked、scanning 或漂移的技能 |
| **NEW** | **每沙箱出站管控** | Envoy 代理对每个沙箱执行默认拒绝的域名白名单 |
| **NEW** | **trace_id 全链路追踪** | 基于 OpenTelemetry 的端到端请求追踪，实现完整可观测性 |

---

## 与 Claude Managed Agents 的能力对齐与路线图

JoySafeter 实现了 Anthropic 为
[Claude Managed Agents](https://claude.com/blog/claude-managed-agents) 描述的同一套
**托管智能体运行模型** —— 你声明 Agent 的工具、技能与护栏，平台在托管 harness 上以沙箱执行、
会话、作用域权限与全链路可观测运行它。不同之处在于：JoySafeter 是**开源、可自托管、引擎无关**
（Claude Code / Codex / 自研 `ccb`）、并**面向安全场景专门化**的。下表逐项对照该模型与 JoySafeter 当前的落地情况。

**图例：** ✅ 已交付 · 🟡 部分实现 · ⬜ 规划中（见路线图）

| Managed-agent 能力 | JoySafeter | 我们如何实现 |
|---|:---:|---|
| 托管 Agent harness / 编排 | ✅ | Orchestrator + gRPC `AgentBridge` + 沙箱内 Rust `sandbox-runner` harness |
| 沙箱执行 | ✅ | 每会话独立加固容器；Docker（默认）/ E2B / Daytona，统一 SPI |
| 工具、自定义工具 & MCP | ✅ | 每 Agent 的内置工具、自定义工具与 `mcp_configs`，经 gRPC 下发到沙箱 |
| 作用域权限 / 护栏 | ✅ | 每工具策略（`always_ask` / `always_allow`）+ 人工确认（HITL） |
| 凭据管理 | ✅ | Secrets（Provider Key）+ Vaults（MCP 凭据），AES-256-GCM 加密，作为沙箱 env 注入 |
| 会话与可恢复执行 | ✅ | `JoySafeterSession` + 追加式事件日志；重连时按 harness 会话/工作目录恢复 |
| 记忆库（Memory Store） | ✅ | 版本化、Agent 可写的记忆库，与沙箱双向同步 |
| 可观测性 / 会话追踪 | ✅ | OTel traces + `observations`，外加每个工具调用与决策的实时 SSE 事件流 |
| 部署 CLI + 控制台 | ✅ | `joysafeterctl`（声明式 REST CLI）+ Web 工作台 |
| 多智能体编排（lead → specialists） | 🟡 | 目前为 harness 驱动的子 Agent，经 `TaskNotification` 事件呈现；一等公民式的 lead/specialist 编排在路线图中 |
| 持久化 checkpoint | 🟡 | 目前为会话级恢复；步级持久 checkpoint 规划中 |
| Outcomes（rubric + grader 自我纠错闭环） | ⬜ | 规划中 |
| Dreaming（定时记忆整理 / 自我进化） | ⬜ | 规划中 |
| Webhooks（任务/结果完成通知） | ⬜ | 规划中 |

### 路线图 / TODO

结合我们已有的能力与 managed-agent 前沿特性，下一步工作项：

- [ ] **Outcomes** —— 用户定义 rubric（评分标准），由独立 grader 在自己的上下文中评估每次结果，Agent 自我纠错直至达标（无需逐次人工审查）。
- [ ] **一等公民式多智能体编排** —— lead agent 委派给各 specialist 子 Agent（各自独立的模型 / 提示词 / 工具），在共享会话工作区上并行执行，并对每个子 Agent 提供完整追踪（目前子 Agent 由 harness 拉起，仅通过 `agent.bg_task_*` 事件观测）。
- [ ] **Dreaming** —— 定时任务回顾历史会话与记忆库，提炼反复出现的模式与错误，整理记忆（可选自动更新或先审后改）。
- [ ] **Webhooks** —— 任务或 outcome 完成时通知外部系统（或触发后续 Agent）。
- [ ] **步级持久 checkpoint** —— 支持长任务中途续跑，超越当前的会话/工作目录重连恢复。
- [ ] **会话时长计量与成本分析** —— 在控制台呈现每会话运行时长 + token/成本核算。

> 有用例急需其中某项？欢迎提 issue —— 路线图由社区共同驱动。

---

## 文档

### 快速上手
- [INSTALL_CN.md](INSTALL_CN.md) — 安装指南（Docker / 手动 / 预构建镜像）
- [DEVELOPMENT.md](DEVELOPMENT.md) — 本地开发
- [deploy/README.md](deploy/README.md) — Docker 部署

### 深入了解
- [docs/README.md](docs/README.md) — 文档地图
- [docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md) — 架构总览
- [docs/DOCUMENTATION_STATUS.md](docs/DOCUMENTATION_STATUS.md) — 当前文档复核状态
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
