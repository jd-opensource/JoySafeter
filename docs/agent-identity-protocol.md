# Agent Identity Provider

## Overview

JoySafeter supports **pluggable agent identity injection** for outbound requests. When enabled, the platform automatically injects identity headers into HTTP requests from the sandbox to downstream services via the Envoy egress proxy.

This enables downstream systems to identify:
- **Which agent** is making the request
- **On behalf of which user** the agent is acting

The sandbox itself **never sees these credentials** — they are injected at the Envoy egress boundary.

## Architecture

```
                 Orchestrator (server-side only)
┌────────────────────────────────────────────────────────┐
│                                                        │
│  session.metadata.agent_identity_context               │
│    └→ identity_token (encrypted)                       │
│    └→ user_name                                        │
│                                                        │
│  AgentIdentityProvider.resolve()                       │
│    └→ BotToken (cached in Redis, never downstream)     │
│    └→ agentToken (short-lived)                         │
│    └→ SSO ticket / ME token (short-lived)              │
│                                                        │
│  → EgressCredentialRoute[]                             │
│    └→ inject_headers: [X-Security-AgentToken, Cookie]  │
│                                                        │
└────────────────────────────────────────────────────────┘
                         │
                         ▼ (Envoy xDS push)
┌────────────────────────────────────────────────────────┐
│                 Envoy Proxy                             │
│  match_host → inject headers → TLS originate → upstream│
└────────────────────────────────────────────────────────┘
                         ↑
┌────────────────────────────────────────────────────────┐
│            Sandbox (Agent runtime)                      │
│  fetch("https://api.example.com/...")                   │
│  → Envoy auto-injects identity headers                 │
│  → Agent code is completely unaware                    │
└────────────────────────────────────────────────────────┘
```

## Implementing a Custom Provider

The open-source core defines the `AgentIdentityProvider` trait in `crates/agent-identity-trait/src/lib.rs`. Implement this trait to integrate your own identity platform:

```rust
use agent_identity_trait::*;
use async_trait::async_trait;

#[derive(Debug)]
pub struct MyIdentityProvider { /* ... */ }

#[async_trait]
impl AgentIdentityProvider for MyIdentityProvider {
    fn name(&self) -> &str { "my-provider" }
    fn enabled(&self) -> bool { true }

    fn has_config(&self, agent_metadata: Option<&serde_json::Value>) -> bool {
        // Check if agent.metadata contains your provider's config
        agent_metadata
            .and_then(|m| m.get("my_identity"))
            .is_some()
    }

    async fn resolve(&self, ctx: &IdentityResolveContext) -> anyhow::Result<AgentIdentityInjection> {
        // 1. Use ctx.identity_token to bootstrap your token exchange
        // 2. Cache long-lived tokens, exchange for short-lived ones
        // 3. Return per-host injection headers
        Ok(AgentIdentityInjection {
            targets: vec![
                IdentityEgressTarget {
                    host: "api.example.com".to_string(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![
                        ("Authorization".to_string(), format!("Bearer {}", my_token)),
                    ],
                    remove_headers: vec!["authorization".to_string()],
                }
            ],
        })
    }

    async fn cleanup(&self, ctx: &IdentityCleanupContext) {
        // Revoke cached tokens when agent is deleted
    }
}
```

## Agent Configuration

Provider-specific config goes in `agent.metadata.agent_identity`:

```json
{
  "metadata": {
    "agent_identity": {
      "enabled": true,
      "platform_id": "my-platform",
      "sso_targets": ["sso-api.example.com"],
      "me_targets": ["me-api.example.com"],
      "agent_token_targets": ["gateway.example.com"]
    }
  }
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_IDENTITY_BASE_URL` | No | Identity platform API base URL. Empty = feature disabled |
| `REDIS_URL` / `REDIS_HOST` | Yes (if enabled) | Redis for BotToken cache |
| `JOYSAFETER_VAULT_ENCRYPTION_KEY` | Yes | Encrypts identity_token stored in session.metadata |

## Security Model

| Layer | What happens | Security guarantee |
|-------|-------------|-------------------|
| **API layer** | User's credential encrypted into session.metadata | AES-256-GCM, same key as vault |
| **Orchestrator** | Decrypts → exchanges → produces short-lived tokens | Lives only in process memory |
| **Redis cache** | BotToken cached (server-side only) | Never enters sandbox or downstream |
| **Envoy inject** | Short-lived tokens placed in inject_headers | Only path to downstream |
| **Sandbox** | `remove_headers` strips any spoofed identity headers | Cannot forge identity |
| **Downstream** | Receives `X-Security-AgentToken` + user identity Cookie | Can verify agent + user |

### Key Invariants

- **BotToken**: Server-side only (Redis + orchestrator memory). NEVER in sandbox env/secrets/inject_headers.
- **agentToken / SSO ticket / ME token**: ONLY in Envoy `inject_headers`. Never stored persistently.
- **User's raw credential**: Encrypted in session.metadata, decrypted once per resolve, then discarded.
- **Sandbox isolation**: `network=none` ensures all traffic routes through Envoy. `remove_headers` prevents spoofing.

## Built-in Providers

| Provider | Feature Flag | Crate | Status |
|----------|-------------|-------|--------|
| `NoopAgentIdentityProvider` | (always) | `agent-identity-trait` | Default, does nothing |
| `JdAgentIdentityProvider` | `jd-identity` | `crates/jd-agent-identity` | Internal (JD protocol) |

## Workspace Structure

```
joysafeter_orchestrator_rs/
├── src/kernel/agent_identity_provider.rs  ← re-exports trait
├── crates/
│   ├── agent-identity-trait/              ← open-source: trait + Noop
│   └── jd-agent-identity/                 ← internal: JD protocol impl
└── Cargo.toml                             ← feature: jd-identity
```

## How Token Refresh Works

The `egress_policy_hash` (in `sandbox_resolver.rs`) includes a SHA-256 of every `inject_headers` value. When the provider produces a fresh agentToken (different value), the hash changes, which automatically triggers `refresh_networking` → Envoy receives the updated headers via Delta xDS. No sandbox restart needed.

## Fail-Open Behavior

Identity injection is **non-blocking**:
- Provider `resolve()` errors → logged, sandbox runs without identity
- SSO/ME exchange fails → `warn!`, agentToken still injected where possible
- Redis unavailable → BotToken cache miss every time (still works, just slower)
- `_store_agent_identity_context` fails → task runs, identity won't work for that task
