# Agent Identity Provider — 智能体出站身份注入

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 JoySafeter 平台提供可插拔的智能体出站身份注入能力。Agent 执行 Task 时，通过 Envoy 出站代理自动注入身份标识 headers，使下游系统能识别「哪个智能体 + 代表哪个用户」在调用。开源核心只暴露 Provider trait，京东内部协议实现作为 feature flag 插件。

**Architecture:** 三层设计——
1. 开源核心：`AgentIdentityProvider` trait + Noop 默认实现 + `build_agent_identity_egress()` 路由构建器
2. 内部插件：`jd-agent-identity` crate 实现 JD Agent Identity Protocol（createBotToken / exchangeAgentToken / exchangeUserIdentity / destroyBotToken + Redis 缓存）
3. 注入层：复用现有 `EgressCredentialRoute` + Envoy `inject_headers` 机制，与 LLM/MCP/Git/External 同构

**Tech Stack:** Rust (async-trait + tokio + reqwest + redis + serde_json), Envoy xDS (EgressCredentialRoute), Cargo feature flags

---

## Task 1: Provider Trait 定义（开源核心）

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/agent_identity_provider.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`

**Step 1: 创建 trait 定义 + 公共类型 + Noop 实现**

```rust
// src/kernel/agent_identity_provider.rs

//! Pluggable agent identity injection for outbound requests.
//!
//! When an Agent executes a Task, the platform may need to inject identity
//! headers into the sandbox's outbound HTTP requests so downstream services
//! can identify "which agent + on behalf of which user" is calling.
//!
//! This module defines the [`AgentIdentityProvider`] trait. The orchestrator
//! core depends only on this trait — concrete implementations (e.g. JD Agent
//! Identity Protocol) live behind Cargo feature flags or external crates.
//!
//! Default: [`NoopAgentIdentityProvider`] — does nothing; identity injection
//! is disabled unless a provider is explicitly configured.

use async_trait::async_trait;
use serde_json::Value as JsonValue;

// ---------------------------------------------------------------------------
// Public types shared between core and provider implementations
// ---------------------------------------------------------------------------

/// A single target host + the headers to inject on outbound requests to it.
#[derive(Debug, Clone)]
pub struct IdentityEgressTarget {
    /// Target host that triggers injection (matched by Envoy vhost).
    pub host: String,
    /// Port (default 443).
    pub port: u16,
    /// Whether the upstream requires TLS origination.
    pub tls: bool,
    /// Headers to inject (name, value). These are secrets — only live in
    /// Envoy inject_headers, never in sandbox env/secrets.
    pub inject_headers: Vec<(String, String)>,
    /// Headers to strip from the sandbox request before injection
    /// (prevents sandbox from spoofing identity headers).
    pub remove_headers: Vec<String>,
}

/// Resolved identity injection result for one task execution.
#[derive(Debug, Clone, Default)]
pub struct AgentIdentityInjection {
    /// Per-host injection targets. Empty = no identity injection this run.
    pub targets: Vec<IdentityEgressTarget>,
}

/// Context passed to the provider for token resolution.
#[derive(Debug, Clone)]
pub struct IdentityResolveContext {
    /// Agent's unique ID.
    pub agent_id: String,
    /// Session ID (if available).
    pub session_id: String,
    /// Task ID being executed.
    pub task_id: String,
    /// Triggering user's raw identity credential (decrypted from storage).
    /// Provider uses this to bootstrap its token exchange flow.
    pub identity_token: String,
    /// Triggering user's display name / email (for cache keying).
    pub user_name: String,
    /// Agent-level identity config parsed from metadata.
    pub provider_config: JsonValue,
}

/// Context for cleanup operations.
#[derive(Debug, Clone)]
pub struct IdentityCleanupContext {
    pub agent_id: String,
    pub user_name: Option<String>,
}

// ---------------------------------------------------------------------------
// Provider trait
// ---------------------------------------------------------------------------

/// Trait for pluggable agent identity injection.
///
/// Implementations are responsible for:
/// - Parsing agent metadata to determine if/how identity injection is needed
/// - Managing credential lifecycle (caching, refreshing, revoking)
/// - Producing the final headers to inject via Envoy
///
/// The orchestrator core calls these methods during sandbox resolution and
/// agent lifecycle events. Implementations must be `Send + Sync` and safe
/// for concurrent use across tasks.
#[async_trait]
pub trait AgentIdentityProvider: Send + Sync + std::fmt::Debug {
    /// Human-readable provider name (for logging/diagnostics).
    fn name(&self) -> &str;

    /// Whether this provider is active. Returns false → entire injection
    /// pipeline is skipped (zero overhead when disabled).
    fn enabled(&self) -> bool;

    /// Check if the given agent has identity injection configured.
    /// Called during `build_resolve_context()` — should be fast (no I/O).
    ///
    /// Returns true if `agent_metadata` contains valid identity config
    /// that this provider can handle.
    fn has_config(&self, agent_metadata: Option<&JsonValue>) -> bool;

    /// Resolve identity tokens and produce injection targets.
    ///
    /// This is the core method. Called once per sandbox resolution (i.e. per
    /// task start or sandbox reuse). The provider should:
    /// 1. Obtain/cache the long-lived credential (e.g. BotToken)
    /// 2. Exchange for short-lived tokens (e.g. agentToken, SSO ticket)
    /// 3. Return per-host injection headers
    ///
    /// Errors are non-fatal: the orchestrator logs and continues without
    /// identity injection (fail-open). The sandbox still runs.
    async fn resolve(
        &self,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection>;

    /// Cleanup credentials when an agent is deleted or a user revokes access.
    ///
    /// Implementations should revoke cached tokens and notify the identity
    /// platform. Errors are logged but not propagated.
    async fn cleanup(&self, context: &IdentityCleanupContext);
}

// ---------------------------------------------------------------------------
// Default no-op implementation (open-source default)
// ---------------------------------------------------------------------------

/// No-op provider — identity injection disabled.
///
/// This is the default when no provider feature is enabled. Zero overhead:
/// `enabled()` returns false, so the orchestrator skips the entire pipeline.
#[derive(Debug, Clone, Copy)]
pub struct NoopAgentIdentityProvider;

#[async_trait]
impl AgentIdentityProvider for NoopAgentIdentityProvider {
    fn name(&self) -> &str {
        "noop"
    }

    fn enabled(&self) -> bool {
        false
    }

    fn has_config(&self, _agent_metadata: Option<&JsonValue>) -> bool {
        false
    }

    async fn resolve(
        &self,
        _context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection> {
        Ok(AgentIdentityInjection::default())
    }

    async fn cleanup(&self, _context: &IdentityCleanupContext) {}
}
```

**Step 2: 在 kernel/mod.rs 中注册模块**

在 `src/kernel/mod.rs` 中添加：

```rust
pub mod agent_identity_provider;
```

**Step 3: Commit**

```bash
git add src/kernel/agent_identity_provider.rs src/kernel/mod.rs
git commit -m "feat(orchestrator): define AgentIdentityProvider trait

Pluggable trait for agent outbound identity injection.
Open-source core exposes only the trait + NoopAgentIdentityProvider.
Concrete implementations live behind feature flags."
```

---

## Task 2: JD Agent Identity Protocol 实现（内部 crate）

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/crates/jd-agent-identity/Cargo.toml`
- Create: `backend/app/joysafeter_orchestrator_rs/crates/jd-agent-identity/src/lib.rs`

**Step 1: 创建 crate 结构**

```toml
# crates/jd-agent-identity/Cargo.toml

[package]
name = "jd-agent-identity"
version = "0.1.0"
edition = "2021"
publish = false  # 不发布到公共 registry

[dependencies]
async-trait = "0.1"
anyhow = "1"
chrono = { version = "0.4", features = ["serde"] }
redis = { version = "0.27", features = ["tokio-comp", "aio"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"], default-features = false }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
tracing = "0.1"
uuid = { version = "1", features = ["v4"] }

# 依赖 orchestrator 的 trait 定义
joysafeter-orchestrator = { path = "../..", package = "joysafeter_orchestrator_rs" }
```

> 注：如果 trait 定义需要从 orchestrator crate 拆出来作为独立 crate（`joysafeter-agent-identity-trait`），可后续再重构。初期直接 path 依赖。

**Step 2: 实现 JdAgentIdentityProvider**

```rust
// crates/jd-agent-identity/src/lib.rs

//! JD Agent Identity Protocol implementation.
//!
//! 内部 crate — 不随 JoySafeter 开源发布。
//! 实现京东智能体身份接入协议的四个 API：
//! - 2.1 生成智能体身份 BotToken
//! - 2.2 BotToken 兑换用户身份 (SSO / ME)
//! - 2.3 BotToken 兑换 AgentToken
//! - 2.7 销毁智能体身份 BotToken

use std::time::Duration;

use anyhow::{anyhow, Context};
use async_trait::async_trait;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use tracing::{debug, info, warn};

// Re-export trait types from core
use joysafeter_orchestrator::kernel::agent_identity_provider::{
    AgentIdentityInjection, AgentIdentityProvider, IdentityCleanupContext,
    IdentityEgressTarget, IdentityResolveContext,
};

// ---------------------------------------------------------------------------
// Protocol request/response types
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CreateBotTokenRequest {
    trace_id: String,
    client_id: String,
    platform_id: String,
    agent_id: String,
    session_id: String,
    request_id: String,
    scope: Vec<String>,
    tenant_code: String,
    auth_type: String,
    identity_type: String,
    identity_token: String,
    agent_scene: String,
    timestamp: i64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ApiResponse<T> {
    code: i32,
    message: String,
    data: Option<T>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BotTokenData {
    bot_token: String,
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentTokenData {
    agent_token: String,
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UserIdentityData {
    token: String,
    expires_in: u64,
}

// ---------------------------------------------------------------------------
// Config parsed from agent.metadata.agent_identity
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct JdIdentityConfig {
    platform_id: String,
    client_id: String,
    tenant_code: String,
    agent_scene: String,
    auth_type: String,
    identity_type: String,
    sso_targets: Vec<String>,
    me_targets: Vec<String>,
    agent_token_targets: Vec<String>,
}

impl JdIdentityConfig {
    fn from_json(config: &JsonValue) -> Option<Self> {
        let enabled = config.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true);
        if !enabled {
            return None;
        }
        Some(Self {
            platform_id: json_str(config, "platform_id", "joysafeter"),
            client_id: json_str(config, "client_id", "joysafeter"),
            tenant_code: json_str(config, "tenant_code", ""),
            agent_scene: json_str(config, "agent_scene", "default"),
            auth_type: json_str(config, "auth_type", "sso"),
            identity_type: json_str(config, "identity_type", "cookie"),
            sso_targets: json_str_array(config, "sso_targets"),
            me_targets: json_str_array(config, "me_targets"),
            agent_token_targets: json_str_array(config, "agent_token_targets"),
        })
    }

    fn all_scope_hosts(&self) -> Vec<String> {
        let mut all = Vec::new();
        all.extend(self.sso_targets.iter().cloned());
        all.extend(self.me_targets.iter().cloned());
        all.extend(self.agent_token_targets.iter().cloned());
        all.sort();
        all.dedup();
        all
    }
}

fn json_str(v: &JsonValue, key: &str, default: &str) -> String {
    v.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or(default)
        .to_string()
}

fn json_str_array(v: &JsonValue, key: &str) -> Vec<String> {
    v.get(key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

// ---------------------------------------------------------------------------
// Provider implementation
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct JdAgentIdentityProvider {
    http: reqwest::Client,
    base_url: String,
    redis_client: redis::Client,
}

impl JdAgentIdentityProvider {
    /// Create from environment. Returns None if AGENT_IDENTITY_BASE_URL is unset.
    pub fn from_env(redis_client: redis::Client) -> Option<Self> {
        let base_url = std::env::var("AGENT_IDENTITY_BASE_URL").ok()?;
        if base_url.trim().is_empty() {
            return None;
        }
        Some(Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .expect("build reqwest client"),
            base_url: base_url.trim_end_matches('/').to_string(),
            redis_client,
        })
    }

    // --- API 调用 ---

    async fn api_create_bot_token(&self, req: &CreateBotTokenRequest) -> anyhow::Result<BotTokenData> {
        let url = format!("{}/api/v1/bot-token/create", self.base_url);
        let resp: ApiResponse<BotTokenData> = self
            .http
            .post(&url)
            .json(req)
            .send()
            .await
            .context("createBotToken request failed")?
            .json()
            .await
            .context("createBotToken response parse failed")?;
        if resp.code != 0 {
            anyhow::bail!("createBotToken: code={}, msg={}", resp.code, resp.message);
        }
        resp.data.ok_or_else(|| anyhow!("createBotToken: no data"))
    }

    async fn api_exchange_agent_token(&self, bot_token: &str) -> anyhow::Result<AgentTokenData> {
        let url = format!("{}/api/v1/bot-token/exchange-agent-token", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botToken": bot_token,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let resp: ApiResponse<AgentTokenData> = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeAgentToken request failed")?
            .json()
            .await
            .context("exchangeAgentToken response parse failed")?;
        if resp.code != 0 {
            anyhow::bail!("exchangeAgentToken: code={}, msg={}", resp.code, resp.message);
        }
        resp.data.ok_or_else(|| anyhow!("exchangeAgentToken: no data"))
    }

    async fn api_exchange_user_identity(
        &self,
        bot_token: &str,
        target_type: &str,
    ) -> anyhow::Result<UserIdentityData> {
        let url = format!("{}/api/v1/bot-token/exchange-user-identity", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botToken": bot_token,
            "targetType": target_type,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let resp: ApiResponse<UserIdentityData> = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .with_context(|| format!("exchangeUserIdentity({target_type}) request failed"))?
            .json()
            .await
            .with_context(|| format!("exchangeUserIdentity({target_type}) parse failed"))?;
        if resp.code != 0 {
            anyhow::bail!(
                "exchangeUserIdentity({}): code={}, msg={}",
                target_type, resp.code, resp.message
            );
        }
        resp.data.ok_or_else(|| anyhow!("exchangeUserIdentity({target_type}): no data"))
    }

    async fn api_destroy_bot_token(&self, bot_token: &str) -> anyhow::Result<()> {
        let url = format!("{}/api/v1/bot-token/destroy", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botToken": bot_token,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let resp: ApiResponse<()> = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("destroyBotToken request failed")?
            .json()
            .await
            .context("destroyBotToken response parse failed")?;
        if resp.code != 0 {
            warn!(code = resp.code, msg = %resp.message, "destroyBotToken non-zero (non-fatal)");
        }
        Ok(())
    }

    // --- Redis 缓存 ---

    fn cache_key(platform_id: &str, agent_id: &str, auth_type: &str, user_name: &str) -> String {
        format!("joysafeter:bot_token:{platform_id}:{agent_id}:{auth_type}:{user_name}")
    }

    async fn get_cached_bot_token(&self, key: &str) -> Option<String> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await.ok()?;
        conn.get::<_, Option<String>>(key).await.ok().flatten()
    }

    async fn cache_bot_token(&self, key: &str, value: &str, ttl_secs: u64) {
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            return;
        };
        let _ = conn.set_ex::<_, _, ()>(key, value, ttl_secs).await;
    }

    async fn delete_cache(&self, key: &str) {
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            return;
        };
        let _ = conn.del::<_, ()>(key).await;
    }

    // --- 核心兑换流程 ---

    async fn get_or_create_bot_token(
        &self,
        config: &JdIdentityConfig,
        ctx: &IdentityResolveContext,
    ) -> anyhow::Result<String> {
        let key = Self::cache_key(
            &config.platform_id,
            &ctx.agent_id,
            &config.auth_type,
            &ctx.user_name,
        );

        // Cache hit
        if let Some(cached) = self.get_cached_bot_token(&key).await {
            debug!(cache_key = %key, "BotToken cache hit");
            return Ok(cached);
        }

        // Cache miss → call createBotToken
        debug!(cache_key = %key, "BotToken cache miss, calling createBotToken");
        let req = CreateBotTokenRequest {
            trace_id: uuid::Uuid::new_v4().to_string(),
            client_id: config.client_id.clone(),
            platform_id: config.platform_id.clone(),
            agent_id: ctx.agent_id.clone(),
            session_id: ctx.session_id.clone(),
            request_id: ctx.task_id.clone(),
            scope: config.all_scope_hosts(),
            tenant_code: config.tenant_code.clone(),
            auth_type: config.auth_type.clone(),
            identity_type: config.identity_type.clone(),
            identity_token: ctx.identity_token.clone(),
            agent_scene: config.agent_scene.clone(),
            timestamp: chrono::Utc::now().timestamp_millis(),
        };
        let data = self.api_create_bot_token(&req).await?;

        // Cache with safety margin
        let ttl = data.expires_in.saturating_sub(60).max(60);
        self.cache_bot_token(&key, &data.bot_token, ttl).await;
        info!(agent_id = %ctx.agent_id, expires_in = data.expires_in, "Created BotToken");

        Ok(data.bot_token)
    }

    fn build_targets(
        &self,
        config: &JdIdentityConfig,
        agent_token: &str,
        sso_ticket: Option<&str>,
        me_token: Option<&str>,
    ) -> Vec<IdentityEgressTarget> {
        let mut targets = Vec::new();
        let remove_all = vec![
            "x-security-agenttoken".to_string(),
            "cookie".to_string(),
        ];
        let remove_token_only = vec!["x-security-agenttoken".to_string()];

        // SSO targets
        if let Some(ticket) = sso_ticket {
            for host in &config.sso_targets {
                targets.push(IdentityEgressTarget {
                    host: host.clone(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![
                        ("X-Security-AgentToken".into(), agent_token.to_string()),
                        ("Cookie".into(), format!("ssguestId={ticket}")),
                    ],
                    remove_headers: remove_all.clone(),
                });
            }
        }

        // ME targets
        if let Some(token) = me_token {
            for host in &config.me_targets {
                targets.push(IdentityEgressTarget {
                    host: host.clone(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![
                        ("X-Security-AgentToken".into(), agent_token.to_string()),
                        ("Cookie".into(), format!("TP_AGENT={token}")),
                    ],
                    remove_headers: remove_all.clone(),
                });
            }
        }

        // agentToken-only targets
        for host in &config.agent_token_targets {
            if config.sso_targets.contains(host) || config.me_targets.contains(host) {
                continue;
            }
            targets.push(IdentityEgressTarget {
                host: host.clone(),
                port: 443,
                tls: true,
                inject_headers: vec![
                    ("X-Security-AgentToken".into(), agent_token.to_string()),
                ],
                remove_headers: remove_token_only.clone(),
            });
        }

        targets
    }
}

#[async_trait]
impl AgentIdentityProvider for JdAgentIdentityProvider {
    fn name(&self) -> &str {
        "jd-agent-identity"
    }

    fn enabled(&self) -> bool {
        true
    }

    fn has_config(&self, agent_metadata: Option<&JsonValue>) -> bool {
        agent_metadata
            .and_then(|m| m.get("agent_identity"))
            .and_then(|c| JdIdentityConfig::from_json(c))
            .is_some()
    }

    async fn resolve(
        &self,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection> {
        let config = JdIdentityConfig::from_json(&context.provider_config)
            .ok_or_else(|| anyhow!("invalid agent_identity config"))?;

        // 1. Get or create BotToken (cached)
        let bot_token = self.get_or_create_bot_token(&config, context).await?;

        // 2. Exchange BotToken → AgentToken (always, short-lived)
        let agent_token_data = self.api_exchange_agent_token(&bot_token).await?;

        // 3. Exchange BotToken → SSO ticket (if configured)
        let sso_ticket = if !config.sso_targets.is_empty() {
            match self.api_exchange_user_identity(&bot_token, "sso").await {
                Ok(data) => Some(data.token),
                Err(e) => {
                    warn!(error = %e, "SSO ticket exchange failed (non-fatal)");
                    None
                }
            }
        } else {
            None
        };

        // 4. Exchange BotToken → ME token (if configured)
        let me_token = if !config.me_targets.is_empty() {
            match self.api_exchange_user_identity(&bot_token, "me").await {
                Ok(data) => Some(data.token),
                Err(e) => {
                    warn!(error = %e, "ME token exchange failed (non-fatal)");
                    None
                }
            }
        } else {
            None
        };

        // 5. Build injection targets
        let targets = self.build_targets(
            &config,
            &agent_token_data.agent_token,
            sso_ticket.as_deref(),
            me_token.as_deref(),
        );

        info!(
            agent_id = %context.agent_id,
            targets = targets.len(),
            sso = sso_ticket.is_some(),
            me = me_token.is_some(),
            "Agent identity tokens resolved"
        );

        Ok(AgentIdentityInjection { targets })
    }

    async fn cleanup(&self, context: &IdentityCleanupContext) {
        // Scan Redis for all BotTokens matching this agent
        let pattern = format!("joysafeter:bot_token:*:{}:*", context.agent_id);
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            return;
        };

        let keys: Vec<String> = match redis::cmd("KEYS")
            .arg(&pattern)
            .query_async(&mut conn)
            .await
        {
            Ok(keys) => keys,
            Err(e) => {
                warn!(error = %e, "Failed to scan BotToken keys for cleanup");
                return;
            }
        };

        for key in keys {
            if let Some(bot_token) = self.get_cached_bot_token(&key).await {
                let _ = self.api_destroy_bot_token(&bot_token).await;
            }
            self.delete_cache(&key).await;
        }
        info!(agent_id = %context.agent_id, "BotToken cleanup complete");
    }
}
```

**Step 3: Commit**

```bash
git add crates/jd-agent-identity/
git commit -m "feat(jd-identity): implement JD Agent Identity Protocol provider

Internal crate (not open-sourced) implementing:
- createBotToken with Redis caching
- exchangeAgentToken (per-task, short-lived)
- exchangeUserIdentity (SSO/ME)
- destroyBotToken (cleanup)

Implements AgentIdentityProvider trait from orchestrator core."
```

---

## Task 3: Cargo Feature Flag 接线

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/Cargo.toml`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/main.rs`

**Step 1: 添加 feature flag 和可选依赖**

```toml
# Cargo.toml 新增

[features]
default = []
jd-identity = ["dep:jd-agent-identity"]

[dependencies]
async-trait = "0.1"
# ... existing deps ...
jd-agent-identity = { path = "crates/jd-agent-identity", optional = true }
```

**Step 2: 在 main.rs 中根据 feature 实例化 provider**

```rust
// main.rs — 在 redis_client 初始化之后

use crate::kernel::agent_identity_provider::{AgentIdentityProvider, NoopAgentIdentityProvider};

let identity_provider: Arc<dyn AgentIdentityProvider> = {
    #[cfg(feature = "jd-identity")]
    {
        match redis_client.as_ref().and_then(|rc| {
            jd_agent_identity::JdAgentIdentityProvider::from_env(rc.clone())
        }) {
            Some(provider) => {
                info!("Agent identity provider: jd-agent-identity (enabled)");
                Arc::new(provider)
            }
            None => {
                info!("Agent identity provider: noop (AGENT_IDENTITY_BASE_URL not set)");
                Arc::new(NoopAgentIdentityProvider)
            }
        }
    }
    #[cfg(not(feature = "jd-identity"))]
    {
        info!("Agent identity provider: noop (jd-identity feature not enabled)");
        Arc::new(NoopAgentIdentityProvider)
    }
};
```

**Step 3: Commit**

```bash
git add Cargo.toml src/main.rs
git commit -m "feat(orchestrator): wire identity provider via feature flag

jd-identity feature enables JD protocol; default is NoopProvider.
Provider is instantiated at startup and passed to SandboxResolver."
```

---

## Task 4: SandboxResolver 集成 — Envoy 动态注入

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`

**Step 1: 给 SandboxResolver 新增 identity_provider 字段**

```rust
// sandbox_resolver.rs — struct SandboxResolver 新增字段
pub struct SandboxResolver {
    pool: PgPool,
    provider: Arc<dyn SandboxProvider>,
    config: JoySafeterConfig,
    session_locks: dashmap::DashMap<Uuid, Arc<tokio::sync::Mutex<()>>>,
    network_policy_ready: dashmap::DashMap<Uuid, String>,
    pool_replenish_notify: Option<Arc<tokio::sync::Notify>>,
    xds_store: Option<Arc<dyn XdsStateStore>>,
    // ★ 新增
    identity_provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
}
```

新增 builder 方法：

```rust
pub fn with_identity_provider(
    mut self,
    provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
) -> Self {
    self.identity_provider = provider;
    self
}
```

修改 `new()` 默认值：

```rust
identity_provider: Arc::new(
    crate::kernel::agent_identity_provider::NoopAgentIdentityProvider,
),
```

**Step 2: 在 `EgressKind` 中新增 `AgentIdentity`**

```rust
// lds_backend.rs:166
pub enum EgressKind {
    Llm,
    Mcp,
    Git,
    External,
    AgentIdentity,  // ← 新增
}
```

**Step 3: 在 `build_resolve_context()` 中调用 provider**

在 `sandbox_resolver.rs:902-923` 的 `if network.as_deref() == Some("none")` 块中，在现有四个 builders 之后添加：

```rust
            // Agent Identity egress injection (provider-based, fail-open)
            if self.identity_provider.enabled() {
                if let Some(identity_routes) = self
                    .resolve_identity_egress_routes(agent.as_ref(), session_id)
                    .await
                {
                    routes.extend(identity_routes);
                }
            }
```

**Step 4: 实现 `resolve_identity_egress_routes` 辅助方法**

```rust
    /// Resolve agent identity egress routes via the pluggable provider.
    /// Returns None on any failure (fail-open: sandbox works without identity).
    async fn resolve_identity_egress_routes(
        &self,
        agent: Option<&JoySafeterAgent>,
        session_id: Option<Uuid>,
    ) -> Option<Vec<EgressCredentialRoute>> {
        use crate::kernel::agent_identity_provider::{
            IdentityEgressTarget, IdentityResolveContext,
        };

        let agent = agent?;
        if !self.identity_provider.has_config(agent.metadata.as_ref()) {
            return None;
        }

        let provider_config = agent
            .metadata
            .as_ref()?
            .get("agent_identity")?
            .clone();

        // Load identity context (user's encrypted identity_token + user_name)
        let (identity_token, user_name) = self
            .load_identity_context(agent.id, session_id)
            .await?;

        let context = IdentityResolveContext {
            agent_id: agent.id.to_string(),
            session_id: session_id.map(|id| id.to_string()).unwrap_or_default(),
            task_id: agent.id.to_string(), // will be replaced with actual task_id
            identity_token,
            user_name,
            provider_config,
        };

        match self.identity_provider.resolve(&context).await {
            Ok(injection) if !injection.targets.is_empty() => {
                let routes = injection
                    .targets
                    .into_iter()
                    .map(|target| self.target_to_route(target))
                    .collect();
                Some(routes)
            }
            Ok(_) => None,
            Err(e) => {
                warn!(
                    agent_id = %agent.id,
                    error = %e,
                    "Agent identity resolve failed (sandbox continues without identity)"
                );
                None
            }
        }
    }

    /// Convert provider target to EgressCredentialRoute.
    fn target_to_route(&self, target: IdentityEgressTarget) -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: format!("agent-identity:{}", target.host),
            kind: EgressKind::AgentIdentity,
            exposure: EgressExposure::Transparent,
            match_host: target.host.clone(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: target.host,
            upstream_port: target.port,
            upstream_prefix: "/".to_string(),
            upstream_tls: target.tls,
            cluster_name: String::new(), // filled by to_policy()
            inject_headers: target.inject_headers,
            remove_headers: target.remove_headers,
        }
    }

    /// Load triggering user's identity context from session metadata.
    async fn load_identity_context(
        &self,
        _agent_id: Uuid,
        session_id: Option<Uuid>,
    ) -> Option<(String, String)> {
        let session_id = session_id?;
        let row: Option<(Option<serde_json::Value>,)> = sqlx::query_as(
            "SELECT metadata FROM joysafeter_sessions WHERE id = $1",
        )
        .bind(session_id)
        .fetch_optional(&self.pool)
        .await
        .ok()
        .flatten();

        let metadata = row?.0?;
        let ctx = metadata.get("agent_identity_context")?;
        let identity_token = ctx.get("identity_token")?.as_str()?.to_string();
        let user_name = ctx.get("user_name")?.as_str()?.to_string();

        // Decrypt
        let cipher = VaultCipher::from_env();
        let decrypted = cipher.decrypt_or_passthrough(&identity_token).ok()?;
        Some((decrypted, user_name))
    }
```

**Step 5: Commit**

```bash
git add src/kernel/sandbox_resolver.rs src/sandbox/lds_backend.rs
git commit -m "feat(orchestrator): integrate identity provider into build_resolve_context

Identity provider is called during sandbox resolution. Provider returns
injection targets → converted to EgressCredentialRoutes → pushed to Envoy.
Fail-open: errors logged, sandbox runs without identity injection."
```

---

## Task 5: API 层 — 捕获用户 identityToken

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py` (或 `tasks.py`)
- Create: `backend/alembic/versions/xxxx_add_sessions_metadata.py` (if needed)

**Step 1: 创建 DB migration（如 sessions 表还没有 metadata 字段）**

```python
"""add metadata jsonb to joysafeter_sessions"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def upgrade():
    op.add_column("joysafeter_sessions", sa.Column("metadata", JSONB, nullable=True))

def downgrade():
    op.drop_column("joysafeter_sessions", "metadata")
```

**Step 2: 在 Task/Session 创建时存储加密的 identity context**

```python
# 在 session start 或 task create 流程中:

async def store_identity_context_for_agent(
    db: AsyncSession,
    session_id: str,
    request: Request,
    user_id: str,
):
    """If the agent has identity config, capture user's credential for later use."""
    from app.joysafeter_shared.config.settings import settings

    # Extract raw credential from request
    identity_token = request.cookies.get(settings.cookie_name, "")
    if not identity_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            identity_token = auth_header[7:]
    if not identity_token:
        return

    # Encrypt with VaultCipher (same key as Rust side)
    from app.joysafeter_shared.security.vault import vault_encrypt
    encrypted = vault_encrypt(identity_token)

    # Resolve user email for cache key
    from sqlalchemy import select, text
    from app.joysafeter_domain.models.joysafeter_auth import AuthUser
    result = await db.execute(select(AuthUser.email).where(AuthUser.id == user_id).limit(1))
    row = result.scalar_one_or_none()
    user_name = row or user_id

    # Store in session.metadata
    import json
    from datetime import datetime, timezone
    context_json = json.dumps({
        "agent_identity_context": {
            "identity_token": encrypted,
            "user_name": user_name,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    })
    await db.execute(
        text("""
            UPDATE joysafeter_sessions
            SET metadata = COALESCE(metadata, '{}'::jsonb) || :ctx::jsonb
            WHERE id = :sid
        """),
        {"ctx": context_json, "sid": session_id},
    )
```

**Step 3: Commit**

```bash
git add backend/alembic/versions/ backend/app/joysafeter_api/
git commit -m "feat(api): capture identity context on session/task creation

Encrypts triggering user's SSO cookie into session.metadata.agent_identity_context
so orchestrator can bootstrap BotToken creation during sandbox resolve."
```

---

## Task 6: Agent 删除时调用 Provider cleanup

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/agents.py`

**Step 1: 在 delete_agent / archive_agent 中添加 cleanup 调用**

```python
# agents.py — delete_agent 或 _destroy_sandboxes_for_agent 附近

async def _cleanup_agent_identity(agent_id: str):
    """Notify identity provider to clean up cached credentials."""
    import aiohttp
    from app.joysafeter_shared.config.settings import settings

    base_url = getattr(settings, "agent_identity_base_url", "")
    if not base_url:
        return

    # Rust orchestrator handles cleanup via provider.cleanup()
    # For Python-side, scan and destroy via Redis directly
    redis = await get_redis_connection()
    if not redis:
        return

    pattern = f"joysafeter:bot_token:*:{agent_id}:*"
    async for key in redis.scan_iter(match=pattern):
        bot_token = await redis.get(key)
        if bot_token:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        f"{base_url}/api/v1/bot-token/destroy",
                        json={
                            "traceId": str(uuid.uuid4()),
                            "botToken": bot_token.decode() if isinstance(bot_token, bytes) else bot_token,
                            "timestamp": int(time.time() * 1000),
                        },
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
            except Exception as e:
                logger.warning(f"destroyBotToken failed: {e}")
        await redis.delete(key)
```

在 `delete_agent` endpoint 中调用：

```python
await _cleanup_agent_identity(str(agent_id))
```

**Step 2: Commit**

```bash
git add backend/app/joysafeter_api/api/v1/agents.py
git commit -m "feat(api): cleanup agent identity on agent deletion"
```

---

## Task 7: 配置 + 文档

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/config.rs`
- Create: `docs/agent-identity-protocol.md`

**Step 1: config.rs 中预留环境变量读取**

```rust
// config.rs 无需新增字段 — AGENT_IDENTITY_BASE_URL 由 provider 自己读取
// 但可以加一个 feature flag 文档注释：

// Agent Identity Provider
// Controlled by compile-time feature `jd-identity` + env AGENT_IDENTITY_BASE_URL.
// When disabled (default), no identity injection occurs.
```

**Step 2: 编写集成文档**

```markdown
# Agent Identity Provider

## Overview

JoySafeter supports pluggable agent identity injection for outbound requests.
When enabled, the platform automatically injects identity headers into requests
from the sandbox to downstream services via the Envoy egress proxy.

## Architecture

```
Agent Metadata ──→ Provider.has_config() ──→ Provider.resolve()
                                                     │
                                                     ▼
                                          AgentIdentityInjection
                                                     │
                                                     ▼
                                          EgressCredentialRoute[]
                                                     │
                                                     ▼
                                          Envoy inject_headers
```

## Implementing a Custom Provider

Implement `AgentIdentityProvider` trait:

```rust
use joysafeter_orchestrator::kernel::agent_identity_provider::*;

#[async_trait]
impl AgentIdentityProvider for MyProvider {
    fn name(&self) -> &str { "my-provider" }
    fn enabled(&self) -> bool { true }
    fn has_config(&self, metadata: Option<&JsonValue>) -> bool { ... }
    async fn resolve(&self, ctx: &IdentityResolveContext) -> Result<AgentIdentityInjection> { ... }
    async fn cleanup(&self, ctx: &IdentityCleanupContext) { ... }
}
```

## Configuration (Agent Metadata)

Provider-specific config goes in `agent.metadata.agent_identity`:

```json
{
  "agent_identity": {
    "enabled": true,
    // ... provider-specific fields
  }
}
```

## Security Model

- Raw user credentials: encrypted in session.metadata, decrypted only in orchestrator memory
- Provider-cached tokens (e.g. BotToken): server-side Redis only, never enter sandbox
- Injected tokens (e.g. agentToken): ONLY in Envoy inject_headers, never in env/secrets
- Sandbox spoofing prevention: remove_headers strips any sandbox-supplied identity headers

## Built-in Providers

| Provider | Feature Flag | Status |
|----------|-------------|--------|
| `NoopAgentIdentityProvider` | (default) | Always available, does nothing |
| `JdAgentIdentityProvider` | `jd-identity` | Internal, not open-sourced |
```

**Step 3: Commit**

```bash
git add docs/agent-identity-protocol.md src/config.rs
git commit -m "docs: agent identity provider integration guide"
```

---

## 文件变更总览

| 文件 | 层 | 开源 | 说明 |
|------|---|------|------|
| `src/kernel/agent_identity_provider.rs` | 核心 | ✅ | Trait + Noop 默认实现 |
| `src/kernel/mod.rs` | 核心 | ✅ | 注册模块 |
| `src/sandbox/lds_backend.rs` | 核心 | ✅ | `EgressKind::AgentIdentity` |
| `src/kernel/sandbox_resolver.rs` | 核心 | ✅ | 调 provider + 转 route |
| `src/main.rs` | 核心 | ✅ | Feature flag provider 实例化 |
| `Cargo.toml` | 核心 | ✅ | `jd-identity` 可选特性 |
| `crates/jd-agent-identity/` | 插件 | ❌ | 京东协议实现 |
| `api/v1/sessions.py` / `tasks.py` | API | ✅ | 捕获 identityToken |
| `api/v1/agents.py` | API | ✅ | Agent 删除 cleanup |
| `alembic/versions/` | DB | ✅ | sessions.metadata |
| `docs/agent-identity-protocol.md` | 文档 | ✅ | 集成指南 |
