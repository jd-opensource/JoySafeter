<!-- Logo image placeholder - add docs/assets/logo.png when available -->
<!-- <p align="center">
  <img src="docs/assets/logo.png" alt="JoySafeter" width="120" />
</p> -->

<h1 align="center">JoySafeter</h1>

<p align="center">
  <strong>Build Production-Grade AI Security Agents in 3 Minutes</strong>
</p>

<p align="center">
  Enterprise-grade intelligent agent orchestration platform with SOTA security capabilities
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

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

<!-- Screenshot placeholder - add docs/assets/screenshot-builder.png when available -->
<!-- <p align="center">
  <img src="docs/assets/screenshot-builder.png" alt="Agent Builder Screenshot" width="800" />
</p> -->

## Table of Contents

- [Why JoySafeter?](#why-joysafeter)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Why JoySafeter?

> **JoySafeter is not just a productivity tool, but an "operating system" for security capabilities.**
> It unifies fragmented security tools into a collaborative AI army through visual intelligent orchestration, and precipitates individual expert experience into organizational digital assets. It is the first to define a new paradigm of **AI-driven Security Operations (AISecOps)** in the industry.

<table>
<tr>
<td width="50%">

### For Enterprise Security Teams

- **Visual Development** — No-code agent builder for rapid prototyping
- **200+ Security Tools** — Pre-integrated Nmap, Nuclei, Trivy, and more
- **Governance & Audit** — Full execution tracing and observability
- **Multi-tenancy** — Isolated workspaces with role-based access

</td>
<td width="50%">

### For AI Security Researchers

- **Graph-based Workflows** — Complex control flows with loops, conditionals, and parallel execution
- **Memory Evolution** — Long/short-term memory for continuous learning
- **MCP Protocol** — Model Context Protocol for unlimited tool extensibility
- **DeepAgents Mode** — Multi-level hierarchical agent orchestration

</td>
</tr>
</table>

---

## Features

JoySafeter is an enterprise-grade AI security agent orchestration platform, featuring:

- **Rapid Mode**: Natural language → auto-orchestrated agent teams → runnable workflow in minutes
- **Deep Mode**: Visual workflow builder + debugging + observability for complex, iterative security research
- **Skills**: Pre-built security skills and a scalable skill system (progressive disclosure)
- **Multi-agent orchestration**: DeepAgents manager-worker star topology
- **Observability**: Streaming execution + tracing (Langfuse)
- **Deployment**: Production-ready Docker deployment and scenario scripts

For detailed feature descriptions and the technical matrix, see:
- Architecture overview: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Developer details: [DEVELOPMENT.md](DEVELOPMENT.md)

---


## Architecture

See: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Recent Change Log

### Core Capabilities
- **Meta-Cognitive Superpowers**: Introduced structured reasoning capabilities including Brainstorming, Strategic Planning, and Execution. This elevates the agent from simple task execution to complex problem-solving by formalizing the "thinking process" into executable semantic skills.
- **Extensible Skill Protocol**: Established the `SKILL.md` standard with a "Progressive Disclosure" architecture. This mechanism optimizes context window usage by dynamically loading skill metadata, instructions, and resources only when needed, turning the agent into an infinitely validatable platform.

### System Architecture
- **Multi-Tenant Sandbox Engine**: Implemented strict per-user isolation for code execution environments. This enterprise-grade security feature guarantees data sovereignty and prevents state leakage between concurrent user sessions.
- **Glass-Box Observability**: Integrated deep visualization of agent execution traces with Langfuse. Users can now observe the real-time decision-making process and state transitions, providing full transparency into the agent's "thought process".

### Optimization & Infrastructure
- **Secure Runtime Transition**: Deprecated legacy insecure execution paths, enforcing the new Sandbox architecture for all dynamic code operations.
- **Enterprise Identity Integration**: Standardized Single Sign-On (SSO) protocols with built-in templates for GitHub, Google, and Microsoft, plus configurable OIDC providers (Keycloak, Authentik, GitLab) and JD SSO support. See backend/config/oauth_providers.yaml and backend/config/README_OAUTH_LOCAL.md.
- **Core Kernel Upgrade**: Upgraded `deepagents` kernel to v0.4.0, incorporating the latest stability improvements and performance optimizations.


---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Next.js 16, React 19, TypeScript | Server-side rendering, App Router |
| **UI Components** | Radix UI, Tailwind CSS, Framer Motion | Accessible, animated components |
| **State Management** | Zustand, TanStack Query | Client & server state |
| **Graph Visualization** | React Flow | Interactive node-based editor |
| **Backend** | FastAPI, Python 3.12+ | Async API with OpenAPI docs |
| **AI Framework** | LangChain 1.2+, LangGraph 1.0+, DeepAgents | Agent orchestration & workflows |
| **MCP Integration** | mcp 1.20+, fastmcp 2.14+ | Tool protocol support |
| **Database** | PostgreSQL, SQLAlchemy 2.0 | Async ORM with migrations |
| **Caching** | Redis | Session cache & rate limiting |
| **Observability** | Langfuse, Loguru | Tracing & structured logging |

---

## Quick Start

### Prerequisites

- Docker + Docker Compose (recommended for first-time users)
- Python 3.12+ and Node.js 20+ (only if you plan to run backend/frontend locally)

### One-Click Run (Docker, Recommended)

```bash
./deploy/quick-start.sh
```

### Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |

### Next Steps

- Full installation options (manual deploy / pre-built images): [INSTALL.md](INSTALL.md)
- Local development: [DEVELOPMENT.md](DEVELOPMENT.md)
- Production deployment guide: [deploy/README.md](deploy/README.md) and [deploy/PRODUCTION_IP_GUIDE.md](deploy/PRODUCTION_IP_GUIDE.md)

## Roadmap

See [docs/plans/](docs/plans/) and project issues for the latest roadmap and design notes.

---


---

## Documentation

### Start here

- Installation: [INSTALL.md](INSTALL.md)
- Development: [DEVELOPMENT.md](DEVELOPMENT.md)
- Deployment (Docker): [deploy/README.md](deploy/README.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

### Submodules

- Backend: [backend/README.md](backend/README.md)
- Frontend: [frontend/README.md](frontend/README.md)

### Project governance

- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---



## Community

Join the WeChat user group if you have questions or want to connect with other users:

<p align="center">
  <img src="docs/assets/web-chat-group.jpg" alt="JoySafeter User Group" width="300" />
</p>

## Contributing

We welcome contributions from the community! See our [Contributing Guide](CONTRIBUTING.md) for details.

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

---

<p align="center">
  <sub>For commercial solutions, please contact JD Technology Solutions Team at <a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
