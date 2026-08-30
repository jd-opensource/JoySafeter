use base64::Engine as _;
use sqlx::PgPool;

use crate::ids::SessionId;
use crate::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressRetryMode,
    UpstreamTarget, GIT_EGRESS_HOST,
};
use crate::kernel::repository_access::material::RepositoryAccessMaterial;

/// Build git egress credentials: decrypt each session repo's clone token and
/// produce an [`EgressCredentialRoute`] keyed by a stable slug ([`git_repo_slug`]). The
/// sandbox clones from `git-egress.internal/git/<slug>/` (no token); Envoy
/// rewrites to the real host + repo path, injects HTTP Basic auth, and
/// forwards over the upstream scheme. The real token never enters the sandbox.
pub(crate) async fn build_git_egress(
    pool: &PgPool,
    material: &dyn RepositoryAccessMaterial,
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

    let mut egress = Vec::new();
    for (idx, (url, mount_name, encrypted_token)) in rows.into_iter().enumerate() {
        let Some(token) = material.reveal_optional(&encrypted_token)? else {
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
