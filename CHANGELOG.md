# Changelog

All notable changes to JoySafeter are documented in this file.

---

## 2026-03 — Skill Platform & Enterprise Identity

### Core Capabilities

- **Skill Versioning & Collaboration**
  - Publish, rollback, and browse skill version history
  - Invite collaborators with role-based permissions (owner / editor / viewer)
  - Ownership transfer with safety checks
  - Platform API tokens for CI/CD and programmatic access

- **Extensible Skill Protocol**
  - Established the `SKILL.md` standard with a "Progressive Disclosure" architecture
  - Dynamic loading of skill metadata, instructions, and resources to optimize context window usage

### System Architecture

- **Multi-Tenant Sandbox Engine**
  - Strict per-user isolation for code execution environments (OpenClaw)
  - Guarantees data sovereignty and prevents state leakage between concurrent sessions

- **Glass-Box Observability**
  - Deep Langfuse integration for real-time execution tracing
  - Visualize agent decision-making process and state transitions

### Enterprise & Infrastructure

- **Enterprise SSO Integration**
  - Built-in templates for GitHub, Google, and Microsoft
  - Configurable OIDC providers: Keycloak, Authentik, GitLab
  - JD SSO support
  - See `backend/config/oauth_providers.yaml` and `backend/config/README_OAUTH_LOCAL.md`

- **Secure Runtime Transition**
  - Deprecated legacy insecure execution paths
  - All dynamic code operations enforced through Sandbox architecture

- **DeepAgents Kernel v0.4.0**
  - Latest stability improvements and performance optimizations

- **Meta-Cognitive Superpowers**
  - Structured reasoning capabilities: Brainstorming, Strategic Planning, and Execution
  - Formalizes the "thinking process" into executable semantic skills
