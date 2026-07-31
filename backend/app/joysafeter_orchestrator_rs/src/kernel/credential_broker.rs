//! The `CredentialBroker` — the single point in the system that turns a
//! non-secret [`CredentialRef`] into the actual injected header value.
//!
//! This is the ONLY place a provider/MCP/Git/external secret is decrypted at
//! request time. It lives in the orchestrator (it has DB + [`VaultCipher`]);
//! the data planes never decrypt — they call the resolution service (SP-3
//! Tasks 4/5), which calls this broker. Resolved values are held only
//! transiently in a short-TTL in-memory cache, keyed by `(sandbox_id,
//! route_id)` and evicted on sandbox teardown.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use base64::Engine as _;
use sqlx::PgPool;
use uuid::Uuid;

use crate::egress::policy::{CredentialRef, EgressCredentialRoute, InjectScheme};
use crate::kernel::harness_input_builder::VaultCipher;

/// Default lifetime of a cached resolved header. Short enough to bound staleness
/// after a credential rotation, long enough to absorb a burst of requests from
/// one sandbox without re-decrypting on every call.
const DEFAULT_CACHE_TTL: Duration = Duration::from_secs(60);

/// A resolved credential ready to inject: the (non-secret) header name plus the
/// fully formatted header value. The value is sensitive — `Debug` is redacted so
/// it can never leak through a log line or error chain.
#[derive(Clone)]
pub struct ResolvedHeader {
    pub name: String,
    pub value: String,
}

impl std::fmt::Debug for ResolvedHeader {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ResolvedHeader")
            .field("name", &self.name)
            .field("value", &"<redacted>")
            .finish()
    }
}

struct CacheEntry {
    header: ResolvedHeader,
    expires_at: Instant,
}

/// Resolves credential references to injectable headers. Backed by the DB +
/// [`VaultCipher`], fronted by a short-TTL per-route cache.
pub struct CredentialBroker {
    pool: PgPool,
    ttl: Duration,
    cache: Mutex<HashMap<(Uuid, String), CacheEntry>>,
}

impl CredentialBroker {
    pub fn new(pool: PgPool) -> Self {
        Self::with_ttl(pool, DEFAULT_CACHE_TTL)
    }

    pub fn with_ttl(pool: PgPool, ttl: Duration) -> Self {
        Self {
            pool,
            ttl,
            cache: Mutex::new(HashMap::new()),
        }
    }

    /// Resolve a route's credential into its injectable header, using and
    /// populating the `(sandbox_id, route_id)` cache. Returns
    /// `CREDENTIAL_RESOLVE_FAILED`-worthy errors when the secret cannot be
    /// found or decrypted; callers map this to a structured deny.
    pub async fn resolve(
        &self,
        sandbox_id: Uuid,
        route: &EgressCredentialRoute,
    ) -> anyhow::Result<ResolvedHeader> {
        let cache_key = (sandbox_id, route.id.clone());
        if let Some(header) = self.cache_get(&cache_key) {
            return Ok(header);
        }

        let secret = self.resolve_secret(&route.credential_ref).await?;
        let header = ResolvedHeader {
            name: route.inject_header.clone(),
            value: format_header_value(&route.inject_scheme, &secret),
        };

        self.cache_put(cache_key, header.clone());
        Ok(header)
    }

    /// Drop all cached resolutions for a sandbox. Called on teardown so a
    /// destroyed sandbox leaves no secret material resident. Wired into the
    /// teardown path in SP-3 Task 6; remove this allow then.
    #[allow(dead_code)]
    pub fn evict(&self, sandbox_id: Uuid) {
        let mut cache = self.cache.lock().expect("credential cache poisoned");
        cache.retain(|(sid, _), _| *sid != sandbox_id);
    }

    fn cache_get(&self, key: &(Uuid, String)) -> Option<ResolvedHeader> {
        let mut cache = self.cache.lock().expect("credential cache poisoned");
        match cache.get(key) {
            Some(entry) if entry.expires_at > Instant::now() => Some(entry.header.clone()),
            Some(_) => {
                cache.remove(key);
                None
            }
            None => None,
        }
    }

    fn cache_put(&self, key: (Uuid, String), header: ResolvedHeader) {
        let mut cache = self.cache.lock().expect("credential cache poisoned");
        cache.insert(
            key,
            CacheEntry {
                header,
                expires_at: Instant::now() + self.ttl,
            },
        );
    }

    /// Resolve a credential reference to the raw (decrypted) secret string.
    async fn resolve_secret(&self, cred_ref: &CredentialRef) -> anyhow::Result<String> {
        let cipher = VaultCipher::from_env();
        match cred_ref {
            CredentialRef::Llm {
                secret_name,
                secret_key,
                project_id,
            }
            | CredentialRef::External {
                secret_name,
                secret_key,
                project_id,
            } => {
                self.resolve_secret_field(&cipher, secret_name, secret_key, project_id.as_deref())
                    .await
            }
            CredentialRef::Mcp {
                vault_id,
                mcp_server_url,
            } => self.resolve_mcp(&cipher, *vault_id, mcp_server_url).await,
            CredentialRef::Git {
                session_id,
                mount_name,
            } => self.resolve_git(&cipher, *session_id, mount_name).await,
        }
    }

    /// Decrypt `joysafeter_secrets.data[secret_key]` for a managed Secret.
    /// Backs both LLM and External refs (identical storage).
    async fn resolve_secret_field(
        &self,
        cipher: &VaultCipher,
        secret_name: &str,
        secret_key: &str,
        project_id: Option<&str>,
    ) -> anyhow::Result<String> {
        let row: Option<(serde_json::Value,)> = sqlx::query_as(
            r#"
            SELECT data FROM joysafeter_secrets
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(secret_name)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await?;

        let Some((data,)) = row else {
            anyhow::bail!("managed secret '{secret_name}' not found");
        };
        let raw = data
            .get(secret_key)
            .and_then(|value| {
                value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .or_else(|| Some(value.to_string()))
            })
            .ok_or_else(|| anyhow::anyhow!("secret '{secret_name}' has no key '{secret_key}'"))?;
        cipher.decrypt_or_passthrough(&raw)
    }

    /// Decrypt the MCP token from a session vault credential matched by URL.
    async fn resolve_mcp(
        &self,
        cipher: &VaultCipher,
        vault_id: Uuid,
        mcp_server_url: &str,
    ) -> anyhow::Result<String> {
        let row: Option<(String,)> = sqlx::query_as(
            r#"
            SELECT c.token_value
            FROM joysafeter_vault_credentials c
            JOIN joysafeter_vaults v ON v.id = c.vault_id
            WHERE c.vault_id = $1
              AND c.mcp_server_url = $2
              AND c.deleted_at IS NULL
              AND c.archived_at IS NULL
              AND v.deleted_at IS NULL
              AND v.archived_at IS NULL
            LIMIT 1
            "#,
        )
        .bind(vault_id)
        .bind(mcp_server_url)
        .fetch_optional(&self.pool)
        .await?;

        let Some((token_value,)) = row else {
            anyhow::bail!(
                "no vault credential for MCP server '{mcp_server_url}' in vault {vault_id}"
            );
        };
        cipher.decrypt_or_passthrough(&token_value)
    }

    /// Decrypt the Git token from a session repo matched by mount name.
    async fn resolve_git(
        &self,
        cipher: &VaultCipher,
        session_id: Uuid,
        mount_name: &str,
    ) -> anyhow::Result<String> {
        let row: Option<(String,)> = sqlx::query_as(
            r#"
            SELECT encrypted_token
            FROM joysafeter_session_repos
            WHERE session_id = $1 AND mount_name = $2
            ORDER BY created_at
            LIMIT 1
            "#,
        )
        .bind(session_id)
        .bind(mount_name)
        .fetch_optional(&self.pool)
        .await?;

        let Some((encrypted_token,)) = row else {
            anyhow::bail!("no session repo '{mount_name}' for session {session_id}");
        };
        cipher.decrypt_or_passthrough(&encrypted_token)
    }
}

/// Format a resolved secret into a header value per the injection scheme.
/// Mirrors the historical inline formatting so the byte-identical header is
/// reconstructed from `(ref, scheme)`.
pub(crate) fn format_header_value(scheme: &InjectScheme, secret: &str) -> String {
    match scheme {
        InjectScheme::Bearer => format!("Bearer {secret}"),
        InjectScheme::Basic { username } => {
            let encoded =
                base64::engine::general_purpose::STANDARD.encode(format!("{username}:{secret}"));
            format!("Basic {encoded}")
        }
        InjectScheme::Raw => secret.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::egress::policy::{EgressExposure, EgressKind};
    use sqlx::postgres::PgPoolOptions;

    #[test]
    fn format_header_value_matches_historical_formatting() {
        assert_eq!(
            format_header_value(&InjectScheme::Bearer, "sk-abc"),
            "Bearer sk-abc"
        );
        assert_eq!(
            format_header_value(&InjectScheme::Raw, "AIza-raw"),
            "AIza-raw"
        );
        // Basic mirrors git: base64("x-access-token:<token>").
        let basic = format_header_value(
            &InjectScheme::Basic {
                username: "x-access-token".to_string(),
            },
            "ghp_tok",
        );
        let expected = format!(
            "Basic {}",
            base64::engine::general_purpose::STANDARD.encode("x-access-token:ghp_tok")
        );
        assert_eq!(basic, expected);
    }

    #[test]
    fn resolved_header_debug_redacts_value() {
        let header = ResolvedHeader {
            name: "authorization".to_string(),
            value: "Bearer super-secret".to_string(),
        };
        let rendered = format!("{header:?}");
        assert!(rendered.contains("authorization"));
        assert!(rendered.contains("<redacted>"));
        assert!(!rendered.contains("super-secret"));
    }

    fn external_route(secret_name: &str, secret_key: &str) -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: "external:svc".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "svc.example.com".to_string(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host: "svc.example.com".to_string(),
            upstream_port: 443,
            upstream_prefix: "/".to_string(),
            upstream_tls: true,
            cluster_name: String::new(),
            credential_ref: CredentialRef::External {
                secret_name: secret_name.to_string(),
                secret_key: secret_key.to_string(),
                project_id: None,
            },
            inject_header: "x-api-key".to_string(),
            inject_scheme: InjectScheme::Raw,
            remove_headers: vec![],
        }
    }

    async fn test_pool() -> Option<PgPool> {
        let Ok(url) = std::env::var("DATABASE_URL") else {
            eprintln!("skipping credential broker DB test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(2)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    #[tokio::test]
    async fn broker_resolves_external_secret_caches_and_evicts() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = Uuid::now_v7();
        let secret_name = format!("broker-test-secret-{sandbox_id}");
        // Store a plaintext value (no enc: prefix) so decrypt_or_passthrough
        // returns it verbatim regardless of the vault key.
        sqlx::query(
            r#"INSERT INTO joysafeter_secrets (id, name, data)
               VALUES ($1, $2, $3)"#,
        )
        .bind(Uuid::now_v7())
        .bind(&secret_name)
        .bind(serde_json::json!({ "API_KEY": "plain-key-123" }))
        .execute(&pool)
        .await
        .expect("insert secret");

        let broker = CredentialBroker::new(pool.clone());
        let route = external_route(&secret_name, "API_KEY");

        let header = broker.resolve(sandbox_id, &route).await.expect("resolve");
        assert_eq!(header.name, "x-api-key");
        assert_eq!(header.value, "plain-key-123");

        // Second resolve is a cache hit for the same (sandbox_id, route_id).
        assert!(broker
            .cache
            .lock()
            .unwrap()
            .contains_key(&(sandbox_id, route.id.clone())));
        let again = broker.resolve(sandbox_id, &route).await.expect("cache hit");
        assert_eq!(again.value, "plain-key-123");

        // Eviction drops the cached material for that sandbox.
        broker.evict(sandbox_id);
        assert!(!broker
            .cache
            .lock()
            .unwrap()
            .contains_key(&(sandbox_id, route.id.clone())));

        sqlx::query("DELETE FROM joysafeter_secrets WHERE name = $1")
            .bind(&secret_name)
            .execute(&pool)
            .await
            .expect("cleanup secret");
    }

    #[tokio::test]
    async fn broker_missing_secret_fails() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let broker = CredentialBroker::new(pool);
        let route = external_route("broker-test-nonexistent-secret", "API_KEY");
        let err = broker
            .resolve(Uuid::now_v7(), &route)
            .await
            .expect_err("missing secret must fail");
        assert!(format!("{err}").contains("not found"));
    }
}
