use super::*;
use crate::config::JoySafeterConfig;
use crate::db::models::JoySafeterAgent;
use crate::db::task_identity_store::PostgresTaskIdentityStore;
use crate::ids::{CredentialGroupId, FileId, OrganizationId, SessionResourceId};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::runtime_projection::{
    build_external_egress, build_git_egress, extract_llm_egress, EnvironmentRow,
};
use crate::kernel::mcp_runtime_plan::{resolve_mcp_runtime_plan_with_access, EffectiveNetworkMode};
use crate::kernel::network_policy::envoy_model::SandboxCredentials;
use crate::kernel::network_policy::{DesiredNetworkPolicy, NetworkPolicyGeneration};
use crate::kernel::repository_access::material::RepositoryAccessMaterialAdapter;
use crate::kernel::task_identity::material::TaskIdentityMaterialAdapter;
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};
use async_trait::async_trait;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::collections::HashMap;
use std::env;
use std::net::IpAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use uuid::Uuid;

use super::identity_policy::identity_lease_matches;
use super::model::{ExpectedFingerprint, ResolveContext};
use super::networking::PreparedSandboxNetworking;
use super::runtime_plan::{
    apply_claude_code_sandbox_privacy, apply_sandbox_timezone, provisioning_config,
};
use crate::kernel::task_identity::{TaskIdentityContextError, TaskIdentityService};

const ENCRYPTED_HELLO_WORLD: &str = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
const TEST_IDENTITY_KEY: [u8; 32] = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    26, 27, 28, 29, 30, 31,
];

impl SandboxResolver {
    pub fn new(pool: PgPool, provider: Arc<dyn SandboxProvider>, config: JoySafeterConfig) -> Self {
        let networking = SandboxNetworkingService::test_fixture(pool.clone());
        let lifecycle =
            SandboxLifecycleService::new(pool.clone(), provider.clone(), networking.clone());
        let pool_service = SandboxPoolService::new(
            pool.clone(),
            provider.clone(),
            config.clone(),
            networking.clone(),
            lifecycle.clone(),
        );
        let provisioning = SandboxProvisioningService::new(
            pool.clone(),
            provider,
            config.clone(),
            networking.clone(),
            lifecycle.clone(),
        );
        let identity = TaskIdentityService::new(
            Arc::new(PostgresTaskIdentityStore::new(pool.clone())),
            Arc::new(TaskIdentityMaterialAdapter::from_env()),
            config.agent_identity_allowed_hosts.clone(),
        );
        let context_builder = ResolveContextBuilder::new(
            pool.clone(),
            config,
            networking.clone(),
            identity,
            CredentialMaterialAccessService::new(pool.clone()),
            Arc::new(RepositoryAccessMaterialAdapter::from_env()),
        );
        Self::new_with_services(
            pool,
            networking,
            lifecycle,
            pool_service,
            provisioning,
            context_builder,
        )
    }
}

struct StaticMcpAddressResolver;

#[async_trait]
impl crate::kernel::mcp_network_policy::McpAddressResolver for StaticMcpAddressResolver {
    async fn resolve(
        &self,
        _host: &str,
        _port: u16,
    ) -> Result<Vec<IpAddr>, crate::kernel::mcp_network_policy::McpNetworkPolicyError> {
        Ok(vec!["93.184.216.34".parse().expect("valid public IP")])
    }
}

fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn allow(hosts: &[&str]) -> Vec<String> {
    hosts.iter().map(|host| host.to_string()).collect()
}

fn ready_standalone_authority() -> crate::xds::authority::XdsAuthority {
    let authority = crate::xds::authority::XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    authority
}

fn identity_target(
    host: &str,
) -> crate::kernel::agent_identity_provider::IdentityEgressRequestTarget {
    crate::kernel::agent_identity_provider::IdentityEgressRequestTarget {
        route_id: format!("external-identity:{host}:0"),
        endpoint: format!("https://{host}/"),
        host: host.to_string(),
        port: 443,
        tls: true,
    }
}

#[tokio::test]
async fn external_egress_rejects_malformed_credential_ref() {
    let pool = PgPoolOptions::new()
        .connect_lazy("postgres://localhost/unused")
        .expect("create lazy pool");
    let environment = EnvironmentRow {
        config: serde_json::json!({
            "egress_services": [
                {
                    "name": "secocean",
                    "base_url": "https://secocean.example.com",
                    "credential_ref": "019f891f-6539-71d3-b791-c25814af3efd",
                    "inject": {
                        "type": "cookie",
                        "credential_field": "COOKIE_HEADER"
                    }
                }
            ]
        }),
        image_tag: None,
    };

    let access = CredentialMaterialAccessService::new(pool.clone());
    let context = CredentialAccessContext::runtime(None, None, None);
    let error = build_external_egress(&access, &context, Some(&environment), None)
        .await
        .expect_err("bare UUID in external egress must fail");

    assert_eq!(
        error.downcast_ref(),
        Some(&CredentialRuntimeError::CorruptRecord)
    );
}

#[tokio::test]
async fn external_egress_rejects_non_string_credential_ref() {
    let pool = PgPoolOptions::new()
        .connect_lazy("postgres://localhost/unused")
        .expect("create lazy pool");
    let environment = EnvironmentRow {
        config: serde_json::json!({
            "egress_services": [
                {
                    "name": "secocean",
                    "base_url": "https://secocean.example.com",
                    "credential_ref": 7,
                    "inject": {
                        "type": "cookie",
                        "credential_field": "COOKIE_HEADER"
                    }
                }
            ]
        }),
        image_tag: None,
    };

    let access = CredentialMaterialAccessService::new(pool.clone());
    let context = CredentialAccessContext::runtime(None, None, None);
    let error = build_external_egress(&access, &context, Some(&environment), None)
        .await
        .expect_err("non-string external egress credential id must fail");

    assert_eq!(
        error.downcast_ref(),
        Some(&CredentialRuntimeError::CorruptRecord)
    );
}

#[tokio::test]
async fn external_egress_builds_route_scoped_agent_identity_targets() {
    let pool = PgPoolOptions::new()
        .connect_lazy("postgres://localhost/unused")
        .expect("create lazy pool");
    let environment = EnvironmentRow {
        config: serde_json::json!({
            "egress_services": [{
                "name": "crm-internal",
                "base_url": "http://crm.internal:8080/api/",
                "auth_source": "agent_identity",
                "allowed_paths": ["/customer/"]
            }]
        }),
        image_tag: None,
    };
    let access = CredentialMaterialAccessService::new(pool);
    let context = CredentialAccessContext::runtime(None, None, None);

    let (routes, targets) = build_external_egress(&access, &context, Some(&environment), None)
        .await
        .expect("build identity egress route");

    assert_eq!(routes.len(), 1);
    assert_eq!(routes[0].id, "external-identity:crm-internal:0");
    assert!(routes[0].inject_headers.is_empty());
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].route_id, routes[0].id);
    assert_eq!(targets[0].endpoint, "http://crm.internal:8080/api/");
    assert_eq!(targets[0].host, "crm.internal");
    assert_eq!(targets[0].port, 8080);
    assert!(!targets[0].tls);
}

#[test]
fn identity_host_allowlist_is_exact_or_dot_boundary_wildcard() {
    let allowed = vec!["api.example.com".to_string(), "*.trusted.test".to_string()];

    assert!(TaskIdentityService::host_allowed(
        "api.example.com",
        &allowed
    ));
    assert!(TaskIdentityService::host_allowed(
        "mcp.trusted.test",
        &allowed
    ));
    assert!(!TaskIdentityService::host_allowed(
        "evil-api.example.com",
        &allowed
    ));
    assert!(!TaskIdentityService::host_allowed("trusted.test", &allowed));
    assert!(!TaskIdentityService::host_allowed(
        "trusted.test.evil.invalid",
        &allowed
    ));
}

#[test]
fn identity_lease_metadata_uses_canonical_task_id_without_credentials() {
    let task_id = TaskId::new();
    let lease = identity_lease_metadata(task_id, Some(120));

    assert_eq!(lease["task_id"], task_id.to_string());
    assert_eq!(lease["refresh_after_seconds"], 120);
    assert!(lease.get("credential").is_none());
    assert!(lease.get("headers").is_none());
}

#[test]
fn identity_lease_matches_only_the_owning_task() {
    let owner = TaskId::new();
    let other = TaskId::new();
    let config = serde_json::json!({
        "agent_identity_lease": identity_lease_metadata(owner, Some(60))
    });

    assert!(identity_lease_matches(Some(&config), owner));
    assert!(!identity_lease_matches(Some(&config), other));
    assert!(!identity_lease_matches(None, owner));
}

#[test]
fn static_recovery_removes_agent_identity_routes() {
    let mut routes = vec![
        EgressCredentialRoute {
            id: "external-identity:crm:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/api/".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "secret".to_string())],
            remove_headers: vec!["authorization".to_string()],
        },
        EgressCredentialRoute {
            id: "external:static:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "static.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "static.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "static".to_string())],
            remove_headers: vec!["authorization".to_string()],
        },
    ];

    remove_agent_identity_routes(&mut routes);

    assert_eq!(routes.len(), 1);
    assert_eq!(routes[0].id, "external:static:0");
}

#[test]
fn identity_headers_merge_only_into_matching_mcp_placeholder_route() {
    let mut routes = vec![EgressCredentialRoute {
        id: "mcp:trusted".to_string(),
        kind: EgressKind::Mcp,
        exposure: EgressExposure::Placeholder,
        match_host: MCP_EGRESS_HOST.to_string(),
        path_mapping: EgressPathMapping::RewriteExact {
            exposed_path: "/mcp/trusted/".to_string(),
            upstream_path: "/api".to_string(),
        },
        retry_mode: EgressRetryMode::Disabled,
        upstream_host: "api.example.com".to_string(),
        upstream_port: 443,
        upstream_tls: true,
        cluster_name: String::new(),
        vetted_addresses: vec![],
        inject_headers: vec![("authorization".to_string(), "Bearer mcp".to_string())],
        remove_headers: vec!["authorization".to_string()],
    }];

    crate::kernel::network_policy::identity::merge_identity_injection(
        &mut routes,
        crate::kernel::agent_identity_provider::AgentIdentityInjection {
            targets: vec![
                crate::kernel::agent_identity_provider::IdentityEgressTarget {
                    route_id: "mcp:trusted".to_string(),
                    host: "api.example.com".to_string(),
                    port: 443,
                    tls: true,
                    inject_headers: vec![(
                        "X-Security-AgentToken".to_string(),
                        "agent-token".to_string(),
                    )],
                    remove_headers: vec!["x-security-agenttoken".to_string()],
                },
            ],
            valid_for_seconds: Some(300),
        },
    )
    .expect("matching route should merge");

    assert_eq!(routes[0].inject_headers.len(), 2);
    assert!(routes[0]
        .inject_headers
        .iter()
        .any(|(name, value)| name == "authorization" && value == "Bearer mcp"));
    assert!(routes[0]
        .inject_headers
        .iter()
        .any(|(name, value)| { name == "X-Security-AgentToken" && value == "agent-token" }));
    assert!(routes[0]
        .remove_headers
        .iter()
        .any(|name| name == "x-security-agenttoken"));
}

/// Run `extract_llm_egress` and return the single LLM route it emits, if any.
/// The builder now returns a `Vec<EgressCredentialRoute>`; LLM egress is
/// always zero or one route.
fn extract_llm_route(
    env: &mut HashMap<String, String>,
    provider_id: &str,
    protocol_id: &str,
    allowed_hosts: &[String],
) -> Option<EgressCredentialRoute> {
    let binding = crate::kernel::llm_catalog::validate_runtime_secret(
        "native",
        "model",
        Some(provider_id),
        Some(protocol_id),
    )
    .expect("test binding must be Catalog-valid");
    extract_llm_egress(env, Some(&binding), allowed_hosts)
        .into_iter()
        .next()
}

fn expected_fingerprint(egress_policy_hash: &str) -> ExpectedFingerprint {
    ExpectedFingerprint {
        image: "joysafeter-agent:latest".to_string(),
        engine_kind: "claude".to_string(),
        networking: Some(serde_json::json!({
            "type": "limited",
            "allowed_hosts": ["api.example.com"]
        })),
        env: HashMap::from([("SAFE_ENV".to_string(), "value".to_string())]),
        mounts: vec![],
        egress_policy_hash: egress_policy_hash.to_string(),
    }
}

fn empty_network_policy_revision() -> String {
    DesiredNetworkPolicy::from_inputs(None, &SandboxCredentials::default())
        .expect("empty sandbox policy must be valid")
        .revision()
        .to_string()
}

#[test]
fn sandbox_timezone_uses_platform_default_without_overriding_environment() {
    let mut default_env = HashMap::new();
    apply_sandbox_timezone(&mut default_env, "Asia/Shanghai");
    assert_eq!(
        default_env.get("TZ").map(String::as_str),
        Some("Asia/Shanghai")
    );

    let mut explicit_env = HashMap::from([("TZ".to_string(), "America/New_York".to_string())]);
    apply_sandbox_timezone(&mut explicit_env, "Asia/Shanghai");
    assert_eq!(
        explicit_env.get("TZ").map(String::as_str),
        Some("America/New_York")
    );
}

#[test]
fn claude_code_sandbox_privacy_defaults_without_overriding_environment() {
    let mut default_env = HashMap::new();
    apply_claude_code_sandbox_privacy(&mut default_env);
    assert_eq!(
        default_env.get("DISABLE_TELEMETRY").map(String::as_str),
        Some("1")
    );
    assert_eq!(
        default_env
            .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
            .map(String::as_str),
        Some("1")
    );

    let mut explicit_env = HashMap::from([
        ("DISABLE_TELEMETRY".to_string(), "0".to_string()),
        (
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC".to_string(),
            "0".to_string(),
        ),
    ]);
    apply_claude_code_sandbox_privacy(&mut explicit_env);
    assert_eq!(
        explicit_env.get("DISABLE_TELEMETRY").map(String::as_str),
        Some("0")
    );
    assert_eq!(
        explicit_env
            .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
            .map(String::as_str),
        Some("0")
    );
}

#[test]
fn runtime_fingerprint_ignores_egress_policy_hash_only() {
    let expected = expected_fingerprint("new-policy");
    let mut stored = expected_fingerprint("old-policy").to_json();

    assert!(runtime_fingerprint_matches(
        Some(&serde_json::json!({"fingerprint": stored.clone()})),
        Some("different-column-image"),
        &expected,
    ));

    stored["image"] = serde_json::Value::String("other-image".to_string());
    assert!(!runtime_fingerprint_matches(
        Some(&serde_json::json!({"fingerprint": stored})),
        Some("joysafeter-agent:latest"),
        &expected,
    ));
}

#[test]
fn egress_policy_hash_tracks_header_secret_without_leaking_it() {
    let mut credentials = SandboxCredentials {
        routes: vec![EgressCredentialRoute {
            id: "external_svc".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Placeholder,
            match_host: "external-egress.internal".to_string(),
            path_mapping: EgressPathMapping::RewritePrefix {
                exposed_prefix: "/svc/".to_string(),
                upstream_prefix: "/".to_string(),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "external_svc".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "Bearer first".to_string())],
            remove_headers: vec![],
        }],
        proxy_auth_token: None,
    };
    let networking = serde_json::json!({"type": "limited"});

    let first = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials)
        .unwrap()
        .revision();
    credentials.routes[0].inject_headers[0].1 = "Bearer second".to_string();
    let second = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials)
        .unwrap()
        .revision();

    assert_ne!(first, second);
    assert!(!first.to_string().contains("first"));
    assert!(!second.to_string().contains("second"));
}

fn database_url() -> Option<String> {
    env::var("JOYSAFETER_TEST_DATABASE_URL")
        .ok()
        .or_else(|| env::var("DATABASE_URL").ok())
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
}

async fn test_pool() -> Option<PgPool> {
    let Some(url) = database_url() else {
        eprintln!("skipping real Postgres sandbox resolver test: DATABASE_URL is not set");
        return None;
    };
    Some(
        PgPoolOptions::new()
            .max_connections(3)
            .connect(&url)
            .await
            .expect("connect to migrated Postgres test database"),
    )
}

#[tokio::test]
async fn expired_repository_tokens_are_not_exposed_to_git_egress() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let repo_id = SessionResourceId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();

    let result: anyhow::Result<()> = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(format!("expired-repo-token-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await?;

        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await?;

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_repos (
                    id, session_id, url, branch, mount_path, mount_name,
                    encrypted_token, token_expires_at, token_rotated_at
                )
                VALUES (
                    $1, $2, 'https://github.com/example/private.git', 'main',
                    '/workspace/private', 'private', $3, NOW() - INTERVAL '1 second',
                    NOW() - INTERVAL '1 hour'
                )
                "#,
        )
        .bind(repo_id)
        .bind(session_id)
        .bind(ENCRYPTED_HELLO_WORLD)
        .execute(&pool)
        .await?;

        let routes = build_git_egress(
            &pool,
            &RepositoryAccessMaterialAdapter::from_env(),
            Some(session_id),
        )
        .await?;
        anyhow::ensure!(
            routes.is_empty(),
            "expired repository token reached Git egress"
        );
        Ok(())
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_repos WHERE id = $1")
        .bind(repo_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;

    result.expect("expired repository token must be unavailable to Git egress");
}

async fn assert_existing_runtime_requires_restart(
    runtime_config_status: &str,
    applied_generation: i64,
) {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-runtime-freshness-{unique}:latest");
    let external_id = format!("resolver-runtime-freshness-{sandbox_id}");

    let result = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver freshness system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-runtime-freshness-agent-{unique}"))
        .bind(serde_json::json!({"id": "resolver-runtime-freshness-model"}))
        .execute(&pool)
        .await
        .expect("insert runtime freshness agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, runtime_config_generation
                )
                VALUES ($1, $2, 'idle', 2)
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert runtime freshness session");

        let expected = ExpectedFingerprint {
            image: image.clone(),
            engine_kind: "claude".to_string(),
            networking: None,
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: empty_network_policy_revision(),
        };
        let sandbox_config = provisioning_config(
            "runtime_freshness",
            100,
            "Runtime freshness fixture",
            true,
            &expected,
            Some("resolver-runtime-freshness-token"),
        );
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "recording",
            &image,
            Some(session_id),
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("create runtime freshness sandbox");
        sqlx::query(
            r#"
                UPDATE joysafeter_sandboxes
                SET status = 'running',
                    runtime_config_status = $2,
                    runtime_config_applied_generation = $3
                WHERE id = $1
                "#,
        )
        .bind(sandbox_id)
        .bind(runtime_config_status)
        .bind(applied_generation)
        .execute(&pool)
        .await
        .expect("set runtime freshness state");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.sandbox_image = image.clone();
        config.image_claude = image;

        let resolver = recording_resolver(pool.clone(), provider.clone(), config);
        let error = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("stale existing runtime must require an explicit restart");
        assert!(matches!(
            error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id: id })
                if *id == sandbox_id
        ));
        assert!(provider.destroyed.lock().await.is_empty());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;

    result
}

#[tokio::test]
async fn sandbox_resolver_rejects_raw_stale_existing_runtime_without_destroy() {
    assert_existing_runtime_requires_restart("restart_required", 2).await;
}

#[tokio::test]
async fn sandbox_resolver_rejects_generation_mismatched_existing_runtime_without_destroy() {
    assert_existing_runtime_requires_restart("ready", 1).await;
}

async fn assert_new_sandbox_generation_rejection_cleanup(destroy_fails: bool) {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-new-generation-{unique}:latest");

    let result = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver generation system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-new-generation-agent-{unique}"))
        .bind(serde_json::json!({"id": "resolver-new-generation-model"}))
        .execute(&pool)
        .await
        .expect("insert new generation agent");
        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, runtime_config_generation
                )
                VALUES ($1, $2, 'idle', 1)
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert new generation session");

        let provider = Arc::new(RecordingProvider {
            create_advances_generation: Mutex::new(Some((pool.clone(), session_id))),
            destroy_error: Mutex::new(destroy_fails.then(|| "provider destroy failed".to_string())),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.sandbox_image = image.clone();
        config.image_claude = image;

        let resolver = recording_resolver(pool.clone(), provider.clone(), config);
        let error = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("generation change after provider create must reject activation");
        if destroy_fails {
            assert!(matches!(
                error.downcast_ref::<RuntimeFreshnessError>(),
                Some(RuntimeFreshnessError::CleanupFailed(_))
            ));
        } else {
            assert!(matches!(
                error.downcast_ref::<RuntimeFreshnessError>(),
                Some(RuntimeFreshnessError::GenerationChanged {
                    expected: 1,
                    actual: 2
                })
            ));
        }
        assert_eq!(provider.created.lock().await.len(), 1);
        assert_eq!(provider.destroyed.lock().await.len(), 1);
        assert_eq!(provider.networking_teardowns.lock().await.len(), 1);
        let rejected_sandbox: Option<(String, String, Option<String>)> = sqlx::query_as(
            "SELECT status, runner_auth_state, external_id FROM joysafeter_sandboxes WHERE chat_session_id = $1",
        )
        .bind(session_id)
        .fetch_optional(&pool)
        .await
        .expect("load rejected sandbox row");
        if destroy_fails {
            let rejected_sandbox = rejected_sandbox
                .expect("failed provider cleanup must retain a fenced retryable row");
            assert_eq!(rejected_sandbox.0, "stopping");
            assert_eq!(rejected_sandbox.1, "revoked");
            assert!(rejected_sandbox.2.is_some_and(|value| !value.is_empty()));
        } else {
            assert!(rejected_sandbox.is_none());
        }
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;

    result
}

#[tokio::test]
async fn sandbox_resolver_destroys_new_provider_after_generation_rejection() {
    assert_new_sandbox_generation_rejection_cleanup(false).await;
}

#[tokio::test]
async fn sandbox_resolver_stops_after_new_provider_cleanup_failure() {
    assert_new_sandbox_generation_rejection_cleanup(true).await;
}

#[derive(Default)]
struct RecordingProvider {
    created: Mutex<Vec<SandboxCreateConfig>>,
    create_advances_generation: Mutex<Option<(PgPool, SessionId)>>,
    networking: Mutex<Vec<(SandboxId, Option<serde_json::Value>)>>,
    networking_credentials: Mutex<Vec<SandboxCredentials>>,
    networking_error: Mutex<Option<String>>,
    networking_teardowns: Mutex<Vec<SandboxId>>,
    start_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
    start_observed_statuses: Mutex<Vec<String>>,
    start_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
    start_error: Mutex<Option<String>>,
    status_marks_idle: Mutex<Option<(PgPool, SandboxId)>>,
    status_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
    status_marks_restart_required: Mutex<Option<(PgPool, SandboxId)>>,
    status_error: Mutex<Option<String>>,
    status_result: Mutex<Option<SandboxStatus>>,
    destroy_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
    destroy_observed_statuses: Mutex<Vec<String>>,
    destroyed: Mutex<Vec<String>>,
    destroy_error: Mutex<Option<String>>,
}

#[async_trait]
impl SandboxProvider for RecordingProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        self.created.lock().await.push(config.clone());
        if let Some((pool, session_id)) = self.create_advances_generation.lock().await.clone() {
            sqlx::query(
                r#"
                    UPDATE joysafeter_sessions
                    SET runtime_config_generation = runtime_config_generation + 1
                    WHERE id = $1
                    "#,
            )
            .bind(session_id)
            .execute(&pool)
            .await?;
        }
        Ok(format!("external-{}", config.sandbox_id))
    }

    async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
        if let Some((pool, sandbox_id)) = self.start_status_probe.lock().await.clone() {
            if let Some(status) = sqlx::query_scalar::<_, String>(
                "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_optional(&pool)
            .await?
            {
                self.start_observed_statuses.lock().await.push(status);
            }
        }
        if let Some((pool, sandbox_id)) = self.start_marks_error.lock().await.clone() {
            queries::mark_sandbox_error(&pool, sandbox_id, Some("concurrent restart failure"))
                .await?;
        }
        if let Some(message) = self.start_error.lock().await.clone() {
            anyhow::bail!(message);
        }
        Ok(())
    }

    async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
        Ok(())
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        if let Some((pool, sandbox_id)) = self.destroy_status_probe.lock().await.clone() {
            if let Some(status) = sqlx::query_scalar::<_, String>(
                "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_optional(&pool)
            .await?
            {
                self.destroy_observed_statuses.lock().await.push(status);
            }
        }
        self.destroyed.lock().await.push(external_id.to_string());
        if let Some(message) = self.destroy_error.lock().await.clone() {
            anyhow::bail!(message);
        }
        Ok(())
    }

    async fn status(&self, _external_id: &str) -> anyhow::Result<SandboxStatus> {
        if let Some((pool, sandbox_id)) = self.status_marks_idle.lock().await.clone() {
            queries::transition_sandbox_cas(&pool, sandbox_id, "provisioning", "idle").await?;
        }
        if let Some((pool, sandbox_id)) = self.status_marks_error.lock().await.clone() {
            queries::mark_sandbox_error(&pool, sandbox_id, Some("concurrent pool claim error"))
                .await?;
        }
        if let Some((pool, sandbox_id)) = self.status_marks_restart_required.lock().await.clone() {
            sqlx::query(
                r#"
                    UPDATE joysafeter_sandboxes
                    SET runtime_config_status = 'restart_required',
                        runtime_config_last_reason = 'newer_provider_marker',
                        runtime_config_required_at = '2026-08-21T14:15:16.777777Z'::timestamptz
                    WHERE id = $1
                    "#,
            )
            .bind(sandbox_id)
            .execute(&pool)
            .await?;
        }
        if let Some(message) = self.status_error.lock().await.clone() {
            anyhow::bail!(message);
        }
        Ok(self
            .status_result
            .lock()
            .await
            .clone()
            .unwrap_or(SandboxStatus::Running))
    }

    async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
        Ok(String::new())
    }

    fn provider_name(&self) -> &'static str {
        "recording"
    }

    fn capabilities(&self) -> crate::sandbox::provider::ProviderCapabilities {
        crate::sandbox::provider::ProviderCapabilities {
            has_host_mount: false,
            has_egress_management: true,
            network_isolation: crate::sandbox::provider::NetworkIsolation::Envoy,
            stop_preserves_state: false,
        }
    }
}

#[async_trait]
impl NetworkPolicyRuntime for RecordingProvider {
    async fn initialize(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn prune(
        &self,
        _live_sandbox_ids: &std::collections::HashSet<SandboxId>,
    ) -> anyhow::Result<usize> {
        Ok(0)
    }

    async fn recover(
        &self,
        _authority_epoch: u64,
        entries: Vec<crate::kernel::network_policy::ports::NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<crate::kernel::network_policy::ports::NetworkPolicyRecoveryReport> {
        Ok(
            crate::kernel::network_policy::ports::NetworkPolicyRecoveryReport {
                ready: entries
                    .into_iter()
                    .map(|entry| (entry.sandbox_id, entry.generation))
                    .collect(),
                ..crate::kernel::network_policy::ports::NetworkPolicyRecoveryReport::default()
            },
        )
    }

    async fn apply(
        &self,
        request: crate::kernel::network_policy::ports::NetworkPolicyApplyRequest,
        policy: crate::kernel::network_policy::envoy_model::SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.networking.lock().await.push((
            request.sandbox_id,
            Some(serde_json::json!({
                "type": "limited",
                "allowed_hosts": policy.allowlist_hosts,
            })),
        ));
        self.networking_credentials
            .lock()
            .await
            .push(SandboxCredentials {
                routes: policy.credential_routes,
                proxy_auth_token: policy.proxy_auth_token,
            });
        if let Some(message) = self.networking_error.lock().await.clone() {
            anyhow::bail!(message);
        }
        Ok(())
    }

    async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.networking_teardowns.lock().await.push(sandbox_id);
        Ok(())
    }
}

struct PostgresTestNetworkPolicyMaterialResolver {
    pool: PgPool,
}

#[async_trait]
impl NetworkPolicyMaterialResolver for PostgresTestNetworkPolicyMaterialResolver {
    async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        let credential_access = CredentialMaterialAccessService::new(self.pool.clone());
        let repository_material = RepositoryAccessMaterialAdapter::from_env();
        let credentials =
            crate::kernel::credentials::runtime_projection::rebuild_sandbox_credentials(
                &self.pool,
                &credential_access,
                &repository_material,
                &sandbox,
                &[],
            )
            .await?;
        DesiredNetworkPolicy::from_inputs(networking, &credentials)
    }
}

fn recording_resolver(
    pool: PgPool,
    provider: Arc<RecordingProvider>,
    config: JoySafeterConfig,
) -> SandboxResolver {
    SandboxResolver::new(pool.clone(), provider.clone(), config)
        .with_network_policy_runtime(provider)
        .with_network_policy_material_resolver(Arc::new(
            PostgresTestNetworkPolicyMaterialResolver { pool },
        ))
        .with_network_policy_control(ready_standalone_authority(), None)
}

#[tokio::test]
async fn local_authority_applies_ephemeral_identity_credentials_without_rebuild() {
    let provider = RecordingProvider::default();
    let authority = crate::xds::authority::XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    let guard = authority
        .mutation_guard()
        .expect("standalone authority guard");
    let sandbox_id = SandboxId::new();
    let credentials = SandboxCredentials {
        routes: vec![EgressCredentialRoute {
            id: "external-identity:crm:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/api/".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![(
                "X-Security-AgentToken".to_string(),
                "ephemeral-token".to_string(),
            )],
            remove_headers: vec!["x-security-agenttoken".to_string()],
        }],
        proxy_auth_token: Some("runner-token".to_string()),
    };
    let networking = serde_json::json!({
        "type": "limited",
        "allowed_hosts": []
    });
    let desired =
        DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials).expect("desired policy");
    let generation = NetworkPolicyGeneration {
        policy_hash: desired.revision().to_string(),
        policy_version: 1,
    };

    crate::kernel::network_policy::application::apply_ephemeral(
        &provider,
        sandbox_id,
        &generation,
        desired.render_for(sandbox_id),
        &guard,
    )
    .await
    .expect("ephemeral credentials should reach local authority");

    let applied = provider.networking_credentials.lock().await;
    assert_eq!(applied.len(), 1);
    assert_eq!(
        applied[0].routes[0].inject_headers,
        vec![(
            "X-Security-AgentToken".to_string(),
            "ephemeral-token".to_string()
        )]
    );
}

#[tokio::test]
async fn task_identity_cleanup_replaces_dynamic_policy_and_clears_lease() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::new();
    let task_id = TaskId::new();
    let networking = serde_json::json!({"type": "limited", "allowed_hosts": []});
    let dynamic_credentials = SandboxCredentials {
        routes: vec![EgressCredentialRoute {
            id: "external-identity:crm:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/api/".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![(
                "X-Security-AgentToken".to_string(),
                "ephemeral-token".to_string(),
            )],
            remove_headers: vec!["x-security-agenttoken".to_string()],
        }],
        proxy_auth_token: Some("runner-token".to_string()),
    };
    let dynamic_hash = DesiredNetworkPolicy::from_inputs(Some(&networking), &dynamic_credentials)
        .expect("dynamic policy")
        .revision()
        .to_string();
    let expected = ExpectedFingerprint {
        image: "identity-cleanup:latest".to_string(),
        engine_kind: "claude".to_string(),
        networking: Some(networking),
        env: HashMap::new(),
        mounts: vec![],
        egress_policy_hash: dynamic_hash.clone(),
    };
    let mut config =
        provisioning_config("ready", 100, "Ready", true, &expected, Some("runner-token"));
    config["agent_identity_lease"] = identity_lease_metadata(task_id, Some(120));
    queries::create_sandbox(
        &pool,
        sandbox_id,
        "external-identity-cleanup",
        "recording",
        "identity-cleanup:latest",
        None,
        None,
        None,
        Some(&config),
    )
    .await
    .expect("create identity cleanup sandbox");
    let generation = queries::prepare_generation(&pool, sandbox_id, &dynamic_hash)
        .await
        .expect("prepare dynamic generation")
        .into_generation();
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("mark dynamic policy ready"),
        queries::NetworkPolicyAckOutcome::Applied
    );
    let provider = Arc::new(RecordingProvider::default());
    let mut resolver_config = JoySafeterConfig::from_env();
    resolver_config.sandbox_provider = "recording".to_string();
    let resolver = recording_resolver(pool.clone(), provider.clone(), resolver_config);
    let identity_policy = resolver.identity_policy_service();

    let other_task_id = TaskId::new();
    assert!(!identity_policy
        .clear_policy(sandbox_id, other_task_id)
        .await
        .expect("foreign task must not clear identity policy"));
    assert!(provider.networking_credentials.lock().await.is_empty());
    let sandbox_before_owner_cleanup = queries::get_sandbox(&pool, sandbox_id)
        .await
        .expect("load sandbox before owner cleanup")
        .expect("sandbox exists before owner cleanup");
    assert!(identity_lease_matches(
        sandbox_before_owner_cleanup.config.as_ref(),
        task_id
    ));

    assert!(identity_policy
        .clear_policy(sandbox_id, task_id)
        .await
        .expect("clear identity policy"));

    let applied = provider.networking_credentials.lock().await;
    assert_eq!(applied.len(), 1);
    assert!(applied[0].routes.is_empty());
    assert_eq!(applied[0].proxy_auth_token.as_deref(), Some("runner-token"));
    let sandbox = queries::get_sandbox(&pool, sandbox_id)
        .await
        .expect("load sandbox")
        .expect("sandbox exists");
    assert_eq!(
        sandbox
            .config
            .as_ref()
            .and_then(|value| value.get("agent_identity_lease")),
        Some(&serde_json::Value::Null)
    );
    assert_eq!(sandbox.networking_status, "ready");
    assert_ne!(
        sandbox.networking_applied_hash.as_deref(),
        Some(dynamic_hash.as_str())
    );

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
}

struct AckingNetworkPolicyQueue {
    pool: PgPool,
    requests: Mutex<Vec<NetworkPolicyRequest>>,
}

#[async_trait]
impl NetworkPolicyRequestQueue for AckingNetworkPolicyQueue {
    async fn publish(&self, request: NetworkPolicyRequest) -> anyhow::Result<()> {
        if let Some(generation) = request.generation.as_ref() {
            assert!(matches!(
                queries::mark_generation_applied(&self.pool, request.sandbox_id, generation)
                    .await?,
                queries::NetworkPolicyAckOutcome::Applied
                    | queries::NetworkPolicyAckOutcome::AlreadyReady
            ));
        }
        self.requests.lock().await.push(request);
        Ok(())
    }
}

#[tokio::test]
async fn multi_replica_networking_requests_authority_without_local_provider_push() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let networking = serde_json::json!({
        "type": "limited",
        "allowed_hosts": ["api.example.com"]
    });
    let context = ResolveContext {
        session_id: None,
        project_id: None,
        runtime_config_generation: 0,
        network: Some("none".to_string()),
        expected: ExpectedFingerprint {
            image: "authority-test:latest".to_string(),
            engine_kind: "claude".to_string(),
            networking: Some(networking),
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: "authority-policy".to_string(),
        },
        memory_mounts: vec![],
        mounts: vec![],
        credentials: SandboxCredentials::default(),
        identity_refresh_after_seconds: None,
    };
    queries::create_sandbox(
        &pool,
        sandbox_id,
        "external-authority-test",
        "recording",
        "authority-test:latest",
        None,
        None,
        None,
        Some(&provisioning_config(
            "networking",
            80,
            "Awaiting authority",
            false,
            &context.expected,
            Some("runner-token"),
        )),
    )
    .await
    .expect("create authority test sandbox");
    let generation =
        queries::prepare_generation(&pool, sandbox_id, &context.expected.egress_policy_hash)
            .await
            .expect("prepare authority generation")
            .into_generation();
    let provider = Arc::new(RecordingProvider::default());
    let request_queue = Arc::new(AckingNetworkPolicyQueue {
        pool: pool.clone(),
        requests: Mutex::new(Vec::new()),
    });
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config)
        .with_network_policy_queue(request_queue.clone());

    resolver
        .networking
        .apply_prepared(
            sandbox_id,
            &generation,
            PreparedSandboxNetworking {
                credentials: &context.credentials,
                identity_lease: None,
                proxy_auth_token: Some("runner-token".to_string()),
            },
        )
        .await
        .expect("authority request should become ready");

    assert!(provider.networking.lock().await.is_empty());
    assert_eq!(
        request_queue.requests.lock().await.as_slice(),
        &[NetworkPolicyRequest::reconcile(sandbox_id, generation)]
    );

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn duplicate_authority_request_keeps_ready_generation_without_provider_push() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let networking = serde_json::json!({"type": "limited", "allowed_hosts": []});
    let expected = ExpectedFingerprint {
        image: "authority-duplicate:latest".to_string(),
        engine_kind: "claude".to_string(),
        networking: Some(networking),
        env: HashMap::new(),
        mounts: vec![],
        egress_policy_hash: "authority-duplicate-policy".to_string(),
    };
    queries::create_sandbox(
        &pool,
        sandbox_id,
        "external-authority-duplicate",
        "recording",
        "authority-duplicate:latest",
        None,
        None,
        None,
        Some(&provisioning_config(
            "networking",
            100,
            "Ready",
            true,
            &expected,
            Some("runner-token"),
        )),
    )
    .await
    .expect("create duplicate authority test sandbox");
    let generation = queries::prepare_generation(&pool, sandbox_id, &expected.egress_policy_hash)
        .await
        .expect("prepare duplicate generation")
        .into_generation();
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("mark duplicate generation ready"),
        queries::NetworkPolicyAckOutcome::Applied
    );
    let provider = RecordingProvider::default();
    let authority = crate::xds::authority::XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    let guard = authority.mutation_guard().expect("authority guard");

    let material_resolver = RejectingNetworkPolicyMaterialResolver;
    let outcome = crate::kernel::network_policy::application::apply_generation_as_authority(
        &pool,
        &provider,
        &material_resolver,
        sandbox_id,
        &generation,
        &guard,
    )
    .await
    .expect("duplicate request should be idempotent");

    assert_eq!(
        outcome,
        crate::kernel::network_policy::application::NetworkingReconcileOutcome::AlreadyReady {
            policy_hash: generation.policy_hash.clone()
        }
    );
    assert!(provider.networking.lock().await.is_empty());
    let state: String =
        sqlx::query_scalar("SELECT networking_status FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load duplicate request state");
    assert_eq!(state, "ready");

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
}

#[derive(Debug, Default)]
struct SlowIdentityProvider {
    calls: AtomicUsize,
    captured_material: Mutex<Vec<bool>>,
}

#[derive(Debug, Default)]
struct EmptyIdentityProvider {
    calls: AtomicUsize,
}

#[async_trait]
impl crate::kernel::agent_identity_provider::AgentIdentityProvider for EmptyIdentityProvider {
    fn name(&self) -> &str {
        "empty-test"
    }

    fn enabled(&self) -> bool {
        true
    }

    async fn resolve(
        &self,
        _context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
    ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(
            crate::kernel::agent_identity_provider::AgentIdentityInjection {
                targets: vec![],
                valid_for_seconds: None,
            },
        )
    }

    async fn cleanup(
        &self,
        _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
    ) {
    }
}

#[derive(Debug, Default)]
struct FailingIdentityProvider {
    calls: AtomicUsize,
}

#[async_trait]
impl crate::kernel::agent_identity_provider::AgentIdentityProvider for FailingIdentityProvider {
    fn name(&self) -> &str {
        "failing-test"
    }

    fn enabled(&self) -> bool {
        true
    }

    async fn resolve(
        &self,
        _context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
    ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        anyhow::bail!("deterministic identity provider failure")
    }

    async fn cleanup(
        &self,
        _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
    ) {
    }
}

#[async_trait]
impl crate::kernel::agent_identity_provider::AgentIdentityProvider for SlowIdentityProvider {
    fn name(&self) -> &str {
        "slow-test"
    }

    fn enabled(&self) -> bool {
        true
    }

    async fn resolve(
        &self,
        context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
    ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.captured_material
            .lock()
            .await
            .push(!context.identity_token.is_empty() || context.auth_code.is_some());
        tokio::time::sleep(Duration::from_millis(100)).await;
        Ok(
            crate::kernel::agent_identity_provider::AgentIdentityInjection {
                targets: vec![
                    crate::kernel::agent_identity_provider::IdentityEgressTarget {
                        route_id: context.egress_targets[0].route_id.clone(),
                        host: context.egress_targets[0].host.clone(),
                        port: 443,
                        tls: true,
                        inject_headers: vec![(
                            "X-Security-AgentToken".to_string(),
                            "agent-token".to_string(),
                        )],
                        remove_headers: vec!["x-security-agenttoken".to_string()],
                    },
                ],
                valid_for_seconds: Some(120),
            },
        )
    }

    async fn cleanup(
        &self,
        _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
    ) {
    }
}

#[tokio::test]
async fn task_identity_context_is_project_scoped_expiring_and_single_consume() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let empty_task_id = TaskId::from_uuid(Uuid::now_v7());
    let failing_task_id = TaskId::from_uuid(Uuid::now_v7());
    let expired_task_id = TaskId::from_uuid(Uuid::now_v7());
    let malformed_task_id = TaskId::from_uuid(Uuid::now_v7());
    let invalid_kind_task_id = TaskId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let org_id = OrganizationId::new();
    let user_id = UserId::new();

    async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
        )
        .bind(&org_id)
        .bind(format!("Identity Org {unique}"))
        .bind(format!("identity-org-{unique}"))
        .execute(&pool)
        .await
        .expect("insert organization");
        sqlx::query(
            r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
        )
        .bind(&project_id)
        .bind(&org_id)
        .bind(format!("Identity Project {unique}"))
        .bind(format!("identity-project-{unique}"))
        .execute(&pool)
        .await
        .expect("insert project");
        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("identity-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert agent");
        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert identity session");
        for id in [
            task_id,
            empty_task_id,
            failing_task_id,
            expired_task_id,
            malformed_task_id,
        ] {
            sqlx::query(
                r#"
                    INSERT INTO joysafeter_tasks (
                        id, project_id, user_id, agent_id, chat_session_id, status, prompt, output,
                        timeout_sec, retry_count, max_retries
                    )
                    VALUES ($1, $2, $3, $4, $5, 'pending', 'identity', '', 7200, 0, 2)
                    "#,
            )
            .bind(id)
            .bind(&project_id)
            .bind(user_id)
            .bind(agent_id)
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("insert task");
        }
        let ciphertext = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
        for id in [task_id, empty_task_id, failing_task_id] {
            sqlx::query(
                r#"
                    INSERT INTO joysafeter_task_identity_contexts (
                        task_id, project_id, user_id, user_name, credential_kind,
                        credential_fingerprint, encrypted_credential, captured_at, expires_at
                    )
                    VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                            NULL, $4, NOW(), NOW() + INTERVAL '5 minutes')
                    "#,
            )
            .bind(id)
            .bind(&project_id)
            .bind(user_id)
            .bind(ciphertext)
            .execute(&pool)
            .await
            .expect("insert active identity context");
        }
        sqlx::query(
            r#"
                INSERT INTO joysafeter_task_identity_contexts (
                    task_id, project_id, user_id, user_name, credential_kind,
                    credential_fingerprint, encrypted_credential, captured_at, expires_at
                )
                VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                        NULL, $4, NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '5 minutes')
                "#,
        )
        .bind(expired_task_id)
        .bind(&project_id)
        .bind(user_id)
        .bind(ciphertext)
        .execute(&pool)
        .await
        .expect("insert expired identity context");
        sqlx::query(
            r#"
                INSERT INTO joysafeter_task_identity_contexts (
                    task_id, project_id, user_id, user_name, credential_kind,
                    credential_fingerprint, encrypted_credential, captured_at, expires_at
                )
                VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                        NULL, $4, NOW(), NOW() + INTERVAL '5 minutes')
                "#,
        )
        .bind(malformed_task_id)
        .bind(&project_id)
        .bind(user_id)
        .bind("enc:v1:not-base64")
        .execute(&pool)
        .await
        .expect("insert malformed identity context");

        let key_error_provider = Arc::new(SlowIdentityProvider::default());
        let key_error_resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_provider(key_error_provider.clone())
        .with_identity_allowed_hosts(allow(&["api.example.com"]))
        .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::without_key());
        let key_error_agent = queries::get_agent(&pool, agent_id)
            .await
            .expect("load key-error agent")
            .expect("key-error agent exists");
        assert_eq!(
            key_error_resolver
                .identity_service()
                .resolve_injection(
                    Some(&key_error_agent),
                    task_id,
                    Some(session_id),
                    Some(project_id),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::Material(TaskIdentityMaterialError::KeyInvalid)
        );
        assert_eq!(key_error_provider.calls.load(Ordering::SeqCst), 0);

        let identity_provider = Arc::new(SlowIdentityProvider::default());
        let resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_provider(identity_provider.clone())
        .with_identity_allowed_hosts(allow(&["api.example.com"]))
        .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::with_key(
            TEST_IDENTITY_KEY,
        ));
        assert_eq!(
            resolver
                .identity_service()
                .resolve_injection(
                    Some(
                        &queries::get_agent(&pool, agent_id)
                            .await
                            .expect("load project-mismatch agent")
                            .expect("project-mismatch agent exists"),
                    ),
                    task_id,
                    Some(session_id),
                    Some(ProjectId::new()),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::ProjectMismatch
        );
        let expired_state: (String, bool) = sqlx::query_as(
            "SELECT state, encrypted_credential IS NOT NULL FROM joysafeter_task_identity_contexts WHERE task_id = $1",
        )
        .bind(expired_task_id)
        .fetch_one(&pool)
        .await
        .expect("load expired identity state");
        assert_eq!(expired_state, ("captured".to_string(), true));

        assert_eq!(
            resolver
                .identity_service()
                .resolve_injection(
                    Some(
                        &queries::get_agent(&pool, agent_id)
                            .await
                            .expect("load agent")
                            .expect("agent exists"),
                    ),
                    malformed_task_id,
                    Some(session_id),
                    Some(project_id),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::Material(TaskIdentityMaterialError::EnvelopeInvalid)
        );
        assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 0);

        let agent = queries::get_agent(&pool, agent_id)
            .await
            .expect("load agent")
            .expect("agent exists");
        let no_host_provider = Arc::new(SlowIdentityProvider::default());
        let no_host_resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_provider(no_host_provider.clone())
        .with_identity_allowed_hosts(allow(&["other.example.com"]))
        .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::with_key(
            TEST_IDENTITY_KEY,
        ));
        assert_eq!(
            no_host_resolver
                .identity_service()
                .resolve_injection(
                    Some(&agent),
                    empty_task_id,
                    Some(session_id),
                    Some(project_id),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::NoTrustedHosts
        );
        assert_eq!(no_host_provider.calls.load(Ordering::SeqCst), 0);

        let empty_provider = Arc::new(EmptyIdentityProvider::default());
        let empty_resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_provider(empty_provider.clone())
        .with_identity_allowed_hosts(allow(&["api.example.com"]))
        .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::with_key(
            TEST_IDENTITY_KEY,
        ));
        assert_eq!(
            empty_resolver
                .identity_service()
                .resolve_injection(
                    Some(&agent),
                    empty_task_id,
                    Some(session_id),
                    Some(project_id),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::EmptyInjection
        );
        assert_eq!(empty_provider.calls.load(Ordering::SeqCst), 1);

        let failing_provider = Arc::new(FailingIdentityProvider::default());
        let failing_resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_provider(failing_provider.clone())
        .with_identity_allowed_hosts(allow(&["api.example.com"]))
        .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::with_key(
            TEST_IDENTITY_KEY,
        ));
        assert_eq!(
            failing_resolver
                .identity_service()
                .resolve_injection(
                    Some(&agent),
                    failing_task_id,
                    Some(session_id),
                    Some(project_id),
                    &[identity_target("api.example.com")],
                )
                .await
                .unwrap_err(),
            TaskIdentityContextError::Provider
        );
        assert_eq!(failing_provider.calls.load(Ordering::SeqCst), 1);
        let failed_state: (String, bool, bool) = sqlx::query_as(
            r#"
                SELECT state, encrypted_credential IS NOT NULL, resolution_id IS NULL
                FROM joysafeter_task_identity_contexts WHERE task_id = $1
                "#,
        )
        .bind(failing_task_id)
        .fetch_one(&pool)
        .await
        .expect("load retryable identity state after provider failure");
        assert_eq!(failed_state, ("captured".to_string(), true, true));

        assert_eq!(
            resolver
                .identity_service()
                .decode_context(
                    Some((
                        user_id,
                        Some("user@example.com".to_string()),
                        "future_identity".to_string(),
                        ENCRYPTED_HELLO_WORLD.to_string(),
                    )),
                )
                .unwrap_err(),
            TaskIdentityContextError::KindInvalid
        );
        assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 0);

        let candidate_hosts = [identity_target("api.example.com")];
        let first = resolver.identity_service().resolve_injection(
            Some(&agent),
            task_id,
            Some(session_id),
            Some(project_id),
            &candidate_hosts,
        );
        let second = resolver.identity_service().resolve_injection(
            Some(&agent),
            task_id,
            Some(session_id),
            Some(project_id),
            &candidate_hosts,
        );
        let (first, second) = tokio::join!(first, second);
        let outcomes = [first, second];
        assert_eq!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, Ok(Some(_))))
                .count(),
            1
        );
        assert_eq!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, Err(TaskIdentityContextError::ClaimConflict)))
                .count(),
            1
        );
        assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            identity_provider.captured_material.lock().await.as_slice(),
            &[true]
        );
        let consumed: (String, bool, bool, bool) = sqlx::query_as(
            r#"
                SELECT state, consumed_at IS NOT NULL, encrypted_credential IS NULL,
                       resolution_id IS NULL
                FROM joysafeter_task_identity_contexts WHERE task_id = $1
                "#,
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load consumed identity state");
        assert_eq!(consumed, ("issued".to_string(), true, true, true));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE agent_id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(&project_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(&org_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn task_identity_sql_errors_are_not_optional_absence() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let resolver = SandboxResolver::new(
        pool.clone(),
        Arc::new(RecordingProvider::default()),
        JoySafeterConfig::from_env(),
    )
    .with_identity_allowed_hosts(allow(&["api.example.com"]));
    let project_id = ProjectId::new();
    let agent = JoySafeterAgent {
        id: AgentId::new(),
        project_id: Some(project_id),
        name: "closed-pool-identity-agent".to_string(),
        engine_kind: None,
        model: None,
        system_prompt: None,
        description: None,
        env: None,
        mcp_servers: None,
        skills: None,
        agents: None,
        commands: None,
        tools: None,
        metadata: None,
        multiagent: None,
        version: 1,
        environment_id: None,
        model_credential_id: None,
    };
    pool.close().await;

    assert_eq!(
        resolver
            .identity_service()
            .resolve_injection(
                Some(&agent),
                TaskId::from_uuid(Uuid::now_v7()),
                Some(SessionId::new()),
                Some(project_id),
                &[identity_target("api.example.com")],
            )
            .await
            .unwrap_err(),
        TaskIdentityContextError::Database
    );
}

#[test]
fn anthropic_auth_token_uses_bearer_and_leaves_no_key() {
    // Gateway / internal endpoint style: ANTHROPIC_AUTH_TOKEN → Bearer.
    let mut e = env(&[
        ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
        ("ANTHROPIC_API_KEY", "tok-123"),
        ("ANTHROPIC_BASE_URL", "https://llm.internal.example.com/v1"),
        ("DB_PASSWORD", "keepme"),
    ]);
    let egress = extract_llm_route(
        &mut e,
        "anthropic",
        "anthropic_messages",
        &allow(&["llm.internal.example.com"]),
    )
    .expect("egress");

    // Bearer header, real host preserved in egress, TLS upstream.
    assert_eq!(egress.upstream_host, "llm.internal.example.com");
    assert_eq!(egress.upstream_port, 443);
    assert_eq!(
        egress.path_mapping,
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any
        }
    );
    assert!(egress.upstream_tls);
    assert_eq!(
        egress.inject_headers,
        vec![("authorization".to_string(), "Bearer tok-123".to_string())]
    );

    // No real LLM key remains in the container env; Claude Code only gets a
    // non-secret placeholder so it does not fall back to /login.
    assert_eq!(
        e.get("ANTHROPIC_API_KEY").unwrap(),
        CLAUDE_CODE_PLACEHOLDER_API_KEY
    );
    assert!(!e.contains_key("ANTHROPIC_AUTH_TOKEN"));
    assert_eq!(
        e.get("ANTHROPIC_BASE_URL").unwrap(),
        "http://llm.internal.example.com:443/v1/"
    );
    // Non-LLM env var is untouched.
    assert_eq!(e.get("DB_PASSWORD").unwrap(), "keepme");
}

#[test]
fn llm_egress_uses_catalog_binding_instead_of_key_inference() {
    let binding = crate::kernel::llm_catalog::validate_runtime_secret(
        "native",
        "model",
        Some("deepseek"),
        Some("chat_completions"),
    )
    .expect("DeepSeek Chat Completions must be valid for Native");
    let mut e = env(&[("OPENAI_API_KEY", "sk-deepseek")]);

    let egress = extract_llm_egress(&mut e, Some(&binding), &allow(&["api.deepseek.com"]))
        .into_iter()
        .next()
        .expect("egress route");

    assert_eq!(egress.upstream_host, "api.deepseek.com");
    assert_eq!(
        egress.inject_headers,
        vec![(
            "authorization".to_string(),
            "Bearer sk-deepseek".to_string()
        )]
    );
}

#[test]
fn anthropic_api_key_uses_x_api_key() {
    // Official-style key (no AUTH_TOKEN) → x-api-key header.
    let mut e = env(&[
        ("ANTHROPIC_API_KEY", "sk-ant-xyz"),
        ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    ]);
    let egress = extract_llm_route(
        &mut e,
        "anthropic",
        "anthropic_messages",
        &allow(&["api.anthropic.com"]),
    )
    .expect("egress");
    assert_eq!(
        egress.inject_headers,
        vec![("x-api-key".to_string(), "sk-ant-xyz".to_string())]
    );
    assert_eq!(
        e.get("ANTHROPIC_API_KEY").unwrap(),
        CLAUDE_CODE_PLACEHOLDER_API_KEY
    );
}

#[test]
fn official_host_requires_explicit_allowlist() {
    let mut e = env(&[
        ("ANTHROPIC_API_KEY", "sk-ant-xyz"),
        ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    ]);

    assert!(extract_llm_route(&mut e, "anthropic", "anthropic_messages", &[]).is_none());
    assert!(!e.contains_key("ANTHROPIC_API_KEY"));
    assert_eq!(
        e.get("ANTHROPIC_BASE_URL").unwrap(),
        "https://api.anthropic.com"
    );
}

#[test]
fn unallowlisted_custom_host_removes_real_key_without_placeholder() {
    let mut e = env(&[
        ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
        ("ANTHROPIC_API_KEY", "tok-123"),
        ("ANTHROPIC_BASE_URL", "https://evil.example.com/v1"),
    ]);

    assert!(extract_llm_route(
        &mut e,
        "anthropic",
        "anthropic_messages",
        &allow(&["api.anthropic.com"]),
    )
    .is_none());
    assert!(!e.contains_key("ANTHROPIC_AUTH_TOKEN"));
    assert!(!e.contains_key("ANTHROPIC_API_KEY"));
    assert_eq!(
        e.get("ANTHROPIC_BASE_URL").unwrap(),
        "https://evil.example.com/v1"
    );
}

#[test]
fn llm_base_path_keeps_trailing_slash_for_envoy_rewrite() {
    let mut e = env(&[
        ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
        ("ANTHROPIC_BASE_URL", "http://ai-api.jdcloud.com/anthropic"),
    ]);
    let egress = extract_llm_route(
        &mut e,
        "custom",
        "anthropic_messages",
        &allow(&["ai-api.jdcloud.com"]),
    )
    .expect("egress");
    assert_eq!(egress.upstream_host, "ai-api.jdcloud.com");
    assert_eq!(egress.upstream_port, 80);
    assert_eq!(
        egress.path_mapping,
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any
        }
    );
    assert!(!egress.upstream_tls);
}

#[test]
fn openai_uses_bearer() {
    let mut e = env(&[
        ("OPENAI_API_KEY", "sk-oai"),
        ("OPENAI_BASE_URL", "https://gw.internal/v1"),
    ]);
    let egress = extract_llm_route(
        &mut e,
        "custom",
        "openai_responses",
        &allow(&["gw.internal"]),
    )
    .expect("egress");
    assert_eq!(egress.upstream_host, "gw.internal");
    assert_eq!(
        egress.path_mapping,
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any
        }
    );
    assert_eq!(
        egress.inject_headers,
        vec![("authorization".to_string(), "Bearer sk-oai".to_string())]
    );
    assert_eq!(
        e.get("OPENAI_API_KEY").unwrap(),
        CODEX_PLACEHOLDER_OPENAI_API_KEY
    );
    assert!(!e.contains_key("ANTHROPIC_API_KEY"));
    assert_eq!(
        e.get("OPENAI_BASE_URL").unwrap(),
        "http://gw.internal:443/v1/"
    );
}

#[test]
fn no_llm_key_returns_none() {
    let mut e = env(&[("DB_PASSWORD", "x")]);
    assert!(extract_llm_route(&mut e, "openai", "openai_responses", &[]).is_none());
    assert_eq!(e.get("DB_PASSWORD").unwrap(), "x");
}

#[test]
fn plaintext_base_url_keeps_http_upstream() {
    // If the configured endpoint is plain http, the cluster should not TLS.
    let mut e = env(&[
        ("ANTHROPIC_AUTH_TOKEN", "t"),
        ("ANTHROPIC_BASE_URL", "http://llm.internal:8080/v1"),
    ]);
    let egress = extract_llm_route(
        &mut e,
        "custom",
        "anthropic_messages",
        &allow(&["llm.internal"]),
    )
    .expect("egress");
    assert_eq!(egress.upstream_host, "llm.internal");
    assert_eq!(egress.upstream_port, 8080);
    assert_eq!(
        egress.path_mapping,
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any
        }
    );
    assert!(!egress.upstream_tls);
    assert_eq!(
        e.get("ANTHROPIC_BASE_URL").unwrap(),
        "http://llm.internal:8080/v1/"
    );
}

#[test]
fn localhost_and_private_ip_literals_are_rejected_even_if_allowlisted() {
    for host in ["localhost", "127.0.0.1", "10.0.0.1", "169.254.169.254"] {
        let mut e = env(&[
            ("OPENAI_API_KEY", "sk-oai"),
            ("OPENAI_BASE_URL", &format!("https://{host}/v1")),
        ]);

        assert!(
            extract_llm_route(&mut e, "custom", "openai_responses", &allow(&[host]),).is_none(),
            "host should be rejected: {host}"
        );
        assert!(!e.contains_key("OPENAI_API_KEY"));
    }
}

#[test]
fn unsupported_base_url_scheme_is_rejected_without_placeholder() {
    let mut e = env(&[
        ("OPENAI_API_KEY", "sk-oai"),
        ("OPENAI_BASE_URL", "file:///tmp/socket"),
    ]);

    assert!(extract_llm_route(
        &mut e,
        "custom",
        "openai_responses",
        &allow(&["api.openai.com"]),
    )
    .is_none());
    assert!(!e.contains_key("OPENAI_API_KEY"));
}

#[tokio::test]
async fn sandbox_pool_service_provision_finalizes_pooled_row() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let image = format!("resolver-pool-image-{}:latest", Uuid::now_v7().simple());
    let provider = Arc::new(RecordingProvider::default());
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_workspace_root = None;
    config.envoy_enabled = false;

    let networking = SandboxNetworkingService::test_fixture(pool.clone());
    let lifecycle =
        SandboxLifecycleService::new(pool.clone(), provider.clone(), networking.clone());
    let pool_service = SandboxPoolService::new(
        pool.clone(),
        provider.clone(),
        config,
        networking,
        lifecycle,
    );
    let sandbox_id = pool_service
        .provision(&image)
        .await
        .expect("provision warm pool sandbox");

    let result = async {
        let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
            "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load provisioned pool sandbox");
        assert_eq!(sandbox.0, "pooled");
        assert_eq!(sandbox.1, None);
        assert_eq!(
            sandbox
                .2
                .get("provisioning")
                .and_then(|value| value.get("stage"))
                .and_then(|value| value.as_str()),
            Some("pool_warm")
        );
        assert!(sandbox.2.get("runner_token").is_none());
        let proxy_token = sandbox
            .2
            .get("egress_proxy_token")
            .and_then(serde_json::Value::as_str)
            .expect("persist dedicated egress proxy token");
        let fingerprint_env = sandbox
            .2
            .get("fingerprint")
            .and_then(|value| value.get("env"))
            .and_then(serde_json::Value::as_object)
            .expect("persist runtime fingerprint env hashes");
        assert!(!fingerprint_env.contains_key("JOYSAFETER_RUNNER_TOKEN"));
        assert!(!fingerprint_env.contains_key("JOYSAFETER_EGRESS_PROXY_TOKEN"));

        let created = provider.created.lock().await;
        assert_eq!(created.len(), 1);
        assert!(!created[0].env.contains_key("JOYSAFETER_RUNNER_TOKEN"));
        assert!(!created[0].env.contains_key("JOYSAFETER_EGRESS_PROXY_TOKEN"));
        let runner_token = created[0].runtime_credentials.runner_session_token();
        let projected_proxy_token = created[0].runtime_credentials.egress_proxy_token();
        assert_eq!(projected_proxy_token, proxy_token);
        assert_ne!(runner_token, proxy_token);
        assert_eq!(created[0].sandbox_id, sandbox_id);
        assert_eq!(created[0].image.as_str(), image);
        assert_eq!(created[0].workspace_path.as_deref(), None);
        assert_eq!(
            created[0].env.get("JOYSAFETER_SANDBOX_ID"),
            Some(&sandbox_id.as_uuid().to_string())
        );
        assert_eq!(
            created[0].env.get("DISABLE_TELEMETRY").map(String::as_str),
            Some("1")
        );
        assert_eq!(
            created[0]
                .env
                .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
                .map(String::as_str),
            Some("1")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_pool_ready_error_race_does_not_destroy_changed_runtime() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let unique = Uuid::now_v7().simple().to_string();
    let image = format!("resolver-pool-ready-error-{unique}:latest");
    let trigger_name = format!("trg_pool_ready_error_{unique}");
    let function_name = format!("fn_pool_ready_error_{unique}");
    let image_literal = image.replace('\'', "''");

    sqlx::query(&format!(
        r#"
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.image = '{image_literal}'
                   AND OLD.external_id = ''
                   AND NEW.external_id <> '' THEN
                    NEW.status := 'error';
                    NEW.config := COALESCE(NEW.config, '{{}}'::jsonb)
                        || jsonb_build_object('setup_error', 'concurrent pool ready error');
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            "#
    ))
    .execute(&pool)
    .await
    .expect("create pool ready error trigger function");
    sqlx::query(&format!(
        r#"
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON joysafeter_sandboxes
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            "#
    ))
    .execute(&pool)
    .await
    .expect("create pool ready error trigger");

    let provider = Arc::new(RecordingProvider::default());
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_workspace_root = None;
    config.envoy_enabled = false;
    let networking = SandboxNetworkingService::test_fixture(pool.clone());
    let lifecycle =
        SandboxLifecycleService::new(pool.clone(), provider.clone(), networking.clone());
    let pool_service = SandboxPoolService::new(
        pool.clone(),
        provider.clone(),
        config,
        networking,
        lifecycle,
    );

    let result = pool_service.provision(&image).await;
    let destroyed = provider.destroyed.lock().await.clone();
    let sandbox: Option<(Uuid, String, serde_json::Value)> = sqlx::query_as(
            "SELECT id, status, config FROM joysafeter_sandboxes WHERE image = $1 ORDER BY created_at DESC LIMIT 1",
        )
        .bind(&image)
        .fetch_optional(&pool)
        .await
        .expect("load pool ready error sandbox");

    let _ = sqlx::query(&format!(
        "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
    ))
    .execute(&pool)
    .await;
    let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
        .execute(&pool)
        .await;
    if let Some((sandbox_id, _, _)) = sandbox.as_ref() {
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    let err = result.expect_err("concurrent pool-ready error must abort provisioning");
    let message = err.to_string();
    assert!(
        message.contains("changed state before ready finalization"),
        "{message}"
    );
    assert!(destroyed.is_empty());
    let Some((_, status, config)) = sandbox else {
        panic!("expected pool ready error sandbox row");
    };
    assert_eq!(status, "error");
    assert_eq!(
        config.get("setup_error").and_then(|value| value.as_str()),
        Some("concurrent pool ready error")
    );
}

#[tokio::test]
async fn sandbox_resolver_new_sandbox_error_race_does_not_destroy_changed_runtime() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let unique = Uuid::now_v7().simple().to_string();
    let image = format!("resolver-new-error-{unique}:latest");
    let trigger_name = format!("trg_new_sandbox_error_{unique}");
    let function_name = format!("fn_new_sandbox_error_{unique}");
    let image_literal = image.replace('\'', "''");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 1)
            "#,
    )
    .bind(agent_id)
    .bind(format!("resolver-new-error-agent-{unique}"))
    .execute(&pool)
    .await
    .expect("insert new sandbox error agent");
    sqlx::query("INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')")
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert new sandbox error session");

    sqlx::query(&format!(
        r#"
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.image = '{image_literal}'
                   AND OLD.external_id = ''
                   AND NEW.external_id <> '' THEN
                    NEW.status := 'error';
                    NEW.config := COALESCE(NEW.config, '{{}}'::jsonb)
                        || jsonb_build_object('setup_error', 'concurrent new sandbox error');
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            "#
    ))
    .execute(&pool)
    .await
    .expect("create new sandbox error trigger function");
    sqlx::query(&format!(
        r#"
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON joysafeter_sandboxes
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            "#
    ))
    .execute(&pool)
    .await
    .expect("create new sandbox error trigger");

    let provider = Arc::new(RecordingProvider::default());
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_pool_enabled = false;
    config.sandbox_workspace_root = None;
    config.envoy_enabled = false;
    config.image_claude = image.clone();
    config.sandbox_image = image.clone();
    let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

    let result = resolver
        .resolve(
            TaskId::from_uuid(Uuid::now_v7()),
            Some(session_id),
            Some(agent_id),
            None,
        )
        .await;
    let destroyed = provider.destroyed.lock().await.clone();
    let sandbox: Option<(Uuid, String, serde_json::Value)> = sqlx::query_as(
            "SELECT id, status, config FROM joysafeter_sandboxes WHERE chat_session_id = $1 ORDER BY created_at DESC LIMIT 1",
        )
        .bind(session_id)
        .fetch_optional(&pool)
        .await
        .expect("load new sandbox error row");

    let _ = sqlx::query(&format!(
        "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
    ))
    .execute(&pool)
    .await;
    let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
        .execute(&pool)
        .await;
    if let Some((sandbox_id, _, _)) = sandbox.as_ref() {
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;

    let err = result.expect_err("concurrent new-sandbox error must abort resolve");
    let message = err.to_string();
    assert!(
        message.contains("changed state before provisioning transition"),
        "{message}"
    );
    assert!(destroyed.is_empty());
    let Some((_, status, config)) = sandbox else {
        panic!("expected new sandbox error row");
    };
    assert_eq!(status, "error");
    assert_eq!(
        config.get("setup_error").and_then(|value| value.as_str()),
        Some("concurrent new sandbox error")
    );
}

#[tokio::test]
async fn sandbox_resolver_pool_claim_accepts_runner_ready_idle_race() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-pool-claim-idle-{unique}:latest");
    let external_id = format!("resolver-pool-claim-idle-{sandbox_id}");

    let result = async {
            sqlx::query(
                r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-pool-claim-idle-agent-{unique}"))
            .execute(&pool)
            .await
            .expect("insert pool claim idle agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert pool claim idle session");
            sqlx::query(
                "UPDATE joysafeter_sessions SET runtime_config_generation = 7 WHERE id = $1",
            )
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("set pool claim desired generation");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "pool_warm",
                100,
                "Warm pooled sandbox ready for claim",
                true,
                &expected,
                Some("pool-claim-idle-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create pooled sandbox");
            assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize pooled sandbox"));

            let provider = Arc::new(RecordingProvider {
                status_marks_idle: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = true;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.image_claude = image.clone();
            config.sandbox_image = image.clone();
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("pool claim should survive runner-ready idle race");
            assert_eq!(resolved.sandbox_id, sandbox_id);
            assert_eq!(resolved.external_id, external_id);
            assert_eq!(resolved.runtime_config_generation, 7);
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<SessionId>, serde_json::Value, String, i64) =
                sqlx::query_as(
                "SELECT status, chat_session_id, config, runtime_config_status, runtime_config_applied_generation FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load claimed pool sandbox after idle race");
            assert_eq!(sandbox.0, "idle");
            assert_eq!(sandbox.1, Some(session_id));
            assert_eq!(
                sandbox
                    .2
                    .get("provisioning")
                    .and_then(|value| value.get("stage"))
                    .and_then(|value| value.as_str()),
                Some("pool_claimed")
            );
            assert_eq!(sandbox.3, "ready");
            assert_eq!(sandbox.4, 7);
        }
        .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_stopped_pool_claim_starts_after_db_claim() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-pool-stopped-start-{unique}:latest");
    let external_id = format!("resolver-pool-stopped-start-{sandbox_id}");

    let result = async {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 1)
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-pool-stopped-start-agent-{unique}"))
        .execute(&pool)
        .await
        .expect("insert stopped pool claim agent");

        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert stopped pool claim session");

        let expected = ExpectedFingerprint {
            image: image.clone(),
            engine_kind: "claude".to_string(),
            networking: None,
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: empty_network_policy_revision(),
        };
        let sandbox_config = provisioning_config(
            "pool_warm",
            100,
            "Stopped warm pooled sandbox ready for claim",
            true,
            &expected,
            Some("pool-stopped-start-token"),
        );
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "recording",
            &image,
            None,
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("create stopped pooled sandbox");
        assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("finalize stopped pooled sandbox"));

        let provider = Arc::new(RecordingProvider {
            start_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
            status_result: Mutex::new(Some(SandboxStatus::Stopped)),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = true;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.image_claude = image.clone();
        config.sandbox_image = image.clone();
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let resolved = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect("stopped pool claim should restart after DB claim");
        assert_eq!(resolved.sandbox_id, sandbox_id);
        assert_eq!(resolved.external_id, external_id);

        assert_eq!(
            provider.start_observed_statuses.lock().await.as_slice(),
            &["provisioning".to_string()]
        );
        assert!(provider.destroyed.lock().await.is_empty());

        let sandbox: (String, Option<SessionId>, serde_json::Value) = sqlx::query_as(
            "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load stopped pool sandbox after restart claim");
        assert_eq!(sandbox.0, "provisioning");
        assert_eq!(sandbox.1, Some(session_id));
        assert_eq!(
            sandbox
                .2
                .get("provisioning")
                .and_then(|value| value.get("stage"))
                .and_then(|value| value.as_str()),
            Some("pool_restarting")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_pool_claim_error_race_does_not_destroy_changed_runtime() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-pool-claim-error-{unique}:latest");
    let external_id = format!("resolver-pool-claim-error-{sandbox_id}");

    let result = async {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 1)
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-pool-claim-error-agent-{unique}"))
        .execute(&pool)
        .await
        .expect("insert pool claim error agent");

        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert pool claim error session");

        let expected = ExpectedFingerprint {
            image: image.clone(),
            engine_kind: "claude".to_string(),
            networking: None,
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: empty_network_policy_revision(),
        };
        let sandbox_config = provisioning_config(
            "pool_warm",
            100,
            "Warm pooled sandbox ready for claim",
            true,
            &expected,
            Some("pool-claim-error-token"),
        );
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "recording",
            &image,
            None,
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("create pooled sandbox");
        assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("finalize pooled sandbox"));

        let provider = Arc::new(RecordingProvider {
            status_marks_error: Mutex::new(Some((pool.clone(), sandbox_id))),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = true;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.image_claude = image.clone();
        config.sandbox_image = image.clone();
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let err = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("concurrent pool claim error must abort resolve");
        let message = err.to_string();
        assert!(
            message.contains("changed during provider activation"),
            "{message}"
        );
        assert!(provider.destroyed.lock().await.is_empty());

        let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
            "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load pool sandbox after error race");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1, Some(session_id.as_uuid()));
        assert_eq!(
            sandbox
                .2
                .get("setup_error")
                .and_then(|value| value.as_str()),
            Some("concurrent pool claim error")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_pool_cleanup_failure_keeps_attached_runtime_non_ready() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-pool-cleanup-failure-{unique}:latest");
    let external_id = format!("resolver-pool-cleanup-failure-{sandbox_id}");

    let result = async {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 1)
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-pool-cleanup-failure-agent-{unique}"))
        .execute(&pool)
        .await
        .expect("insert pool cleanup failure agent");

        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert pool cleanup failure session");

        let expected = ExpectedFingerprint {
            image: image.clone(),
            engine_kind: "claude".to_string(),
            networking: None,
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: empty_network_policy_revision(),
        };
        let sandbox_config = provisioning_config(
            "pool_warm",
            100,
            "Warm pooled sandbox ready for claim",
            true,
            &expected,
            Some("pool-cleanup-failure-token"),
        );
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "recording",
            &image,
            None,
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("create pooled sandbox");
        assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("finalize pooled sandbox"));

        let provider = Arc::new(RecordingProvider {
            status_error: Mutex::new(Some("provider status failed".to_string())),
            destroy_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
            destroy_error: Mutex::new(Some("provider destroy failed".to_string())),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = true;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.image_claude = image.clone();
        config.sandbox_image = image.clone();
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let err = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("provider cleanup failure must stop pool resolution");
        assert!(matches!(
            err.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::CleanupFailed(_))
        ));
        assert_eq!(
            provider.destroyed.lock().await.as_slice(),
            &[external_id.clone()]
        );
        assert_eq!(
            provider.destroy_observed_statuses.lock().await.as_slice(),
            &["stopping".to_string()]
        );
        assert_eq!(provider.created.lock().await.len(), 0);

        let sandbox: (
            String,
            Option<SessionId>,
            String,
            Option<String>,
            bool,
            Option<i64>,
        ) = sqlx::query_as(
            r#"
                    SELECT status, chat_session_id, runtime_config_status,
                           runtime_config_last_reason,
                           runtime_config_required_at IS NOT NULL,
                           runtime_config_applied_generation
                    FROM joysafeter_sandboxes
                    WHERE id = $1
                    "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load pool sandbox after cleanup failure");
        assert_eq!(sandbox.0, "stopping");
        assert_eq!(sandbox.1, Some(session_id));
        assert_eq!(sandbox.2, "restart_required");
        assert_eq!(
            sandbox.3.as_deref(),
            Some("claimed pool sandbox provider status failed")
        );
        assert!(sandbox.4);
        assert_eq!(sandbox.5, Some(0));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_builds_mcp_egress_from_session_credential_groups() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let org_id = OrganizationId::new();
    let project_id = ProjectId::new();
    let mcp_url = "https://mcp.vault-alias.example/api";
    let normalized = mcp_url::normalize(mcp_url);

    async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
        )
        .bind(&org_id)
        .bind(format!("Resolver MCP Org {unique}"))
        .bind(format!("resolver-mcp-org-{unique}"))
        .execute(&pool)
        .await
        .expect("insert organization");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
        )
        .bind(&project_id)
        .bind(&org_id)
        .bind(format!("Resolver MCP Project {unique}"))
        .bind(format!("resolver-mcp-project-{unique}"))
        .execute(&pool)
        .await
        .expect("insert project");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_credential_groups (id, project_id, name, description)
                VALUES ($1, $2, $3, '')
                "#,
        )
        .bind(group_id)
        .bind(&project_id)
        .bind(format!("resolver-group-alias-{unique}"))
        .execute(&pool)
        .await
        .expect("insert credential group");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, credential_type, mcp_server_url,
                     normalized_mcp_server_url, group_id, data)
                VALUES ($1, $2, 'mcp', 'resolver alias credential', 'static_bearer', $3,
                        $4, $5, $6)
                "#,
        )
        .bind(credential_id)
        .bind(&project_id)
        .bind(mcp_url)
        .bind(&normalized)
        .bind(group_id)
        .bind(serde_json::json!({"token_value": ENCRYPTED_HELLO_WORLD}))
        .execute(&pool)
        .await
        .expect("insert mcp credential");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("resolver-vault-alias-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .bind(serde_json::json!([{
            "name": "secure-mcp",
            "type": "streamable_http",
            "url": mcp_url,
            "auth_requirement": "required"
        }]))
        .execute(&pool)
        .await
        .expect("insert agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert session");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
                VALUES ($1, $2)
                "#,
        )
        .bind(session_id)
        .bind(group_id)
        .execute(&pool)
        .await
        .expect("bind session credential group");

        let agent = queries::get_agent(&pool, agent_id)
            .await
            .expect("load agent")
            .expect("agent exists");
        let access = CredentialMaterialAccessService::with_material_adapter(
            pool.clone(),
            crate::kernel::credentials::material::ManagedCredentialMaterialAdapter::from_key(
                TEST_IDENTITY_KEY,
            ),
        );
        let context = CredentialAccessContext::runtime(Some(session_id), None, Some(0));
        let egress =
            crate::kernel::mcp_runtime_plan::resolve_mcp_runtime_plan_with_access_and_resolver(
                &access,
                &context,
                Some(project_id),
                Some(session_id),
                agent.id,
                0,
                EffectiveNetworkMode::Limited,
                agent.mcp_servers.as_ref(),
                &StaticMcpAddressResolver,
                &crate::kernel::mcp_network_policy::McpNetworkPolicy::default(),
            )
            .await
            .expect("build MCP runtime plan")
            .egress_routes();

        assert_eq!(egress.len(), 1);
        assert!(egress[0].id.starts_with("mcp:"));
        let EgressPathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } = &egress[0].path_mapping
        else {
            panic!("expected exact MCP path rewrite")
        };
        assert!(exposed_path.starts_with("/r/"));
        assert!(!exposed_path.contains("secure-mcp"));
        assert_eq!(egress[0].upstream_host, "mcp.vault-alias.example");
        assert_eq!(egress[0].upstream_port, 443);
        assert_eq!(upstream_path, "/api");
        assert!(egress[0].upstream_tls);
        assert_eq!(
            egress[0].inject_headers,
            vec![(
                "authorization".to_string(),
                "Bearer hello-world".to_string()
            )]
        );
        let audit = sqlx::query_as::<_, (String, String, Option<SessionId>, serde_json::Value)>(
            r#"
                SELECT usage, result, session_id, field_names
                FROM joysafeter_credential_access_audits
                WHERE credential_id = $1
                "#,
        )
        .bind(credential_id)
        .fetch_one(&pool)
        .await
        .expect("load MCP credential access audit");
        assert_eq!(audit.0, "mcp_egress");
        assert_eq!(audit.1, "success");
        assert_eq!(audit.2, Some(session_id));
        assert_eq!(audit.3, serde_json::json!(["token_value"]));

        sqlx::query("UPDATE joysafeter_credentials SET data = $2 WHERE id = $1")
            .bind(credential_id)
            .bind(serde_json::json!({
                "token_value": "invalid-envelope-secret-sentinel"
            }))
            .execute(&pool)
            .await
            .expect("corrupt MCP credential envelope");
        let failure_context = CredentialAccessContext::runtime(Some(session_id), None, Some(1));
        let error = resolve_mcp_runtime_plan_with_access(
            &access,
            &failure_context,
            Some(project_id),
            Some(session_id),
            agent.id,
            1,
            EffectiveNetworkMode::Limited,
            agent.mcp_servers.as_ref(),
        )
        .await
        .expect_err("invalid MCP ciphertext must fail closed");
        assert_eq!(
            error.downcast_ref(),
            Some(&CredentialRuntimeError::EnvelopeInvalid)
        );
        let failed_audit = sqlx::query_as::<_, (String, String, serde_json::Value)>(
            r#"
                SELECT result, error_code, field_names
                FROM joysafeter_credential_access_audits
                WHERE credential_id = $1 AND generation = 1
                "#,
        )
        .bind(credential_id)
        .fetch_one(&pool)
        .await
        .expect("load failed MCP credential access audit");
        assert_eq!(failed_audit.0, "failed");
        assert_eq!(failed_audit.1, "envelope_invalid");
        assert_eq!(failed_audit.2, serde_json::json!(["token_value"]));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
        .bind(credential_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_credential_groups WHERE id = $1")
        .bind(group_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(&project_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(&org_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn sandbox_resolver_restart_does_not_resurrect_concurrent_error() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-race-image-{unique}:latest");
    let external_id = format!("resolver-race-{sandbox_id}");

    async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver race system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-race-agent-{unique}"))
        .bind(serde_json::json!({"id": "resolver-race-model"}))
        .execute(&pool)
        .await
        .expect("insert resolver race agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert resolver race session");

        let expected = ExpectedFingerprint {
            image: image.clone(),
            engine_kind: "claude".to_string(),
            networking: None,
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: empty_network_policy_revision(),
        };
        let sandbox_config = provisioning_config(
            "stopped_for_restart",
            100,
            "Stopped sandbox ready for restart",
            true,
            &expected,
            Some("resolver-race-token"),
        );

        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "recording",
            &image,
            Some(session_id),
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("create stopped sandbox");
        sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("mark sandbox stopped");

        let provider = Arc::new(RecordingProvider {
            start_marks_error: Mutex::new(Some((pool.clone(), sandbox_id))),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.sandbox_image = image.clone();
        config.image_claude = image.clone();

        let resolver = SandboxResolver::new(pool.clone(), provider, config);
        let err = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("concurrent error must abort stopped sandbox restart");
        let message = err.to_string();
        assert!(
            message.contains("changed state during restart"),
            "{message}"
        );

        let sandbox: (String, serde_json::Value) =
            sqlx::query_as("SELECT status, config FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after restart race");
        assert_eq!(sandbox.0, "error");
        assert_eq!(
            sandbox
                .1
                .get("setup_error")
                .and_then(|value| value.as_str()),
            Some("concurrent restart failure")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn sandbox_resolver_restart_claims_row_before_provider_start() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-restart-ordering-{unique}:latest");
    let external_id = format!("resolver-restart-ordering-{sandbox_id}");

    async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver restart ordering system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-restart-ordering-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-restart-ordering-model"}))
            .execute(&pool)
            .await
            .expect("insert resolver restart ordering agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert resolver restart ordering session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stopped_for_restart",
                100,
                "Stopped sandbox ready for restart",
                true,
                &expected,
                Some("resolver-restart-ordering-token"),
            );

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create restart ordering sandbox");
            sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("mark restart ordering sandbox stopped");

            let provider = Arc::new(RecordingProvider {
                start_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);
            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("restart stopped sandbox");
            assert_eq!(resolved.sandbox_id, sandbox_id);
            assert_eq!(resolved.external_id, external_id);

            assert_eq!(
                provider.start_observed_statuses.lock().await.as_slice(),
                &["provisioning".to_string()]
            );

            let sandbox_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load restarted sandbox status");
            assert_eq!(sandbox_status, "provisioning");
        }
        .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[derive(Clone, Copy)]
enum RestartProviderFailure {
    RuntimeGone,
    StatusError,
    StartError,
}

async fn assert_restart_failure_restores_runtime_configuration(
    failure: RestartProviderFailure,
    write_newer_marker: bool,
) {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-restart-compensation-{unique}:latest");
    let external_id = format!("resolver-restart-compensation-{sandbox_id}");
    let original_required_at = "2026-08-21T12:34:56.123456Z"
        .parse::<chrono::DateTime<chrono::Utc>>()
        .expect("valid original timestamp");

    async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver restart compensation system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-restart-compensation-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-restart-compensation-model"}))
            .execute(&pool)
            .await
            .expect("insert resolver restart compensation agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert resolver restart compensation session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stopped_for_restart",
                100,
                "Stopped sandbox ready for restart",
                true,
                &expected,
                Some("resolver-restart-compensation-token"),
            );

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stopped sandbox");
            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET status = 'stopped',
                    runtime_config_status = 'restart_required',
                    runtime_config_last_reason = 'original_provider_marker',
                    runtime_config_required_at = $2
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .bind(original_required_at)
            .execute(&pool)
            .await
            .expect("mark stopped sandbox restart required");

            let provider = Arc::new(RecordingProvider {
                status_result: Mutex::new(match failure {
                    RestartProviderFailure::RuntimeGone => Some(SandboxStatus::NotFound),
                    RestartProviderFailure::StatusError | RestartProviderFailure::StartError => {
                        Some(SandboxStatus::Stopped)
                    }
                }),
                status_error: Mutex::new(match failure {
                    RestartProviderFailure::StatusError => Some("provider status failed".to_string()),
                    _ => None,
                }),
                start_error: Mutex::new(match failure {
                    RestartProviderFailure::StartError => Some("provider start failed".to_string()),
                    _ => None,
                }),
                status_marks_restart_required: Mutex::new(
                    write_newer_marker.then_some((pool.clone(), sandbox_id)),
                ),
                destroy_error: Mutex::new(Some("provider destroy failed".to_string())),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider, config);
            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("destroy failure must abort replacement provisioning");
            if write_newer_marker {
                assert!(matches!(
                    err.downcast_ref::<RuntimeFreshnessError>(),
                    Some(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id: id })
                        if *id == sandbox_id
                ));
            } else {
                assert!(err.to_string().contains("failed to destroy sandbox"));
            }

            let restored: (
                String,
                String,
                Option<String>,
                Option<chrono::DateTime<chrono::Utc>>,
            ) = sqlx::query_as(
                r#"
                SELECT status, runtime_config_status, runtime_config_last_reason, runtime_config_required_at
                FROM joysafeter_sandboxes
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after restart and destroy compensation");

            if write_newer_marker {
                assert_eq!(
                    restored,
                    (
                        "provisioning".to_string(),
                        "restart_required".to_string(),
                        Some("newer_provider_marker".to_string()),
                        Some(
                            "2026-08-21T14:15:16.777777Z"
                                .parse::<chrono::DateTime<chrono::Utc>>()
                                .expect("valid newer timestamp"),
                        ),
                    )
                );
            } else {
                assert_eq!(
                    restored,
                    (
                        "stopped".to_string(),
                        "restart_required".to_string(),
                        Some("original_provider_marker".to_string()),
                        Some(original_required_at),
                    )
                );
            }
        }
        .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn sandbox_resolver_restores_freshness_after_missing_runtime_and_destroy_failure() {
    assert_restart_failure_restores_runtime_configuration(
        RestartProviderFailure::RuntimeGone,
        false,
    )
    .await;
}

#[tokio::test]
async fn sandbox_resolver_restores_freshness_after_status_and_destroy_failures() {
    assert_restart_failure_restores_runtime_configuration(
        RestartProviderFailure::StatusError,
        false,
    )
    .await;
}

#[tokio::test]
async fn sandbox_resolver_restores_freshness_after_start_and_destroy_failures() {
    assert_restart_failure_restores_runtime_configuration(
        RestartProviderFailure::StartError,
        false,
    )
    .await;
}

#[tokio::test]
async fn sandbox_resolver_compensation_preserves_newer_freshness_marker() {
    assert_restart_failure_restores_runtime_configuration(
        RestartProviderFailure::StatusError,
        true,
    )
    .await;
}

#[tokio::test]
async fn sandbox_resolver_isolates_stale_creating_before_provider_destroy() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let stale_sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let image = format!("resolver-stale-creating-{unique}:latest");
    let external_id = format!("resolver-stale-creating-{stale_sandbox_id}");

    let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver stale creating system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-stale-creating-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-stale-creating-model"}))
            .execute(&pool)
            .await
            .expect("insert stale creating agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert stale creating session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stale_creating",
                0,
                "Stale creating sandbox should be isolated before provider destroy",
                false,
                &expected,
                Some("resolver-stale-creating-token"),
            );

            queries::create_sandbox(
                &pool,
                stale_sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stale creating sandbox");

            let provider = Arc::new(RecordingProvider {
                destroy_status_probe: Mutex::new(Some((pool.clone(), stale_sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);
            let resolved = resolver
                .resolve(
                    task_id,
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("resolve replacement after stale creating cleanup");
            assert_ne!(resolved.sandbox_id, stale_sandbox_id);

            let observed = provider.destroy_observed_statuses.lock().await.clone();
            assert_eq!(observed, vec!["stopping".to_string()]);

            let stale: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(stale_sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load stale creating sandbox after cleanup");
            assert_eq!(stale.0, "destroyed");
            assert!(stale.1);
        }
        .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn sandbox_resolver_uses_session_snapshot_for_image_network_and_env() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let agent_name = format!("resolver-snapshot-agent-{unique}");
    let environment_name = format!("resolver-snapshot-env-{unique}");
    let snapshot = serde_json::json!({
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "id": agent_id.to_string(),
        "version": 3,
        "name": agent_name,
        "engine_kind": "claude",
        "model": {"id": "snapshot-model"},
        "env": {"AGENT_ENV": "snapshot-agent"},
        "mcp_servers": [],
        "tools": [],
        "skills": [],
        "agents": [],
        "commands": [],
        "environment_id": environment_id.to_string(),
        "environment": {
            "environment_id": environment_id.to_string(),
            "name": environment_name,
            "image_tag": "snapshot-image:1",
            "image_version": 1,
            "config": {
                "env_vars": {"ENV_LEVEL": "snapshot-env"},
                "networking": {
                    "type": "limited",
                    "allowed_hosts": ["api.openai.com"]
                }
            }
        }
    });

    async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_environments
                    (id, name, description, config, image_tag, image_version)
                VALUES ($1, $2, 'resolver snapshot test env', $3, 'live-image:2', 2)
                "#,
        )
        .bind(environment_id)
        .bind(&environment_name)
        .bind(serde_json::json!({
            "env_vars": {"ENV_LEVEL": "live-env", "LIVE_ONLY": "must-not-appear"},
            "networking": {"type": "unrestricted"}
        }))
        .execute(&pool)
        .await
        .expect("insert live environment");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata,
                    version, environment_id
                )
                VALUES (
                    $1, $2, 'codex', $3, 'live system', $4, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 4, $5
                )
                "#,
        )
        .bind(agent_id)
        .bind(&agent_name)
        .bind(serde_json::json!({"id": "live-model"}))
        .bind(serde_json::json!({"AGENT_ENV": "live-agent", "LIVE_AGENT_ONLY": "must-not-appear"}))
        .bind(environment_id)
        .execute(&pool)
        .await
        .expect("insert live agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, agent_version, agent_snapshot, environment_id
                )
                VALUES ($1, $2, 'idle', 3, $3, $4)
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&snapshot)
        .bind(environment_id)
        .execute(&pool)
        .await
        .expect("insert snapshot session");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.image_claude = "fallback-claude:latest".to_string();
        config.image_codex = "fallback-codex:latest".to_string();
        let resolver = recording_resolver(pool.clone(), provider.clone(), config);

        let resolved = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect("resolve sandbox from snapshot");
        let sandbox_id = resolved.sandbox_id;

        let created = provider.created.lock().await;
        assert_eq!(created.len(), 1);
        let create_config = &created[0];
        assert_eq!(create_config.image, "snapshot-image:1");
        assert_eq!(create_config.network.as_deref(), Some("none"));
        assert_eq!(
            create_config.env.get("ENV_LEVEL").map(String::as_str),
            Some("snapshot-env")
        );
        assert_eq!(
            create_config.env.get("AGENT_ENV").map(String::as_str),
            Some("snapshot-agent")
        );
        assert!(!create_config.env.contains_key("LIVE_ONLY"));
        assert!(!create_config.env.contains_key("LIVE_AGENT_ONLY"));
        drop(created);

        let networking = provider.networking.lock().await;
        assert_eq!(networking.len(), 1);
        assert_eq!(networking[0].0, sandbox_id);
        assert_eq!(
            networking[0]
                .1
                .as_ref()
                .and_then(|value| value.get("type"))
                .and_then(|value| value.as_str()),
            Some("limited")
        );
        drop(networking);

        let sandbox_config: (String, serde_json::Value) =
            sqlx::query_as("SELECT image, config FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load created sandbox");
        assert_eq!(sandbox_config.0, "snapshot-image:1");
        assert_eq!(
            sandbox_config
                .1
                .get("fingerprint")
                .and_then(|value| value.get("networking"))
                .and_then(|value| value.get("type"))
                .and_then(|value| value.as_str()),
            Some("limited")
        );
        assert!(sandbox_config
            .1
            .get("fingerprint")
            .and_then(|value| value.get("env"))
            .and_then(|value| value.get("ENV_LEVEL"))
            .is_some());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
        .bind(environment_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn new_limited_sandbox_networking_failure_is_destroyed_and_not_returned() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let snapshot = serde_json::json!({
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "id": agent_id.to_string(),
        "version": 1,
        "name": format!("network-failure-agent-{unique}"),
        "engine_kind": "claude",
        "model": {"id": "claude-sonnet"},
        "env": {},
        "mcp_servers": [],
        "tools": [],
        "skills": [],
        "agents": [],
        "commands": [],
        "environment_id": environment_id.to_string(),
        "environment": {
            "environment_id": environment_id.to_string(),
            "name": format!("network-failure-env-{unique}"),
            "image_tag": "network-failure:latest",
            "image_version": 1,
            "config": {"networking": {"type": "limited", "allowed_hosts": []}}
        }
    });

    sqlx::query(
        r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, metadata, version
            )
            VALUES (
                $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                '{}'::jsonb, 1
            )
            "#,
    )
    .bind(agent_id)
    .bind(format!("network-failure-agent-{unique}"))
    .bind(serde_json::json!({"id": "claude-sonnet"}))
    .execute(&pool)
    .await
    .expect("insert agent");
    sqlx::query(
        r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot)
            VALUES ($1, $2, 'idle', 1, $3)
            "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(&snapshot)
    .execute(&pool)
    .await
    .expect("insert session");

    let provider = Arc::new(RecordingProvider {
        networking_error: Mutex::new(Some("synthetic Envoy rejection".to_string())),
        ..Default::default()
    });
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_pool_enabled = false;
    config.sandbox_workspace_root = None;
    config.envoy_enabled = true;
    config.image_claude = "network-failure:latest".to_string();
    let resolver = recording_resolver(pool.clone(), provider.clone(), config);

    let error = resolver
        .resolve(
            TaskId::from_uuid(Uuid::now_v7()),
            Some(session_id),
            Some(agent_id),
            None,
        )
        .await
        .expect_err("networking failure must reject new sandbox resolution");
    assert!(error
        .to_string()
        .contains("failed to setup Envoy networking"));
    assert_eq!(provider.destroyed.lock().await.len(), 1);

    let active_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1 AND destroyed_at IS NULL",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count active sandboxes");
    assert_eq!(active_count, 0);

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn new_sandbox_ack_persistence_error_runs_complete_compensation() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let function_name = format!("fail_network_ready_{unique}");
    let trigger_name = format!("trg_fail_network_ready_{unique}");
    let snapshot = serde_json::json!({
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "id": agent_id.to_string(),
        "version": 1,
        "name": format!("ack-failure-agent-{unique}"),
        "engine_kind": "claude",
        "model": {"id": "claude-sonnet"},
        "env": {},
        "mcp_servers": [],
        "tools": [],
        "skills": [],
        "agents": [],
        "commands": [],
        "environment_id": environment_id.to_string(),
        "environment": {
            "environment_id": environment_id.to_string(),
            "name": format!("ack-failure-env-{unique}"),
            "image_tag": "ack-failure:latest",
            "image_version": 1,
            "config": {"networking": {"type": "limited", "allowed_hosts": []}}
        }
    });

    sqlx::query(
        r#"INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, metadata, version
            ) VALUES ($1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                '{}'::jsonb, 1)"#,
    )
    .bind(agent_id)
    .bind(format!("ack-failure-agent-{unique}"))
    .bind(serde_json::json!({"id": "claude-sonnet"}))
    .execute(&pool)
    .await
    .expect("insert ack failure agent");
    sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot) VALUES ($1, $2, 'idle', 1, $3)",
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&snapshot)
        .execute(&pool)
        .await
        .expect("insert ack failure session");
    sqlx::query(&format!(
            r#"CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.chat_session_id = '{session_uuid}'::uuid AND NEW.networking_status = 'ready' THEN
                    RAISE EXCEPTION 'synthetic ACK persistence failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql"#
        , session_uuid = session_id.as_uuid()))
        .execute(&pool)
        .await
        .expect("create ACK failure trigger function");
    sqlx::query(&format!(
            "CREATE TRIGGER {trigger_name} BEFORE UPDATE OF networking_status ON joysafeter_sandboxes FOR EACH ROW EXECUTE FUNCTION {function_name}()"
        ))
        .execute(&pool)
        .await
        .expect("create ACK failure trigger");

    let provider = Arc::new(RecordingProvider::default());
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_pool_enabled = false;
    config.sandbox_workspace_root = None;
    config.envoy_enabled = true;
    config.image_claude = "ack-failure:latest".to_string();
    let resolver = recording_resolver(pool.clone(), provider.clone(), config);

    let error = resolver
        .resolve(
            TaskId::from_uuid(Uuid::now_v7()),
            Some(session_id),
            Some(agent_id),
            None,
        )
        .await
        .expect_err("ACK persistence failure must reject the new sandbox");
    assert!(
        format!("{error:#}").contains("failed to setup Envoy networking"),
        "unexpected error chain: {error:#}"
    );
    assert_eq!(provider.destroyed.lock().await.len(), 1);
    assert_eq!(provider.networking_teardowns.lock().await.len(), 1);
    let active_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1 AND destroyed_at IS NULL",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count active sandboxes after ACK failure");
    assert_eq!(active_count, 0);

    let _ = sqlx::query(&format!(
        "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
    ))
    .execute(&pool)
    .await;
    let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn reused_limited_sandbox_networking_failure_is_not_returned() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let snapshot = serde_json::json!({
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "id": agent_id.to_string(),
        "version": 1,
        "name": format!("reuse-network-failure-agent-{unique}"),
        "engine_kind": "claude",
        "model": {"id": "claude-sonnet"},
        "env": {},
        "mcp_servers": [],
        "tools": [],
        "skills": [],
        "agents": [],
        "commands": [],
        "environment_id": environment_id.to_string(),
        "environment": {
            "environment_id": environment_id.to_string(),
            "name": format!("reuse-network-failure-env-{unique}"),
            "image_tag": "reuse-network-failure:latest",
            "image_version": 1,
            "config": {"networking": {"type": "limited", "allowed_hosts": []}}
        }
    });

    sqlx::query(
        r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, metadata, version
            )
            VALUES (
                $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                '{}'::jsonb, 1
            )
            "#,
    )
    .bind(agent_id)
    .bind(format!("reuse-network-failure-agent-{unique}"))
    .bind(serde_json::json!({"id": "claude-sonnet"}))
    .execute(&pool)
    .await
    .expect("insert agent");
    sqlx::query(
        r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot)
            VALUES ($1, $2, 'idle', 1, $3)
            "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(&snapshot)
    .execute(&pool)
    .await
    .expect("insert session");

    let provider = Arc::new(RecordingProvider::default());
    let mut config = JoySafeterConfig::from_env();
    config.sandbox_provider = "recording".to_string();
    config.sandbox_pool_enabled = false;
    config.sandbox_workspace_root = None;
    config.envoy_enabled = true;
    config.image_claude = "reuse-network-failure:latest".to_string();
    let resolver = recording_resolver(pool.clone(), provider.clone(), config);

    let resolved = resolver
        .resolve(
            TaskId::from_uuid(Uuid::now_v7()),
            Some(session_id),
            Some(agent_id),
            None,
        )
        .await
        .expect("create initial limited sandbox");
    assert!(
        queries::transition_sandbox_cas(&pool, resolved.sandbox_id, "provisioning", "idle",)
            .await
            .expect("mark initial sandbox idle")
    );
    resolver.networking.forget_ready(resolved.sandbox_id);
    sqlx::query(
        r#"
            UPDATE joysafeter_sandboxes
            SET networking_status = 'pending',
                networking_applied_hash = NULL,
                networking_applied_version = NULL,
                networking_ready_at = NULL
            WHERE id = $1
            "#,
    )
    .bind(resolved.sandbox_id)
    .execute(&pool)
    .await
    .expect("mark reused sandbox network policy pending");
    *provider.networking_error.lock().await = Some("synthetic Envoy refresh rejection".to_string());

    let error = resolver
        .resolve(
            TaskId::from_uuid(Uuid::now_v7()),
            Some(session_id),
            Some(agent_id),
            None,
        )
        .await
        .expect_err("networking refresh failure must reject sandbox reuse");
    assert!(error.to_string().contains("failed to refresh Envoy policy"));
    assert!(provider.destroyed.lock().await.is_empty());

    let networking_state: (String, Option<String>) = sqlx::query_as(
        "SELECT networking_status, networking_last_error FROM joysafeter_sandboxes WHERE id = $1",
    )
    .bind(resolved.sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load failed reused sandbox networking state");
    assert_eq!(networking_state.0, "nacked");
    assert!(networking_state
        .1
        .as_deref()
        .is_some_and(|reason| reason.contains("synthetic Envoy refresh rejection")));

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn sandbox_resolver_snapshot_session_file_injection_storage_missing_fails_resolve() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let file_id = FileId::from_uuid(Uuid::now_v7());
    let session_file_id = SessionResourceId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let org_id = OrganizationId::new();
    let project_id = ProjectId::new();
    let missing_storage_key = format!("missing-resolver-session-file-{unique}.txt");
    let workspace_root =
        std::env::temp_dir().join(format!("joysafeter-resolver-workspace-{unique}"));

    async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
        )
        .bind(&org_id)
        .bind(format!("Resolver File Org {unique}"))
        .bind(format!("resolver-file-org-{unique}"))
        .execute(&pool)
        .await
        .expect("insert organization");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
        )
        .bind(&project_id)
        .bind(&org_id)
        .bind(format!("Resolver File Project {unique}"))
        .bind(format!("resolver-file-project-{unique}"))
        .execute(&pool)
        .await
        .expect("insert project");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("resolver-file-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert session");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_files (
                    id, project_id, filename, purpose, content_type, size_bytes,
                    sha256, storage_key, downloadable
                )
                VALUES (
                    $1, $2, 'missing.txt', 'user_upload', 'text/plain', 12,
                    'missing-sha', $3, true
                )
                "#,
        )
        .bind(file_id)
        .bind(&project_id)
        .bind(&missing_storage_key)
        .execute(&pool)
        .await
        .expect("insert file metadata");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_files
                    (id, session_id, file_id, mount_path, access)
                VALUES ($1, $2, $3, '/workspace/missing.txt', 'read_only')
                "#,
        )
        .bind(session_file_id)
        .bind(session_id)
        .bind(file_id)
        .execute(&pool)
        .await
        .expect("insert session file mount");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = Some(workspace_root.to_string_lossy().to_string());
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let err = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("missing declared session file content must fail sandbox resolve");
        let message = err.to_string();
        assert!(
            message.contains("failed to inject session files"),
            "{message}"
        );
        assert!(message.contains(&missing_storage_key), "{message}");
        assert!(
            provider.created.lock().await.is_empty(),
            "sandbox provider must not create a sandbox after declared input load fails"
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_files WHERE id = $1")
        .bind(session_file_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_files WHERE id = $1")
        .bind(file_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(&project_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(&org_id)
        .execute(&pool)
        .await;
    let _ = tokio::fs::remove_dir_all(&workspace_root).await;
}
