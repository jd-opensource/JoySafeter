<!-- Logo 图片占位符 - 当 docs/assets/logo.png 可用时添加 -->
<!-- <p align="center">
  <img src="docs/assets/logo.png" alt="JoySafeter" width="120" />
</p> -->

<h1 align="center">JoySafeter</h1>

<p align="center">
  <strong>可视化构建、编排、运行 AI 安全 Agent —— 从想法到生产，只需几分钟。</strong>
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

<!-- 截图 / GIF 占位符 — 替换为实际产品截图 -->
<!-- <p align="center">
  <img src="docs/assets/screenshot-builder.png" alt="Agent 构建器截图" width="800" />
</p> -->

---

## 快速开始

一行命令启动 JoySafeter：

```bash
./deploy/quick-start.sh
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

> **环境要求：** Docker + Docker Compose。手动安装或预构建镜像请参考 [INSTALL_CN.md](INSTALL_CN.md)。

---

## 最新动态

> 完整更新记录：[CHANGELOG.md](CHANGELOG.md)

| 标签 | 功能 | 一句话说明 |
|------|------|-----------|
| **NEW** | **技能版本化与协作** | 发布、回滚、管理技能版本；邀请协作者并按角色授权；平台 API Token 支持 CI/CD 集成 |
| **NEW** | **多租户沙箱引擎** | 用户级代码执行隔离——会话间零状态泄露 |
| **NEW** | **企业 SSO** | 内置 GitHub / Google / Microsoft 模板，支持 OIDC（Keycloak、Authentik、GitLab）与 JD SSO |
| **UPGRADE** | **DeepAgents v0.4** | 多智能体内核的最新稳定性与性能优化 |
| **UPGRADE** | **白盒可观测性** | 基于 Langfuse 实时追踪每一步 Agent 决策与状态流转 |

---

## 核心能力

<table>
<tr>
<td width="50%">

### 可视化构建 Agent

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

### 企业级就绪

- **多租户** —— 基于角色的工作区隔离
- **全链路审计** —— 执行追踪与合规治理
- **SSO 集成** —— GitHub、Google、Microsoft、OIDC、JD SSO
- **生产部署** —— Docker Compose 一键部署脚本

</td>
<td width="50%">

### AI 原生架构

- **DeepAgents** —— Manager-Worker 多层级智能体协作
- **记忆进化** —— 长短期记忆机制，越用越聪明
- **技能体系** —— 版本化、可复用的能力单元，渐进式披露
- **LangGraph 引擎** —— 基于图的工作流与完整状态管理

</td>
</tr>
</table>

> **项目背景：** 通用 LLM 在安全领域准确率不足，单 Agent 难以应对复杂安全场景。JoySafeter 通过 Multi-Agent 协作、认知进化引擎、场景化战力速配，实现了安全能力的规模化运营，率先定义了 **AI 驱动安全运营（AISecOps）** 新范式。

---

## 架构概览

> 详细架构：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)

<p align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter 架构图" width="800" />
</p>

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16, React 19, TypeScript | 服务端渲染, App Router |
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

## 文档

### 快速上手

- [INSTALL_CN.md](INSTALL_CN.md) — 安装指南（Docker / 手动 / 预构建镜像）
- [DEVELOPMENT.md](DEVELOPMENT.md) — 本地开发
- [deploy/README.md](deploy/README.md) — Docker 部署
- [deploy/PRODUCTION_IP_GUIDE.md](deploy/PRODUCTION_IP_GUIDE.md) — 生产环境部署

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

## 路线图

最新路线图与设计备忘请查看 [docs/plans/](docs/plans/) 与项目 Issues。

---

## 社区

如有问题或想与其他用户交流，欢迎扫码加入微信交流群：

<p align="center">
  <img src="docs/assets/wechat-group-3.png" alt="JoySafeter 用户交流群 1" width="300" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/assets/wechat-group-4.png" alt="JoySafeter 用户交流群 2" width="300" />
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

<p align="center">
  <sub>如需咨询商业方案，请联系京东科技解决方案团队，联系方式：<a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
