//! Runtime credential projection for sandbox environments and egress policy.
//!
//! This module owns the transformation from durable credential/session records
//! into ephemeral container environment values and Envoy credential routes. It
//! does not own sandbox lifecycle or xDS publication.

use std::collections::HashMap;
use std::net::IpAddr;

use anyhow::Context;
use base64::Engine as _;
use sqlx::PgPool;
use tracing::warn;
use url::Url;

use crate::db::models::{JoySafeterAgent, JoySafeterSandbox};
use crate::db::queries;
use crate::ids::{CredentialId, EnvironmentId, ProjectId, SessionId};
use crate::kernel::agent_identity_provider::IdentityEgressRequestTarget;
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::credentials::reference::decode_environment;
use crate::kernel::credentials::service::ResolvedServiceCredential;
use crate::kernel::llm_catalog::RuntimeCredentialBinding;
use crate::kernel::llm_providers::credential_profile_spec;
use crate::kernel::mcp_runtime_plan::{
    effective_network_mode, resolve_mcp_runtime_plan_with_access,
};
use crate::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode, SandboxCredentials, UpstreamTarget, GIT_EGRESS_HOST,
};
use crate::kernel::repository_access::material::RepositoryAccessMaterialAdapter;
use crate::kernel::run_spec::{
    agent_for_execution, environment_credential_ids, environment_for_execution,
};

/// Normalizes a stored secret `protocol` into the container-env signal read by
/// pi-entrypoint.sh. Returns `None` for `custom`/blank so we never emit a
/// meaningless `JOYSAFETER_MODEL_PROTOCOL`.
pub(crate) fn model_protocol_env_value(protocol: &str) -> Option<String> {
    match protocol.trim() {
        "" | "custom" => None,
        other => Some(other.to_string()),
    }
}

/// Maps a stored secret `protocol` to the ccb provider-switch env var that flips
/// the native harness off its default Anthropic path. ccb ignores `OPENAI_BASE_URL`
/// on its own — without `CLAUDE_CODE_USE_OPENAI` set it stays in first-party
/// Anthropic mode and demands a login, so OpenAI-family models fail with
/// "Not logged in". Returns `None` for Anthropic/custom/blank, which need no switch.
pub(crate) fn model_protocol_provider_switch(protocol: &str) -> Option<&'static str> {
    match protocol.trim() {
        "openai_responses" | "chat_completions" => Some("CLAUDE_CODE_USE_OPENAI"),
        _ => None,
    }
}

pub(crate) async fn resolve_agent_env_from(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    agent: Option<&JoySafeterAgent>,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<ResolvedAgentEnv> {
    let mut env = HashMap::new();
    let Some(agent) = agent else {
        return Ok(ResolvedAgentEnv::default());
    };

    if let Some(environment) = environment {
        if let Some(env_vars) = environment
            .config
            .get("env_vars")
            .and_then(|v| v.as_object())
        {
            for (key, value) in env_vars {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                env.insert(key.clone(), value);
            }
        }

        // Environment-level credentials use canonical `cred_` ids and resolve
        // against `joysafeter_credentials` with kind=service.
        for credential_id in environment_credential_ids(&environment.config)? {
            merge_credential_ref_into_env(
                credential_access,
                access_context,
                &mut env,
                credential_id,
                agent.project_id,
                false,
                None,
            )
            .await?;
        }
    }

    if let Some(model_credential_id) = agent.model_credential_id {
        let llm_binding = merge_credential_ref_into_env(
            credential_access,
            access_context,
            &mut env,
            model_credential_id,
            agent.project_id,
            true,
            Some(agent.engine_kind.as_deref().unwrap_or("claude")),
        )
        .await?;
        if let Some(obj) = agent.env.as_ref().and_then(|v| v.as_object()) {
            for (key, value) in obj {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                env.insert(key.clone(), value);
            }
        }
        return Ok(ResolvedAgentEnv {
            values: env,
            llm_binding,
        });
    }

    if let Some(obj) = agent.env.as_ref().and_then(|v| v.as_object()) {
        for (key, value) in obj {
            let value = value
                .as_str()
                .map(ToOwned::to_owned)
                .unwrap_or_else(|| value.to_string());
            env.insert(key.clone(), value);
        }
    }

    Ok(ResolvedAgentEnv {
        values: env,
        llm_binding: None,
    })
}

/// Extract LLM egress credentials from the resolved env, removing the real
/// key from the env map and repointing the base URL at the Envoy egress
/// boundary. After this, the container env holds no LLM API key — the key is
/// injected by Envoy at the egress boundary instead.
///
/// Credential handling is selected by the Catalog-resolved profile, and
/// provider defaults come from the validated Provider/Protocol binding.
pub(crate) fn extract_llm_egress(
    env: &mut HashMap<String, String>,
    binding: Option<&RuntimeCredentialBinding>,
    allowed_hosts: &[String],
) -> Vec<EgressCredentialRoute> {
    let Some(binding) = binding else {
        return vec![];
    };
    let Some(spec) = credential_profile_spec(&binding.credential_profile_id) else {
        warn!(
            credential_profile_id = %binding.credential_profile_id,
            protocol_id = %binding.protocol_id,
            "LLM credential profile has no runtime routing implementation"
        );
        return vec![];
    };
    let Some(credential_key) = spec
        .credential_keys
        .iter()
        .find(|credential| env.contains_key(credential.key))
    else {
        return vec![];
    };

    let Some(key_value) = env.remove(credential_key.key) else {
        return vec![];
    };

    // Remove all extra keys associated with this provider (unconditional —
    // mirrors the original behavior where Anthropic vars are always removed
    // regardless of which one matched).
    for extra in spec.extra_keys_to_remove {
        env.remove(*extra);
    }

    let base_url_var = binding.base_url_key.as_str();

    // Parse the configured base URL to learn the real upstream
    // host/port/scheme/path. The sandbox is then repointed at the placeholder
    // egress host over plaintext http:// — it never learns the real address.
    // Envoy matches the placeholder, injects the key, host_rewrites to the
    // real upstream, and forwards via that upstream's STRICT_DNS cluster.
    let configured = env
        .get(base_url_var)
        .cloned()
        .or_else(|| binding.default_base_url.clone());
    let (upstream_host, upstream_port, upstream_prefix, upstream_tls) = match configured.as_deref()
    {
        Some(raw) => {
            let url = match Url::parse(raw) {
                Ok(url) => url,
                Err(e) => {
                    warn!(base_url_var, error = %e, "Invalid LLM base URL; skipping credential injection");
                    return vec![];
                }
            };
            if url.scheme() != "http" && url.scheme() != "https" {
                warn!(
                    base_url_var,
                    scheme = url.scheme(),
                    "Unsupported LLM base URL scheme; skipping credential injection"
                );
                return vec![];
            }
            let host = match url.host_str() {
                Some(host) => host.to_string(),
                None => return vec![],
            };
            let tls = url.scheme() == "https";
            let port = url.port().unwrap_or(if tls { 443 } else { 80 });
            let prefix = normalize_llm_upstream_prefix(url.path());
            (host, port, prefix, tls)
        }
        None => {
            warn!(
                base_url_var,
                credential_profile_id = %binding.credential_profile_id,
                protocol_id = %binding.protocol_id,
                "LLM binding requires an explicit base URL"
            );
            return vec![];
        }
    };

    if !is_llm_egress_host_allowed(&upstream_host, allowed_hosts) {
        warn!(
            base_url_var,
            upstream_host = %upstream_host,
            "LLM base URL host is not allowlisted; skipping credential injection"
        );
        return vec![];
    }

    // Insert non-secret placeholder so the agent CLI doesn't fall back to
    // interactive login. Envoy overwrites/removes auth headers at the egress
    // boundary and injects the real credential there.
    if let Some((placeholder_var, placeholder_val)) = spec.placeholder {
        env.insert(placeholder_var.to_string(), placeholder_val.to_string());
    }

    // Repoint the agent at the real upstream host but downgrade to plaintext
    // http:// so the request goes through the HTTP proxy as a normal request
    // (not a CONNECT tunnel). This lets Envoy see and inject headers. Envoy
    // does TLS origination via the shared dynamic_forward_proxy_tls cluster.
    let base_url_for_sandbox = if upstream_tls {
        format!(
            "http://{}:{}{}",
            upstream_host, upstream_port, upstream_prefix
        )
    } else {
        format!(
            "http://{}:{}{}",
            upstream_host, upstream_port, upstream_prefix
        )
    };
    env.insert(base_url_var.to_string(), base_url_for_sandbox);

    let header_value = if credential_key.is_bearer {
        format!("Bearer {key_value}")
    } else {
        key_value
    };

    vec![EgressCredentialRoute {
        id: "llm".to_string(),
        kind: EgressKind::Llm,
        exposure: EgressExposure::Transparent,
        match_host: upstream_host.clone(),
        path_mapping: EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        },
        retry_mode: EgressRetryMode::SafeIdempotent,
        upstream_host,
        upstream_port,
        upstream_tls,
        cluster_name: String::new(),
        vetted_addresses: vec![],
        inject_headers: vec![(credential_key.header_name.to_string(), header_value)],
        remove_headers: vec![],
    }]
}

/// Build git egress credentials: decrypt each session repo's clone token and
/// produce an [`EgressCredentialRoute`] keyed by a stable slug ([`git_repo_slug`]). The
/// sandbox clones from `git-egress.internal/git/<slug>/` (no token); Envoy
/// rewrites to the real host + repo path, injects HTTP Basic auth, and
/// forwards over the upstream scheme. The real token never enters the sandbox.
pub(crate) async fn build_git_egress(
    pool: &PgPool,
    session_id: Option<SessionId>,
) -> anyhow::Result<Vec<EgressCredentialRoute>> {
    let Some(session_id) = session_id else {
        return Ok(vec![]);
    };
    let rows: Vec<(String, String, String)> = sqlx::query_as(
        r#"
        SELECT url, mount_name,
               CASE
                   WHEN token_expires_at IS NULL OR token_expires_at > NOW()
                   THEN encrypted_token
                   ELSE ''
               END AS encrypted_token
        FROM joysafeter_session_repos
        WHERE session_id = $1
        ORDER BY created_at
        "#,
    )
    .bind(session_id)
    .fetch_all(pool)
    .await
    .map_err(|e| {
        anyhow::anyhow!("failed to load session repos for Git egress in session {session_id}: {e}")
    })?;

    let material_adapter = RepositoryAccessMaterialAdapter::from_env();
    let mut egress = Vec::new();
    for (idx, (url, mount_name, encrypted_token)) in rows.into_iter().enumerate() {
        let Some(token) = material_adapter.reveal_optional(&encrypted_token)? else {
            continue;
        };
        let upstream = UpstreamTarget::from_url(&url)
            .map_err(|e| anyhow::anyhow!("invalid Git repo URL '{url}': {e}"))?;
        // Preserve the repo path so Envoy rewrites /git/<slug>/ back to the
        // real repo path (e.g. /org/repo.git/), keeping git smart-HTTP happy.
        let mut prefix = upstream.prefix;
        if !prefix.ends_with('/') {
            prefix.push('/');
        }
        // HTTP Basic auth: username "x-access-token" (GitHub) / any (GitLab),
        // password = token. base64("x-access-token:<token>").
        let basic =
            base64::engine::general_purpose::STANDARD.encode(format!("x-access-token:{token}"));
        let slug = crate::kernel::network_policy::envoy_model::git_repo_slug(&mount_name, idx);
        egress.push(EgressCredentialRoute {
            id: format!("git:{slug}"),
            kind: EgressKind::Git,
            exposure: EgressExposure::Placeholder,
            match_host: GIT_EGRESS_HOST.to_string(),
            path_mapping: EgressPathMapping::RewritePrefix {
                exposed_prefix: format!("/git/{slug}/"),
                upstream_prefix: prefix,
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: upstream.host,
            upstream_port: upstream.port,
            upstream_tls: upstream.tls,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), format!("Basic {basic}"))],
            remove_headers: vec![],
        });
    }
    Ok(egress)
}

/// Build external-service egress routes from `environment.config.egress_services`.
///
/// For each service, emits a placeholder route (on `external-egress.internal`)
/// and a transparent route (on the real host) so skills can use either URL
/// pattern. The secret is decrypted and headers are built according to the
/// `inject` config (bearer / api_key / cookie).
pub(crate) async fn build_external_egress(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    environment: Option<&EnvironmentRow>,
    project_id: Option<ProjectId>,
) -> anyhow::Result<(Vec<EgressCredentialRoute>, Vec<IdentityEgressRequestTarget>)> {
    let Some(environment) = environment else {
        return Ok((vec![], vec![]));
    };
    let decoded = decode_environment(&environment.config)?;

    let mut routes = Vec::new();
    for reference in decoded.http_egress {
        let name = reference
            .name
            .as_deref()
            .ok_or(CredentialRuntimeError::FieldMissing)?;
        let name = sanitize_external_service_name(name);
        if name.is_empty() {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }

        let upstream = UpstreamTarget::from_url(&reference.endpoint)
            .map_err(|_| CredentialRuntimeError::CorruptRecord)?;
        let host = upstream.host;
        let tls = upstream.tls;
        let port = upstream.port;
        let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);

        let credential_id = reference.credential_id;
        let credential_field = reference.credential_field.as_str();
        let credential_value = load_service_egress_field(
            credential_access,
            access_context,
            credential_id,
            project_id,
            credential_field,
        )
        .await
        .with_context(|| {
            format!("failed to load external egress service {name:?} credential {credential_id}")
        })?;
        let secret = HashMap::from([(credential_field.to_string(), credential_value)]);
        let headers = build_external_inject_headers(
            &secret,
            &reference.inject_kind,
            credential_field,
            reference.header.as_deref(),
        )?;

        let remove_headers = vec![
            "authorization".to_string(),
            "cookie".to_string(),
            "x-api-key".to_string(),
            "api-key".to_string(),
            "x-goog-api-key".to_string(),
        ];

        // Transparent route(s): sandbox calls the real host over plaintext http.
        // Envoy matches the real host vhost, injects the credential, and
        // TLS-originates to the real upstream when needed.
        let allowed_paths = reference.allowed_paths;

        if allowed_paths.is_empty() {
            routes.push(EgressCredentialRoute {
                id: format!("external-direct:{name}"),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: host.clone(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix(upstream_prefix.clone()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: host.clone(),
                upstream_port: port,
                upstream_tls: tls,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: headers.clone(),
                remove_headers: remove_headers.clone(),
            });
        } else {
            for (idx, entry) in allowed_paths.iter().enumerate() {
                let is_prefix = entry.ends_with('/');
                let full_path = join_service_path(&upstream_prefix, entry);
                routes.push(EgressCredentialRoute {
                    id: format!("external-direct:{name}:{idx}"),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Transparent,
                    match_host: host.clone(),
                    path_mapping: EgressPathMapping::Passthrough {
                        matcher: if is_prefix {
                            EgressPathMatcher::Prefix(full_path.clone())
                        } else {
                            EgressPathMatcher::Exact(full_path.clone())
                        },
                    },
                    retry_mode: EgressRetryMode::SafeIdempotent,
                    upstream_host: host.clone(),
                    upstream_port: port,
                    upstream_tls: tls,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: headers.clone(),
                    remove_headers: remove_headers.clone(),
                });
            }
        }
    }
    let mut identity_targets = Vec::new();
    let services = environment
        .config
        .get("egress_services")
        .and_then(serde_json::Value::as_array)
        .cloned()
        .unwrap_or_default();
    for service in services {
        let service = service
            .as_object()
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        let auth_source = service
            .get("auth_source")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("service_credential");
        if auth_source != "agent_identity" {
            continue;
        }
        if service
            .get("credential_ref")
            .is_some_and(|value| !value.is_null())
            || service.get("inject").is_some_and(|value| !value.is_null())
        {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }
        let name = sanitize_external_service_name(
            service
                .get("name")
                .and_then(serde_json::Value::as_str)
                .ok_or(CredentialRuntimeError::FieldMissing)?,
        );
        if name.is_empty() {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }
        let endpoint = service
            .get("base_url")
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or(CredentialRuntimeError::FieldMissing)?
            .to_string();
        let upstream = UpstreamTarget::from_url(&endpoint)
            .map_err(|_| CredentialRuntimeError::CorruptRecord)?;
        let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);
        let default_allowed_paths = vec![serde_json::Value::String("/".to_string())];
        let allowed_paths = match service.get("allowed_paths") {
            None | Some(serde_json::Value::Null) => &default_allowed_paths,
            Some(serde_json::Value::Array(paths)) if paths.is_empty() => &default_allowed_paths,
            Some(serde_json::Value::Array(paths)) => paths,
            Some(_) => return Err(CredentialRuntimeError::CorruptRecord.into()),
        };
        for (index, entry) in allowed_paths.iter().enumerate() {
            let entry = entry
                .as_str()
                .filter(|path| path.starts_with('/') && !path.contains(['?', '#']))
                .ok_or(CredentialRuntimeError::CorruptRecord)?;
            let full_path = join_service_path(&upstream_prefix, entry);
            let route_id = format!("external-identity:{name}:{index}");
            routes.push(EgressCredentialRoute {
                id: route_id.clone(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: upstream.host.clone(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: if entry.ends_with('/') {
                        EgressPathMatcher::Prefix(full_path)
                    } else {
                        EgressPathMatcher::Exact(full_path)
                    },
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: upstream.host.clone(),
                upstream_port: upstream.port,
                upstream_tls: upstream.tls,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![],
                remove_headers: vec![
                    "authorization".to_string(),
                    "cookie".to_string(),
                    "x-security-agenttoken".to_string(),
                ],
            });
            identity_targets.push(IdentityEgressRequestTarget {
                route_id,
                endpoint: endpoint.clone(),
                host: upstream.host.clone(),
                port: upstream.port,
                tls: upstream.tls,
            });
        }
    }
    Ok((routes, identity_targets))
}

async fn load_service_egress_field(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    credential_id: CredentialId,
    project_id: Option<ProjectId>,
    field: &str,
) -> anyhow::Result<String> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    credential_access
        .resolve_http_egress_field(&project_id, credential_id, field, access_context)
        .await
}

async fn merge_credential_ref_into_env(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    env: &mut HashMap<String, String>,
    credential_id: CredentialId,
    project_id: Option<ProjectId>,
    override_existing: bool,
    runtime_engine_kind: Option<&str>,
) -> anyhow::Result<Option<RuntimeCredentialBinding>> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    if let Some(engine_kind) = runtime_engine_kind {
        let resolved = credential_access
            .resolve_model(&project_id, credential_id, engine_kind, access_context)
            .await?;
        if override_existing {
            if let Some(value) = model_protocol_env_value(&resolved.protocol_id) {
                env.insert("JOYSAFETER_MODEL_PROTOCOL".to_string(), value);
            }
        }
        // ccb only routes to a non-Anthropic provider when the matching
        // CLAUDE_CODE_USE_* switch is set; the egress-repointed base URL and
        // placeholder key are otherwise ignored and the native harness falls
        // back to the Anthropic /login gate ("Not logged in"). Only the native
        // ccb harness reads CLAUDE_CODE_USE_*; other engines (codex, pi) handle
        // OpenAI-compatible providers natively and must not get the switch.
        if engine_kind == "native" {
            if let Some(switch) = model_protocol_provider_switch(&resolved.protocol_id) {
                if override_existing || !env.contains_key(switch) {
                    env.insert(switch.to_string(), "1".to_string());
                }
            }
        }
        for (key, value) in resolved.material.iter() {
            if override_existing || !env.contains_key(key) {
                env.insert(key.to_string(), value.to_string());
            }
        }
        return Ok(Some(resolved.runtime_binding()));
    }

    let resolved = credential_access
        .resolve_environment(&project_id, credential_id, access_context)
        .await?;
    let ResolvedServiceCredential::Environment(material) = resolved else {
        return Err(CredentialRuntimeError::CorruptRecord.into());
    };
    let material = material
        .as_object()
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
    for (key, value) in material {
        if override_existing || !env.contains_key(key) {
            let value = value
                .as_str()
                .ok_or(CredentialRuntimeError::CorruptRecord)?;
            env.insert(key.clone(), value.to_string());
        }
    }
    Ok(None)
}

/// Rebuild the egress credentials for a live sandbox during orchestrator startup
/// recovery. Re-derives the same LLM/MCP/git secrets that were injected at
/// creation time by decrypting the current DB rows, so a restarted orchestrator
/// (whose in-memory/gRPC xDS state was wiped) restores credential injection for
/// still-running sandboxes. Returns empty when the sandbox has no session/agent.
pub(crate) async fn rebuild_sandbox_credentials(
    pool: &PgPool,
    sandbox: &crate::db::models::JoySafeterSandbox,
    llm_egress_allowed_hosts: &[String],
) -> anyhow::Result<SandboxCredentials> {
    let mut routes = Vec::new();

    let Some(session_id) = sandbox.chat_session_id else {
        return Ok(SandboxCredentials {
            routes,
            proxy_auth_token: sandbox_runner_token(sandbox),
        });
    };
    let session = queries::get_session(pool, session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("sandbox recovery session {session_id} was not found"))?;
    let networking = sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"));
    let live_agent = match session.agent_id {
        Some(aid) => queries::get_agent(pool, aid).await?,
        None => None,
    };
    let snapshot_environment = environment_for_execution(Some(&session));
    let agent = agent_for_execution(live_agent, Some(&session))?;
    let access_context = CredentialAccessContext::runtime(
        Some(session_id),
        None,
        Some(session.runtime_config_generation),
    );
    let credential_access = CredentialMaterialAccessService::new(pool.clone());

    // Re-resolve the agent env (with decrypted secrets) exactly as at creation,
    // then extract the LLM egress from it. We discard the env itself — only the
    // extracted egress credential is needed for recovery.
    if let Some(agent_ref) = agent.as_ref() {
        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else {
            match agent_ref.environment_id {
                Some(environment_id) => {
                    load_environment_row(pool, environment_id, agent_ref.project_id).await?
                }
                None => None,
            }
        };
        let resolved_env = resolve_agent_env_from(
            &credential_access,
            &access_context,
            agent.as_ref(),
            environment.as_ref(),
        )
        .await?;
        let mut env = resolved_env.values;
        routes.extend(extract_llm_egress(
            &mut env,
            resolved_env.llm_binding.as_ref(),
            llm_egress_allowed_hosts,
        ));
        let (external_routes, _) = build_external_egress(
            &credential_access,
            &access_context,
            environment.as_ref(),
            session.project_id.or(agent_ref.project_id),
        )
        .await?;
        routes.extend(external_routes);
        remove_agent_identity_routes(&mut routes);
        let network_mode = effective_network_mode(networking, false)?;
        let mcp_plan = resolve_mcp_runtime_plan_with_access(
            &credential_access,
            &access_context,
            session.project_id.or(agent_ref.project_id),
            Some(session_id),
            agent_ref.id,
            session.runtime_config_generation,
            network_mode,
            agent_ref.mcp_servers.as_ref(),
        )
        .await?;
        routes.extend(mcp_plan.egress_routes());
    }
    match build_git_egress(pool, Some(session_id)).await {
        Ok(git) => routes.extend(git),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild Git egress credentials during sandbox recovery: {e}"
        ),
    }
    Ok(SandboxCredentials {
        routes,
        proxy_auth_token: sandbox_runner_token(sandbox),
    })
}

pub(crate) fn remove_agent_identity_routes(routes: &mut Vec<EgressCredentialRoute>) {
    routes.retain(|route| !route.id.starts_with("external-identity:"));
}

/// Standalone environment loader for recovery (mirrors `load_environment`).
async fn load_environment_row(
    pool: &PgPool,
    environment_id: EnvironmentId,
    project_id: Option<ProjectId>,
) -> anyhow::Result<Option<EnvironmentRow>> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    let environment = sqlx::query_as::<_, EnvironmentRow>(
        r#"
        SELECT config, image_tag FROM joysafeter_environments
        WHERE id = $1 AND deleted_at IS NULL AND project_id = $2
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .fetch_optional(pool)
    .await?;
    let diagnostic_project = if environment.is_none() {
        sqlx::query_as::<_, (ProjectId,)>(
            "SELECT project_id FROM joysafeter_environments WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(environment_id)
        .fetch_optional(pool)
        .await?
    } else {
        None
    };
    if environment.is_some() {
        return Ok(environment);
    }
    match diagnostic_project {
        Some((actual_project,)) if actual_project != project_id => {
            Err(CredentialRuntimeError::ProjectMismatch.into())
        }
        Some(_) => Err(CredentialRuntimeError::CorruptRecord.into()),
        None => Err(CredentialRuntimeError::NotFound.into()),
    }
}

pub(crate) fn sandbox_runner_token(sandbox: &JoySafeterSandbox) -> Option<String> {
    sandbox
        .config
        .as_ref()?
        .get("runner_token")?
        .as_str()
        .filter(|token| !token.trim().is_empty())
        .map(ToOwned::to_owned)
}

fn normalize_llm_upstream_prefix(path: &str) -> String {
    if path.is_empty() || path == "/" {
        return "/".to_string();
    }

    let mut prefix = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

fn is_llm_egress_host_allowed(host: &str, allowed_hosts: &[String]) -> bool {
    let Some(host) = normalize_llm_host(host) else {
        return false;
    };

    if is_blocked_llm_host(&host) {
        return false;
    }

    allowed_hosts
        .iter()
        .filter_map(|entry| normalize_llm_host_pattern(entry))
        .any(|pattern| llm_host_matches_pattern(&host, &pattern))
}

fn normalize_llm_host(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, false)
}

fn normalize_llm_host_pattern(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, true)
}

fn normalize_llm_host_inner(raw: &str, allow_wildcard: bool) -> Option<String> {
    let mut value = raw.trim().to_ascii_lowercase();
    if value.is_empty() {
        return None;
    }

    if value.contains("://") {
        value = Url::parse(&value).ok()?.host_str()?.to_string();
    } else {
        if let Some((before_path, _)) = value.split_once('/') {
            value = before_path.to_string();
        }
        if value.starts_with('[') {
            let end = value.find(']')?;
            value = value[1..end].to_string();
        } else if let Some((host, port)) = value.rsplit_once(':') {
            if !host.contains(':') && port.parse::<u16>().is_ok() {
                value = host.to_string();
            }
        }
    }

    value = value.trim_matches('.').to_string();
    if value.is_empty() {
        return None;
    }

    if value.starts_with("*.") {
        if !allow_wildcard {
            return None;
        }
        let suffix = value.trim_start_matches("*.");
        if suffix.is_empty() || suffix.contains('*') {
            return None;
        }
        return Some(format!("*.{suffix}"));
    }

    if value.contains('*') {
        return None;
    }

    Some(value)
}

fn llm_host_matches_pattern(host: &str, pattern: &str) -> bool {
    if let Some(suffix) = pattern.strip_prefix("*.") {
        return host != suffix && host.ends_with(&format!(".{suffix}"));
    }

    host == pattern
}

fn is_blocked_llm_host(host: &str) -> bool {
    if host == "localhost" || host.ends_with(".localhost") {
        return true;
    }

    host.parse::<IpAddr>()
        .map(is_blocked_llm_ip)
        .unwrap_or(false)
}

fn is_blocked_llm_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let octets = ip.octets();
            octets[0] == 0
                || octets[0] == 10
                || octets[0] == 127
                || (octets[0] == 100 && (64..=127).contains(&octets[1]))
                || (octets[0] == 169 && octets[1] == 254)
                || (octets[0] == 172 && (16..=31).contains(&octets[1]))
                || (octets[0] == 192 && octets[1] == 168)
                || (octets[0] == 198 && (18..=19).contains(&octets[1]))
                || octets[0] >= 224
        }
        IpAddr::V6(ip) => {
            let segments = ip.segments();
            let first = segments[0];
            ip.is_loopback()
                || ip.is_unspecified()
                || (first & 0xfe00) == 0xfc00
                || (first & 0xffc0) == 0xfe80
                || (first & 0xff00) == 0xff00
        }
    }
}

#[derive(Debug, sqlx::FromRow)]
pub(crate) struct EnvironmentRow {
    pub(crate) config: serde_json::Value,
    pub(crate) image_tag: Option<String>,
}

#[derive(Debug, Default)]
pub(crate) struct ResolvedAgentEnv {
    pub(crate) values: HashMap<String, String>,
    pub(crate) llm_binding: Option<RuntimeCredentialBinding>,
}

fn sanitize_external_service_name(name: &str) -> String {
    name.trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn normalize_external_upstream_prefix(path: &str) -> String {
    let mut prefix = if path.is_empty() {
        "/".to_string()
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if prefix != "/" && !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

/// Join a service base prefix with an allowlist entry into a full host path.
fn join_service_path(base_prefix: &str, entry: &str) -> String {
    if entry.starts_with('/') {
        return entry.to_string();
    }
    let base = base_prefix.strip_suffix('/').unwrap_or(base_prefix);
    format!("{base}/{entry}")
}

fn build_external_inject_headers(
    secret: &HashMap<String, String>,
    inject_kind: &str,
    credential_field: &str,
    header: Option<&str>,
) -> Result<Vec<(String, String)>, CredentialRuntimeError> {
    match inject_kind {
        "bearer" => {
            let token = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?;
            let header = header.unwrap_or("authorization");
            Ok(vec![(header.to_string(), format!("Bearer {token}"))])
        }
        "api_key" | "raw_header" => {
            let value = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?;
            let header = header.unwrap_or("x-api-key");
            Ok(vec![(header.to_string(), value.clone())])
        }
        "cookie" => {
            let cookie_header = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?
                .clone();
            Ok(vec![("cookie".to_string(), cookie_header)])
        }
        _ => Err(CredentialRuntimeError::UnsupportedScheme),
    }
}
