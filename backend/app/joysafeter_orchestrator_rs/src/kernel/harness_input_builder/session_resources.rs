use sqlx::{FromRow, PgPool};

use crate::db::queries;
use crate::ids::SessionId;
use crate::kernel::harness_contract::{
    HarnessFileMount, HarnessInput, HarnessMemoryFile, HarnessMemoryStoreMount, HarnessRepository,
};
use crate::kernel::repository_access::material::RepositoryAccessMaterial;

pub(super) async fn load_memory_stores(
    pool: &PgPool,
    session_id: SessionId,
    input: &mut HarnessInput,
) -> anyhow::Result<()> {
    let stores = queries::list_session_memory_stores(pool, session_id)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load memory stores for session {session_id}: {e}")
        })?;

    let mut prompt_parts = vec![
        "# Memory".to_string(),
        "The following memory stores are mounted. Use them to persist and retrieve information across sessions.".to_string(),
        String::new(),
    ];

    for store in stores {
        let mount_path = format!("/mnt/memory/{}", store.mount_name);
        let mut files = vec![];
        let rows = queries::load_memory_files(pool, store.store_id, 10000)
            .await
            .map_err(|e| {
                anyhow::anyhow!(
                    "failed to load memory files for store {} mounted on session {}: {e}",
                    store.store_id,
                    session_id
                )
            })?;
        for row in rows {
            files.push(HarnessMemoryFile {
                relative_path: row.path,
                content: row.content.unwrap_or_default().into_bytes(),
            });
        }

        input.memory_mounts.push(HarnessMemoryStoreMount {
            mount_name: store.mount_name.clone(),
            mount_path: mount_path.clone(),
            access: store.access.clone(),
            files,
        });

        prompt_parts.push(format!("- `{}` (access: {})", mount_path, store.access));
        if let Some(instructions) = store.instructions.as_deref().filter(|v| !v.is_empty()) {
            prompt_parts.push(format!("  Instructions: {instructions}"));
        }
    }

    if input.memory_mounts.is_empty() {
        return Ok(());
    }
    input.memory_system_prompt = Some(prompt_parts.join("\n"));
    Ok(())
}

pub(super) async fn load_session_files(
    pool: &PgPool,
    session_id: SessionId,
    input: &mut HarnessInput,
) -> anyhow::Result<()> {
    let rows: Vec<SessionFileRow> = sqlx::query_as(
        r#"
        SELECT sf.mount_path, f.filename, f.storage_key, f.size_bytes
        FROM joysafeter_session_files sf
        JOIN joysafeter_files f ON f.id = sf.file_id
        WHERE sf.session_id = $1 AND f.deleted_at IS NULL
        ORDER BY sf.mount_path
        "#,
    )
    .bind(session_id)
    .fetch_all(pool)
    .await
    .map_err(|e| {
        anyhow::anyhow!("failed to load session file rows for session {session_id}: {e}")
    })?;

    for row in rows {
        let content = load_session_file_resource(&row).await.map_err(|e| {
            anyhow::anyhow!(
                "failed to prepare session file '{}' from storage key '{}': {e}",
                row.filename,
                row.storage_key
            )
        })?;
        input.files.push(HarnessFileMount {
            path: row.mount_path,
            content,
            filename: row.filename,
        });
    }
    Ok(())
}

/// Load session-scoped GitHub repository resources and validate their clone
/// material through the Repository Access adapter. Repos live on the session
/// (``joysafeter_session_repos``), not on ``agent.metadata``; the token is
/// and never expose clone material to the runner.
pub(super) async fn load_session_repos(
    pool: &PgPool,
    material: &dyn RepositoryAccessMaterial,
    session_id: SessionId,
    input: &mut HarnessInput,
) -> anyhow::Result<()> {
    let rows: Vec<SessionRepoRow> = sqlx::query_as(
        r#"
        SELECT url, branch, mount_path, mount_name,
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
    .map_err(|e| anyhow::anyhow!("failed to load session repos for session {session_id}: {e}"))?;

    if rows.is_empty() {
        return Ok(());
    }

    for (idx, row) in rows.into_iter().enumerate() {
        let token = material.reveal_optional(&row.encrypted_token)?;
        let has_token = token.is_some();
        // Validate the token through the adapter, but
        // never hand it to the sandbox. When a token exists, the clone URL is
        // rewritten to the Envoy egress boundary; Envoy injects the real
        // credential. Public repos (no token) keep their original URL.
        let url = if has_token {
            // Repoint the clone URL at the placeholder egress host + a stable
            // per-repo slug over plaintext http:// — the sandbox never learns
            // the real git host. Envoy matches `/git/<slug>/`, injects the
            // credential, and rewrites host+path to the real remote.
            let slug =
                crate::kernel::network_policy::envoy_model::git_repo_slug(&row.mount_name, idx);
            format!(
                "http://{}/git/{}/",
                crate::kernel::network_policy::envoy_model::GIT_EGRESS_HOST,
                slug
            )
        } else {
            row.url
        };
        input.repos.push(HarnessRepository {
            url,
            branch: row.branch,
            path: row.mount_path,
            mount_name: row.mount_name,
        });
    }
    Ok(())
}

// Storage read is now handled by `sandbox::storage::read_file()`.

async fn load_session_file_resource(row: &SessionFileRow) -> anyhow::Result<Vec<u8>> {
    crate::sandbox::storage::read_file(&row.storage_key).await
}

#[derive(Debug, FromRow)]
struct SessionFileRow {
    mount_path: String,
    filename: String,
    storage_key: String,
    size_bytes: i64,
}

#[derive(Debug, FromRow)]
struct SessionRepoRow {
    url: String,
    branch: String,
    mount_path: String,
    mount_name: String,
    encrypted_token: String,
}
