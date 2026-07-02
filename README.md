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
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.122+-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs&logoColor=white" alt="Next.js 16"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-Protocol-purple" alt="MCP Protocol"></a>
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
| Penetration testing | Fixed scripts, static playbooks | Autonomous agents that adapt to findings in real time |
| Tool integration | Custom glue code per tool | Any tool via MCP Protocol, zero glue |
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
2. Choose an engine (Claude Code / Codex / native) and select penetration testing skills
3. Provide an authorized target URL and test requirements
4. Agent runs autonomously inside an isolated sandbox — if it discovers a login page, it automatically triggers auth bypass testing
5. Download the final report when the session completes

> **Note:** Requires sandbox image `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/ghcr.io/jd-opensource/joysafeter-sandbox:latest` configured in Sandbox Settings.

This dynamic decision-making — where the agent adapts its next step based on what it finds — is what fixed scripts cannot replicate.

---

## Core Capabilities

<table>
<tr>
<td width="50%">

### Agent Builder

- **Configure once, run anywhere** — an agent bundles an engine, model, system prompt, tools, skills, and MCP servers
- **Quickstart** — describe your goal in natural language and get a running agent in minutes
- **AI skill authoring** — draft, edit, and version skills with an LLM-assisted editor

</td>
<td width="50%">

### Security Tools, Ready to Use

- Pre-integrated security tooling such as **Nmap, Nuclei, Trivy**, and more
- **MCP Protocol** — extend with any tool via Model Context Protocol
- **30+ pre-built skills** — penetration testing, document analysis, planning/meta, and more

</td>
</tr>
<tr>
<td width="50%">

### Multi-Engine Execution

- **Pluggable engines** — Claude Code CLI, Codex app-server, and a self-developed `native` (`ccb`) engine, selected per agent
- **Isolated sandboxes** — every session runs in its own hardened container; providers include Docker (default), E2B, and Daytona
- **Skill system** — versioned, reusable capability packs with security scanning and progressive disclosure

</td>
<td width="50%">

### Enterprise Ready

- **Multi-tenancy** — isolated workspaces with role-based access control
- **Full audit trail** — append-only event log per session with full-chain tracing
- **SSO integration** — GitHub, Google, Microsoft, OIDC (Keycloak, Authentik, GitLab), JD SSO
- **Egress control** — per-sandbox Envoy proxy with deny-all-by-default domain allowlist

</td>
</tr>
</table>

---

## Quick Start

### Docker Compose (recommended)

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# Choose the orchestrator implementation by profile:
docker compose --profile python-orchestrator up -d --build
# or the Rust orchestrator:
# docker compose --profile rust-orchestrator up -d --build
```

Access points:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

The backend is a single codebase split into three services by the `JOYSAFETER_SERVICE_ROLE`
environment variable, deployed as separate containers:

- `api` — REST `/api/v1/*`, SSE event stream, notification WebSocket, auth.
- `orchestrator` — task scheduler, gRPC `AgentBridge`, and sandbox lifecycle.
- `worker` — consumes the Redis event stream and persists events to Postgres.

Supporting infrastructure: PostgreSQL, Redis, Envoy (per-sandbox egress proxy), and
skillspector (skill security scanner).

### Local test one-command startup

```bash
cd deploy
./local-test.sh
```

### Common deployment commands

```bash
./deploy/local-test.sh                     # local test one-command startup
./deploy/deploy.sh build                   # build frontend + backend images
./deploy/deploy.sh build --all             # build all images
```

> **Prerequisites:** Docker + Docker Compose. See [deploy/README.md](deploy/README.md) for deployment details.

---

## Architecture

<p align="center">
  <img src="docs/architecture-diagram.png" alt="JoySafeter System Architecture" width="900" />
</p>

> Full architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**Key design principles:**

- **Three services, one codebase** — `api`, `orchestrator`, and `worker` share a single codebase and select their behavior at boot from `JOYSAFETER_SERVICE_ROLE` (`all` runs everything in one process for local dev)
- **DB is the source of truth for scheduling** — the API enqueues a task onto a Redis list as a wakeup signal; the orchestrator claims pending rows from Postgres with `FOR UPDATE SKIP LOCKED`
- **Decoupled persistence and live delivery** — a two-phase event bus fans out to Redis Streams (durable, consumed by the Worker → `joysafeter_session_events`) and Redis Pub/Sub (ephemeral, driving the SSE fan-out to the browser)
- **Live events over SSE** — the browser subscribes to `GET /api/v1/sessions/{id}/events/stream` (DB replay via `?after_seq`, then live); WebSocket is reserved for `/ws/notifications`
- **Sandboxed execution over gRPC** — agents never run in the orchestrator process; a Rust `sandbox-runner` inside a per-session container speaks the gRPC `AgentBridge` protocol back to the orchestrator
- **Pluggable engines** — `claude` (Claude Code CLI), `codex` (Codex app-server), and `native` (self-developed `ccb` binary), selected per agent by `engine_kind`
- **Pluggable sandboxes** — Docker (default, hardened), E2B, and Daytona providers behind one `SandboxProvider` SPI
- **Centralized state machines** — guarded FSMs for Task, Session, Sandbox, and Skill lifecycle
- **Normalized error system** — `AppError` produces a canonical `ErrorDescriptor` (`{code, message, data, source, retryable, user_action}`) consumed identically across HTTP and streaming paths
- **OTel-backed observation** — full-chain `trace_id` propagation with spans persisted to the database
- **Encrypted credentials** — provider API keys live in Secrets and MCP credentials in Vaults, both AES-256-GCM encrypted and injected into the sandbox at run time
- **Layered skill system** — skills are versioned capability packs, security-scanned (fail-closed) before use

### User Journey — Quick Start

> **Login** → **Add provider keys (Secrets)** → **Configure MCP credentials (Vaults)** → **Skill Management** → **Build Agent** → **Open a Session** → **Chat & watch live events** → **Download report**

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript | Server-side rendering, product surface under `/managed/**` |
| **UI** | Radix UI, Tailwind CSS, Framer Motion | Accessible, animated components |
| **State** | Zustand, TanStack Query | Client & server state |
| **Backend** | FastAPI 0.122+, Python 3.12+ | Async API with OpenAPI docs, three services split by `JOYSAFETER_SERVICE_ROLE` |
| **Agent runtime** | Rust `sandbox-runner` + Claude Code / Codex / `ccb` harness | Per-session sandboxed execution over gRPC `AgentBridge` |
| **MCP** | mcp 1.20+, fastmcp 2.14+ | Tool protocol support |
| **Database** | PostgreSQL, SQLAlchemy 2.0 | Async ORM with Alembic migrations |
| **Event bus / cache** | Redis (Streams · Pub/Sub · list) | Durable event stream, live SSE fan-out, task queue |
| **Egress control** | Envoy | Per-sandbox deny-all-by-default domain allowlist |
| **Observability** | OpenTelemetry, Loguru | Full-chain tracing & structured logging |

---

## What's New

> Full history: [CHANGELOG.md](CHANGELOG.md)

| Tag | Feature | What it means |
|-----|---------|---------------|
| **NEW** | **Three-Service Architecture** | The single-process monolith was split into `api` / `orchestrator` / `worker`, one codebase selected by `JOYSAFETER_SERVICE_ROLE`, deployed as separate containers |
| **NEW** | **Redis-Backed Event Bus** | A two-phase bus fans out to Redis Streams (durable, Worker-consumed) and Redis Pub/Sub (live SSE), replacing the old in-process WebSocket bus |
| **NEW** | **SSE Live Event Stream** | The browser subscribes to `GET /api/v1/sessions/{id}/events/stream` with `?after_seq` replay; WebSocket is reserved for notifications |
| **NEW** | **Sandboxed gRPC Execution** | A Rust `sandbox-runner` runs the harness inside a per-session container and speaks the gRPC `AgentBridge` protocol back to the orchestrator |
| **NEW** | **Pluggable Engines** | `claude` (Claude Code CLI), `codex` (Codex app-server), and `native` (self-developed `ccb`), selected per agent |
| **NEW** | **Pluggable Sandboxes** | Docker (default, hardened), E2B, and Daytona providers behind one SPI |
| **NEW** | **AI Skill Authoring** | LLM-assisted skill drafting, a code editor, and version diffs in the workspace UI |
| **NEW** | **Secrets & Vaults** | AES-256-GCM encrypted provider API keys (Secrets) and MCP credentials (Vaults), injected into the sandbox at run time |
| **NEW** | **Skill Security Scanning** | Fail-closed skillspector gate scans every skill write before it can be used |
| **NEW** | **Per-Sandbox Egress Control** | Envoy proxy enforces a deny-all-by-default domain allowlist per sandbox |
| **NEW** | **Full-Chain trace_id Propagation** | End-to-end request tracing via OpenTelemetry for complete observability |

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
<td align="center"><a href="https://fastapi.tiangolo.com/"><img src="https://fastapi.tiangolo.com/img/icon-white.svg" width="48"/><br/><sub>FastAPI</sub></a></td>
<td align="center"><a href="https://nextjs.org/"><img src="https://assets.vercel.com/image/upload/v1662130559/nextjs/Icon_dark_background.png" width="48"/><br/><sub>Next.js</sub></a></td>
<td align="center"><a href="https://www.radix-ui.com/"><img src="https://avatars.githubusercontent.com/u/75042455?s=64" width="48"/><br/><sub>Radix UI</sub></a></td>
<td align="center"><a href="https://www.envoyproxy.io/"><img src="https://avatars.githubusercontent.com/u/13843634?s=64" width="48"/><br/><sub>Envoy</sub></a></td>
<td align="center"><a href="https://opentelemetry.io/"><img src="https://avatars.githubusercontent.com/u/49998002?s=64" width="48"/><br/><sub>OpenTelemetry</sub></a></td>
</tr>
</table>

---

<p align="center">
  <sub>Made with ❤️ by the JoySafeter Team</sub><br/>
  <sub>For commercial solutions, contact JD Technology Solutions Team at <a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
