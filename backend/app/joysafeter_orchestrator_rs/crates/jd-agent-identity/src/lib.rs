//! JD Agent Identity Protocol implementation.
//!
//! Internal crate — not published with JoySafeter open-source releases.
//!
//! Implements the JD Agent Identity Protocol with four APIs:
//! - 2.1 createBotToken — generate agent identity credential from user identity
//! - 2.2 exchangeUserToken — BotToken → user identityToken
//! - 2.3 exchangeAgentToken — BotToken → short-lived agentToken
//! - 2.7 destroyBotToken — revoke agent identity credential
//!
//! BotToken and UserToken are cached in Redis with their protocol-defined
//! identity dimensions. AgentToken remains task-scoped. Tokens are injected
//! only at the Envoy boundary and are never passed into the sandbox.

use std::collections::HashMap;
use std::time::{Duration, Instant};

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
    #[serde(skip_serializing_if = "String::is_empty")]
    tenant_code: String,
    auth_type: String,
    identity_type: String,
    identity_token: String,
    agent_scene: String,
    force_refresh: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    env_info: Option<HashMap<String, serde_json::Value>>,
    headers_map: HashMap<String, String>,
    timestamp: i64,
    signature: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    extensions: Option<HashMap<String, serde_json::Value>>,
}

/// Standard response envelope from the JD identity platform.
///
/// Note: `code` is a STRING ("200" = success), and there is a top-level
/// `success` boolean. `message` is retained for bounded, sanitized diagnostics.
#[derive(Debug, Deserialize)]
struct ApiResponse<T> {
    #[serde(default)]
    success: bool,
    #[serde(default)]
    code: String,
    #[serde(default)]
    message: Option<String>,
    data: Option<T>,
}

impl<T> ApiResponse<T> {
    /// A response is OK when success=true or code=="200".
    fn is_ok(&self) -> bool {
        self.success || self.code == "200"
    }
}

fn diagnostic_message(message: &str) -> String {
    const MAX_CHARS: usize = 512;

    let mut sanitized = String::with_capacity(message.len().min(MAX_CHARS));
    let mut chars = message.chars();
    for ch in chars.by_ref().take(MAX_CHARS) {
        sanitized.push(if ch.is_control() { ' ' } else { ch });
    }
    if chars.next().is_some() {
        sanitized.push('…');
    }
    sanitized
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
    #[serde(default)]
    expires_in: u64,
}

#[derive(Debug)]
struct CachedToken {
    value: String,
    remaining_seconds: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExchangeUserTokenRequest {
    trace_id: String,
    client_id: String,
    platform_id: String,
    agent_id: String,
    session_id: String,
    request_id: String,
    bot_token: String,
    auth_type: String,
    identity_type: String,
    domain: String,
    env_info: HashMap<String, serde_json::Value>,
    timestamp: i64,
    signature: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    extensions: Option<HashMap<String, serde_json::Value>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UserIdentityData {
    user_name: String,
    identity_token: String,
    /// Credential validity in seconds. Some successful responses omit it.
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

fn cache_ttl_seconds(expires_in: u64) -> u64 {
    // Keep a 60-second safety margin without ever extending a short-lived
    // credential beyond the lifetime advertised by the identity platform.
    expires_in.saturating_sub(60).max(1)
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
/// Field names and nesting mirror `EnvInfoUtils.collectMap()` from the JD Java
/// client, including `jdos.podIp` rather than a top-level `podIp`.
fn collect_env_info(
    pod_ip: Option<&str>,
    app_name: Option<&str>,
) -> HashMap<String, serde_json::Value> {
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

    info.insert(
        "ips".to_string(),
        pod_ip.map_or_else(|| json!([]), |pod_ip| json!([pod_ip])),
    );
    info.insert("macs".to_string(), json!([]));

    let cpu_count = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    info.insert("cpuLogical".to_string(), json!(cpu_count));
    info.insert("cpuModel".to_string(), json!(""));

    let tz = std::env::var("TZ").unwrap_or_else(|_| "UTC".to_string());
    info.insert("timezone".to_string(), json!(tz));
    info.insert("utcOffset".to_string(), json!(""));
    info.insert("locale".to_string(), json!(""));

    info.insert("pid".to_string(), json!(std::process::id()));
    info.insert(
        "collectedAt".to_string(),
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
    if !k8s_namespace.trim().is_empty() {
        info.insert("podNamespace".to_string(), json!(k8s_namespace.trim()));
    }

    // JDOS environment is nested in the Java SDK response map.
    let mut jdos = HashMap::new();
    for (env_name, field_name) in [
        ("JDOS_DATACENTER", "datacenter"),
        ("JDOS_AREA", "area"),
        ("umpCenter", "umpCenter"),
        ("JDOS_ZONE", "zone"),
        ("deploy_app_name", "deployAppName"),
        ("SYSTEM_NAME", "systemName"),
        ("APP_ID", "appId"),
        ("APP_GROUP", "appGroup"),
        ("JDOS_ENV", "env"),
        ("JDOS_REGION", "region"),
        ("JDOS_CONF_UUID", "confUuid"),
        ("JDOS_IMAGE", "image"),
        ("JDOS_TENANT", "tenant"),
        ("JDOS_SITE_ENV", "siteEnv"),
        ("INSTANCE_NAME", "instanceName"),
        ("JDOS_CPU", "cpu"),
        ("JDOS_MEMORY", "memory"),
        ("jdos_pfinder_status", "pfinderStatus"),
        ("JDOS_PORT_RETAIN", "portRetain"),
        ("DEPLOY_UNIT_ID", "deployUnitId"),
    ] {
        if let Ok(value) = std::env::var(env_name) {
            let value = value.trim();
            if !value.is_empty() {
                jdos.insert(field_name.to_string(), json!(value));
            }
        }
    }
    if let Some(pod_ip) = pod_ip {
        jdos.insert("podIp".to_string(), json!(pod_ip));
    }
    if let Some(app_name) = app_name {
        jdos.insert("appName".to_string(), json!(app_name));
    }
    if !jdos.is_empty() {
        info.insert("jdos".to_string(), json!(jdos));
    }
    info.insert("sdkType".to_string(), json!(1));

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
/// 3. exchangeUserToken (server-side cached, injected as a user credential)
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
    /// Temporary diagnostic switch. When false, resolve only AgentToken and
    /// never exchange or inject the current executor's UserToken.
    exchange_user_token_enabled: bool,
    user_token_cookie_name: String,
    pod_ip: Option<String>,
    app_name: Option<String>,
    redis_client: redis::Client,
}

fn default_user_token_cookie_name(auth_type: &str) -> &'static str {
    if auth_type.eq_ignore_ascii_case("me") {
        "TP_AGENT"
    } else {
        "sso.jd.com"
    }
}

fn validate_enum_value(name: &str, value: String, allowed: &[&str]) -> anyhow::Result<String> {
    let value = value.trim().to_string();
    if allowed.contains(&value.as_str()) {
        Ok(value)
    } else {
        anyhow::bail!(
            "{name} has unsupported value; expected one of: {}",
            allowed.join(", ")
        )
    }
}

fn env_bool(name: &str, default: bool) -> anyhow::Result<bool> {
    let Ok(raw) = std::env::var(name) else {
        return Ok(default);
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => anyhow::bail!("{name} must be a boolean value"),
    }
}

fn validate_pod_ip(value: Option<&str>, required: bool) -> anyhow::Result<Option<String>> {
    let value = value.map(str::trim).filter(|value| !value.is_empty());
    let Some(value) = value else {
        if required {
            anyhow::bail!(
                "JDOS_POD_IP or POD_IP is required when JD_AGENT_IDENTITY_EXCHANGE_USER_TOKEN_ENABLED=true"
            );
        }
        return Ok(None);
    };

    value
        .parse::<std::net::IpAddr>()
        .with_context(|| format!("POD_IP must be a valid IPv4 or IPv6 address, got {value:?}"))?;
    Ok(Some(value.to_string()))
}

fn validate_app_name(value: Option<&str>, required: bool) -> anyhow::Result<Option<String>> {
    let value = value.map(str::trim).filter(|value| !value.is_empty());
    let Some(value) = value else {
        if required {
            anyhow::bail!(
                "APP_NAME is required when JD_AGENT_IDENTITY_EXCHANGE_USER_TOKEN_ENABLED=true"
            );
        }
        return Ok(None);
    };
    Ok(Some(value.to_string()))
}

impl JdAgentIdentityProvider {
    /// Create from environment variables + a Redis client.
    ///
    /// Required env vars:
    /// - AGENT_IDENTITY_BASE_URL: API base URL
    /// - JD_AGENT_IDENTITY_CLIENT_SECRET: signing secret for getSign()
    /// - JD_AGENT_IDENTITY_CLIENT_ID: 申请的应用标识
    /// - JD_AGENT_IDENTITY_PLATFORM_ID: 智能体平台ID
    /// - JD_AGENT_IDENTITY_AUTH_TYPE: 用户身份认证方式 (e.g. "SSO")
    /// - JD_AGENT_IDENTITY_IDENTITY_TYPE: 用户身份凭证类型 (e.g. "cookie")
    /// - JD_AGENT_IDENTITY_AGENT_SCENE: 智能体业务场景
    /// - JD_AGENT_IDENTITY_EXCHANGE_USER_TOKEN_ENABLED: whether to exchange and inject UserToken
    ///
    /// AGENT_IDENTITY_COOKIE_NAME is consumed only by the API when capturing
    /// the incoming browser cookie. JD_AGENT_IDENTITY_USER_TOKEN_COOKIE_NAME
    /// identifies the downstream cookie carrying exchangeUserToken.identityToken.
    pub fn from_env(redis_client: redis::Client) -> anyhow::Result<Self> {
        fn required(name: &str) -> anyhow::Result<String> {
            let value = std::env::var(name).unwrap_or_default();
            if value.trim().is_empty() {
                anyhow::bail!("{name} is required when AGENT_IDENTITY_PROVIDER=jd");
            }
            Ok(value)
        }

        let base_url = required("AGENT_IDENTITY_BASE_URL")?;
        let auth_type = validate_enum_value(
            "JD_AGENT_IDENTITY_AUTH_TYPE",
            std::env::var("JD_AGENT_IDENTITY_AUTH_TYPE").unwrap_or_else(|_| "SSO".to_string()),
            &["NONE", "SSO", "JDPin", "Service"],
        )?;
        let identity_type = validate_enum_value(
            "JD_AGENT_IDENTITY_IDENTITY_TYPE",
            std::env::var("JD_AGENT_IDENTITY_IDENTITY_TYPE")
                .unwrap_or_else(|_| "ssoTicket".to_string()),
            &[
                "ssoTicket",
                "meToken",
                "meUserToken",
                "meIMAid",
                "hioToken",
                "cloudInstanceId",
                "sandboxInstanceId",
                "thor",
                "flash",
            ],
        )?;
        let agent_scene = validate_enum_value(
            "JD_AGENT_IDENTITY_AGENT_SCENE",
            std::env::var("JD_AGENT_IDENTITY_AGENT_SCENE")
                .unwrap_or_else(|_| "jdcloud_box_skill".to_string()),
            &[
                "master_agent",
                "jdcloud_box_skill",
                "jdcloud_box_rpa",
                "local_box_skill",
                "local_box_rpa",
            ],
        )?;
        let user_token_cookie_name = std::env::var("JD_AGENT_IDENTITY_USER_TOKEN_COOKIE_NAME")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| default_user_token_cookie_name(&auth_type).to_string());
        let exchange_user_token_enabled =
            env_bool("JD_AGENT_IDENTITY_EXCHANGE_USER_TOKEN_ENABLED", true)?;
        let pod_ip = std::env::var("JDOS_POD_IP")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .or_else(|| std::env::var("POD_IP").ok());
        let pod_ip = validate_pod_ip(pod_ip.as_deref(), exchange_user_token_enabled)?;
        let app_name = validate_app_name(
            std::env::var("APP_NAME").ok().as_deref(),
            exchange_user_token_enabled,
        )?;
        Ok(Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .expect("build reqwest client"),
            base_url: base_url.trim_end_matches('/').to_string(),
            sign_secret: required("JD_AGENT_IDENTITY_CLIENT_SECRET")?,
            client_id: required("JD_AGENT_IDENTITY_CLIENT_ID")?,
            platform_id: required("JD_AGENT_IDENTITY_PLATFORM_ID")?,
            auth_type,
            identity_type,
            agent_scene,
            exchange_user_token_enabled,
            user_token_cookie_name,
            pod_ip,
            app_name,
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
        let started = Instant::now();
        debug!(
            trace_id = %req.trace_id,
            agent_id = %req.agent_id,
            scope = %req.scope,
            credential_source = "browser_cookie",
            auth_type = %req.auth_type,
            identity_type = %req.identity_type,
            agent_scene = %req.agent_scene,
            tenant_code_configured = !req.tenant_code.trim().is_empty(),
            "createBotToken request"
        );
        let response = self
            .http
            .post(&url)
            .json(req)
            .send()
            .await
            .context("createBotToken request failed")?;
        let http_status = response.status();
        let resp: ApiResponse<BotTokenData> = response
            .json()
            .await
            .context("createBotToken response parse failed")?;
        if !resp.is_ok() {
            let message = diagnostic_message(resp.message.as_deref().unwrap_or(""));
            warn!(
                trace_id = %req.trace_id,
                agent_id = %req.agent_id,
                session_id = %req.session_id,
                task_id = %req.request_id,
                credential_source = "browser_cookie",
                auth_type = %req.auth_type,
                identity_type = %req.identity_type,
                agent_scene = %req.agent_scene,
                tenant_code_configured = !req.tenant_code.trim().is_empty(),
                http_status = http_status.as_u16(),
                code = %resp.code,
                message = %message,
                elapsed_ms = started.elapsed().as_millis(),
                "createBotToken failed"
            );
            anyhow::bail!("createBotToken failed with code={}", resp.code);
        }
        let data = resp
            .data
            .ok_or_else(|| anyhow!("createBotToken: no data"))?;
        info!(
            trace_id = %req.trace_id,
            agent_id = %req.agent_id,
            session_id = %req.session_id,
            task_id = %req.request_id,
            http_status = http_status.as_u16(),
            expires_in = data.expires_in,
            elapsed_ms = started.elapsed().as_millis(),
            "createBotToken succeeded"
        );
        Ok(data)
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
        let started = Instant::now();
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
            "envInfo": collect_env_info(self.pod_ip.as_deref(), self.app_name.as_deref()),
            "timestamp": timestamp,
            "signature": signature,
        });
        debug!(
            trace_id = %trace_id,
            agent_id = agent_id,
            session_id = session_id,
            task_id = request_id,
            domain = domain,
            "exchangeAgentToken request"
        );
        let response = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeAgentToken request failed")?;
        let http_status = response.status();
        let resp: ApiResponse<AgentTokenData> = response
            .json()
            .await
            .context("exchangeAgentToken response parse failed")?;
        if !resp.is_ok() {
            let message = diagnostic_message(resp.message.as_deref().unwrap_or(""));
            warn!(
                trace_id = %trace_id,
                agent_id = agent_id,
                session_id = session_id,
                task_id = request_id,
                domain = domain,
                http_status = http_status.as_u16(),
                code = %resp.code,
                message = %message,
                elapsed_ms = started.elapsed().as_millis(),
                "exchangeAgentToken failed"
            );
            anyhow::bail!("exchangeAgentToken failed with code={}", resp.code);
        }
        let data = resp
            .data
            .ok_or_else(|| anyhow!("exchangeAgentToken: no data"))?;
        info!(
            trace_id = %trace_id,
            agent_id = agent_id,
            session_id = session_id,
            task_id = request_id,
            domain = domain,
            http_status = http_status.as_u16(),
            expires_in = data.expires_in,
            elapsed_ms = started.elapsed().as_millis(),
            "exchangeAgentToken succeeded"
        );
        Ok(data)
    }

    /// 2.2 BotToken 兑换用户身份 (SSO / ME)
    ///
    /// signParam = platformId + agentId + authType + identityType + botToken
    async fn api_exchange_user_token(
        &self,
        bot_token: &str,
        agent_id: &str,
        session_id: &str,
        request_id: &str,
        domain: &str,
    ) -> anyhow::Result<UserIdentityData> {
        let url = format!("{}/ai/identity/sec/api/exchangeUserToken", self.base_url);
        let started = Instant::now();
        let trace_id = uuid::Uuid::new_v4().to_string();
        let timestamp = chrono::Utc::now().timestamp_millis();
        let signature = self.sign_exchange_user_token(agent_id, bot_token, timestamp, &trace_id);
        let body = ExchangeUserTokenRequest {
            trace_id: trace_id.clone(),
            client_id: self.client_id.clone(),
            platform_id: self.platform_id.clone(),
            agent_id: agent_id.to_string(),
            session_id: session_id.to_string(),
            request_id: request_id.to_string(),
            bot_token: bot_token.to_string(),
            auth_type: self.auth_type.clone(),
            identity_type: self.identity_type.clone(),
            domain: domain.to_string(),
            env_info: collect_env_info(self.pod_ip.as_deref(), self.app_name.as_deref()),
            timestamp,
            signature,
            extensions: None,
        };
        let env_info_pod_ip = body
            .env_info
            .get("jdos")
            .and_then(JsonValue::as_object)
            .and_then(|jdos| jdos.get("podIp"))
            .and_then(JsonValue::as_str)
            .unwrap_or("<missing>");
        debug!(
            trace_id = %trace_id,
            agent_id = agent_id,
            session_id = session_id,
            task_id = request_id,
            domain = domain,
            env_info_pod_ip = env_info_pod_ip,
            "exchangeUserToken request"
        );
        let response = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeUserToken request failed")?;
        let http_status = response.status();
        let resp: ApiResponse<UserIdentityData> = response
            .json()
            .await
            .map_err(|error| anyhow!("exchangeUserToken response parse failed: {error}"))?;
        if !resp.is_ok() {
            let message = diagnostic_message(resp.message.as_deref().unwrap_or(""));
            warn!(
                trace_id = %trace_id,
                agent_id = agent_id,
                session_id = session_id,
                task_id = request_id,
                domain = domain,
                env_info_pod_ip = env_info_pod_ip,
                http_status = http_status.as_u16(),
                code = %resp.code,
                message = %message,
                elapsed_ms = started.elapsed().as_millis(),
                "exchangeUserToken failed"
            );
            anyhow::bail!("exchangeUserToken failed with code={}", resp.code);
        }
        let data = resp
            .data
            .ok_or_else(|| anyhow!("exchangeUserToken: no data"))?;
        info!(
            trace_id = %trace_id,
            agent_id = agent_id,
            session_id = session_id,
            task_id = request_id,
            domain = domain,
            http_status = http_status.as_u16(),
            expires_in = data.expires_in,
            elapsed_ms = started.elapsed().as_millis(),
            "exchangeUserToken succeeded"
        );
        Ok(data)
    }

    /// 2.7 销毁智能体身份 BotToken
    async fn api_destroy_bot_token(&self, bot_token: &str) -> anyhow::Result<()> {
        let url = format!("{}/ai/identity/sec/api/revokeBotToken", self.base_url);
        let body = serde_json::json!({
            "traceId": uuid::Uuid::new_v4().to_string(),
            "botToken": bot_token,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        let response = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("destroyBotToken request failed")?;
        let http_status = response.status();
        let resp: ApiResponse<JsonValue> = response
            .json()
            .await
            .context("destroyBotToken response parse failed")?;
        if !resp.is_ok() {
            let message = diagnostic_message(resp.message.as_deref().unwrap_or(""));
            warn!(
                http_status = http_status.as_u16(),
                code = %resp.code,
                message = %message,
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
        context: &IdentityResolveContext,
    ) -> anyhow::Result<BotTokenData> {
        let url = format!("{}/ai/identity/sec/api/exchangeBotToken", self.base_url);
        let started = Instant::now();
        let trace_id = uuid::Uuid::new_v4().to_string();
        let body = serde_json::json!({
            "traceId": trace_id,
            "botAuthCode": auth_code,
            "timestamp": chrono::Utc::now().timestamp_millis(),
        });
        debug!(
            trace_id = %trace_id,
            agent_id = %context.agent_id,
            session_id = %context.session_id,
            task_id = %context.task_id,
            project_id = %context.project_id,
            "exchangeBotToken request"
        );
        let response = self
            .http
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("exchangeBotToken(authCode) request failed")?;
        let http_status = response.status();
        let resp: ApiResponse<BotTokenData> = response
            .json()
            .await
            .context("exchangeBotToken(authCode) response parse failed")?;
        if !resp.is_ok() {
            let message = diagnostic_message(resp.message.as_deref().unwrap_or(""));
            warn!(
                trace_id = %trace_id,
                agent_id = %context.agent_id,
                session_id = %context.session_id,
                task_id = %context.task_id,
                project_id = %context.project_id,
                http_status = http_status.as_u16(),
                code = %resp.code,
                message = %message,
                elapsed_ms = started.elapsed().as_millis(),
                "exchangeBotToken failed"
            );
            anyhow::bail!("exchangeBotToken failed with code={}", resp.code);
        }
        let data = resp
            .data
            .ok_or_else(|| anyhow!("exchangeBotToken: no data"))?;
        info!(
            trace_id = %trace_id,
            agent_id = %context.agent_id,
            session_id = %context.session_id,
            task_id = %context.task_id,
            project_id = %context.project_id,
            http_status = http_status.as_u16(),
            expires_in = data.expires_in,
            elapsed_ms = started.elapsed().as_millis(),
            "exchangeBotToken succeeded"
        );
        Ok(data)
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

    /// UserToken cache key required by the identity protocol:
    /// platformId + agentId + authType + identityType + userName.
    fn user_token_cache_key(
        platform_id: &str,
        agent_id: &str,
        auth_type: &str,
        identity_type: &str,
        user_name: &str,
    ) -> String {
        format!(
            "joysafeter:user_token:{platform_id}:{agent_id}:{auth_type}:{identity_type}:{user_name}"
        )
    }

    fn user_identity_request_url(host_or_url: &str) -> String {
        let value = host_or_url.trim();
        if value.starts_with("https://") || value.starts_with("http://") {
            return value.to_string();
        }
        format!("https://{}/", value.trim_end_matches('.'))
    }

    async fn get_cached_token(&self, key: &str) -> Option<CachedToken> {
        let mut conn = self
            .redis_client
            .get_multiplexed_async_connection()
            .await
            .ok()?;
        // Fetch the value and its remaining lifetime in one Redis round trip.
        // The entry may expire between commands; a missing value or
        // non-positive TTL is therefore handled as a normal cache miss.
        let (value, ttl): (Option<String>, i64) = redis::pipe()
            .cmd("GET")
            .arg(key)
            .cmd("TTL")
            .arg(key)
            .query_async(&mut conn)
            .await
            .ok()?;
        let value = value?;
        if ttl <= 0 {
            return None;
        }
        Some(CachedToken {
            value,
            remaining_seconds: ttl as u64,
        })
    }

    async fn get_cached_bot_token(&self, key: &str) -> Option<CachedToken> {
        self.get_cached_token(key).await
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

    async fn get_cached_user_token(&self, key: &str) -> Option<CachedToken> {
        self.get_cached_token(key).await
    }

    async fn cache_user_token(&self, key: &str, value: &str, ttl_secs: u64) {
        let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await else {
            warn!("Redis connection failed for UserToken cache write");
            return;
        };
        if let Err(e) = conn.set_ex::<_, _, ()>(key, value, ttl_secs).await {
            warn!(error = %e, "Failed to cache UserToken");
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
    ) -> anyhow::Result<CachedToken> {
        let scope_str = ctx.egress_hosts.join(",");
        let tenant_scope = format!("{}:{}", ctx.project_id, config.tenant_code);
        let agent_id = ctx.agent_id.to_string();
        let user_id = ctx.user_id.to_string();
        let key = Self::cache_key(
            &self.platform_id,
            &tenant_scope,
            &agent_id,
            &self.auth_type,
            &user_id,
            &scope_str,
        );

        // Cache hit
        if let Some(cached) = self.get_cached_bot_token(&key).await {
            info!(
                provider = "jd",
                agent_id = %ctx.agent_id,
                session_id = %ctx.session_id,
                task_id = %ctx.task_id,
                project_id = %ctx.project_id,
                cache_status = "hit",
                "BotToken resolved from server cache"
            );
            return Ok(cached);
        }

        // Cache miss → call createBotToken
        debug!(
            provider = "jd",
            agent_id = %ctx.agent_id,
            session_id = %ctx.session_id,
            task_id = %ctx.task_id,
            project_id = %ctx.project_id,
            cache_status = "miss",
            "BotToken cache miss"
        );
        if ctx.identity_token.trim().is_empty() {
            anyhow::bail!(
                "AGENT_IDENTITY_AUTHORIZATION_REQUIRED: no cached BotToken, BotAuthCode, or browser identity credential for the current executor"
            );
        }
        if ctx.headers_map.is_empty() {
            anyhow::bail!(
                "AGENT_IDENTITY_AUTHORIZATION_REQUIRED: createBotToken requires captured client headers"
            );
        }
        let trace_id = uuid::Uuid::new_v4().to_string();
        let timestamp = chrono::Utc::now().timestamp_millis();
        let session_id = ctx.session_id.to_string();
        let task_id = ctx.task_id.to_string();
        let signature =
            self.sign_create_bot_token(&agent_id, &ctx.identity_token, timestamp, &trace_id);
        let req = CreateBotTokenRequest {
            trace_id,
            client_id: self.client_id.clone(),
            platform_id: self.platform_id.clone(),
            agent_id,
            session_id,
            request_id: task_id,
            scope: scope_str,
            tenant_code: config.tenant_code.clone(),
            auth_type: self.auth_type.clone(),
            identity_type: self.identity_type.clone(),
            identity_token: ctx.identity_token.clone(),
            agent_scene: self.agent_scene.clone(),
            force_refresh: false,
            env_info: Some(collect_env_info(
                self.pod_ip.as_deref(),
                self.app_name.as_deref(),
            )),
            headers_map: ctx.headers_map.clone(),
            timestamp,
            signature,
            extensions: None,
        };
        let data = self.api_create_bot_token(&req).await?;

        // Cache with a 60-second safety margin without exceeding expiry.
        let ttl = cache_ttl_seconds(data.expires_in);
        self.cache_bot_token(&key, &data.bot_token, ttl).await;
        info!(
            agent_id = %ctx.agent_id,
            expires_in = data.expires_in,
            "Created and cached BotToken"
        );

        Ok(CachedToken {
            value: data.bot_token,
            remaining_seconds: ttl,
        })
    }

    async fn get_or_exchange_user_token(
        &self,
        bot_token: &str,
        context: &IdentityResolveContext,
        host: &str,
        cached_user_token: Option<CachedToken>,
    ) -> anyhow::Result<CachedToken> {
        if let Some(cached) = cached_user_token {
            info!(
                provider = "jd",
                agent_id = %context.agent_id,
                session_id = %context.session_id,
                task_id = %context.task_id,
                project_id = %context.project_id,
                domain = host,
                cache_status = "hit",
                "UserToken resolved from server cache"
            );
            return Ok(cached);
        }

        // Identity resolution happens while the sandbox egress policy is being
        // built, before an MCP/Skill HTTP request exists. The trusted upstream
        // host is therefore represented by its configured HTTP(S) URL;
        // request-specific paths and query parameters are not available at
        // this stage.
        let request_url = Self::user_identity_request_url(host);
        let agent_id = context.agent_id.to_string();
        let session_id = context.session_id.to_string();
        let task_id = context.task_id.to_string();
        let data = self
            .api_exchange_user_token(bot_token, &agent_id, &session_id, &task_id, &request_url)
            .await?;
        if data.identity_token.trim().is_empty() {
            anyhow::bail!("exchangeUserToken returned an empty identityToken");
        }
        if data.user_name.trim().is_empty() {
            anyhow::bail!("exchangeUserToken returned an empty userName");
        }

        let key = Self::user_token_cache_key(
            &self.platform_id,
            &context.agent_id.to_string(),
            &self.auth_type,
            &self.identity_type,
            data.user_name.trim(),
        );
        // Do not cache beyond the provider's advertised lifetime. A response
        // without an expiry is cached only briefly so a stale credential does
        // not become effectively permanent.
        let ttl = cache_ttl_seconds(data.expires_in);
        self.cache_user_token(&key, &data.identity_token, ttl).await;
        info!(
            provider = "jd",
            agent_id = %context.agent_id,
            session_id = %context.session_id,
            task_id = %context.task_id,
            project_id = %context.project_id,
            domain = %request_url,
            cache_status = "miss",
            expires_in = data.expires_in,
            "Exchanged and cached UserToken"
        );
        Ok(CachedToken {
            value: data.identity_token,
            remaining_seconds: ttl,
        })
    }

    async fn resolve_bot_token(
        &self,
        config: &JdIdentityConfig,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<CachedToken> {
        if let Some(ref auth_code) = context.auth_code {
            let agent_id = context.agent_id.to_string();
            let user_id = context.user_id.to_string();
            let cache_key = Self::cache_key(
                &self.platform_id,
                &format!("{}:{}", context.project_id, config.tenant_code),
                &agent_id,
                &self.auth_type,
                &user_id,
                &context.egress_hosts.join(","),
            );
            // BotAuthCode is one-time authority supplied for this call. Always
            // exchange it and replace any cached BotToken for this actor/scope.
            let data = self
                .api_exchange_bot_token_from_auth_code(auth_code, context)
                .await?;
            let ttl = cache_ttl_seconds(data.expires_in);
            self.cache_bot_token(&cache_key, &data.bot_token, ttl).await;
            info!(
                agent_id = %context.agent_id,
                source = "auth_code",
                cache_status = "replaced",
                expires_in = data.expires_in,
                "Obtained BotToken via BotAuthCode"
            );
            Ok(CachedToken {
                value: data.bot_token,
                remaining_seconds: ttl,
            })
        } else {
            // Web SSO or refresh path: use the actor-scoped cache first, then
            // create a BotToken from captured browser identity if needed.
            self.get_or_create_bot_token(config, context).await
        }
    }

    fn injection_headers(
        &self,
        agent_token: &str,
        user_token: Option<&str>,
    ) -> (Vec<(String, String)>, Vec<String>) {
        let mut inject_headers =
            vec![("X-Security-AgentToken".to_string(), agent_token.to_string())];
        // Always remove sandbox-supplied identity headers. When UserToken
        // exchange is disabled this prevents an untrusted Cookie from taking
        // the place of the deliberately omitted user identity.
        let remove_headers = vec!["x-security-agenttoken".to_string(), "cookie".to_string()];
        if let Some(user_token) = user_token {
            inject_headers.push((
                "Cookie".to_string(),
                format!("{}={user_token}", self.user_token_cookie_name),
            ));
        }
        (inject_headers, remove_headers)
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
        let _ = agent_metadata;
        true
    }

    async fn resolve(
        &self,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection> {
        let resolve_started = Instant::now();
        let Some(config) = JdIdentityConfig::from_json(&context.provider_config) else {
            debug!(agent_id = %context.agent_id, "Agent identity explicitly disabled");
            return Ok(AgentIdentityInjection::default());
        };
        let user_id = context.user_id.to_string();
        let actor_id_hash = format!("{:x}", md5::compute(user_id.as_bytes()));
        info!(
            provider = "jd",
            agent_id = %context.agent_id,
            session_id = %context.session_id,
            task_id = %context.task_id,
            project_id = %context.project_id,
            actor_id_hash = %actor_id_hash,
            targets = context.egress_targets.len().max(context.egress_hosts.len()),
            exchange_user_token_enabled = self.exchange_user_token_enabled,
            "Starting Agent Identity resolution"
        );

        // BotToken resolution and the independent UserToken cache lookup run in
        // parallel. On a fully warm path this removes one serialized Redis
        // round trip; on a BotToken exchange it hides the UserToken lookup
        // behind the remote identity call.
        let user_token_cache_key = Self::user_token_cache_key(
            &self.platform_id,
            &context.agent_id.to_string(),
            &self.auth_type,
            &self.identity_type,
            &context.user_name,
        );
        let cached_user_token_future = async {
            if self.exchange_user_token_enabled {
                self.get_cached_user_token(&user_token_cache_key).await
            } else {
                None
            }
        };
        let (bot_token, cached_user_token) = futures::join!(
            self.resolve_bot_token(&config, context),
            cached_user_token_future,
        );
        let bot_token = bot_token?;

        let requested_targets = if context.egress_targets.is_empty() {
            context
                .egress_hosts
                .iter()
                .map(|host| agent_identity_trait::IdentityEgressRequestTarget {
                    route_id: host.clone(),
                    endpoint: Self::user_identity_request_url(host),
                    host: host.clone(),
                    port: 443,
                    tls: true,
                })
                .collect::<Vec<_>>()
        } else {
            context.egress_targets.clone()
        };
        let first_target = requested_targets
            .first()
            .ok_or_else(|| anyhow!("agent identity requires at least one egress target"))?;

        // Dynamic user identity is an all-or-nothing contract. Never send only
        // AgentToken when the environment requested current-executor identity.
        let mut unique_endpoints = requested_targets
            .iter()
            .map(|target| target.endpoint.clone())
            .collect::<Vec<_>>();
        unique_endpoints.sort();
        unique_endpoints.dedup();
        let agent_token_futures = unique_endpoints.iter().map(|endpoint| async {
            let agent_id = context.agent_id.to_string();
            let session_id = context.session_id.to_string();
            let task_id = context.task_id.to_string();
            let data = self
                .api_exchange_agent_token(
                    &bot_token.value,
                    &agent_id,
                    &session_id,
                    &task_id,
                    endpoint,
                )
                .await?;
            Ok::<_, anyhow::Error>((endpoint.clone(), data.agent_token, data.expires_in))
        });
        let user_token_future = async {
            if self.exchange_user_token_enabled {
                self.get_or_exchange_user_token(
                    &bot_token.value,
                    context,
                    &first_target.endpoint,
                    cached_user_token,
                )
                .await
                .map(Some)
            } else {
                info!(
                    provider = "jd",
                    agent_id = %context.agent_id,
                    session_id = %context.session_id,
                    task_id = %context.task_id,
                    project_id = %context.project_id,
                    "UserToken exchange disabled by configuration"
                );
                Ok::<Option<CachedToken>, anyhow::Error>(None)
            }
        };
        let agent_tokens_future = futures::future::try_join_all(agent_token_futures);
        let (user_token, agent_tokens) =
            futures::try_join!(user_token_future, agent_tokens_future)?;
        let valid_for_seconds = agent_tokens
            .iter()
            .map(|(_, _, expires_in)| *expires_in)
            .chain(user_token.iter().map(|token| token.remaining_seconds))
            .filter(|seconds| *seconds > 0)
            .min();
        let agent_tokens = agent_tokens
            .into_iter()
            .map(|(endpoint, token, _)| (endpoint, token))
            .collect::<HashMap<_, _>>();

        let mut targets = Vec::with_capacity(requested_targets.len());
        for target in requested_targets {
            let agent_token = agent_tokens
                .get(&target.endpoint)
                .ok_or_else(|| anyhow!("missing AgentToken for resolved egress target"))?;
            let (inject_headers, remove_headers) = self.injection_headers(
                agent_token,
                user_token.as_ref().map(|token| token.value.as_str()),
            );
            targets.push(IdentityEgressTarget {
                route_id: target.route_id,
                host: target.host,
                port: target.port,
                tls: target.tls,
                inject_headers,
                remove_headers: remove_headers.clone(),
            });
        }

        info!(
            provider = "jd",
            agent_id = %context.agent_id,
            session_id = %context.session_id,
            task_id = %context.task_id,
            project_id = %context.project_id,
            targets = targets.len(),
            user_identity = user_token.is_some(),
            actor_id_hash = %actor_id_hash,
            elapsed_ms = resolve_started.elapsed().as_millis(),
            "Agent identity resolved for all egress hosts"
        );

        Ok(AgentIdentityInjection {
            targets,
            valid_for_seconds,
        })
    }

    async fn cleanup(&self, context: &IdentityCleanupContext) {
        let pattern = if let Some(ref user_id) = context.user_id {
            let user_id = user_id.to_string();
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
                if let Err(e) = self.api_destroy_bot_token(&bot_token.value).await {
                    warn!(error = %e, key = %key, "destroyBotToken failed (non-fatal)");
                }
            }
            self.delete_cache_key(key).await;
        }

        // UserToken is derived from BotToken and must not outlive an agent
        // identity cleanup. User-scoped cleanup conservatively evicts every
        // UserToken for the agent because the protocol cache key uses userName
        // while IdentityCleanupContext carries the immutable user ID.
        let user_token_pattern = format!("joysafeter:user_token:*:{}:*:*:*", context.agent_id);
        let mut user_token_keys = Vec::new();
        let mut cursor = 0_u64;
        loop {
            let scan: redis::RedisResult<(u64, Vec<String>)> = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg(&user_token_pattern)
                .arg("COUNT")
                .arg(100)
                .query_async(&mut conn)
                .await;
            let (next_cursor, mut batch) = match scan {
                Ok(result) => result,
                Err(e) => {
                    warn!(error = %e, "Failed to scan UserToken keys for cleanup");
                    return;
                }
            };
            user_token_keys.append(&mut batch);
            cursor = next_cursor;
            if cursor == 0 {
                break;
            }
        }
        for key in &user_token_keys {
            self.delete_cache_key(key).await;
        }

        if !keys.is_empty() || !user_token_keys.is_empty() {
            info!(
                agent_id = %context.agent_id,
                bot_token_keys_cleaned = keys.len(),
                user_token_keys_cleaned = user_token_keys.len(),
                "Agent identity token cleanup complete"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        cache_ttl_seconds, collect_env_info, default_user_token_cookie_name, diagnostic_message,
        validate_app_name, validate_enum_value, validate_pod_ip, ApiResponse,
        CreateBotTokenRequest, ExchangeUserTokenRequest, JdAgentIdentityProvider, JdIdentityConfig,
        UserIdentityData,
    };
    use agent_identity_trait::{
        AgentId, AgentIdentityProvider, IdentityResolveContext, ProjectId, SessionId, TaskId,
        UserId,
    };
    use redis::AsyncCommands;
    use serde_json::json;
    use std::collections::HashMap;
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
            auth_type: "SSO".to_string(),
            identity_type: "cookie".to_string(),
            agent_scene: "test".to_string(),
            exchange_user_token_enabled: true,
            user_token_cookie_name: "sso.jd.com".to_string(),
            pod_ip: Some("127.0.0.1".to_string()),
            app_name: Some("joysafeter-orchestrator".to_string()),
            redis_client: redis::Client::open("redis://127.0.0.1:1/").expect("create Redis client"),
        }
    }

    #[test]
    fn cache_ttl_keeps_margin_without_extending_short_lived_tokens() {
        assert_eq!(cache_ttl_seconds(300), 240);
        assert_eq!(cache_ttl_seconds(60), 1);
        assert_eq!(cache_ttl_seconds(30), 1);
        assert_eq!(cache_ttl_seconds(0), 1);
    }

    #[test]
    fn user_token_cookie_defaults_follow_jd_auth_type() {
        assert_eq!(default_user_token_cookie_name("sso"), "sso.jd.com");
        assert_eq!(default_user_token_cookie_name("SSO"), "sso.jd.com");
        assert_eq!(default_user_token_cookie_name("me"), "TP_AGENT");
    }

    #[test]
    fn auth_type_uses_protocol_enum_value_with_exact_case() {
        assert_eq!(
            validate_enum_value("authType", "SSO".to_string(), &["NONE", "SSO"])
                .expect("SSO is the documented protocol value"),
            "SSO"
        );
        assert!(validate_enum_value("authType", "sso".to_string(), &["NONE", "SSO"]).is_err());
    }

    #[test]
    fn pod_ip_is_required_for_user_token_exchange() {
        assert!(validate_pod_ip(None, true).is_err());
        assert!(validate_pod_ip(Some("  "), true).is_err());
        assert!(validate_pod_ip(Some("not-an-ip"), true).is_err());
        assert_eq!(
            validate_pod_ip(Some(" 10.244.4.71 "), true).expect("valid pod IP"),
            Some("10.244.4.71".to_string())
        );
        assert_eq!(
            validate_pod_ip(Some("fd00::10"), true).expect("valid IPv6 pod IP"),
            Some("fd00::10".to_string())
        );
        assert_eq!(validate_pod_ip(None, false).expect("optional pod IP"), None);
    }

    #[test]
    fn app_name_is_required_for_user_token_exchange() {
        assert!(validate_app_name(None, true).is_err());
        assert!(validate_app_name(Some("  "), true).is_err());
        assert_eq!(
            validate_app_name(Some(" joysafeter-orchestrator "), true)
                .expect("valid application name"),
            Some("joysafeter-orchestrator".to_string())
        );
        assert_eq!(
            validate_app_name(None, false).expect("optional application name"),
            None
        );
    }

    #[test]
    fn env_info_matches_java_sdk_pod_ip_nesting_and_field_names() {
        let info = collect_env_info(Some("10.244.4.71"), Some("joysafeter-orchestrator"));

        assert!(info.get("podIp").is_none());
        assert_eq!(info["jdos"]["podIp"], json!("10.244.4.71"));
        assert_eq!(info["jdos"]["appName"], json!("joysafeter-orchestrator"));
        assert_eq!(info.get("ips"), Some(&json!(["10.244.4.71"])));
        assert!(info.contains_key("cpuLogical"));
        assert!(info.contains_key("collectedAt"));
        assert_eq!(info.get("sdkType"), Some(&json!(1)));
        assert!(!info.contains_key("cpuCount"));
        assert!(!info.contains_key("timestamp"));
        assert!(!info.contains_key("k8sNamespace"));
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
    fn legacy_agent_switch_does_not_disable_environment_identity_policy() {
        let provider = provider_for_config_tests();

        assert!(provider.has_config(Some(&json!({"agent_identity": {"enabled": false}}))));
    }

    #[test]
    fn legacy_disabled_config_still_parses_tenant_metadata() {
        let config = JdIdentityConfig::from_json(&json!({
            "enabled": false,
            "tenant_code": "tenant"
        }))
        .expect("environment policy owns enablement");

        assert_eq!(config.tenant_code, "tenant");
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

    #[test]
    fn user_token_cache_key_uses_protocol_identity_dimensions() {
        assert_eq!(
            JdAgentIdentityProvider::user_token_cache_key(
                "platform",
                "agent",
                "sso",
                "cookie",
                "user@example.com",
            ),
            "joysafeter:user_token:platform:agent:sso:cookie:user@example.com"
        );
    }

    #[test]
    fn user_identity_domain_defaults_to_https_for_legacy_host_input() {
        assert_eq!(
            JdAgentIdentityProvider::user_identity_request_url("api.example.com."),
            "https://api.example.com/"
        );
    }

    #[test]
    fn user_identity_domain_preserves_configured_http_url() {
        assert_eq!(
            JdAgentIdentityProvider::user_identity_request_url("http://api.internal:8080/mcp"),
            "http://api.internal:8080/mcp"
        );
    }

    #[test]
    fn exchange_user_token_request_matches_protocol_fields() {
        let env_info = HashMap::from([
            ("jdos".to_string(), json!({"podIp": "10.244.0.82"})),
            ("ips".to_string(), json!(["10.244.0.82"])),
        ]);
        let request = ExchangeUserTokenRequest {
            trace_id: "trace".to_string(),
            client_id: "client".to_string(),
            platform_id: "platform".to_string(),
            agent_id: "agent".to_string(),
            session_id: "session".to_string(),
            request_id: "request".to_string(),
            bot_token: "bot-token".to_string(),
            auth_type: "SSO".to_string(),
            identity_type: "cookie".to_string(),
            domain: "https://api.example.com/mcp?query=1".to_string(),
            env_info,
            timestamp: 1_700_000_000_000,
            signature: "signature".to_string(),
            extensions: None,
        };

        let value = serde_json::to_value(request).expect("serialize exchangeUserToken request");
        assert_eq!(
            value,
            json!({
                "traceId": "trace",
                "clientId": "client",
                "platformId": "platform",
                "agentId": "agent",
                "sessionId": "session",
                "requestId": "request",
                "botToken": "bot-token",
                "authType": "SSO",
                "identityType": "cookie",
                "domain": "https://api.example.com/mcp?query=1",
                "envInfo": {
                    "jdos": {"podIp": "10.244.0.82"},
                    "ips": ["10.244.0.82"]
                },
                "timestamp": 1_700_000_000_000_i64,
                "signature": "signature"
            })
        );
    }

    #[test]
    fn create_bot_token_omits_empty_conditional_tenant_code() {
        let request = CreateBotTokenRequest {
            trace_id: "trace".to_string(),
            client_id: "client".to_string(),
            platform_id: "platform".to_string(),
            agent_id: "agent".to_string(),
            session_id: "session".to_string(),
            request_id: "request".to_string(),
            scope: "secocean.jd.com".to_string(),
            tenant_code: String::new(),
            auth_type: "SSO".to_string(),
            identity_type: "ssoTicket".to_string(),
            identity_token: "identity-token".to_string(),
            agent_scene: "jdcloud_box_skill".to_string(),
            force_refresh: false,
            env_info: Some(HashMap::new()),
            headers_map: HashMap::from([
                (
                    "Cookie".to_string(),
                    "sso.jd.com=identity-token".to_string(),
                ),
                ("User-Agent".to_string(), "browser-agent".to_string()),
            ]),
            timestamp: 1_700_000_000_000,
            signature: "signature".to_string(),
            extensions: None,
        };

        let value = serde_json::to_value(request).expect("serialize createBotToken request");
        assert!(value.get("tenantCode").is_none());
        assert_eq!(value["scope"], "secocean.jd.com");
        assert_eq!(value["forceRefresh"], false);
        assert_eq!(value["headersMap"]["Cookie"], "sso.jd.com=identity-token");
        assert_eq!(value["headersMap"]["User-Agent"], "browser-agent");
    }

    #[test]
    fn user_identity_response_matches_protocol_fields() {
        let response: ApiResponse<UserIdentityData> = serde_json::from_value(json!({
            "success": true,
            "code": "200",
            "message": "success",
            "data": {
                "traceId": "trace",
                "clientId": "client",
                "platformId": "platform",
                "agentId": "agent",
                "tenantCode": "tenant",
                "userName": "user@example.com",
                "identityToken": "user-identity-token",
                "createTime": 1_700_000_000_000_i64,
                "updateTime": 1_700_000_000_100_i64,
                "expireTime": 1_700_000_300_000_i64,
                "expiresIn": 300,
                "extensions": {"source": "jd"}
            }
        }))
        .expect("parse exchangeUserToken response");
        assert_eq!(response.message.as_deref(), Some("success"));
        let data = response.data.expect("response data");

        assert_eq!(data.user_name, "user@example.com");
        assert_eq!(data.identity_token, "user-identity-token");
        assert_eq!(data.expires_in, 300);

        let minimal: ApiResponse<UserIdentityData> = serde_json::from_value(json!({
            "success": true,
            "code": "200",
            "message": null,
            "data": {
                "userName": "user@example.com",
                "identityToken": "user-identity-token"
            }
        }))
        .expect("parse minimal exchangeUserToken response");
        assert!(minimal.message.is_none());
        assert_eq!(minimal.data.expect("response data").expires_in, 0);

        let incompatible: Result<ApiResponse<UserIdentityData>, _> =
            serde_json::from_value(json!({
                "success": true,
                "code": "200",
                "data": {"userToken": "wrong-field", "expiresIn": 300}
            }));
        assert!(incompatible.is_err());
    }

    #[test]
    fn upstream_diagnostic_message_is_single_line_and_bounded() {
        assert_eq!(
            diagnostic_message("validation\nfailed\r\n"),
            "validation failed  "
        );

        let oversized = "x".repeat(513);
        let sanitized = diagnostic_message(&oversized);
        assert_eq!(sanitized.chars().count(), 513);
        assert!(sanitized.ends_with('…'));
    }

    #[test]
    fn user_token_is_injected_as_cookie_alongside_agent_token() {
        let provider = provider_for_config_tests();
        let (inject_headers, remove_headers) =
            provider.injection_headers("agent-token", Some("user-token"));

        assert_eq!(
            inject_headers,
            vec![
                (
                    "X-Security-AgentToken".to_string(),
                    "agent-token".to_string(),
                ),
                ("Cookie".to_string(), "sso.jd.com=user-token".to_string(),),
            ]
        );
        assert_eq!(
            remove_headers,
            vec!["x-security-agenttoken".to_string(), "cookie".to_string()]
        );
    }

    #[test]
    fn agent_token_only_mode_does_not_inject_or_accept_a_cookie() {
        let provider = provider_for_config_tests();
        let (inject_headers, remove_headers) = provider.injection_headers("agent-token", None);

        assert_eq!(
            inject_headers,
            vec![(
                "X-Security-AgentToken".to_string(),
                "agent-token".to_string(),
            )]
        );
        assert_eq!(
            remove_headers,
            vec!["x-security-agenttoken".to_string(), "cookie".to_string()]
        );
    }

    #[tokio::test]
    async fn auth_code_always_redeems_and_replaces_cached_bot_token() {
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
            auth_type: "SSO".to_string(),
            identity_type: "cookie".to_string(),
            agent_scene: "test".to_string(),
            exchange_user_token_enabled: true,
            user_token_cookie_name: "sso.jd.com".to_string(),
            pod_ip: Some("127.0.0.1".to_string()),
            app_name: Some("joysafeter-orchestrator".to_string()),
            redis_client: redis_client.clone(),
        };
        let context = IdentityResolveContext {
            project_id: ProjectId::new(),
            user_id: UserId::new(),
            agent_id: AgentId::new(),
            session_id: SessionId::new(),
            task_id: TaskId::new(),
            identity_token: String::new(),
            headers_map: HashMap::new(),
            auth_code: Some("one-time-code".to_string()),
            user_name: "user@example.com".to_string(),
            provider_config: json!({"tenant_code": "tenant"}),
            egress_hosts: vec!["api.example.com".to_string()],
            egress_targets: vec![],
        };
        let config =
            JdIdentityConfig::from_json(&context.provider_config).expect("identity config");
        let cache_key = JdAgentIdentityProvider::cache_key(
            &provider.platform_id,
            &format!("{}:{}", context.project_id, config.tenant_code),
            &context.agent_id.to_string(),
            &provider.auth_type,
            &context.user_id.to_string(),
            &context.egress_hosts.join(","),
        );
        let user_token_cache_key = JdAgentIdentityProvider::user_token_cache_key(
            &provider.platform_id,
            &context.agent_id.to_string(),
            &provider.auth_type,
            &provider.identity_type,
            &context.user_name,
        );
        let mut redis = redis_client
            .get_multiplexed_async_connection()
            .await
            .expect("connect Redis");
        redis
            .set_ex::<_, _, ()>(&cache_key, "cached-bot", 60)
            .await
            .expect("seed BotToken cache");
        redis
            .set_ex::<_, _, ()>(&user_token_cache_key, "cached-user-token", 60)
            .await
            .expect("seed UserToken cache");

        let injection = provider.resolve(&context).await.expect("resolve identity");
        assert_eq!(injection.targets.len(), 1);
        assert!(injection.targets[0]
            .inject_headers
            .iter()
            .any(|(name, value)| name == "Cookie" && value == "sso.jd.com=cached-user-token"));
        server.await.expect("identity test server");
        let paths = observed_paths.lock().await.clone();
        assert_eq!(
            paths,
            vec![
                "/ai/identity/sec/api/exchangeBotToken".to_string(),
                "/ai/identity/sec/api/exchangeAgentToken".to_string(),
            ]
        );
        let _: () = redis.del(cache_key).await.expect("clean BotToken cache");
        let _: () = redis
            .del(user_token_cache_key)
            .await
            .expect("clean UserToken cache");
    }
}
