use chrono::{DateTime, Utc};
use sqlx::{FromRow, PgConnection, PgPool};
use url::Url;

use crate::ids::{CredentialGroupId, CredentialId, SessionId};

use super::contract::canonical_auth_scheme;
use super::error::CredentialRuntimeError;
use super::material::ManagedCredentialMaterialAdapter;
use super::record::{CredentialKind, CredentialRecord, McpCredentialRecord, ProjectId};

#[derive(Clone)]
pub struct CredentialStore {
    pool: PgPool,
    material: ManagedCredentialMaterialAdapter,
}

impl CredentialStore {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            material: ManagedCredentialMaterialAdapter::from_env(),
        }
    }

    pub fn with_material_adapter(pool: PgPool, material: ManagedCredentialMaterialAdapter) -> Self {
        Self { pool, material }
    }

    pub async fn get_active(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
    ) -> Result<CredentialRecord, CredentialRuntimeError> {
        let row = sqlx::query_as::<_, CredentialRow>(
            r#"
            SELECT id, project_id, kind, provider, protocol, data, group_id,
                   mcp_server_url, normalized_mcp_server_url, credential_type,
                   archived_at, deleted_at,
                   project_id = $2 AS project_matches
            FROM joysafeter_credentials
            WHERE id = $1
            "#,
        )
        .bind(credential_id)
        .bind(project_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| CredentialRuntimeError::CorruptRecord)?
        .ok_or(CredentialRuntimeError::NotFound)?;
        self.validate_credential_row(row)
    }

    pub async fn lock_active(
        &self,
        connection: &mut PgConnection,
        project_id: &ProjectId,
        credential_id: CredentialId,
    ) -> Result<CredentialRecord, CredentialRuntimeError> {
        let row = sqlx::query_as::<_, CredentialRow>(
            r#"
            SELECT id, project_id, kind, provider, protocol, data, group_id,
                   mcp_server_url, normalized_mcp_server_url, credential_type,
                   archived_at, deleted_at,
                   project_id = $2 AS project_matches
            FROM joysafeter_credentials
            WHERE id = $1
            FOR UPDATE
            "#,
        )
        .bind(credential_id)
        .bind(project_id.as_str())
        .fetch_optional(connection)
        .await
        .map_err(|_| CredentialRuntimeError::CorruptRecord)?
        .ok_or(CredentialRuntimeError::NotFound)?;
        self.validate_credential_row(row)
    }

    pub async fn load_session_mcp_members(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> Result<Vec<McpCredentialRecord>, CredentialRuntimeError> {
        let rows = sqlx::query_as::<_, SessionMcpRow>(
            r#"
            SELECT sessions.project_id AS session_project_id,
                   sessions.archived_at AS session_archived_at,
                   sessions.status AS session_status,
                   sessions.project_id = $2 AS session_project_matches,
                   associations.credential_group_id AS association_group_id,
                   groups.id AS group_id,
                   groups.project_id AS group_project_id,
                   groups.archived_at AS group_archived_at,
                   groups.deleted_at AS group_deleted_at,
                   groups.project_id = $2 AS group_project_matches,
                   credentials.id AS credential_id,
                   credentials.project_id AS credential_project_id,
                   credentials.kind AS credential_kind,
                   credentials.provider AS credential_provider,
                   credentials.protocol AS credential_protocol,
                   credentials.data AS credential_data,
                   credentials.group_id AS credential_group_id,
                   credentials.mcp_server_url AS credential_mcp_server_url,
                   credentials.normalized_mcp_server_url AS credential_normalized_mcp_server_url,
                   credentials.credential_type AS credential_type,
                   credentials.archived_at AS credential_archived_at,
                   credentials.deleted_at AS credential_deleted_at,
                   credentials.project_id = $2 AS credential_project_matches
            FROM joysafeter_sessions AS sessions
            LEFT JOIN joysafeter_session_credential_groups AS associations
              ON associations.session_id = sessions.id
            LEFT JOIN joysafeter_credential_groups AS groups
              ON groups.id = associations.credential_group_id
            LEFT JOIN joysafeter_credentials AS credentials
              ON credentials.group_id = groups.id
            WHERE sessions.id = $1
            ORDER BY associations.credential_group_id, credentials.id
            "#,
        )
        .bind(session_id)
        .bind(project_id.as_str())
        .fetch_all(&self.pool)
        .await
        .map_err(|_| CredentialRuntimeError::CorruptRecord)?;
        let first = rows.first().ok_or(CredentialRuntimeError::NotFound)?;
        validate_session_state(first)?;

        let mut members = Vec::new();
        for row in rows {
            validate_session_state(&row)?;
            let Some(association_group_id) = row.association_group_id else {
                if row.group_id.is_some() || row.credential_id.is_some() {
                    return Err(CredentialRuntimeError::CorruptRecord);
                }
                continue;
            };
            let group_id = validate_group_state(&row, association_group_id)?;
            let Some(credential_id) = row.credential_id else {
                continue;
            };
            let credential = row.into_credential_row(credential_id)?;
            members.push(self.validate_mcp_row(credential, group_id)?);
        }
        Ok(members)
    }

    fn validate_credential_row(
        &self,
        row: CredentialRow,
    ) -> Result<CredentialRecord, CredentialRuntimeError> {
        validate_resource_state(&row)?;
        let kind = CredentialKind::parse(&row.kind)?;
        validate_kind_identity(&row, kind)?;
        let auth_scheme = match kind {
            CredentialKind::Mcp => Some(canonical_scheme(row.credential_type.as_deref())?),
            _ => None,
        };
        let (server_url, normalized_server_url) = match kind {
            CredentialKind::Mcp => {
                let server_url = row
                    .mcp_server_url
                    .ok_or(CredentialRuntimeError::FieldMissing)?;
                let normalized_server_url = row
                    .normalized_mcp_server_url
                    .ok_or(CredentialRuntimeError::FieldMissing)?;
                validate_mcp_url(&server_url, &normalized_server_url)?;
                (Some(server_url), Some(normalized_server_url))
            }
            _ => (row.mcp_server_url, row.normalized_mcp_server_url),
        };
        Ok(CredentialRecord {
            id: row.id,
            project_id: ProjectId::parse(&row.project_id)?,
            kind,
            provider: row.provider,
            protocol: row.protocol,
            group_id: row.group_id,
            server_url,
            normalized_server_url,
            auth_scheme,
            material: self.material.reveal(&row.data)?,
        })
    }

    fn validate_mcp_row(
        &self,
        row: CredentialRow,
        expected_group_id: CredentialGroupId,
    ) -> Result<McpCredentialRecord, CredentialRuntimeError> {
        validate_resource_state(&row)?;
        let kind = CredentialKind::parse(&row.kind)?;
        if kind != CredentialKind::Mcp {
            return Err(CredentialRuntimeError::KindMismatch);
        }
        validate_kind_identity(&row, kind)?;
        let group_id = row.group_id.ok_or(CredentialRuntimeError::FieldMissing)?;
        if group_id != expected_group_id {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
        let server_url = row
            .mcp_server_url
            .ok_or(CredentialRuntimeError::FieldMissing)?;
        let normalized_server_url = row
            .normalized_mcp_server_url
            .ok_or(CredentialRuntimeError::FieldMissing)?;
        validate_mcp_url(&server_url, &normalized_server_url)?;
        Ok(McpCredentialRecord {
            id: row.id,
            project_id: ProjectId::parse(&row.project_id)?,
            group_id,
            server_url,
            normalized_server_url,
            auth_scheme: canonical_scheme(row.credential_type.as_deref())?,
            material: self.material.reveal(&row.data)?,
        })
    }
}

#[derive(Debug, FromRow)]
struct CredentialRow {
    id: CredentialId,
    project_id: String,
    kind: String,
    provider: Option<String>,
    protocol: Option<String>,
    data: serde_json::Value,
    group_id: Option<CredentialGroupId>,
    mcp_server_url: Option<String>,
    normalized_mcp_server_url: Option<String>,
    credential_type: Option<String>,
    archived_at: Option<DateTime<Utc>>,
    deleted_at: Option<DateTime<Utc>>,
    project_matches: bool,
}

#[derive(Debug, FromRow)]
struct SessionMcpRow {
    session_project_id: Option<String>,
    session_archived_at: Option<DateTime<Utc>>,
    session_status: String,
    session_project_matches: Option<bool>,
    association_group_id: Option<CredentialGroupId>,
    group_id: Option<CredentialGroupId>,
    group_project_id: Option<String>,
    group_archived_at: Option<DateTime<Utc>>,
    group_deleted_at: Option<DateTime<Utc>>,
    group_project_matches: Option<bool>,
    credential_id: Option<CredentialId>,
    credential_project_id: Option<String>,
    credential_kind: Option<String>,
    credential_provider: Option<String>,
    credential_protocol: Option<String>,
    credential_data: Option<serde_json::Value>,
    credential_group_id: Option<CredentialGroupId>,
    credential_mcp_server_url: Option<String>,
    credential_normalized_mcp_server_url: Option<String>,
    credential_type: Option<String>,
    credential_archived_at: Option<DateTime<Utc>>,
    credential_deleted_at: Option<DateTime<Utc>>,
    credential_project_matches: Option<bool>,
}

impl SessionMcpRow {
    fn into_credential_row(
        self,
        credential_id: CredentialId,
    ) -> Result<CredentialRow, CredentialRuntimeError> {
        Ok(CredentialRow {
            id: credential_id,
            project_id: self
                .credential_project_id
                .ok_or(CredentialRuntimeError::CorruptRecord)?,
            kind: self
                .credential_kind
                .ok_or(CredentialRuntimeError::CorruptRecord)?,
            provider: self.credential_provider,
            protocol: self.credential_protocol,
            data: self
                .credential_data
                .ok_or(CredentialRuntimeError::CorruptRecord)?,
            group_id: self.credential_group_id,
            mcp_server_url: self.credential_mcp_server_url,
            normalized_mcp_server_url: self.credential_normalized_mcp_server_url,
            credential_type: self.credential_type,
            archived_at: self.credential_archived_at,
            deleted_at: self.credential_deleted_at,
            project_matches: self
                .credential_project_matches
                .ok_or(CredentialRuntimeError::ProjectMismatch)?,
        })
    }
}

fn validate_resource_state(row: &CredentialRow) -> Result<(), CredentialRuntimeError> {
    if row.deleted_at.is_some() {
        return Err(CredentialRuntimeError::NotFound);
    }
    if !row.project_matches {
        return Err(CredentialRuntimeError::ProjectMismatch);
    }
    if row.archived_at.is_some() {
        return Err(CredentialRuntimeError::Archived);
    }
    Ok(())
}

fn validate_session_state(row: &SessionMcpRow) -> Result<(), CredentialRuntimeError> {
    if row.session_project_id.as_deref().is_none_or(str::is_empty)
        || row.session_project_matches != Some(true)
    {
        return Err(CredentialRuntimeError::ProjectMismatch);
    }
    if row.session_archived_at.is_some() || row.session_status == "terminated" {
        return Err(CredentialRuntimeError::Archived);
    }
    match row.session_status.as_str() {
        "idle" | "running" | "rescheduling" => Ok(()),
        _ => Err(CredentialRuntimeError::CorruptRecord),
    }
}

fn validate_group_state(
    row: &SessionMcpRow,
    association_group_id: CredentialGroupId,
) -> Result<CredentialGroupId, CredentialRuntimeError> {
    let group_id = row.group_id.ok_or(CredentialRuntimeError::CorruptRecord)?;
    if group_id != association_group_id {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    if row.group_project_id.as_deref().is_none_or(str::is_empty)
        || row.group_project_matches != Some(true)
    {
        return Err(CredentialRuntimeError::ProjectMismatch);
    }
    if row.group_deleted_at.is_some() {
        return Err(CredentialRuntimeError::NotFound);
    }
    if row.group_archived_at.is_some() {
        return Err(CredentialRuntimeError::Archived);
    }
    Ok(group_id)
}

fn validate_kind_identity(
    row: &CredentialRow,
    kind: CredentialKind,
) -> Result<(), CredentialRuntimeError> {
    match kind {
        CredentialKind::Model => {
            if row.provider.as_deref().is_none_or(str::is_empty)
                || row.protocol.as_deref().is_none_or(str::is_empty)
                || row.group_id.is_some()
                || row.mcp_server_url.is_some()
                || row.normalized_mcp_server_url.is_some()
                || row.credential_type.is_some()
            {
                return Err(CredentialRuntimeError::CorruptRecord);
            }
        }
        CredentialKind::Service => {
            if row.provider.is_some()
                || row.protocol.is_some()
                || row.group_id.is_some()
                || row.mcp_server_url.is_some()
                || row.normalized_mcp_server_url.is_some()
                || row.credential_type.is_some()
            {
                return Err(CredentialRuntimeError::CorruptRecord);
            }
        }
        CredentialKind::Mcp => {
            if row.provider.is_some()
                || row.protocol.is_some()
                || row.group_id.is_none()
                || row.mcp_server_url.as_deref().is_none_or(str::is_empty)
                || row
                    .normalized_mcp_server_url
                    .as_deref()
                    .is_none_or(str::is_empty)
                || row.credential_type.as_deref().is_none_or(str::is_empty)
            {
                return Err(CredentialRuntimeError::CorruptRecord);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use uuid::Uuid;

    use super::{CredentialRow, CredentialStore};
    use crate::ids::{CredentialGroupId, CredentialId};
    use crate::kernel::credentials::error::CredentialRuntimeError;
    use crate::kernel::credentials::material::ManagedCredentialMaterialAdapter;

    fn store() -> CredentialStore {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("lazy test pool");
        CredentialStore::with_material_adapter(
            pool,
            ManagedCredentialMaterialAdapter::from_key([7; 32]),
        )
    }

    fn archived_row(kind: &str, group_id: Option<CredentialGroupId>) -> CredentialRow {
        CredentialRow {
            id: CredentialId::from_uuid(Uuid::now_v7()),
            project_id: "project-a".to_string(),
            kind: kind.to_string(),
            provider: None,
            protocol: None,
            data: json!({"token": "not-an-envelope"}),
            group_id,
            mcp_server_url: None,
            normalized_mcp_server_url: None,
            credential_type: None,
            archived_at: Some(Utc::now()),
            deleted_at: None,
            project_matches: true,
        }
    }

    #[tokio::test]
    async fn archived_direct_credential_fails_before_material_reveal() {
        let error = store()
            .validate_credential_row(archived_row("service", None))
            .expect_err("archived credential must fail closed");

        assert_eq!(error, CredentialRuntimeError::Archived);
    }

    #[tokio::test]
    async fn archived_mcp_member_fails_before_material_reveal() {
        let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
        let error = store()
            .validate_mcp_row(archived_row("mcp", Some(group_id)), group_id)
            .expect_err("archived MCP member must fail closed");

        assert_eq!(error, CredentialRuntimeError::Archived);
    }
}

fn canonical_scheme(raw: Option<&str>) -> Result<String, CredentialRuntimeError> {
    let raw = raw.ok_or(CredentialRuntimeError::FieldMissing)?;
    canonical_auth_scheme(raw).map(str::to_string)
}

fn validate_mcp_url(
    server_url: &str,
    persisted_normalized: &str,
) -> Result<(), CredentialRuntimeError> {
    let parsed = Url::parse(server_url).map_err(|_| CredentialRuntimeError::CorruptRecord)?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    let canonical = crate::kernel::mcp_url::normalize(server_url);
    if canonical != persisted_normalized {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    Ok(())
}
