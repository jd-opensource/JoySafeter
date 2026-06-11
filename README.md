<h1 align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter" width="80" /><br/>
  JoySafeter
</h1>

<p align="center">
  <strong>The AI-native platform for building, orchestrating, and running security agents at scale.</strong><br/>
  <sub>From idea to production-grade security automation — in minutes, not months.</sub>
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
  English | <a href="./README_CN.md">简体中文</a>
</p>

---

## Why JoySafeter

Traditional security tooling hits a ceiling: scripts are brittle, single agents lack context, and complex scenarios require 2–3 engineers working in parallel. JoySafeter breaks that ceiling.

| Challenge | Traditional Approach | JoySafeter |
|-----------|---------------------|------------|
| APK vulnerability analysis | Manual MobSF + engineer review | Autonomous agent: upload → analyze → report |
| Penetration testing | Fixed scripts, static playbooks | Dynamic DeepAgents that adapt to findings in real time |
| Tool integration | Custom glue code per tool | 200+ tools via MCP Protocol, zero glue |
| Scale | Linear headcount growth | Agent teams that multiply capacity |

> JoySafeter defines a new paradigm: **AI-driven Security Operations (AISecOps)** — where multi-agent collaboration, cognitive memory, and scenario-matched skills replace manual coordination.

---

## Real-World Cases

### Case 1 — APK Vulnerability Detection Agent

> Upload an APK. Get an OWASP Mobile Top 10 report. No engineer required.

<p align="center">
  <img src="docs/assets/APK-case.gif" alt="APK Vulnerability Detection Demo" width="800" />
</p>

**How it works:**

1. User uploads the APK file
2. Agent invokes MobSF for static analysis
3. Extracts critical risk signals — permission abuse, hardcoded secrets, insecure network config
4. Deep-validates high-severity findings via Frida dynamic instrumentation
5. Auto-generates a structured report aligned to OWASP Mobile Top 10

The entire flow — from upload to report — requires zero manual intervention, covering work that traditionally takes 2–3 security engineers.

---

### Case 2 — Penetration Testing Agent

> Describe the target and scope. The agent plans, executes, and adapts — then delivers a report.

<p align="center">
  <img src="docs/assets/pentest-case.gif" alt="Penetration Testing Agent Demo" width="800" />
</p>

**How it works:**

1. Open the Workbench and create a new agent
2. Enable **DeepAgents mode** → select penetration testing skills
3. Provide an authorized target URL and test requirements
4. Agent runs autonomously — if it discovers a login page, it automatically triggers auth bypass testing
5. Download the final report when the run completes

> **Note:** Requires sandbox image `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/ghcr.io/jd-opensource/joysafeter-sandbox:latest` configured in Sandbox Settings.

This dynamic decision-making — where the agent adapts its next step based on what it finds — is what fixed scripts cannot replicate.

---

## Core Capabilities

<table>
<tr>
<td width="50%">

### Visual Agent Builder

- **No-code workflow editor** — drag-and-drop nodes with loops, conditionals, and parallel execution
- **Rapid Mode** — describe in natural language, get a running agent team in minutes
- **Deep Mode** — visual debugging and step-by-step observability for complex security research

</td>
<td width="50%">

### 200+ Security Tools, Ready to Use

- Pre-integrated **Nmap, Nuclei, Trivy**, and more
- **MCP Protocol** — extend with any tool via Model Context Protocol
- **30+ pre-built skills** — penetration testing, document analysis, cloud security, and more

</td>
</tr>
<tr>
<td width="50%">

### DeepAgents Orchestration

- **Manager-Worker multi-level** agent collaboration
- **Memory evolution** — long/short-term memory for continuous learning across sessions
- **Skill system** — versioned, reusable capability units with progressive disclosure
- **LangGraph engine** — graph-based workflows with full state management

</td>
<td width="50%">

### Enterprise Ready

- **Multi-tenancy** — isolated workspaces with role-based access control
- **Full audit trail** — execution tracing and compliance governance
- **SSO integration** — GitHub, Google, Microsoft, OIDC (Keycloak, Authentik, GitLab), JD SSO
- **Multi-tenant sandbox** — per-user isolated code execution, zero state leakage

</td>
</tr>
</table>

---

## Quick Start

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

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

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
./deploy/deploy.sh build                   # 构建 frontend + backend 镜像
./deploy/deploy.sh build --all             # 构建全部镜像
```

> **Prerequisites:** Docker + Docker Compose. See [deploy/README.md](deploy/README.md) for deployment details.

---

## Architecture

<p align="center">
  <img src="docs/architecture-diagram.png" alt="JoySafeter System Architecture" width="900" />
</p>

> Full architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**Key design principles:**

- **Single source of truth for value domains** — `core/contracts/` defines every canonical value (status, error code, trigger source) as Literal types + set constants; no magic strings
- **Engine protocol + registry** — all execution engines implement `ExecutionEngine` Protocol; `EngineRegistry` maps `runtime_kind` to engine instances; adding a new engine is a 3-file change
- **Two-phase event bus** — Phase 1 (persistence + state transition) shares a DB transaction and commits atomically; Phase 2 (WebSocket + task sync) fans out in parallel
- **Centralized state machines** — 6 entity state machines (`Agent`, `Version`, `Release`, `Run`, `Execution`, `Task`) with `transition_*()` as the only status-mutation functions
- **Normalized error system** — `AppError.to_payload()` produces a canonical `ErrorDescriptor` (`{code, message, data, source, retryable, user_action}`) consumed identically across HTTP, WebSocket, SSE, and DB
- **Port/Adapter boundaries** — `core/ports/` defines Protocol interfaces; `services/` provides implementations; `core/` never imports concrete services
- **OTel-backed observation** — `ObservationCollector` injected into `ExecutionContext`; spans exported to both DB and WebSocket for real-time trace display
- **Graph-based execution** — every agent workflow is a stateful LangGraph, enabling pause, resume, and branch
- **Unified WebSocket layer** — BaseWsClient abstract class; Execution / Notification clients share lifecycle, auth (ws-token), and reconnect logic
- **RAII sandbox isolation** — per-user Docker containers with automatic handle release, zero state leakage
- **Canonical model identifiers** — full-stack (provider_name, model_name) resolution via ModelService → ModelFactory
- **Layered skill system** — skills are versioned units that compose into workflows without coupling

### User Journey — Quick Start in 9 Steps

<p align="center">
  <img src="docs/user-journey-quickstart.png" alt="JoySafeter Quick Start User Journey" width="900" />
</p>

> **Login** → **Configure Models** → **MCP Tools** → **Skill Management** → **Build Agent** → **Self-Test (Langfuse Trace)** → **Publish** → **Chat UI** → **Run Center**

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Next.js 16, React 19, TypeScript | Server-side rendering, App Router |
| **UI** | Radix UI, Tailwind CSS, Framer Motion | Accessible, animated components |
| **State** | Zustand, TanStack Query | Client & server state |
| **Workflow Editor** | React Flow | Interactive node-based builder |
| **Backend** | FastAPI, Python 3.12+ | Async API with OpenAPI docs |
| **AI Framework** | LangChain, LangGraph, DeepAgents | Agent orchestration & workflows |
| **MCP** | mcp 1.20+, fastmcp 2.14+ | Tool protocol support |
| **Database** | PostgreSQL, SQLAlchemy 2.0 | Async ORM with migrations |
| **Cache** | Redis | Session cache & rate limiting |
| **Observability** | Langfuse, Loguru | Tracing & structured logging |

---

## What's New

> Full history: [CHANGELOG.md](CHANGELOG.md)

| Tag | Feature | What it means |
|-----|---------|---------------|
| **NEW** | **Architecture Hardening** | 5-layer execution architecture with Engine Protocol, EngineRegistry, two-phase EventBus, centralized state machines, and Port/Adapter boundaries |
| **NEW** | **Unified Error Contract** | `AppError.to_payload()` produces canonical `ErrorDescriptor` consumed identically across HTTP, WS, SSE, and DB; frontend `ApiError` mirrors the shape with typed `source`/`retryable`/`userAction` |
| **NEW** | **State Machine Centralization** | 6 entity state machines (`Agent`, `Version`, `Release`, `Run`, `Execution`, `Task`) with `transition_*()` as the only status-mutation functions |
| **NEW** | **Observation Tracing** | OTel-backed `ObservationCollector` injected into `ExecutionContext`; spans exported to DB and WebSocket for real-time trace display |
| **NEW** | **Run Center Architecture** | Chat & Copilot fully integrated into Run Center — run details, session recovery, and live event replay on page refresh |
| **NEW** | **Dark Mode & Preferences** | System / Light / Dark theme switching; redesigned profile page with language & theme preferences |
| **NEW** | **Unified WebSocket Layer** | BaseWsClient abstract class — Chat, Run, and Notification clients share lifecycle, auth (ws-token), and reconnect logic |
| **NEW** | **Full-Chain trace_id Propagation** | End-to-end request tracing via contextvars for complete observability |
| **NEW** | **Ollama One-Click Integration** | Local Ollama model provider added out of the box |
| **NEW** | **Version Display** | In-app version info tied to bump-version.sh release pipeline |
| **NEW** | **Unified Model Identifiers** | Full-stack (provider_name, model_name) canonical form with data migration — no more legacy field ambiguity |
| **UPGRADE** | **Design Token Overhaul** | Hardcoded colors, font sizes, and border radii replaced with CSS variables and Tailwind tokens; z-index and typography scales unified |
| **UPGRADE** | **Sandbox Overhaul** | RAII handle management, adapter API uploads, security hardening |
| **UPGRADE** | **Frontend Component Extraction** | ConfirmDialog, UnifiedDialog, InlineRenameInput, SidebarContextMenu, AgentListContext — less prop drilling, more reuse |
| **UPGRADE** | **i18n & Code Quality** | Backend error messages internationalized; email templates moved to Jinja2; LLM prompts externalized to Markdown; 129 unused SVG icons removed |

---

## Documentation

### Getting Started
- [INSTALL.md](INSTALL.md) — Installation guide (Docker / manual / pre-built images)
- [DEVELOPMENT.md](DEVELOPMENT.md) — Local development setup
- [deploy/README.md](deploy/README.md) — Docker deployment

### Deep Dive
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Architecture overview
- [backend/README.md](backend/README.md) — Backend guide
- [frontend/README.md](frontend/README.md) — Frontend guide

### Tutorials
See [docs/tutorials/](docs/tutorials/) for step-by-step guides on model setup, MCP integration, skill development, and more.

### Governance
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributing guide
- [SECURITY.md](SECURITY.md) — Security policy
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — Code of conduct

---

## Community

Join the WeChat user group for questions and discussion:

<p align="center">
  <img src="docs/assets/wechat-group-3.png" alt="JoySafeter User Group 3" width="280" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/assets/wechat-group-4.png" alt="JoySafeter User Group 4" width="280" />
</p>

---

## Contributing

```bash
git clone https://github.com/jd-opensource/JoySafeter.git
git checkout -b feature/amazing-feature
git commit -m 'feat: add amazing feature'
git push origin feature/amazing-feature
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

Third-party component licenses: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

---

## Acknowledgments

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
  <sub>Made with ❤️ by the JoySafeter Team</sub><br/>
  <sub>For commercial solutions, contact JD Technology Solutions Team at <a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
