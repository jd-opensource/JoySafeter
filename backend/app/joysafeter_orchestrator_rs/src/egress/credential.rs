use std::collections::HashMap;

use base64::Engine as _;
use sqlx::PgPool;
use tracing::warn;
use uuid::Uuid;

use crate::db::models::JoySafeterAgent;
use crate::db::queries;
use crate::egress::policy::{
    git_repo_slug, normalize_prefix, EgressCredentialRoute, EgressExposure, EgressKind,
    UpstreamTarget, GIT_EGRESS_HOST, MCP_EGRESS_HOST,
};
use crate::kernel::harness_input_builder::VaultCipher;

/// Build MCP egress credentials for a sandbox: for each remote MCP server the
/// agent references, match a vault credential by URL, decrypt its token, and
/// produce a credential route keyed by the server name.
pub(crate) async fn build_mcp_egress(
    pool: &PgPool,
    session_id: Option<Uuid>,
    agent: Option<&JoySafeterAgent>,
) -> anyhow::Result<Vec<EgressCredentialRoute>> {
    let Some(agent) = agent else {
        return Ok(vec![]);
    };
    let Some(session_id) = session_id else {
        return Ok(vec![]);
    };

    let mcp_servers: Vec<(String, String)> = agent
        .mcp_configs
        .as_ref()
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    let name = item.get("name").and_then(|v| v.as_str())?;
                    let url = item.get("url").and_then(|v| v.as_str())?;
                    if url.is_empty() {
                        None
                    } else {
                        Some((name.to_string(), url.to_string()))
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    if mcp_servers.is_empty() {
        return Ok(vec![]);
    }

    let session = match queries::get_session(pool, session_id).await {
        Ok(Some(s)) => s,
        Ok(None) => return Ok(vec![]),
        Err(e) => {
            return Err(anyhow::anyhow!(
                "failed to load session {session_id} while building MCP egress: {e}"
            ));
        }
    };
    let Some(vault_ids) = session.vault_ids.as_ref() else {
        return Ok(vec![]);
    };
    let ids: Vec<Uuid> = vault_ids
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .filter_map(parse_vault_ref)
                .collect()
        })
        .unwrap_or_default();
    if ids.is_empty() {
        return Ok(vec![]);
    }

    let cipher = VaultCipher::from_env();
    let mut token_by_url: HashMap<String, String> = HashMap::new();
    for vault_id in ids {
        let rows: Vec<(Option<String>, String)> = sqlx::query_as(
            r#"
            SELECT c.mcp_server_url, c.token_value
            FROM joysafeter_vault_credentials c
            JOIN joysafeter_vaults v ON v.id = c.vault_id
            WHERE c.vault_id = $1
              AND c.deleted_at IS NULL
              AND c.archived_at IS NULL
              AND v.deleted_at IS NULL
              AND v.archived_at IS NULL
            "#,
        )
        .bind(vault_id)
        .fetch_all(pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load vault credentials for vault {vault_id}: {e}")
        })?;
        for (url, token_value) in rows {
            if let Some(url) = url {
                let tok = cipher.decrypt_or_passthrough(&token_value).map_err(|e| {
                    anyhow::anyhow!(
                        "failed to decrypt vault credential for MCP server '{url}' in vault {vault_id}: {e}"
                    )
                })?;
                token_by_url.insert(url, tok);
            }
        }
    }

    let mut egress = Vec::new();
    for (name, url) in mcp_servers {
        let Some(token) = token_by_url.get(&url) else {
            continue;
        };
        let upstream = UpstreamTarget::from_url(&url)
            .map_err(|e| anyhow::anyhow!("invalid MCP server URL '{url}': {e}"))?;
        egress.push(EgressCredentialRoute {
            id: format!("mcp:{name}"),
            kind: EgressKind::Mcp,
            exposure: EgressExposure::Placeholder,
            match_host: MCP_EGRESS_HOST.to_string(),
            match_prefix: format!("/mcp/{name}/"),
            exact_path: false,
            upstream_host: upstream.host,
            upstream_port: upstream.port,
            upstream_prefix: normalize_prefix(&upstream.prefix),
            upstream_tls: upstream.tls,
            cluster_name: String::new(),
            inject_headers: vec![("authorization".to_string(), format!("Bearer {token}"))],
            remove_headers: vec![],
        });
    }
    Ok(egress)
}

/// Build Git egress credentials from session repos. The sandbox clones from a
/// placeholder host; the egress boundary rewrites to the real repo URL and
/// injects HTTP Basic auth.
pub(crate) async fn build_git_egress(
    pool: &PgPool,
    session_id: Option<Uuid>,
) -> anyhow::Result<Vec<EgressCredentialRoute>> {
    let Some(session_id) = session_id else {
        return Ok(vec![]);
    };
    let rows: Vec<(String, String, String)> = sqlx::query_as(
        r#"
        SELECT url, mount_name, encrypted_token
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

    let cipher = VaultCipher::from_env();
    let mut egress = Vec::new();
    for (idx, (url, mount_name, encrypted_token)) in rows.into_iter().enumerate() {
        if encrypted_token.is_empty() {
            continue;
        }
        let token = cipher
            .decrypt_or_passthrough(&encrypted_token)
            .map_err(|e| {
                anyhow::anyhow!(
                "failed to decrypt Git token for repo '{mount_name}' in session {session_id}: {e}"
            )
            })?;
        if token.is_empty() {
            continue;
        }
        let upstream = UpstreamTarget::from_url(&url)
            .map_err(|e| anyhow::anyhow!("invalid Git repo URL '{url}': {e}"))?;
        let mut prefix = upstream.prefix;
        if !prefix.ends_with('/') {
            prefix.push('/');
        }
        let basic =
            base64::engine::general_purpose::STANDARD.encode(format!("x-access-token:{token}"));
        let slug = git_repo_slug(&mount_name, idx);
        egress.push(EgressCredentialRoute {
            id: format!("git:{slug}"),
            kind: EgressKind::Git,
            exposure: EgressExposure::Placeholder,
            match_host: GIT_EGRESS_HOST.to_string(),
            match_prefix: format!("/git/{slug}/"),
            exact_path: false,
            upstream_host: upstream.host,
            upstream_port: upstream.port,
            upstream_prefix: prefix,
            upstream_tls: upstream.tls,
            cluster_name: String::new(),
            inject_headers: vec![("authorization".to_string(), format!("Basic {basic}"))],
            remove_headers: vec![],
        });
    }
    Ok(egress)
}

/// Build external-service egress routes from `environment.config.egress_services`.
pub(crate) async fn build_external_egress(
    pool: &PgPool,
    environment_config: Option<&serde_json::Value>,
    project_id: Option<&str>,
) -> Vec<EgressCredentialRoute> {
    let Some(services) = environment_config
        .and_then(|config| config.get("egress_services"))
        .and_then(|value| value.as_array())
    else {
        return vec![];
    };

    let mut routes = Vec::new();
    for service in services {
        let Some(name) = service.get("name").and_then(|value| value.as_str()) else {
            continue;
        };
        let name = sanitize_external_service_name(name);
        if name.is_empty() {
            continue;
        }

        let Some(base_url) = service.get("base_url").and_then(|value| value.as_str()) else {
            continue;
        };
        let Ok(upstream) = UpstreamTarget::from_url(base_url) else {
            warn!(service = %name, "Invalid external egress service base_url");
            continue;
        };
        let host = upstream.host;
        let tls = upstream.tls;
        let port = upstream.port;
        let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);

        let Some(credential_ref) = service
            .get("credential_ref")
            .and_then(|value| value.as_str())
            .filter(|value| !value.trim().is_empty())
        else {
            continue;
        };
        let Some(inject) = service.get("inject").and_then(|value| value.as_object()) else {
            continue;
        };

        let secret = match load_secret_data(pool, credential_ref, project_id).await {
            Ok(Some(secret)) => secret,
            Ok(None) => continue,
            Err(e) => {
                warn!(service = %name, credential_ref, "Failed to load external egress secret: {e}");
                continue;
            }
        };
        let headers = match build_external_inject_headers(&secret, inject) {
            Ok(headers) if !headers.is_empty() => headers,
            Ok(_) => continue,
            Err(e) => {
                warn!(service = %name, credential_ref, "Failed to build external egress headers: {e}");
                continue;
            }
        };

        let remove_headers = vec![
            "authorization".to_string(),
            "cookie".to_string(),
            "x-api-key".to_string(),
            "api-key".to_string(),
            "x-goog-api-key".to_string(),
        ];

        let allowed_paths: Vec<String> = service
            .get("allowed_paths")
            .and_then(|value| value.as_array())
            .map(|values| {
                values
                    .iter()
                    .filter_map(|value| value.as_str())
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_default();

        if allowed_paths.is_empty() {
            routes.push(EgressCredentialRoute {
                id: format!("external-direct:{name}"),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: host.clone(),
                match_prefix: upstream_prefix.clone(),
                exact_path: false,
                upstream_host: host.clone(),
                upstream_port: port,
                upstream_prefix: upstream_prefix.clone(),
                upstream_tls: tls,
                cluster_name: String::new(),
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
                    match_prefix: full_path.clone(),
                    exact_path: !is_prefix,
                    upstream_host: host.clone(),
                    upstream_port: port,
                    upstream_prefix: full_path,
                    upstream_tls: tls,
                    cluster_name: String::new(),
                    inject_headers: headers.clone(),
                    remove_headers: remove_headers.clone(),
                });
            }
        }
    }
    routes
}

async fn load_secret_data(
    pool: &PgPool,
    secret_ref: &str,
    project_id: Option<&str>,
) -> anyhow::Result<Option<HashMap<String, String>>> {
    let secret: Option<(serde_json::Value,)> = sqlx::query_as(
        r#"
        SELECT data FROM joysafeter_secrets
        WHERE name = $1 AND deleted_at IS NULL
          AND ($2::text IS NULL OR project_id = $2)
        ORDER BY created_at DESC
        LIMIT 1
        "#,
    )
    .bind(secret_ref)
    .bind(project_id)
    .fetch_optional(pool)
    .await?;

    let Some((data,)) = secret else {
        return Ok(None);
    };

    let cipher = VaultCipher::from_env();
    let mut out = HashMap::new();
    if let Some(obj) = data.as_object() {
        for (key, value) in obj {
            let value = value
                .as_str()
                .map(ToOwned::to_owned)
                .unwrap_or_else(|| value.to_string());
            out.insert(key.clone(), cipher.decrypt_or_passthrough(&value)?);
        }
    }
    Ok(Some(out))
}

fn parse_vault_ref(raw: &str) -> Option<Uuid> {
    raw.strip_prefix("vault_")
        .or_else(|| raw.strip_prefix("vlt_"))
        .unwrap_or(raw)
        .parse()
        .ok()
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
    inject: &serde_json::Map<String, serde_json::Value>,
) -> anyhow::Result<Vec<(String, String)>> {
    let typ = inject
        .get("type")
        .and_then(|value| value.as_str())
        .unwrap_or("bearer");
    match typ {
        "bearer" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("ACCESS_TOKEN");
            let token = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?;
            let header = inject
                .get("header")
                .and_then(|value| value.as_str())
                .unwrap_or("authorization");
            Ok(vec![(header.to_string(), format!("Bearer {token}"))])
        }
        "api_key" | "raw_header" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("API_KEY");
            let value = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?;
            let header = inject
                .get("header")
                .and_then(|value| value.as_str())
                .unwrap_or("x-api-key");
            Ok(vec![(header.to_string(), value.clone())])
        }
        "cookie" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("COOKIE_HEADER");
            let cookie_header = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?
                .clone();
            Ok(vec![("cookie".to_string(), cookie_header)])
        }
        other => anyhow::bail!("unsupported external egress inject type {other}"),
    }
}
