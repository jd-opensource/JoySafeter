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

### One-Click Launch (Recommended)

```bash
./deploy/quick-start.sh
```

The script provides an interactive menu to choose your startup mode and customize ports (with conflict detection):

| Mode | Description | Ports Configured |
|------|-------------|-----------------|
| **(1) Docker Compose Full Stack** | All services in containers, supports localhost or remote server IP/domain | Frontend, Backend, PostgreSQL, Redis |
| **(2) Local Frontend Only** | `bun run dev`, supports connecting to remote backend | Frontend (can specify remote backend address) |
| **(3) Local Backend Only** | `uvicorn --reload`, supports remote DB/Redis | Backend (can specify remote DB/Redis/frontend address) |
| **(4) Local Frontend + Backend** | Auto-starts middleware, supports exposing via non-localhost address | Frontend, Backend |

All modes support remote deployment scenarios:
- **Docker Compose Full Stack** — choose deployment address (localhost or IP/domain) + http/https
- **Local Frontend Only** — optionally connect to a remote backend API (enter backend IP + port + protocol)
- **Local Backend Only** — optionally connect to remote PostgreSQL, Redis, and frontend (enter each address and port)
- **Local Frontend + Backend** — optionally expose services via a non-localhost address
- Non-localhost deployments automatically update `frontend/.env` CSP whitelist (`NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA`)

```bash
./deploy/quick-start.sh --skip-env       # Skip .env file initialization
./deploy/quick-start.sh --skip-db-init   # Skip database initialization
```

### Launch by Scenario

```bash
# ─── Development ────────────────────────────────────────
./deploy/scripts/dev.sh                  # Docker full-stack dev (containerized frontend + backend)
./deploy/scripts/dev-local.sh            # Local dev prep (start middleware, run backend/frontend on host)
./deploy/scripts/dev-backend.sh          # Local backend only (requires middleware running)
./deploy/scripts/dev-frontend.sh         # Local frontend only (requires backend running)

# ─── Production ─────────────────────────────────────────
./deploy/scripts/prod.sh                 # Production deploy (pre-built images + docker-compose.prod.yml)
./deploy/scripts/prod.sh --skip-mcp      # Production without MCP service
./deploy/scripts/prod.sh --skip-pull     # Skip image pull, use local images

# ─── Middleware / Infrastructure ────────────────────────
./deploy/scripts/start-middleware.sh     # Start middleware (PostgreSQL + Redis + MCP)
./deploy/scripts/minimal.sh             # Minimal startup (PostgreSQL + Redis only)
./deploy/scripts/minimal.sh --with-mcp  # Minimal + MCP service
./deploy/scripts/stop-middleware.sh      # Stop middleware

# ─── Test / CI ──────────────────────────────────────────
./deploy/scripts/test.sh                 # Test environment (minimal deps, automation-friendly)

# ─── Install / Check ───────────────────────────────────
./deploy/install.sh                      # Interactive installation wizard (generates config files)
./deploy/install.sh --mode dev --non-interactive  # Non-interactive install
./deploy/scripts/check-env.sh           # Environment preflight (Docker, ports, config files)

# ─── Image Management ──────────────────────────────────
./deploy/deploy.sh build                 # Build frontend + backend images
./deploy/deploy.sh build --all           # Build all images (including OpenClaw)
./deploy/deploy.sh push                  # Build and push to registry
./deploy/deploy.sh pull                  # Pull latest pre-built images
```

### Default Ports

| Service | Port | URL |
|---------|------|-----|
| Frontend | `3000` | http://localhost:3000 |
| Backend API | `8000` | http://localhost:8000 |
| API Docs | `8000/docs` | Swagger UI |
| PostgreSQL | `5432` | Database |
| Redis | `6379` | Cache |

> **Prerequisites:** Docker + Docker Compose. See [INSTALL.md](INSTALL.md) for detailed installation guide, [deploy/PRODUCTION_IP_GUIDE.md](deploy/PRODUCTION_IP_GUIDE.md) for production deployment.

---

## Architecture

<p align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter Architecture" width="800" />
</p>

> Full architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**Key design principles:**

- **Graph-based execution** — every agent workflow is a stateful LangGraph, enabling pause, resume, and branch
- **Glass-box observability** — real-time Langfuse tracing of every agent decision and state transition
- **Layered skill system** — skills are versioned units that compose into workflows without coupling

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
| **NEW** | **Model Settings Master-Detail** | Redesigned model management page — provider sidebar + detail panel, schema-driven forms, one-click custom model setup |
| **NEW** | **Model Usage Stats** | Per-model usage logging with StatsTab visualization and SSE test-stream endpoint |
| **NEW** | **Custom Provider API** | Single `POST /model-providers/custom` endpoint creates provider + credential + model instance in one call |
| **NEW** | **Skill Versioning & Collaboration** | Publish, rollback, manage skill versions; invite collaborators with role-based permissions; platform API tokens for CI/CD |
| **NEW** | **Multi-Tenant Sandbox Engine** | Per-user isolated code execution — zero state leakage between sessions |
| **NEW** | **Enterprise SSO** | Built-in GitHub / Google / Microsoft templates, plus OIDC and JD SSO |
| **UPGRADE** | **DeepAgents v0.4** | Latest stability and performance improvements for the multi-agent kernel |
| **UPGRADE** | **Glass-Box Observability** | Real-time Langfuse tracing of every agent decision and state transition |

---

## Documentation

### Getting Started
- [INSTALL.md](INSTALL.md) — Installation guide (Docker / manual / pre-built images)
- [DEVELOPMENT.md](DEVELOPMENT.md) — Local development setup
- [deploy/README.md](deploy/README.md) — Docker deployment
- [deploy/PRODUCTION_IP_GUIDE.md](deploy/PRODUCTION_IP_GUIDE.md) — Production deployment

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
  <img src="docs/assets/wechat-group-3.png" alt="JoySafeter User Group 1" width="280" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/assets/wechat-group-4.png" alt="JoySafeter User Group 2" width="280" />
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
