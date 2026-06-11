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
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-1.0+-FF6F00?logo=chainlink&logoColor=white" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.122+-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-Protocol-purple" alt="MCP Protocol"></a>
  <a href="#"><img src="https://img.shields.io/badge/DeepAgents-v0.4-red" alt="DeepAgents v0.4"></a>
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
| 渗透测试 | 固定脚本、静态 Playbook | DeepAgents 根据发现实时动态决策 |
| 工具集成 | 每个工具单独写胶水代码 | 200+ 工具通过 MCP 协议零胶水接入 |
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
2. 开启 **DeepAgents 模式** → 选择渗透测试相关 Skills
3. 输入经过授权的目标地址和测试要求
4. Agent 自主运行 —— 若发现登录页面，自动触发认证绕过测试
5. 运行结束后下载完整报告

> **备注：** 需在沙箱设置中配置镜像 `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/ghcr.io/jd-opensource/joysafeter-sandbox:latest`。

这种根据侦察结果动态决定下一步的能力，是传统固定脚本无法实现的。

---

## 核心能力

<table>
<tr>
<td width="50%">

### 可视化 Agent 构建器

- **无代码工作流编辑器** —— 拖拽节点，支持循环、条件、并行执行
- **快速模式** —— 用自然语言描述需求，分钟级生成可运行的 Agent 团队
- **深度模式** —— 可视化调试 + 逐步可观测，适用于复杂安全研究的持续迭代

</td>
<td width="50%">

### 200+ 安全工具开箱即用

- 预集成 **Nmap、Nuclei、Trivy** 等主流工具
- **MCP 协议** —— 通过模型上下文协议扩展任意工具
- **30+ 预置技能** —— 渗透测试、文档分析、云安全等

</td>
</tr>
<tr>
<td width="50%">

### DeepAgents 编排引擎

- **Manager-Worker 多层级**智能体协作
- **记忆进化** —— 长短期记忆机制，跨会话持续学习
- **技能体系** —— 版本化、可复用的能力单元，渐进式披露
- **LangGraph 引擎** —— 基于图的工作流与完整状态管理

</td>
<td width="50%">

### 企业级就绪

- **多租户** —— 基于角色的工作区隔离与访问控制
- **全链路审计** —— 执行追踪与合规治理
- **SSO 集成** —— GitHub、Google、Microsoft、OIDC（Keycloak、Authentik、GitLab）、JD SSO
- **多租户沙箱** —— 用户级代码执行隔离，会话间零状态泄露

</td>
</tr>
</table>

---

## 快速开始

### Docker 三服务启动（推荐）

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy
docker compose up -d --build
```

访问地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

后端默认拆成三个服务：

- `api`：HTTP / WebSocket / 管理接口。
- `orchestrator`：调度、gRPC、sandbox 生命周期。
- `worker`：后台任务、reaper、事件落库。

### 本地测试一键启动

```bash
cd deploy
./local-test.sh
```

### 常用部署命令

```bash
./deploy/local-test.sh                    # 本地测试一键启动
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

- **值域唯一来源** —— `core/contracts/` 以 Literal 类型 + set 常量定义所有规范化值（状态、错误码、触发来源），杜绝魔术字符串
- **引擎协议 + 注册表** —— 所有执行引擎实现 `ExecutionEngine` Protocol；`EngineRegistry` 将 `runtime_kind` 映射到引擎实例；添加新引擎只需改 3 个文件
- **两阶段事件总线** —— 第 1 阶段（持久化 + 状态变迁）共享 DB 事务，原子提交；第 2 阶段（WebSocket + 任务同步）并行扇出
- **集中化状态机** —— 6 个实体状态机（`Agent`、`Version`、`Release`、`Run`、`Execution`、`Task`），`transition_*()` 是唯一的状态修改入口
- **规范化错误系统** —— `AppError.to_payload()` 输出规范的 `ErrorDescriptor`（`{code, message, data, source, retryable, user_action}`），HTTP/WS/SSE/DB 各传输路径一致消费
- **端口/适配器边界** —— `core/ports/` 定义 Protocol 接口；`services/` 提供实现；`core/` 不导入具体服务
- **OTel 观测追踪** —— `ObservationCollector` 注入 `ExecutionContext`；span 导出到 DB 和 WebSocket，支持实时追踪展示
- **图式执行** —— 每个 Agent 工作流都是有状态的 LangGraph，支持暂停、恢复与分支
- **统一 WebSocket 层** —— BaseWsClient 抽象基类；Execution / Notification 客户端共享生命周期、认证与重连逻辑
- **RAII 沙箱隔离** —— 用户级 Docker 容器，句柄自动释放，会话间零状态泄露
- **规范化模型标识** —— 全栈统一 (provider_name, model_name) 解析路径：ModelService → ModelFactory
- **分层技能体系** —— 技能是版本化单元，可自由组合成工作流，互不耦合

### 用户操作路径 —— 9 步快速入门

<p align="center">
  <img src="docs/user-journey-quickstart.png" alt="JoySafeter 快速入门用户路径" width="900" />
</p>

> **登录** → **配置模型** → **MCP 工具** → **Skill 管理** → **构建 Agent** → **自测 (Langfuse Trace)** → **发布** → **Chat 运行** → **Run Center**

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16, React 19, TypeScript | 服务端渲染，App Router |
| **UI** | Radix UI, Tailwind CSS, Framer Motion | 无障碍、动画组件 |
| **状态管理** | Zustand, TanStack Query | 客户端与服务端状态 |
| **工作流编辑器** | React Flow | 交互式节点编辑器 |
| **后端** | FastAPI, Python 3.12+ | 异步 API，OpenAPI 文档 |
| **AI 框架** | LangChain, LangGraph, DeepAgents | Agent 编排与工作流 |
| **MCP** | mcp 1.20+, fastmcp 2.14+ | 工具协议支持 |
| **数据库** | PostgreSQL, SQLAlchemy 2.0 | 异步 ORM，数据库迁移 |
| **缓存** | Redis | 会话缓存与限流 |
| **可观测性** | Langfuse, Loguru | 追踪与结构化日志 |

---

## 最新动态

> 完整更新记录：[CHANGELOG.md](CHANGELOG.md)

| 标签 | 功能 | 一句话说明 |
|------|------|-----------|
| **NEW** | **架构硬化** | 5 层执行架构：引擎协议 + EngineRegistry + 两阶段事件总线 + 集中化状态机 + 端口/适配器边界 |
| **NEW** | **统一错误契约** | `AppError.to_payload()` 输出规范 `ErrorDescriptor`，HTTP/WS/SSE/DB 一致消费；前端 `ApiError` 镜像类型化 `source`/`retryable`/`userAction` |
| **NEW** | **状态机集中化** | 6 个实体状态机（Agent、Version、Release、Run、Execution、Task），`transition_*()` 为唯一状态修改入口 |
| **NEW** | **观测追踪** | 基于 OTel 的 `ObservationCollector` 注入 ExecutionContext；span 导出到 DB 和 WebSocket，支持实时追踪 |
| **NEW** | **Run Center 架构** | Chat 与 Copilot 全面迁入 Run Center——支持运行详情查看、会话恢复、页面刷新后实时事件回放 |
| **NEW** | **深色模式与偏好设置** | 系统/浅色/深色三种主题切换；重新设计个人资料页面，新增语言与主题偏好 |
| **NEW** | **统一 WebSocket 层** | 引入 BaseWsClient 抽象基类——Chat、Run、Notification 三端客户端共享生命周期、认证（ws-token）与重连逻辑 |
| **NEW** | **trace_id 全链路追踪** | 基于 contextvars 的端到端请求追踪，实现完整可观测性 |
| **NEW** | **Ollama 一键集成** | 开箱即用的本地 Ollama 模型供应商 |
| **NEW** | **版本信息展示** | 应用内版本信息展示，接入 bump-version.sh 发布管线 |
| **NEW** | **统一模型标识符** | 全栈统一为 (provider_name, model_name) 规范形式，含数据迁移——彻底消除遗留字段歧义 |
| **UPGRADE** | **设计令牌全面重构** | 硬编码颜色、字号、圆角替换为 CSS 变量与 Tailwind token；z-index 与排版体系统一 |
| **UPGRADE** | **沙箱架构重构** | RAII 句柄管理、适配器 API 上传、安全加固 |
| **UPGRADE** | **前端组件提取** | ConfirmDialog、UnifiedDialog、InlineRenameInput、SidebarContextMenu、AgentListContext——减少属性穿透，提升复用 |
| **UPGRADE** | **i18n 与代码质量** | 后端错误消息国际化；邮件模板迁移至 Jinja2；LLM 提示词外置为 Markdown；移除 129 个未使用 SVG 图标 |

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
<td align="center"><a href="https://github.com/langchain-ai/langchain"><img src="https://avatars.githubusercontent.com/u/126733545?s=64" width="48"/><br/><sub>LangChain</sub></a></td>
<td align="center"><a href="https://github.com/langchain-ai/langgraph"><img src="https://avatars.githubusercontent.com/u/126733545?s=64" width="48"/><br/><sub>LangGraph</sub></a></td>
<td align="center"><a href="https://fastapi.tiangolo.com/"><img src="https://fastapi.tiangolo.com/img/icon-white.svg" width="48"/><br/><sub>FastAPI</sub></a></td>
<td align="center"><a href="https://nextjs.org/"><img src="https://assets.vercel.com/image/upload/v1662130559/nextjs/Icon_dark_background.png" width="48"/><br/><sub>Next.js</sub></a></td>
<td align="center"><a href="https://www.radix-ui.com/"><img src="https://avatars.githubusercontent.com/u/75042455?s=64" width="48"/><br/><sub>Radix UI</sub></a></td>
</tr>
</table>

---

<p align="center">
  <sub>由 JoySafeter 团队用 ❤️ 打造</sub><br/>
  <sub>如需咨询商业方案，请联系京东科技解决方案团队：<a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
