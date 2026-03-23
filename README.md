<!-- Logo image placeholder - add docs/assets/logo.png when available -->
<!-- <p align="center">
  <img src="docs/assets/logo.png" alt="JoySafeter" width="120" />
</p> -->

<h1 align="center">JoySafeter</h1>

<p align="center">
  <strong>Visual platform for building, orchestrating, and running AI security agents — from idea to production in minutes.</strong>
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
  English | <a href="./README_CN.md">简体中文</a>
</p>

<!-- Screenshot / GIF placeholder — replace with actual product screenshot -->
<!-- <p align="center">
  <img src="docs/assets/screenshot-builder.png" alt="Agent Builder Screenshot" width="800" />
</p> -->

---

## Quick Start

Get JoySafeter running in one command:

```bash
./deploy/quick-start.sh
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

> **Prerequisites:** Docker + Docker Compose. See [INSTALL.md](INSTALL.md) for manual setup or pre-built images.

---

## What's New

> Full history: [CHANGELOG.md](CHANGELOG.md)

| Tag | Feature | What it means |
|-----|---------|---------------|
| **NEW** | **Skill Versioning & Collaboration** | Publish, rollback, and manage skill versions; invite collaborators with role-based permissions; platform API tokens for CI/CD integration |
| **NEW** | **Multi-Tenant Sandbox Engine** | Per-user isolated code execution — no state leakage between sessions |
| **NEW** | **Enterprise SSO** | Built-in GitHub / Google / Microsoft templates, plus OIDC (Keycloak, Authentik, GitLab) and JD SSO |
| **UPGRADE** | **DeepAgents v0.4** | Latest stability improvements and performance optimizations for the multi-agent kernel |
| **UPGRADE** | **Glass-Box Observability** | Real-time Langfuse tracing of every agent decision and state transition |

---

## Key Features

<table>
<tr>
<td width="50%">

### Build Agents Visually

- **No-code workflow builder** — drag-and-drop nodes with loops, conditionals, and parallel execution
- **Rapid Mode** — describe what you need in natural language, get a running agent team in minutes
- **Deep Mode** — fine-tune workflows with visual debugging and step-by-step observability

</td>
<td width="50%">

### 200+ Security Tools Built In

- Pre-integrated **Nmap, Nuclei, Trivy**, and more
- **MCP Protocol** — extend with any tool via Model Context Protocol
- **30+ pre-built skills** — penetration testing, document analysis, cloud security, and more

</td>
</tr>
<tr>
<td width="50%">

### Enterprise Ready

- **Multi-tenancy** — isolated workspaces with role-based access
- **Full audit trail** — execution tracing and governance
- **SSO integration** — GitHub, Google, Microsoft, OIDC, JD SSO
- **Production deployment** — Docker Compose with one-click scripts

</td>
<td width="50%">

### AI-Native Architecture

- **DeepAgents** — manager-worker multi-level agent orchestration
- **Memory evolution** — long/short-term memory for continuous learning
- **Skill system** — versioned, reusable capability units with progressive disclosure
- **LangGraph engine** — graph-based workflows with full state management

</td>
</tr>
</table>

---

## Architecture

> Detailed architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

<p align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter Architecture" width="800" />
</p>

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

## Roadmap

See [docs/plans/](docs/plans/) and project issues for the latest roadmap and design notes.

---

## Community

Join the WeChat user group if you have questions or want to connect with other users:

<p align="center">
  <img src="docs/assets/web-chat-group.jpg" alt="JoySafeter User Group" width="300" />
</p>

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

```bash
# Fork and clone
git clone https://github.com/jd-opensource/JoySafeter.git

# Create feature branch
git checkout -b feature/amazing-feature

# Make changes and commit
git commit -m 'feat: add amazing feature'

# Push and create PR
git push origin feature/amazing-feature
```

---

## License

This project is licensed under the **Apache License 2.0** — see the [LICENSE](LICENSE) file for details.

> **Note:** This project includes third-party components with different licenses. See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for details.

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
  <sub>Made with ❤️ by the JoySafeter Team</sub>
</p>

<p align="center">
  <sub>For commercial solutions, please contact JD Technology Solutions Team at <a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
