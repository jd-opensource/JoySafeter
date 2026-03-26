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

## 架构概览

<p align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter 架构图" width="800" />
</p>

> 详细架构：[docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)

**核心设计原则：**

- **图式执行** —— 每个 Agent 工作流都是有状态的 LangGraph，支持暂停、恢复与分支
- **白盒可观测性** —— 基于 Langfuse 实时追踪每一步 Agent 决策与状态流转
- **分层技能体系** —— 技能是版本化单元，可自由组合成工作流，互不耦合

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
| **NEW** | **技能版本化与协作** | 发布、回滚、管理技能版本；邀请协作者并按角色授权；平台 API Token 支持 CI/CD 集成 |
| **NEW** | **多租户沙箱引擎** | 用户级代码执行隔离——会话间零状态泄露 |
| **NEW** | **企业 SSO** | 内置 GitHub / Google / Microsoft 模板，支持 OIDC 与 JD SSO |
| **UPGRADE** | **DeepAgents v0.4** | 多智能体内核的最新稳定性与性能优化 |
| **UPGRADE** | **白盒可观测性** | 基于 Langfuse 实时追踪每一步 Agent 决策与状态流转 |

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

## 社区

如有问题或想与其他用户交流，欢迎扫码加入微信交流群：

<p align="center">
  <img src="docs/assets/wechat-group-3.png" alt="JoySafeter 用户交流群 1" width="280" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/assets/wechat-group-4.png" alt="JoySafeter 用户交流群 2" width="280" />
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
