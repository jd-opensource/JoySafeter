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
//! BotToken is cached in Redis with tenant, immutable user, and scope dimensions.
//! All derived tokens (agentToken, SSO ticket, ME token) are short-lived and
//! ONLY injected via Envoy headers — never stored or passed to the sandbox.

use std::collections::HashMap;
use std::time::Duration;

use anyhow::{anyhow, Context};
use async_trait::async_trait;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use tracing::{debug, info, warn};

use agent_identity_trait::{
    AgentIdentityInjection, AgentIdentityProvider, IdentityCleanupContext, IdentityEgressTarget,
    IdentityResolveContext,
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
    scope: String, // comma-separated domain list
    tenant_code: String,
    auth_type: String,
    identity_type: String,
    identity_token: String,
    agent_scene: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    env_info: Option<HashMap<String, serde_json::Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    headers_map: Option<HashMap<String, String>>,
    timestamp: i64,
    signature: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    extensions: Option<HashMap<String, serde_json::Value>>,
}

/// Standard response envelope from the JD identity platform.
///
/// Note: `code` is a STRING ("200" = success), and there is a top-level
/// `success` boolean. `message` may be absent on success.
#[derive(Debug, Deserialize)]
struct ApiResponse<T> {
    #[serde(default)]
    success: bool,
    #[serde(default)]
    code: String,
    #[serde(default)]
    message: String,
    data: Option<T>,
}

impl<T> ApiResponse<T> {
    /// A response is OK when success=true or code=="200".
    fn is_ok(&self) -> bool {
        self.success || self.code == "200"
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BotTokenData {
    bot_token: String,
    /// Credential validity in seconds.
    #[serde(default)]
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentTokenData {
    agent_token: String,
    #[allow(dead_code)]
    #[serde(default)]
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UserIdentityData {
    token: String,
    #[allow(dead_code)]
    #[serde(default)]
    expires_in: u64,
}

// ---------------------------------------------------------------------------
// Config parsed from agent.metadata.agent_identity
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct JdIdentityConfig {
    tenant_code: String,
}

impl JdIdentityConfig {
    fn from_json(config: &JsonValue) -> Option<Self> {
        let enabled = config
            .get("enabled")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);
        if !enabled {
            return None;
        }
        Some(Self {
            tenant_code: json_str(config, "tenant_code", ""),
        })
    }
}

fn json_str(v: &JsonValue, key: &str, default: &str) -> String {
    v.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or(default)
        .to_string()
}

#[allow(dead_code)]
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

/// Collect environment info matching Java SDK's EnvInfoUtils.collectMap().
///
/// Fields: sdkVersion, os, osVersion, arch, hostname, username, homeDir, uid,
/// ips, macs, cpuCount, cpuModel, memTotalMB, timezone, utcOffset, locale,
/// pid, timestamp, inContainer, inKubernetes, k8sNamespace, jdos.
fn collect_env_info() -> HashMap<String, serde_json::Value> {
    use serde_json::json;

    let mut info = HashMap::new();
    info.insert("sdkVersion".to_string(), json!("rust-0.1.0"));
    info.insert("os".to_string(), json!(std::env::consts::OS));
    info.insert("osVersion".to_string(), json!(""));
    info.insert("arch".to_string(), json!(std::env::consts::ARCH));

    let hostname = std::env::var("HOSTNAME")
        .or_else(|_| {
            gethostname::gethostname()
                .into_string()
                .map_err(|_| std::env::VarError::NotPresent)
        })
        .unwrap_or_default();
    info.insert("hostname".to_string(), json!(hostname));

    let username = std::env::var("USER")
        .or_else(|_| std::env::var("USERNAME"))
        .unwrap_or_default();
    info.insert("username".to_string(), json!(username));

    let home_dir = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
    info.insert("homeDir".to_string(), json!(home_dir));
    info.insert("uid".to_string(), json!(""));

    info.insert("ips".to_string(), json!([]));
    info.insert("macs".to_string(), json!([]));

    let cpu_count = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    info.insert("cpuCount".to_string(), json!(cpu_count));
    info.insert("cpuModel".to_string(), json!(""));
    info.insert("memTotalMB".to_string(), json!(0));

    let tz = std::env::var("TZ").unwrap_or_else(|_| "UTC".to_string());
    info.insert("timezone".to_string(), json!(tz));
    info.insert("utcOffset".to_string(), json!(""));
    info.insert("locale".to_string(), json!(""));

    info.insert("pid".to_string(), json!(std::process::id()));
    info.insert(
        "timestamp".to_string(),
        json!(chrono::Utc::now().to_rfc3339()),
    );

    // Container / K8s detection
    let in_k8s = std::env::var("KUBERNETES_SERVICE_HOST").is_ok();
    let in_container = in_k8s
        || std::path::Path::new("/.dockerenv").exists()
        || std::path::Path::new("/run/.containerenv").exists();
    info.insert("inContainer".to_string(), json!(in_container));
    info.insert("inKubernetes".to_string(), json!(in_k8s));

    let k8s_namespace = std::env::var("POD_NAMESPACE")
        .or_else(|_| {
            std::fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        })
        .unwrap_or_default();
    info.insert("k8sNamespace".to_string(), json!(k8s_namespace));

    // JDOS env
    let mut jdos = HashMap::new();
    for key in ["JDOS_APP_NAME", "JDOS_ENV", "JDOS_IDC", "JDOS_CLUSTER"] {
        if let Ok(val) = std::env::var(key) {
            jdos.insert(key.to_string(), json!(val));
        }
    }
    if !jdos.is_empty() {
        info.insert("jdos".to_string(), json!(jdos));
    }

    info
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
    /// Signing secret for getSign() — env JD_AGENT_IDENTITY_CLIENT_SECRET
    sign_secret: String,
    /// Fixed platform params from environment variables
    client_id: String,
    platform_id: String,
    auth_type: String,
    identity_type: String,
    agent_scene: String,
    redis_client: redis::Client,
}

impl JdAgentIdentityProvider {
    /// Create from environment variables + a Redis client.
    ///
    /// Required env vars:
    /// - AGENT_IDENTITY_BASE_URL: API base URL
    /// - JD_AGENT_IDENTITY_CLIENT_SECRET: signing secret for getSign()
    /// - JD_AGENT_IDENTITY_CLIENT_ID: 申请的应用标识
    /// - JD_AGENT_IDENTITY_PLATFORM_ID: 智能体平台ID
    /// - JD_AGENT_IDENTITY_AUTH_TYPE: 用户身份认证方式 (e.g. "sso")
    /// - JD_AGENT_IDENTITY_IDENTITY_TYPE: 用户身份凭证类型 (e.g. "cookie")
    /// - JD_AGENT_IDENTITY_AGENT_SCENE: 智能体业务场景
    pub fn from_env(redis_client: redis::Client) -> anyhow::Result<Self> {
        fn required(name: &str) -> anyhow::Result<String> {
            let value = std::env::var(name).unwrap_or_default();
            if value.trim().is_empty() {
                anyhow::bail!("{name} is required when AGENT_IDENTITY_PROVIDER=jd");
            }
            Ok(value)
        }

        let base_url = required("AGENT_IDENTITY_BASE_URL")?;
        let allowed_hosts = required("AGENT_IDENTITY_ALLOWED_HOSTS")?;
        if allowed_hosts.split(',').all(|host| host.trim().is_empty()) {
            anyhow::bail!("AGENT_IDENTITY_ALLOWED_HOSTS must contain at least one host");
        }
        Ok(Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .expect("build reqwest client"),
            base_url: base_url.trim_end_matches('/').to_string(),
            sign_secret: required("JD_AGENT_IDENTITY_CLIENT_SECRET")?,
            client_id: required("JD_AGENT_IDENTITY_CLIENT_ID")?,
            platform_id: required("JD_AGENT_IDENTITY_PLATFORM_ID")?,
            auth_type: std::env::var("JD_AGENT_IDENTITY_AUTH_TYPE")
                .unwrap_or_else(|_| "sso".to_string()),
            identity_type: std::env::var("JD_AGENT_IDENTITY_IDENTITY_TYPE")
                .unwrap_or_else(|_| "cookie".to_string()),
            agent_scene: std::env::var("JD_AGENT_IDENTITY_AGENT_SCENE")
                .unwrap_or_else(|_| "cloud_sandbox_skill".to_string()),
            redis_client,
        })
    }

    // --- Signature ------------------------------------------------------------

    /// Generate signature: getSign(clientSecret, signParam, timestamp, traceId)
    ///
    /// Implementation: MD5Hex(clientSecret + signParam + timestamp + traceId)
    fn get_sign(&self, sign_param: &str, timestamp: i64, trace_id: &str) -> String {
        use std::fmt::Write;
        let input = format!(
            "{}{}{}{}",
            self.sign_secret, sign_param, timestamp, trace_id
        );
        let digest = md5::compute(input.as_bytes());
        let mut hex = String::with_capacity(32);
        for byte in digest.iter() {
            let _ = write!(hex, "{:02x}", byte);
        }
        hex
    }

    /// signParam for createBotToken: platformId + agentId + authType + identityType + identityToken
    fn sign_create_bot_token(
        &self,
        agent_id: &str,
        identity_token: &str,
        timestamp: i64,
        trace_id: &str,
    ) -> String {
        let sign_param = format!(
            "{}{}{}{}{}",
            self.platform_id, agent_id, self.auth_type, self.identity_type, identity_token
        );
        self.get_sign(&sign_param, timestamp, trace_id)
    }

    /// signParam for exchangeUserToken: platformId + agentId + authType + identityType + botToken
    fn sign_exchange_user_token(
        &self,
        agent_id: &str,
        bot_token: &str,
        timestamp: i64,
        trace_id: &str,
    ) -> String {
        let sign_param = format!(
            "{}{}{}{}{}",
            self.platform_id, agent_id, self.auth_type, self.identity_type, bot_token
        );
        self.get_sign(&sign_param, timestamp, trace_id)
    }

    /// signParam for exchangeAgentToken: platformId + agentId + botToken
    fn sign_exchange_agent_token(
        &self,
        agent_id: &str,
        bot_token: &str,
        timestamp: i64,
        trace_id: &str,
    ) -> String {
        let sign_param = format!("{}{}{}", self.platform_id, agent_id, bot_token);
        self.get_sign(&sign_param, timestamp, trace_id)
    }

    // --- API calls -----------------------------------------------------------

    /// 2.1 生成智能体身份 BotToken
    async fn api_create_bot_token(
        &self,
        req: &CreateBotTokenRequest,
    ) -> anyhow::Result<BotTokenData> {
        let url = format!("{}/ai/identity/sec/api/createBotToken", self.base_url);
        debug!(
            trace_id = %req.trace_id,
            agent_id = %req.agent_id,
            scope = %req.scope,
            "createBotToken request"
        );
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
        if !resp.is_ok() {
            warn!(
                trace_id = %req.trace_id,
                code = %resp.code,
                msg = %resp.message,
                "createBotToken failed"
            );
            anyhow::bail!("createBotToken: code={}, msg={}", resp.code, resp.message);
        }
        debug!(trace_id = %req.trace_id, "createBotToken success");
        resp.data.ok_or_else(|| anyhow!("createBotToken: no data"))
    }

    /// 2.3 BotToken 兑换 AgentToken
    ///
    /// signParam = platformId + agentId + botToken
    async fn api_exchange_agent_token(
        &self,
        bot_token: &str,
        agent_id: &str,
        session_id: &str,
        request_id: &str,
        domain: &str,
    ) -> anyhow::Result<AgentTokenData> {
        let url = format!("{}/ai/identity/sec/api/exchangeAgentToken", self.base_url);
        let trace_id = uuid::Uuid::new_v4().to_string();
        let timestamp = chrono::Utc::now().timestamp_millis();
        let signature = self.sign_exchange_agent_token(agent_id, bot_token, timestamp, &trace_id);
        let body = serde_json::json!({
            "traceId": trace_id,
            "clientId": self.client_id,
            "platformId": self.platform_id,
            "agentId": agent_id,
            "sessionId": session_id,
            "requestId": request_id,
            "botToken": bot_token,
            "domain": domain,
            "envInfo": collect_env_info(),
            "timestamp": timestamp,
            "signature": signature,
        });
        debug!(
            trace_id = %trace_id,
            agent_id = agent_id,
            domain = domain,
            "exchangeAgentToken request"
        );
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
        if !resp.is_ok() {
            warn!(
                trace_id = %trace_id,
                code = %resp.code,
                msg = %resp.message,
                "exchangeAgentToken failed"
            );
            anyhow::bail!(
                "exchangeAgentToken: code={}, msg={}",
                resp.code,
                resp.message
            );
        }
        debug!(trace_id = %trace_id, "exchangeAgentToken success");
        resp.data
            .ok_or_else(|| anyhow!("exchangeAgentToken: no data"))
    }

    /// 2.2 BotToken 兑换用户身份 (SSO / ME)
    ///
    /// signParam = platformId + agentId + authType + identityType + botToken
    #[allow(dead_code)]
    async fn api_exchange_user_token(
        &self,
        bot_token: &str,
        agent_id: &str,
        session_id: &str,
        request_id: &str,
        domain: &str,
    ) -> anyhow::Result<UserIdentityData> {
        let url = format!("{}/ai/identity/sec/api/exchangeUserToken", self.base_url);
        let trace_id = uuid::Uuid::new_v4().to_string();
        let timestamp = chrono::Utc::now().timestamp_millis();
        let signature = self.sign_exchange_user_token(agent_id, bot_token, timestamp, &trace_id);
        let body = serde_json::json!({
            "traceId": trace_id,
            "clientId": self.client_id,
            "platformId": self.platform_id,
            "agentId": agent_id,
            "sessionId": session_id,
            "requestId": request_id,
            "botToken": bot_token,
            "authType": self.auth_type,
            "identityType": self.identity_type,
            "domain": domain,
            "envInfo": collect_env_info(),
            "timestamp": timestamp,
            "signature": signature,
        });
        debug!(
            trace_id = %trace_id,
            agent_id = agent_id,
            domain = domain,
            "exchangeUserToken request"
        );
        let resp: ApiResponse<UserIdentityData> = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeUserToken request failed")?
            .json()
            .await
            .context("exchangeUserToken response parse failed")?;
        if !resp.is_ok() {
            warn!(
                trace_id = %trace_id,
                code = %resp.code,
                msg = %resp.message,
                "exchangeUserToken failed"
            );
            anyhow::bail!(
                "exchangeUserToken: code={}, msg={}",
                resp.code,
                resp.message
            );
        }
        debug!(trace_id = %trace_id, "exchangeUserToken success");
        resp.data
            .ok_or_else(|| anyhow!("exchangeUserToken: no data"))
    }

    /// 2.7 销毁智能体身份 BotToken
    async fn api_destroy_bot_token(&self, bot_token: &str) -> anyhow::Result<()> {
        let url = format!("{}/ai/identity/sec/api/revokeBotToken", self.base_url);
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
        if !resp.is_ok() {
            warn!(
                code = %resp.code,
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
        let url = format!("{}/ai/identity/sec/api/exchangeBotToken", self.base_url);
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
        if !resp.is_ok() {
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
        tenant_scope: &str,
        agent_id: &str,
        auth_type: &str,
        user_id: &str,
        scope: &str,
    ) -> String {
        format!(
            "joysafeter:bot_token:{}:{:x}:{}:{}:{:x}:{:x}",
            platform_id,
            md5::compute(tenant_scope.as_bytes()),
            agent_id,
            auth_type,
            md5::compute(user_id.as_bytes()),
            md5::compute(scope.as_bytes()),
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
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            warn!(
                key = key,
                "Redis connection failed for BotToken cache write"
            );
            return;
        };
        if let Err(e) = conn.set_ex::<_, _, ()>(key, value, ttl_secs).await {
            warn!(key = key, error = %e, "Failed to cache BotToken");
        }
    }

    async fn delete_cache_key(&self, key: &str) {
        if let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await {
            let _ = conn.del::<_, ()>(key).await;
        }
    }

    // --- Core exchange flow --------------------------------------------------

    async fn get_or_create_bot_token(
        &self,
        config: &JdIdentityConfig,
        ctx: &IdentityResolveContext,
    ) -> anyhow::Result<String> {
        let scope_str = ctx.egress_hosts.join(",");
        let tenant_scope = format!("{}:{}", ctx.project_id, config.tenant_code);
        let key = Self::cache_key(
            &self.platform_id,
            &tenant_scope,
            &ctx.agent_id,
            &self.auth_type,
            &ctx.user_id,
            &scope_str,
        );

        // Cache hit
        if let Some(cached) = self.get_cached_bot_token(&key).await {
            debug!(cache_key = %key, "BotToken cache hit");
            return Ok(cached);
        }

        // Cache miss → call createBotToken
        debug!(cache_key = %key, "BotToken cache miss, creating");
        let trace_id = uuid::Uuid::new_v4().to_string();
        let timestamp = chrono::Utc::now().timestamp_millis();
        let signature =
            self.sign_create_bot_token(&ctx.agent_id, &ctx.identity_token, timestamp, &trace_id);
        // Reconstruct a minimal headersMap containing only the SSO cookie the
        // identity platform needs. The user's full request headers are NOT
        // persisted anywhere (privacy); we rebuild just the Cookie here from the
        // decrypted identity_token.
        let headers_map = if ctx.identity_token.is_empty() {
            None
        } else {
            // Cookie name must match what the API layer captured with. The API
            // uses AGENT_IDENTITY_COOKIE_NAME (provider-agnostic); fall back to
            // the JD default only if unset.
            let cookie_name = std::env::var("AGENT_IDENTITY_COOKIE_NAME")
                .ok()
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| "sso.jd.com".to_string());
            Some(HashMap::from([(
                "Cookie".to_string(),
                format!("{}={}", cookie_name, ctx.identity_token),
            )]))
        };

        let req = CreateBotTokenRequest {
            trace_id,
            client_id: self.client_id.clone(),
            platform_id: self.platform_id.clone(),
            agent_id: ctx.agent_id.clone(),
            session_id: ctx.session_id.clone(),
            request_id: ctx.task_id.clone(),
            scope: scope_str,
            tenant_code: config.tenant_code.clone(),
            auth_type: self.auth_type.clone(),
            identity_type: self.identity_type.clone(),
            identity_token: ctx.identity_token.clone(),
            agent_scene: self.agent_scene.clone(),
            env_info: Some(collect_env_info()),
            headers_map,
            timestamp,
            signature,
            extensions: None,
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
        match agent_metadata.and_then(|metadata| metadata.get("agent_identity")) {
            Some(config) => JdIdentityConfig::from_json(config).is_some(),
            None => true,
        }
    }

    async fn resolve(
        &self,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection> {
        let Some(config) = JdIdentityConfig::from_json(&context.provider_config) else {
            debug!(agent_id = %context.agent_id, "Agent identity explicitly disabled");
            return Ok(AgentIdentityInjection::default());
        };

        // 1. Get BotToken — two paths:
        //    a) API scenario: auth_code → exchangeBotToken(authCode) → botToken
        //    b) Web SSO scenario: identityToken → createBotToken → botToken (cached)
        let bot_token = if let Some(ref auth_code) = context.auth_code {
            let cache_key = Self::cache_key(
                &self.platform_id,
                &format!("{}:{}", context.project_id, config.tenant_code),
                &context.agent_id,
                &self.auth_type,
                &context.user_id,
                &context.egress_hosts.join(","),
            );
            if let Some(cached) = self.get_cached_bot_token(&cache_key).await {
                debug!(cache_key = %cache_key, "BotToken cache hit for auth-code retry");
                cached
            } else {
                let data = self
                    .api_exchange_bot_token_from_auth_code(auth_code)
                    .await?;
                let ttl = data.expires_in.saturating_sub(60).max(60);
                self.cache_bot_token(&cache_key, &data.bot_token, ttl).await;
                info!(
                    agent_id = %context.agent_id,
                    source = "auth_code",
                    expires_in = data.expires_in,
                    "Obtained BotToken via BotAuthCode"
                );
                data.bot_token
            }
        } else {
            // Path B: Web SSO — create with identityToken (or use cache)
            self.get_or_create_bot_token(&config, context).await?
        };

        let remove_headers = vec!["x-security-agenttoken".to_string()];
        let mut targets = Vec::with_capacity(context.egress_hosts.len());
        for host in &context.egress_hosts {
            let agent_token_data = self
                .api_exchange_agent_token(
                    &bot_token,
                    &context.agent_id,
                    &context.session_id,
                    &context.task_id,
                    host,
                )
                .await?;
            targets.push(IdentityEgressTarget {
                host: host.clone(),
                port: 443,
                tls: true,
                inject_headers: vec![(
                    "X-Security-AgentToken".to_string(),
                    agent_token_data.agent_token.clone(),
                )],
                remove_headers: remove_headers.clone(),
            });
        }

        info!(
            agent_id = %context.agent_id,
            targets = targets.len(),
            "Agent identity resolved — X-Security-AgentToken injected for all egress hosts"
        );

        Ok(AgentIdentityInjection { targets })
    }

    async fn cleanup(&self, context: &IdentityCleanupContext) {
        let pattern = if let Some(ref user_id) = context.user_id {
            format!(
                "joysafeter:bot_token:*:*:{}:*:{:x}:*",
                context.agent_id,
                md5::compute(user_id.as_bytes())
            )
        } else {
            format!("joysafeter:bot_token:*:*:{}:*:*:*", context.agent_id)
        };

        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            warn!("Redis unavailable for BotToken cleanup");
            return;
        };

        let mut keys = Vec::new();
        let mut cursor = 0_u64;
        loop {
            let scan: redis::RedisResult<(u64, Vec<String>)> = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg(&pattern)
                .arg("COUNT")
                .arg(100)
                .query_async(&mut conn)
                .await;
            let (next_cursor, mut batch) = match scan {
                Ok(result) => result,
                Err(e) => {
                    warn!(error = %e, "Failed to scan BotToken keys for cleanup");
                    return;
                }
            };
            keys.append(&mut batch);
            cursor = next_cursor;
            if cursor == 0 {
                break;
            }
        }

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

#[cfg(test)]
mod tests {
    use super::{JdAgentIdentityProvider, JdIdentityConfig};
    use agent_identity_trait::{AgentIdentityProvider, IdentityResolveContext};
    use redis::AsyncCommands;
    use serde_json::json;
    use std::sync::Arc;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;
    use tokio::sync::Mutex;
    use tokio::time::{timeout, Duration};

    fn provider_for_config_tests() -> JdAgentIdentityProvider {
        JdAgentIdentityProvider {
            http: reqwest::Client::builder()
                .timeout(Duration::from_millis(100))
                .build()
                .expect("build HTTP client"),
            base_url: "http://127.0.0.1:1".to_string(),
            sign_secret: "secret".to_string(),
            client_id: "client".to_string(),
            platform_id: "platform".to_string(),
            auth_type: "sso".to_string(),
            identity_type: "cookie".to_string(),
            agent_scene: "test".to_string(),
            redis_client: redis::Client::open("redis://127.0.0.1:1/").expect("create Redis client"),
        }
    }

    #[test]
    fn absent_agent_identity_config_uses_global_default() {
        let provider = provider_for_config_tests();

        assert!(provider.has_config(None));
        assert!(provider.has_config(Some(&json!({}))));
    }

    #[test]
    fn explicit_enabled_agent_identity_config_is_active() {
        let provider = provider_for_config_tests();

        assert!(provider.has_config(Some(&json!({"agent_identity": {"enabled": true}}))));
    }

    #[test]
    fn explicit_disabled_agent_identity_config_is_inactive() {
        let provider = provider_for_config_tests();

        assert!(!provider.has_config(Some(&json!({"agent_identity": {"enabled": false}}))));
    }

    #[tokio::test]
    async fn resolve_explicit_disabled_config_returns_no_injection() {
        let provider = provider_for_config_tests();
        let context = IdentityResolveContext {
            project_id: "project".to_string(),
            user_id: "user".to_string(),
            agent_id: "agent".to_string(),
            session_id: "session".to_string(),
            task_id: "task".to_string(),
            identity_token: "identity-token".to_string(),
            auth_code: None,
            user_name: "user@example.com".to_string(),
            provider_config: json!({"enabled": false}),
            egress_hosts: vec!["api.example.com".to_string()],
        };

        let injection = timeout(Duration::from_millis(250), provider.resolve(&context))
            .await
            .expect("disabled resolve must not perform network I/O")
            .expect("disabled resolve");

        assert!(injection.targets.is_empty());
    }

    #[test]
    fn cache_key_is_partitioned_by_tenant_user_and_scope() {
        let base = JdAgentIdentityProvider::cache_key(
            "platform",
            "project-a:tenant-a",
            "agent",
            "sso",
            "user-a",
            "api.example.com",
        );
        assert_ne!(
            base,
            JdAgentIdentityProvider::cache_key(
                "platform",
                "project-b:tenant-a",
                "agent",
                "sso",
                "user-a",
                "api.example.com",
            )
        );
        assert_ne!(
            base,
            JdAgentIdentityProvider::cache_key(
                "platform",
                "project-a:tenant-a",
                "agent",
                "sso",
                "user-b",
                "api.example.com",
            )
        );
        assert_ne!(
            base,
            JdAgentIdentityProvider::cache_key(
                "platform",
                "project-a:tenant-a",
                "agent",
                "sso",
                "user-a",
                "other.example.com",
            )
        );
    }

    #[tokio::test]
    async fn auth_code_retry_reuses_cached_bot_token_before_redeeming_code() {
        let Some(redis_url) = std::env::var("JOYSAFETER_TEST_REDIS_URL").ok() else {
            eprintln!("skipping Redis identity retry test: JOYSAFETER_TEST_REDIS_URL is not set");
            return;
        };
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind identity test server");
        let address = listener.local_addr().expect("identity test address");
        let observed_paths = Arc::new(Mutex::new(Vec::new()));
        let server_paths = observed_paths.clone();
        let server = tokio::spawn(async move {
            loop {
                let Ok(Ok((mut socket, _))) =
                    timeout(Duration::from_millis(500), listener.accept()).await
                else {
                    break;
                };
                let mut request = vec![0_u8; 8192];
                let size = socket
                    .read(&mut request)
                    .await
                    .expect("read identity request");
                let request = String::from_utf8_lossy(&request[..size]);
                let path = request
                    .lines()
                    .next()
                    .and_then(|line| line.split_whitespace().nth(1))
                    .expect("identity request path")
                    .to_string();
                server_paths.lock().await.push(path.clone());
                let body = if path.ends_with("/exchangeBotToken") {
                    json!({
                        "success": true,
                        "code": "200",
                        "data": {"botToken": "exchanged-bot", "expiresIn": 300}
                    })
                } else {
                    json!({
                        "success": true,
                        "code": "200",
                        "data": {"agentToken": "agent-token", "expiresIn": 300}
                    })
                }
                .to_string();
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                socket
                    .write_all(response.as_bytes())
                    .await
                    .expect("write identity response");
            }
        });

        let redis_client = redis::Client::open(redis_url).expect("create Redis client");
        let provider = JdAgentIdentityProvider {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(2))
                .build()
                .expect("build HTTP client"),
            base_url: format!("http://{address}"),
            sign_secret: "secret".to_string(),
            client_id: "client".to_string(),
            platform_id: "platform".to_string(),
            auth_type: "sso".to_string(),
            identity_type: "cookie".to_string(),
            agent_scene: "test".to_string(),
            redis_client: redis_client.clone(),
        };
        let context = IdentityResolveContext {
            project_id: "project".to_string(),
            user_id: "user".to_string(),
            agent_id: "agent".to_string(),
            session_id: "session".to_string(),
            task_id: "task".to_string(),
            identity_token: String::new(),
            auth_code: Some("one-time-code".to_string()),
            user_name: "user@example.com".to_string(),
            provider_config: json!({"tenant_code": "tenant"}),
            egress_hosts: vec!["api.example.com".to_string()],
        };
        let config =
            JdIdentityConfig::from_json(&context.provider_config).expect("identity config");
        let cache_key = JdAgentIdentityProvider::cache_key(
            &provider.platform_id,
            &format!("{}:{}", context.project_id, config.tenant_code),
            &context.agent_id,
            &provider.auth_type,
            &context.user_id,
            &context.egress_hosts.join(","),
        );
        let mut redis = redis_client
            .get_multiplexed_async_connection()
            .await
            .expect("connect Redis");
        redis
            .set_ex::<_, _, ()>(&cache_key, "cached-bot", 60)
            .await
            .expect("seed BotToken cache");

        let injection = provider.resolve(&context).await.expect("resolve identity");
        assert_eq!(injection.targets.len(), 1);
        server.await.expect("identity test server");
        let paths = observed_paths.lock().await.clone();
        assert_eq!(
            paths,
            vec!["/ai/identity/sec/api/exchangeAgentToken".to_string()]
        );
        let _: () = redis.del(cache_key).await.expect("clean BotToken cache");
    }
}
