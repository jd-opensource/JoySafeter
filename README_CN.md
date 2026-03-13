<!-- Logo 图片占位符 - 当 docs/assets/logo.png 可用时添加 -->
<!-- <p align="center">
  <img src="docs/assets/logo.png" alt="JoySafeter" width="120" />
</p> -->

<h1 align="center">JoySafeter</h1>

<p align="center">
  <strong>3分钟生成生产级 Agent 的平台 | 信息安全 SOTA 效果的数字员工</strong>
</p>

<p align="center">
  企业级智能安全体编排平台，基于 LangGraph 构建可视化工作流
</p>

<p align="center">
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-1.0+-FF6F00?logo=chainlink&logoColor=white" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.122+-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-Protocol-purple" alt="MCP Protocol"></a>
</p>

<p align="center">
  <a href="./README.md">English</a> | 简体中文
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> •
  <a href="#文档">文档</a> •
  <a href="#贡献指南">贡献指南</a> •
  <a href="#许可证">许可证</a>
</p>

<!-- 截图占位符 - 当 docs/assets/screenshot-builder.png 可用时添加 -->
<!-- <p align="center">
  <img src="docs/assets/screenshot-builder.png" alt="Agent 构建器截图" width="800" />
</p> -->

## 目录

- [为什么选择 JoySafeter？](#为什么选择-joysafeter)
- [快速开始](#快速开始)
- [文档](#文档)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 为什么选择 JoySafeter？

> **JoySafeter 不仅是一个提效工具，更是安全能力的「操作系统」**
> 它通过可视化的智能编排，将割裂的安全工具统合为协同的 AI 军团，将个人的专家经验沉淀为组织的数字资产，率先在行业内定义了 **AI 驱动安全运营（AISecOps）** 的新范式。

### 项目背景

通用 LLM 在安全等专业领域准确率不足，且对安全任务的理解不深入，安全场景无法通过单 Agent 来解决，导致大模型在信息安全领域难以落地。信息安全场景对抗性强且安全趋势持续变化，如何在 Agent 运行过程中持续积累安全经验让 Agent 越用越聪明，是整个行业面临的挑战。

JoySafeter 通过 Multi-Agent 协作、认知进化引擎、场景化战力速配，实现了安全能力的规模化运营。

<table>
<tr>
<td width="50%">

### 面向企业安全团队

- **可视化开发** — 无代码 Agent 构建器，快速原型验证
- **200+ 安全工具** — 预集成 Nmap、Nuclei、Trivy 等主流工具
- **治理与审计** — 全链路执行追踪与可观测性
- **多租户隔离** — 基于角色的工作区隔离

</td>
<td width="50%">

### 面向 AI 安全研究者

- **图编排工作流** — 支持循环、条件、并行的复杂控制流
- **记忆进化** — 长短期记忆机制，持续学习积累
- **MCP 协议** — 模型上下文协议，无限工具扩展性
- **DeepAgents 模式** — 多层级 Agent 协作编排

</td>
</tr>
</table>

---

## 功能特性

JoySafeter 是企业级 AI 安全 Agent 编排平台，核心能力包括：

- **快速模式**：自然语言需求 → 自动编排 Agent 团队 → 分钟级可运行
- **深度模式**：可视化工作流构建 + 调试 + 可观测，支撑复杂安全研究的持续迭代
- **Skills**：预置安全技能与可扩展技能体系（渐进式披露）
- **多智能体协作**：DeepAgents Manager-Worker 星型拓扑
- **可观测性**：流式输出 + 链路追踪（Langfuse）
- **部署**：生产可用的 Docker 部署与场景化脚本

详细功能介绍与技术矩阵请见：
- 架构总览：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)
- 开发者细节：[DEVELOPMENT.md](DEVELOPMENT.md)

---

## 架构设计

详见：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)。

---

## 最近更新日志

### 核心能力 (Core Capabilities)
- **元认知超能力 (Meta-Cognitive Superpowers)**: 引入了包括头脑风暴 (Brainstorming)、战略规划 (Writing Plans) 和执行 (Executing Plans) 在内的结构化推理能力。通过将 "思考过程" 形式化为可执行的语义技能，将 Agent 从简单的任务执行提升到解决复杂问题的层面。
- **可扩展技能协议 (Extensible Skill Protocol)**: 确立了包含 "渐进式披露 (Progressive Disclosure)" 架构的 `SKILL.md` 标准。该机制通过按需动态加载技能元数据、指令和资源，极大优化了上下文窗口 (Context Window) 的利用率，使 Agent 成为一个能力无限扩展的平台。

### 系统架构 (System Architecture)
- **多租户沙箱引擎 (Multi-Tenant Sandbox Engine)**: 实现了代码执行环境的严格用户级隔离。这一企业级安全特性保证了数据主权，彻底防止了并发用户会话之间的状态泄露。
- **白盒可观测性 (Glass-Box Observability)**: 集成了基于 Langfuse 的深度执行追踪可视化。用户现在可以实时观察 Agent 的决策过程和状态流转，为 Agent 的 "思维过程" 提供了完全的透明度。

### 优化与基础设施 (Optimization & Infrastructure)
- **安全运行时迁移**: 废弃了遗留的不安全执行路径，强制所有动态代码操作使用新的沙箱架构，提升了系统的整体安全性。
- **企业身份集成**: 标准化单点登录 (SSO) 能力：内置 GitHub / Google / Microsoft 模板，并支持 Keycloak / Authentik / GitLab 等 OIDC 配置，以及 JD SSO（非标准 OAuth2）。详见 backend/config/oauth_providers.yaml 与 backend/config/README_OAUTH_LOCAL.md。
- **核心内核升级**: 将 `deepagents` 核心库升级至 v0.4.0，引入了最新的稳定性改进和性能优化。
---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16, React 19, TypeScript | 服务端渲染, App Router |
| **UI 组件** | Radix UI, Tailwind CSS, Framer Motion | 无障碍、动画组件 |
| **状态管理** | Zustand, TanStack Query | 客户端与服务端状态 |
| **图可视化** | React Flow | 交互式节点编辑器 |
| **后端** | FastAPI, Python 3.12+ | 异步 API，OpenAPI 文档 |
| **AI 框架** | LangChain 1.2+, LangGraph 1.0+, DeepAgents | Agent 编排与工作流 |
| **MCP 集成** | mcp 1.20+, fastmcp 2.14+ | 工具协议支持 |
| **数据库** | PostgreSQL, SQLAlchemy 2.0 | 异步 ORM，数据库迁移 |
| **缓存** | Redis | 会话缓存与限流 |
| **可观测性** | Langfuse, Loguru | 追踪与结构化日志 |

---

## 快速开始

### 环境要求

- Docker + Docker Compose（首次使用推荐）
- Python 3.12+ 与 Node.js 20+（仅本地开发后端/前端时需要）

### 一键启动（Docker，推荐）

```bash
./deploy/quick-start.sh
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

### 下一步

- 完整安装（手动部署 / 预构建镜像等）：[INSTALL_CN.md](INSTALL_CN.md)
- 本地开发：[DEVELOPMENT.md](DEVELOPMENT.md)
- 生产部署指南：[deploy/README.md](deploy/README.md) 与 [deploy/PRODUCTION_IP_GUIDE.md](deploy/PRODUCTION_IP_GUIDE.md)

---

## 路线图

最新路线图与设计备忘请查看 [docs/plans/](docs/plans/) 与项目 Issues。

## 文档

### 从这里开始

- 安装指南：[INSTALL_CN.md](INSTALL_CN.md)
- 开发指南：[DEVELOPMENT.md](DEVELOPMENT.md)
- Docker 部署指南：[deploy/README.md](deploy/README.md)
- 架构总览：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)

### 子模块文档

- 后端指南：[backend/README.md](backend/README.md)
- 前端指南：[frontend/README.md](frontend/README.md)

### 项目治理

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全策略：[SECURITY.md](SECURITY.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---



## 社区

如有问题或想与其他用户交流，欢迎扫码加入微信交流群：

<p align="center">
  <img src="docs/assets/web-chat-group.jpg" alt="JoySafeter 用户交流群" width="300" />
</p>

## 贡献指南

我们欢迎社区贡献！详情请查看 [贡献指南](CONTRIBUTING.md)。

```bash
# Fork 并克隆
git clone https://github.com/jd-opensource/JoySafeter.git

# 创建功能分支
git checkout -b feature/amazing-feature

# 提交更改
git commit -m 'feat: add amazing feature'

# 推送并创建 PR
git push origin feature/amazing-feature
```
---

## 许可证

本项目采用 **Apache License 2.0** 开源协议 — 详见 [LICENSE](LICENSE) 文件。

> **注意：** 本项目包含不同许可证的第三方组件，详见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。

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
  <sub>由 JoySafeter 团队用 ❤️ 打造</sub>
</p>

---

<p align="center">
  <sub>如需咨询商业方案，请联系京东科技解决方案团队，联系方式：<a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
