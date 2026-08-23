<h1 align="center">
  <img src="docs/assets/joysafter.png" alt="JoySafeter" width="80" /><br/>
  JoySafeter
</h1>

<p align="center">
  <strong>The open, self-hostable managed-agent platform for security.</strong><br/>
  <sub>Define an agent's tools, skills, and guardrails — JoySafeter runs it on your own hardened, observable infrastructure. From idea to production-grade security automation in minutes, not months.</sub>
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

The managed-agent operating model is the right one for autonomous work. But for **security** —
where you operate on client systems under NDA and run aggressive tooling — *where and how* the
agent runs is the whole decision. JoySafeter gives you that model **on your own infrastructure**:

- **Your data and targets never leave your infra.** Fully self-hosted: prompts, findings, captured
  traffic, and target details stay inside your network. No third party ever sees the engagement.
- **Network-contained execution.** Every session runs in a `NetworkMode=none` sandbox behind an
  Envoy proxy with a **deny-all-by-default egress allowlist** — offensive tools can't phone home or
  pivot into your network unless you explicitly permit it.
- **Publish-boundary skill supply-chain control.** Skills are code that runs in your environment;
  skillspector reports risks by default, and an optional global switch requires a fresh successful
  scan of the exact immutable snapshot before publication.
- **Engine-agnostic.** Claude Code, Codex, or the self-developed `ccb` engine behind one gRPC
  contract — not locked to a single vendor or model.

| | Cloud managed agents | Build it yourself | **JoySafeter** |
|---|---|---|---|
| Data / target residency | Vendor cloud | Yours | **Yours — fully self-hosted** |
| Engine / model | Single vendor | Whatever you wire | **Claude Code / Codex / native, per agent** |
| Network isolation | Vendor-managed | You build it | **Per-sandbox Envoy deny-all egress** |
| Skill & tool safety | Vendor-managed | You build it | **SkillSpector scan + optional publish gate** |
| Time to production | Days | Months | **Days, on your own hardware** |

> JoySafeter frames this as **AI-driven Security Operations (AISecOps)**: the managed-agent model
> — multi-step autonomy, sandboxed tools, sessions, full-chain observability — specialized for
> security and run entirely under your control.

---

## Real-World Cases

### Case 1 — APK Vulnerability Detection Agent

> Upload an APK. Get an OWASP Mobile Top 10 report. No engineer required.

<p align="center">
  <img src="docs/assets/APK-case.gif" alt="APK Vulnerability Detection Demo" width="800" />
</p>

> **This is a demo workflow, not a built-in integration.** The agent is configured with the
> `pentest-mobile-app` skill and a sandbox image carrying mobile-analysis tooling — you choose the tools.

**How it works:**

1. User uploads the APK file
2. The agent runs static analysis with the mobile tooling in its sandbox (e.g. MobSF)
3. Extracts critical risk signals — permission abuse, hardcoded secrets, insecure network config
4. Deep-validates high-severity findings via dynamic instrumentation (e.g. Frida)
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

> **Note:** Requires the matching agent runtime image for the selected engine. Local deployment
> uses `JOYSAFETER_IMAGE_CLAUDE`, `JOYSAFETER_IMAGE_CODEX`, and `JOYSAFETER_IMAGE_NATIVE` from
> `deploy/.env`; registry deployments can sync those values with `./deploy.sh pull --all`.

This dynamic decision-making — where the agent adapts its next step based on what it finds — is what fixed scripts cannot replicate.

---

## Core Capabilities — the managed-agent building blocks

You declare an agent — engine, model, system prompt, tools, skills, MCP servers, guardrails — and
JoySafeter runs it end-to-end on the same managed-agent building blocks Anthropic ships behind
Claude Managed Agents, only **self-hosted and security-specialized**:

<table>
<tr>
<td width="50%">

### 🧠 Managed harness & orchestration

- The **orchestrator** + gRPC `AgentBridge` + in-sandbox Rust `sandbox-runner` decide when to call tools, manage context, and recover from errors
- **DB-backed scheduling** — tasks claimed from Postgres with `FOR UPDATE SKIP LOCKED`, with retries and timeouts
- **Triggers** — auto-run an agent on a **cron** schedule, a one-off time, or an **inbound signed webhook** (HMAC / bearer / token); per-fire session modes (fresh / reuse / pinned / keyed), retry/backoff, and dead-letter auto-disable — [usage docs](backend/README.md#triggers-触发器)
- **Engine-agnostic** — Claude Code CLI, Codex app-server, or the self-developed `native` (`ccb`) harness, selected per agent

</td>
<td width="50%">

### 📦 Sandboxed execution

- Every session runs in its **own hardened container** — dropped capabilities, non-root, no-new-privileges
- **Pluggable providers** — Docker (default), E2B (Firecracker), Daytona, behind one SPI
- **Egress control** — per-sandbox Envoy proxy with a deny-all-by-default domain allowlist

</td>
</tr>
<tr>
<td width="50%">

### 🔧 Tools, custom tools & MCP

- Attach **builtin tools**, **custom tools** (name + JSON Schema), and **MCP servers** per agent
- MCP configs and credential-group members are resolved at run time and delivered to the sandbox over gRPC
- **Security skill packs** drive tools like **Nmap / Nuclei / Trivy** inside the sandbox image; connect any external tool via the **MCP protocol**

</td>
<td width="50%">

### 📚 Skills

- **30 versioned capability packs** — penetration testing, document analysis, planning/meta
- **SkillSpector security scanning** with advisory-by-default results and optional fail-closed enforcement only when publishing
- **AI skill authoring** — draft, edit, version, and diff skills with an LLM-assisted editor

</td>
</tr>
<tr>
<td width="50%">

### 💾 Sessions, memory & resume

- **Sessions** are persistent conversations with an **append-only, seq-ordered event log**
- **Memory stores** — versioned, agent-writable KV stores synced bi-directionally with the sandbox
- **Resumable** — reattach a session's harness + work dir on reconnect

</td>
<td width="50%">

### 🛡️ Scoped permissions & guardrails

- **Per-tool authorization** — `always_ask` / `always_allow`, with human-in-the-loop confirmation for high-risk tools
- **Encrypted credentials** — model, service, and MCP credentials use AES-256-GCM and are injected only into authorized runtimes
- **SSRF guard** — blocks cloud-metadata endpoints; opt-in private-range hardening

</td>
</tr>
<tr>
<td width="50%">

### 🔎 Full-chain observability

- **Live SSE event stream** of every message, thinking step, tool call, tool result, and model request
- **OpenTelemetry** traces + `observations` with token/cost aggregation, `trace_id` propagated end-to-end
- Append-only session event log doubles as a full **audit trail**

</td>
<td width="50%">

### 🏢 Multi-tenancy & access

- **Orgs / projects / RBAC** — isolated workspaces with role-based access control
- **SSO** — GitHub, Google, Microsoft, OIDC (Keycloak, Authentik, GitLab), JD SSO
- **Quickstart** — describe your goal in natural language and get a running agent in minutes

</td>
</tr>
</table>

---

## Quick Start

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

This is the only supported full-stack installation path. `local` selects the Docker daemon's
`amd64` or `arm64` architecture, builds the core services and default Claude Code runtime,
runs database migrations, and starts the complete stack.

Access points:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

See [INSTALL.md](INSTALL.md) for installation, [deploy/README.md](deploy/README.md) for builds and
deployment, and [DEVELOPMENT.md](DEVELOPMENT.md) for host-based development.

---

## Architecture

![JoySafeter managed-agent architecture](docs/architecture-diagram.png)

<sub>Overview infographic — ① control plane (REST · CLI) → ② Agent Harness (in-sandbox) → ③ Session state-layer. Interactive version: [`docs/architecture-diagram.html`](docs/architecture-diagram.html).</sub>

```mermaid
flowchart LR
    FE["Browser"] -->|"REST · SSE"| API["API service"]
    API -->|"rpush task"| RLIST[("Redis list<br/>global_queue")]
    RLIST -.->|"wakeup"| SCHED["Orchestrator<br/>scheduler (DB-authoritative)"]
    SCHED -->|"claim / provision"| SBX["Sandbox (NetworkMode=none)<br/>Rust runner + harness"]
    SBX <-->|"gRPC AgentBridge"| ENVOY["Envoy<br/>sole network conduit"]
    ENVOY <--> GRPC["Orchestrator gRPC :9090"]
    ENVOY -->|"egress allowlist"| EXT["Model API · MCP · targets"]
    GRPC -->|"harness events"| BUS["Two-phase event bus"]
    BUS -->|"① persist XADD"| RSTREAM[("Redis stream")]
    BUS -->|"② broadcast PUBLISH"| RPUB[("Redis pub/sub")]
    RSTREAM -->|"XREADGROUP"| WK["Worker → persist"]
    WK --> PG[("PostgreSQL")]
    WK -.->|"republish"| RPUB
    RPUB -->|"SessionBroadcaster"| API
    API -->|"SSE stream"| FE
```

> Full architecture (deployment topology, gRPC contract, engines, sandbox, event model,
> domain FSMs): **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · layered view:
> [docs/architecture-unified-event-model.mmd](docs/architecture-unified-event-model.mmd)

**Key design principles:**

- **Explicit service boundaries** — Python exposes `api` and `worker` roles; orchestration runs in the Rust `orchestrator-rs` service
- **DB is the source of truth for scheduling** — the API enqueues a task onto a Redis list as a wakeup signal; the orchestrator claims pending rows from Postgres with `FOR UPDATE SKIP LOCKED`
- **Decoupled persistence and live delivery** — a two-phase event bus fans out to Redis Streams (durable, consumed by the Worker → `joysafeter_session_events`) and Redis Pub/Sub (ephemeral, driving the SSE fan-out to the browser)
- **Live events over SSE** — the browser subscribes to `GET /api/v1/sessions/{id}/events/stream` (DB replay via `?after_seq`, then live); WebSocket is reserved for `/ws/notifications`
- **Sandboxed execution over gRPC** — agents never run in the orchestrator process; a Rust `sandbox-runner` inside a per-session container speaks the gRPC `AgentBridge` protocol back to the orchestrator
- **Pluggable engines** — `claude` (Claude Code CLI), `codex` (Codex app-server), and `native` (self-developed `ccb` binary), selected per agent by `engine_kind`
- **Pluggable sandboxes** — Docker (default, hardened), E2B, and Daytona providers behind one `SandboxProvider` SPI
- **Centralized state machines** — guarded FSMs for Task, Session, Sandbox, and Skill lifecycle
- **Normalized error system** — `AppError` produces a canonical `ErrorDescriptor` (`{code, message, data, source, retryable, user_action}`) consumed identically across HTTP and streaming paths
- **OTel-backed observation** — full-chain `trace_id` propagation with spans persisted to the database
- **Encrypted credentials** — model, service, and MCP credentials use unified encrypted storage and are injected into the sandbox at run time
- **Layered skill system** — publication requires approval; agents and runtime consume immutable published versions without rechecking mutable parent scan state

### User Journey — Quick Start

> **Login** → **Add a Model Connection** → **Configure Service or MCP Credentials** → **Skill Management** → **Build Agent** → **Open a Session** → **Chat & watch live events** → **Download report**

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript | Server-side rendering, product surface under `/managed/**` |
| **UI** | Radix UI, Tailwind CSS | Accessible component primitives |
| **State** | Zustand, TanStack Query | Client & server state |
| **Backend** | FastAPI 0.122+, Python 3.12+ | Async API and worker services; orchestration runs in the Rust `orchestrator-rs` service |
| **Agent runtime** | Rust `sandbox-runner` + Claude Code / Codex / `ccb` harness | Per-session sandboxed execution over gRPC `AgentBridge` |
| **MCP** | mcp 1.20+, fastmcp 2.14+ | Tool protocol support |
| **Database** | PostgreSQL, SQLAlchemy 2.0 | Async ORM with Alembic migrations |
| **Event bus / cache** | Redis (Streams · Pub/Sub · list) | Durable event stream, live SSE fan-out, task queue |
| **Egress control** | Envoy | Per-sandbox deny-all-by-default domain allowlist |
| **Observability** | OpenTelemetry, Loguru | Full-chain tracing & structured logging |

---

## Documentation

### Getting Started
- [INSTALL.md](INSTALL.md) — Unified installation entry point
- [DEVELOPMENT.md](DEVELOPMENT.md) — Local development setup
- [deploy/README.md](deploy/README.md) — Builds, image publishing, and deployment

### Deep Dive
- [docs/README.md](docs/README.md) — Documentation map
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Architecture overview
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) — Pre-release production gates
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
