use sqlx::PgPool;

use crate::ids::{FileId, ProjectId, SessionId};

pub async fn insert_artifact_file(
    pool: &PgPool,
    id: FileId,
    project_id: ProjectId,
    session_id: Option<SessionId>,
    filename: &str,
    content_type: &str,
    size_bytes: i64,
    sha256: &str,
    storage_key: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_files (
            id, project_id, filename, purpose, content_type, size_bytes,
            sha256, storage_key, downloadable, session_id, created_at, updated_at
        )
        VALUES ($1, $2, $3, 'artifact_archive', $4, $5, $6, $7, TRUE, $8, NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
        "#,
    )
    .bind(id)
    .bind(project_id)
    .bind(filename)
    .bind(content_type)
    .bind(size_bytes)
    .bind(sha256)
    .bind(storage_key)
    .bind(session_id)
    .execute(pool)
    .await?;
    Ok(())
}
