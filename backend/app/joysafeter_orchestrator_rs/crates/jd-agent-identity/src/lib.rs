//! JD Agent Identity Protocol implementation.
//!
//! Internal crate — not published with JoySafeter open-source releases.
//!
//! Implements the JD Agent Identity Protocol with four APIs:
//! - 2.1 createBotToken — generate agent identity credential from user identity
//! - 2.2 exchangeUserIdentity — BotToken → SSO ticket / ME token
//! - 2.3 exchangeAgentToken — BotToken → short-lived agentToken
//! - 2.7 destroyBotToken — revoke agent identity credential
//!
//! BotToken is cached in Redis (key = platformId:agentId:authType:userName).
//! All derived tokens (agentToken, SSO ticket, ME token) are short-lived and
//! ONLY injected via Envoy headers — never stored or passed to the sandbox.

use std::time::Duration;

use anyhow::{anyhow, Context};
use async_trait::async_trait;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use tracing::{debug, info, warn};

use agent_identity_trait::{
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
    #[allow(dead_code)]
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UserIdentityData {
    token: String,
    #[allow(dead_code)]
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
    /// Hosts requiring SSO ticket + agentToken injection.
    sso_targets: Vec<String>,
    /// Hosts requiring ME token + agentToken injection.
    me_targets: Vec<String>,
    /// Hosts requiring only agentToken injection (UIM gateway etc).
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

/// JD Agent Identity Protocol provider.
///
/// Implements the full credential exchange flow:
/// 1. createBotToken (cached in Redis, keyed by platform+agent+auth+user)
/// 2. exchangeAgentToken (per-task, short-lived)
/// 3. exchangeUserIdentity (SSO/ME, per-task)
/// 4. destroyBotToken (cleanup on agent deletion)
#[derive(Debug)]
pub struct JdAgentIdentityProvider {
    http: reqwest::Client,
    base_url: String,
    redis_client: redis::Client,
}

impl JdAgentIdentityProvider {
    /// Create from environment variables + a Redis client.
    ///
    /// Returns None if `AGENT_IDENTITY_BASE_URL` is not set (feature disabled).
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

    // --- API calls -----------------------------------------------------------

    /// 2.1 生成智能体身份 BotToken
    async fn api_create_bot_token(
        &self,
        req: &CreateBotTokenRequest,
    ) -> anyhow::Result<BotTokenData> {
        let url = format!("{}/ai/identity/sec/api/createBotToken", self.base_url);
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

    /// 2.3 BotToken 兑换 AgentToken
    async fn api_exchange_agent_token(
        &self,
        bot_token: &str,
    ) -> anyhow::Result<AgentTokenData> {
        let url = format!("{}/ai/identity/sec/api/exchangeAgentToken", self.base_url);
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
            anyhow::bail!(
                "exchangeAgentToken: code={}, msg={}",
                resp.code,
                resp.message
            );
        }
        resp.data
            .ok_or_else(|| anyhow!("exchangeAgentToken: no data"))
    }

    /// 2.2 BotToken 兑换用户身份 (SSO / ME)
    async fn api_exchange_user_identity(
        &self,
        bot_token: &str,
        target_type: &str,
    ) -> anyhow::Result<UserIdentityData> {
        let url = format!(
            "{}/ai/identity/sec/api/exchangeUserToken",
            self.base_url
        );
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
            .with_context(|| {
                format!("exchangeUserIdentity({target_type}) request failed")
            })?
            .json()
            .await
            .with_context(|| {
                format!("exchangeUserIdentity({target_type}) parse failed")
            })?;
        if resp.code != 0 {
            anyhow::bail!(
                "exchangeUserIdentity({}): code={}, msg={}",
                target_type,
                resp.code,
                resp.message
            );
        }
        resp.data.ok_or_else(|| {
            anyhow!("exchangeUserIdentity({target_type}): no data")
        })
    }

    /// 2.7 销毁智能体身份 BotToken
    async fn api_destroy_bot_token(&self, bot_token: &str) -> anyhow::Result<()> {
        let url = format!("{}/ai/identity/sec/api/destroyBotToken", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botToken": bot_token,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let resp: ApiResponse<JsonValue> = self
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
            warn!(
                code = resp.code,
                msg = %resp.message,
                "destroyBotToken non-zero (non-fatal)"
            );
        }
        Ok(())
    }

    /// BotAuthCode 兑换 BotToken（API 调用场景）
    ///
    /// 调用方已从身份平台获取了一次性 BotAuthCode，JoySafeter 用它直接
    /// 兑换 BotToken。BotAuthCode 用后即失效。
    async fn api_exchange_bot_token_from_auth_code(
        &self,
        auth_code: &str,
    ) -> anyhow::Result<BotTokenData> {
        let url = format!("{}/ai/identity/sec/api/verifyBotAuthCode", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botAuthCode": auth_code,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let resp: ApiResponse<BotTokenData> = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeBotToken(authCode) request failed")?
            .json()
            .await
            .context("exchangeBotToken(authCode) response parse failed")?;
        if resp.code != 0 {
            anyhow::bail!(
                "exchangeBotToken(authCode): code={}, msg={}",
                resp.code,
                resp.message
            );
        }
        resp.data
            .ok_or_else(|| anyhow!("exchangeBotToken(authCode): no data"))
    }

    // --- Redis cache ---------------------------------------------------------

    fn cache_key(
        platform_id: &str,
        agent_id: &str,
        auth_type: &str,
        user_name: &str,
    ) -> String {
        format!(
            "joysafeter:bot_token:{}:{}:{}:{}",
            platform_id, agent_id, auth_type, user_name
        )
    }

    async fn get_cached_bot_token(&self, key: &str) -> Option<String> {
        let mut conn = self
            .redis_client
            .get_multiplexed_async_connection()
            .await
            .ok()?;
        conn.get::<_, Option<String>>(key).await.ok().flatten()
    }

    async fn cache_bot_token(&self, key: &str, value: &str, ttl_secs: u64) {
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await
        else {
            warn!(key = key, "Redis connection failed for BotToken cache write");
            return;
        };
        if let Err(e) = conn.set_ex::<_, _, ()>(key, value, ttl_secs).await {
            warn!(key = key, error = %e, "Failed to cache BotToken");
        }
    }

    async fn delete_cache_key(&self, key: &str) {
        if let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await
        {
            let _ = conn.del::<_, ()>(key).await;
        }
    }

    // --- Core exchange flow --------------------------------------------------

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
        debug!(cache_key = %key, "BotToken cache miss, creating");
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

        // Cache with safety margin (subtract 60s, minimum 60s)
        let ttl = data.expires_in.saturating_sub(60).max(60);
        self.cache_bot_token(&key, &data.bot_token, ttl).await;
        info!(
            agent_id = %ctx.agent_id,
            expires_in = data.expires_in,
            "Created and cached BotToken"
        );

        Ok(data.bot_token)
    }

    /// Build injection targets from resolved tokens.
    fn build_targets(
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

        // SSO targets: agentToken + sso ticket as Cookie
        if let Some(ticket) = sso_ticket {
            for host in &config.sso_targets {
                targets.push(IdentityEgressTarget {
                    host: host.clone(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![
                        (
                            "X-Security-AgentToken".to_string(),
                            agent_token.to_string(),
                        ),
                        (
                            "Cookie".to_string(),
                            format!("ssguestId={ticket}"),
                        ),
                    ],
                    remove_headers: remove_all.clone(),
                });
            }
        }

        // ME targets: agentToken + me token as Cookie
        if let Some(token) = me_token {
            for host in &config.me_targets {
                targets.push(IdentityEgressTarget {
                    host: host.clone(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![
                        (
                            "X-Security-AgentToken".to_string(),
                            agent_token.to_string(),
                        ),
                        (
                            "Cookie".to_string(),
                            format!("TP_AGENT={token}"),
                        ),
                    ],
                    remove_headers: remove_all.clone(),
                });
            }
        }

        // agentToken-only targets (skip if already covered by SSO/ME)
        for host in &config.agent_token_targets {
            if config.sso_targets.contains(host) || config.me_targets.contains(host)
            {
                continue;
            }
            targets.push(IdentityEgressTarget {
                host: host.clone(),
                port: 443,
                tls: true,
                inject_headers: vec![(
                    "X-Security-AgentToken".to_string(),
                    agent_token.to_string(),
                )],
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

        // 1. Get BotToken — two paths:
        //    a) API scenario: auth_code → exchangeBotToken(authCode) → botToken
        //    b) Web SSO scenario: identityToken → createBotToken → botToken (cached)
        let bot_token = if let Some(ref auth_code) = context.auth_code {
            // Path A: one-time auth code from API caller
            let data = self.api_exchange_bot_token_from_auth_code(auth_code).await?;
            // Cache the resulting botToken for subsequent tasks in this session
            let cache_key = Self::cache_key(
                &config.platform_id,
                &context.agent_id,
                &config.auth_type,
                &context.user_name,
            );
            let ttl = data.expires_in.saturating_sub(60).max(60);
            self.cache_bot_token(&cache_key, &data.bot_token, ttl).await;
            info!(
                agent_id = %context.agent_id,
                source = "auth_code",
                expires_in = data.expires_in,
                "Obtained BotToken via BotAuthCode"
            );
            data.bot_token
        } else {
            // Path B: Web SSO — create with identityToken (or use cache)
            self.get_or_create_bot_token(&config, context).await?
        };

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
        let targets = Self::build_targets(
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
        let pattern = if let Some(ref user) = context.user_name {
            format!("joysafeter:bot_token:*:{}:*:{}", context.agent_id, user)
        } else {
            format!("joysafeter:bot_token:*:{}:*", context.agent_id)
        };

        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await
        else {
            warn!("Redis unavailable for BotToken cleanup");
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

        for key in &keys {
            if let Some(bot_token) = self.get_cached_bot_token(key).await {
                if let Err(e) = self.api_destroy_bot_token(&bot_token).await {
                    warn!(error = %e, key = %key, "destroyBotToken failed (non-fatal)");
                }
            }
            self.delete_cache_key(key).await;
        }

        if !keys.is_empty() {
            info!(
                agent_id = %context.agent_id,
                keys_cleaned = keys.len(),
                "BotToken cleanup complete"
            );
        }
    }
}
