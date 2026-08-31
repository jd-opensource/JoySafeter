use sha2::{Digest, Sha256};
use sqlx::PgPool;
use tracing::{debug, info};

use crate::db::queries;
use crate::grpc::proto::SandboxFileResponse;
use crate::ids::{FileId, SessionId, TaskId};

pub(crate) const ARTIFACT_DIR: &str = "/workspace/artifacts";
pub(crate) const MAX_ARTIFACT_ARCHIVE_BYTES: usize = 100 * 1024 * 1024;

pub async fn persist_task_artifacts(
    pool: &PgPool,
    task_id: TaskId,
    session_id: Option<SessionId>,
    response: SandboxFileResponse,
) -> anyhow::Result<Option<FileId>> {
    let Some(task) = queries::get_task(pool, task_id).await? else {
        return Ok(None);
    };
    let Some(project_id) = task.project_id else {
        return Ok(None);
    };

    if !response.ok {
        if matches!(response.code.as_str(), "NOT_FOUND" | "ARCHIVE_EMPTY") {
            debug!(task_id = %task_id, code = %response.code, "No task artifacts found to archive");
            return Ok(None);
        }
        anyhow::bail!("failed to archive task artifacts: {}", response.error);
    }

    let data = response.content_bytes;
    if data.is_empty() {
        debug!(task_id = %task_id, "No task artifacts found to archive");
        return Ok(None);
    }
    if data.len() > MAX_ARTIFACT_ARCHIVE_BYTES {
        anyhow::bail!("artifact archive exceeds maximum size");
    }

    let file_id = FileId::from_uuid(uuid::Uuid::now_v7());
    let raw_file_id = file_id.as_uuid();
    let filename = format!("artifacts-{task_id}.zip");
    let storage_key = format!(
        "files/{project_id}/artifacts/{}/{raw_file_id}_{filename}",
        &raw_file_id.to_string()[..2]
    );
    crate::sandbox::storage::write_file(&storage_key, &data, "application/zip").await?;

    let sha = format!("{:x}", Sha256::digest(&data));
    queries::insert_artifact_file(
        pool,
        file_id,
        project_id,
        session_id,
        &filename,
        "application/zip",
        data.len() as i64,
        &sha,
        &storage_key,
    )
    .await?;

    info!(task_id = %task_id, file_id = %file_id, bytes = data.len(), "Archived task artifacts");
    Ok(Some(file_id))
}
