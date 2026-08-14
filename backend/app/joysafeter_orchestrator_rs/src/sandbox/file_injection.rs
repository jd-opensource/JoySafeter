use anyhow::Context;
use sqlx::PgPool;
use std::path::{Component, Path};

use tracing::{debug, info, warn};

use crate::ids::SessionId;

/// Strategy-based file injection into sandbox containers — full Python parity.
///
/// Implements the complete chain: DB loading → strategy selection → fallback execution.

/// A file to inject into a sandbox.
#[derive(Debug, Clone)]
pub struct FileToInject {
    #[allow(dead_code)]
    pub filename: String,
    pub mount_path: String,
    pub content: Option<Vec<u8>>,
    #[allow(dead_code)]
    pub storage_key: String,
    #[allow(dead_code)]
    pub size_bytes: u64,
    #[allow(dead_code)]
    pub url: Option<String>,
}

/// Selected injection strategy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InjectionStrategy {
    PresignedUrl,
    GrpcStream,
    HostMount,
    ProviderFallback,
}

/// File injection context (matches Python FileInjectionContext).
#[derive(Debug, Clone)]
pub struct FileInjectionContext {
    pub session_id: SessionId,
    #[allow(dead_code)]
    pub external_id: String,
    pub workspace_path: Option<String>,
    pub runner_capabilities: Vec<String>,
    pub is_pool_sandbox: bool,
}

/// Load session files from DB (JOIN joysafeter_session_files + joysafeter_files).
pub async fn load_session_files(
    pool: &PgPool,
    session_id: SessionId,
) -> anyhow::Result<Vec<FileToInject>> {
    let rows: Vec<SessionFileRow> = sqlx::query_as(
        r#"
        SELECT sf.mount_path, f.filename, f.storage_key, f.size_bytes, f.content_type
        FROM joysafeter_session_files sf
        JOIN joysafeter_files f ON f.id = sf.file_id
        WHERE sf.session_id = $1 AND f.deleted_at IS NULL
        ORDER BY sf.mount_path
        "#,
    )
    .bind(session_id)
    .fetch_all(pool)
    .await?;

    let mut files = Vec::new();
    for row in rows {
        let content = super::storage::read_file(&row.storage_key)
            .await
            .with_context(|| {
                format!(
                    "failed to read session file '{}' from storage key '{}'",
                    row.filename, row.storage_key
                )
            })?;
        files.push(FileToInject {
            filename: row.filename,
            mount_path: row.mount_path,
            content: Some(content),
            storage_key: row.storage_key,
            size_bytes: row.size_bytes.unwrap_or(0) as u64,
            url: None,
        });
    }
    Ok(files)
}

#[derive(Debug, sqlx::FromRow)]
struct SessionFileRow {
    mount_path: String,
    filename: String,
    storage_key: String,
    size_bytes: Option<i64>,
    #[allow(dead_code)]
    content_type: Option<String>,
}

/// Select strategies in priority order with fallback chain.
pub fn select_strategies(
    runner_capabilities: &[String],
    has_workspace_mount: bool,
) -> Vec<InjectionStrategy> {
    let mut strategies = Vec::new();

    // 1. Presigned URL (runner must support it)
    if has_capability(runner_capabilities, "url_download") {
        strategies.push(InjectionStrategy::PresignedUrl);
    }

    // 2. gRPC stream (runner must support FileMount proto processing)
    if has_capability(runner_capabilities, "file_mount") {
        strategies.push(InjectionStrategy::GrpcStream);
    }

    // 3. Host mount (if provider supports it AND workspace dir is bind-mounted)
    if has_workspace_mount {
        strategies.push(InjectionStrategy::HostMount);
    }

    // 4. Provider fallback (docker cp / platform API)
    strategies.push(InjectionStrategy::ProviderFallback);

    strategies
}

/// Select strategies using provider capabilities (preferred over bool overload).
pub fn select_strategies_from_capabilities(
    runner_capabilities: &[String],
    capabilities: &super::provider::ProviderCapabilities,
    has_workspace_context: bool,
) -> Vec<InjectionStrategy> {
    select_strategies(
        runner_capabilities,
        capabilities.has_host_mount && has_workspace_context,
    )
}

fn has_capability(runner_capabilities: &[String], capability: &str) -> bool {
    runner_capabilities.iter().any(|item| item == capability)
}

/// Top-level injection orchestrator — loads files, selects strategy, executes with fallback.
pub async fn inject_session_files(
    pool: &PgPool,
    ctx: &FileInjectionContext,
    provider: &dyn crate::sandbox::provider::SandboxProvider,
) -> anyhow::Result<Vec<FileToInject>> {
    let files = load_session_files(pool, ctx.session_id).await?;
    if files.is_empty() {
        return Ok(vec![]);
    }

    let has_workspace = ctx.workspace_path.is_some();
    let strategies = select_strategies(&ctx.runner_capabilities, has_workspace);

    info!(
        session_id = %ctx.session_id,
        file_count = files.len(),
        strategies = ?strategies,
        "Injecting session files"
    );

    for strategy in &strategies {
        match strategy {
            InjectionStrategy::HostMount => {
                if let Some(ref workspace) = ctx.workspace_path {
                    if ctx.is_pool_sandbox {
                        continue;
                    }
                    let mut injected = 0;
                    for file in &files {
                        if let Some(ref content) = file.content {
                            // Read file content from storage and write to host filesystem
                            let Some(target_path) =
                                resolve_workspace_path(workspace, &file.mount_path)
                            else {
                                anyhow::bail!(
                                    "invalid session file mount path '{}': path escapes workspace",
                                    file.mount_path
                                );
                            };
                            // Create parent directories
                            if let Some(parent) = target_path.parent() {
                                tokio::fs::create_dir_all(parent).await.with_context(|| {
                                    format!(
                                        "failed to create parent directory for session file '{}'",
                                        file.mount_path
                                    )
                                })?;
                            }
                            tokio::fs::write(&target_path, content).await?;
                            if let Err(e) =
                                crate::sandbox::archive::auto_extract_archive(&target_path).await
                            {
                                warn!(
                                    path = %file.mount_path,
                                    filename = %file.filename,
                                    "Failed to auto-extract host-mounted archive: {e}"
                                );
                            }
                            injected += 1;
                        }
                    }
                    if injected > 0 {
                        debug!(count = injected, "Host mount injection completed");
                        return Ok(files);
                    }
                }
            }
            InjectionStrategy::GrpcStream => {
                // Files will be sent inline via SetupSandbox/StartTask FileMount
                // The caller handles this by including files in the proto message
                return Ok(files);
            }
            InjectionStrategy::ProviderFallback => {
                let file_pairs: Vec<(String, Vec<u8>)> = files
                    .iter()
                    .filter_map(|f| {
                        f.content
                            .as_ref()
                            .map(|c| (f.mount_path.clone(), c.clone()))
                    })
                    .collect();

                if !file_pairs.is_empty() {
                    provider.inject_files(&ctx.external_id, &files).await?;
                    debug!(
                        count = file_pairs.len(),
                        "Provider fallback injection completed"
                    );
                }
                return Ok(files);
            }
            InjectionStrategy::PresignedUrl => {
                // Presigned URLs are generated and sent via FileRef in proto
                return Ok(files);
            }
        }
    }

    Ok(files)
}

/// Build gRPC FileMount proto messages for inline injection.
#[allow(dead_code)]
pub fn build_file_mounts(files: &[FileToInject]) -> Vec<crate::grpc::proto::FileMount> {
    files
        .iter()
        .filter_map(|f| {
            f.content
                .as_ref()
                .map(|content| crate::grpc::proto::FileMount {
                    path: f.mount_path.clone(),
                    content: content.clone(),
                    filename: f.filename.clone(),
                })
        })
        .collect()
}

/// Build gRPC FileRef proto messages for presigned URL injection.
#[allow(dead_code)]
pub fn build_file_refs(files: &[FileToInject]) -> Vec<crate::grpc::proto::FileRef> {
    files
        .iter()
        .filter_map(|f| {
            f.url.as_ref().map(|url| crate::grpc::proto::FileRef {
                path: f.mount_path.clone(),
                url: url.clone(),
                filename: f.filename.clone(),
                size_bytes: f.size_bytes as i64,
            })
        })
        .collect()
}

/// Validate that a path doesn't traverse outside the workspace.
#[allow(dead_code)]
pub fn validate_path(relative_path: &str, workspace_prefix: &str) -> bool {
    resolve_workspace_path(workspace_prefix, relative_path).is_some()
}

pub fn resolve_workspace_path(
    workspace_prefix: &str,
    mount_path: &str,
) -> Option<std::path::PathBuf> {
    if mount_path.contains('\0') {
        return None;
    }
    let mut normalized = mount_path.replace('\\', "/");
    normalized = normalized.trim_start_matches('/').to_string();
    if let Some(stripped) = normalized.strip_prefix("workspace/") {
        normalized = stripped.to_string();
    }

    let mut relative_parts = Vec::new();
    for component in Path::new(&normalized).components() {
        match component {
            Component::Normal(part) => relative_parts.push(part.to_os_string()),
            Component::CurDir => {}
            _ => return None,
        }
    }

    let mut path = Path::new(workspace_prefix).to_path_buf();
    for part in relative_parts {
        path.push(part);
    }
    Some(path)
}

// Storage read is now handled by `sandbox::storage::read_file()`.
