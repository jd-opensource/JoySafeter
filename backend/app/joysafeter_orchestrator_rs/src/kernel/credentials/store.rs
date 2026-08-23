use std::collections::BTreeSet;

use chrono::{DateTime, Utc};
use sqlx::{FromRow, PgConnection, PgPool};
use url::Url;

use crate::ids::{CredentialGroupId, CredentialId, SessionId};

use super::contract::canonical_auth_scheme;
use super::error::CredentialRuntimeError;
use super::material::{ManagedCredentialMaterialAdapter, MaterialFieldSelection};
use super::record::{
    CredentialKind, CredentialMetadataRecord, CredentialRecord, McpCredentialMetadataRecord,
    McpCredentialRecord, ProjectId,
};

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

    pub async fn get_active_with_field_selector<F>(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        select_fields: F,
    ) -> Result<CredentialRecord, CredentialRuntimeError>
    where
        F: FnOnce(&CredentialMetadataRecord) -> Result<BTreeSet<String>, CredentialRuntimeError>,
    {
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
        let metadata = self.validate_credential_metadata_row(&row)?;
        let fields = select_fields(&metadata)?;
        self.validate_credential_row_with_selection(row, MaterialFieldSelection::Only(&fields))
    }

    pub async fn lock_active_metadata(
        &self,
        connection: &mut PgConnection,
        project_id: &ProjectId,
        credential_id: CredentialId,
    ) -> Result<CredentialMetadataRecord, CredentialRuntimeError> {
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
        self.validate_credential_metadata_row(&row)
    }

    pub async fn load_session_mcp_members(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> Result<Vec<McpCredentialRecord>, CredentialRuntimeError> {
        self.load_session_mcp_rows(project_id, session_id)
            .await?
            .into_iter()
            .map(|(row, group_id)| self.validate_mcp_row(row, group_id))
            .collect()
    }

    pub async fn load_session_mcp_member_metadata(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> Result<Vec<McpCredentialMetadataRecord>, CredentialRuntimeError> {
        self.load_session_mcp_rows(project_id, session_id)
            .await?
            .into_iter()
            .map(|(row, group_id)| self.validate_mcp_metadata_row(&row, group_id))
            .collect()
    }

    pub(super) async fn get_active_mcp_member(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        expected_group_id: CredentialGroupId,
    ) -> Result<McpCredentialRecord, CredentialRuntimeError> {
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
        self.validate_mcp_row(row, expected_group_id)
    }

    async fn load_session_mcp_rows(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> Result<Vec<(CredentialRow, CredentialGroupId)>, CredentialRuntimeError> {
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
             AND credentials.archived_at IS NULL
             AND credentials.deleted_at IS NULL
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
            members.push((credential, group_id));
        }
        Ok(members)
    }

    fn validate_credential_row(
        &self,
        row: CredentialRow,
    ) -> Result<CredentialRecord, CredentialRuntimeError> {
        self.validate_credential_row_with_selection(row, MaterialFieldSelection::All)
    }

    fn validate_credential_row_with_selection(
        &self,
        row: CredentialRow,
        selection: MaterialFieldSelection<'_>,
    ) -> Result<CredentialRecord, CredentialRuntimeError> {
        let metadata = self.validate_credential_metadata_row(&row)?;
        Ok(CredentialRecord {
            id: metadata.id,
            project_id: metadata.project_id,
            kind: metadata.kind,
            provider: metadata.provider,
            protocol: metadata.protocol,
            group_id: metadata.group_id,
            server_url: metadata.server_url,
            normalized_server_url: metadata.normalized_server_url,
            auth_scheme: metadata.auth_scheme,
            material: self.material.reveal_fields(&row.data, selection)?,
        })
    }

    fn validate_credential_metadata_row(
        &self,
        row: &CredentialRow,
    ) -> Result<CredentialMetadataRecord, CredentialRuntimeError> {
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
                    .clone()
                    .ok_or(CredentialRuntimeError::FieldMissing)?;
                let normalized_server_url = row
                    .normalized_mcp_server_url
                    .clone()
                    .ok_or(CredentialRuntimeError::FieldMissing)?;
                validate_mcp_url(&server_url, &normalized_server_url)?;
                (Some(server_url), Some(normalized_server_url))
            }
            _ => (
                row.mcp_server_url.clone(),
                row.normalized_mcp_server_url.clone(),
            ),
        };
        let material = row
            .data
            .as_object()
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        if material.values().any(|value| !value.is_string()) {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
        Ok(CredentialMetadataRecord {
            id: row.id,
            project_id: ProjectId::parse(&row.project_id)?,
            kind,
            provider: row.provider.clone(),
            protocol: row.protocol.clone(),
            group_id: row.group_id,
            server_url,
            normalized_server_url,
            auth_scheme,
            material_fields: material.keys().cloned().collect(),
        })
    }

    fn validate_mcp_row(
        &self,
        row: CredentialRow,
        expected_group_id: CredentialGroupId,
    ) -> Result<McpCredentialRecord, CredentialRuntimeError> {
        let metadata = self.validate_mcp_metadata_row(&row, expected_group_id)?;
        let material_fields = BTreeSet::from(["token_value".to_string()]);
        Ok(McpCredentialRecord {
            id: metadata.id,
            project_id: metadata.project_id,
            group_id: metadata.group_id,
            server_url: metadata.server_url,
            normalized_server_url: metadata.normalized_server_url,
            auth_scheme: metadata.auth_scheme,
            material: self
                .material
                .reveal_fields(&row.data, MaterialFieldSelection::Only(&material_fields))?,
        })
    }

    fn validate_mcp_metadata_row(
        &self,
        row: &CredentialRow,
        expected_group_id: CredentialGroupId,
    ) -> Result<McpCredentialMetadataRecord, CredentialRuntimeError> {
        let metadata = self.validate_credential_metadata_row(row)?;
        if metadata.kind != CredentialKind::Mcp {
            return Err(CredentialRuntimeError::KindMismatch);
        }
        let group_id = metadata
            .group_id
            .ok_or(CredentialRuntimeError::FieldMissing)?;
        if group_id != expected_group_id {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
        if !metadata.material_fields.contains("token_value") {
            return Err(CredentialRuntimeError::FieldMissing);
        }
        Ok(McpCredentialMetadataRecord {
            id: metadata.id,
            project_id: metadata.project_id,
            group_id,
            server_url: metadata
                .server_url
                .ok_or(CredentialRuntimeError::FieldMissing)?,
            normalized_server_url: metadata
                .normalized_server_url
                .ok_or(CredentialRuntimeError::FieldMissing)?,
            auth_scheme: metadata
                .auth_scheme
                .ok_or(CredentialRuntimeError::FieldMissing)?,
            material_fields: metadata.material_fields,
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
    use std::collections::BTreeSet;

    use chrono::Utc;
    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use uuid::Uuid;

    use super::{CredentialRow, CredentialStore, MaterialFieldSelection};
    use crate::ids::{CredentialGroupId, CredentialId};
    use crate::kernel::credentials::error::CredentialRuntimeError;
    use crate::kernel::credentials::material::ManagedCredentialMaterialAdapter;

    const TEST_KEY: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];
    const HELLO_WORLD: &str = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";

    fn store() -> CredentialStore {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("lazy test pool");
        CredentialStore::with_material_adapter(
            pool,
            ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
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
    async fn active_metadata_validation_does_not_reveal_material() {
        let mut row = archived_row("model", None);
        row.archived_at = None;
        row.provider = Some("anthropic".to_string());
        row.protocol = Some("anthropic_messages".to_string());

        let metadata = store()
            .validate_credential_metadata_row(&row)
            .expect("metadata validation must not reveal invalid ciphertext");

        assert!(metadata.material_fields.contains("token"));
    }

    #[tokio::test]
    async fn mcp_validation_reveals_only_token_value() {
        let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
        let mut row = archived_row("mcp", Some(group_id));
        row.archived_at = None;
        row.mcp_server_url = Some("https://mcp.example.com".to_string());
        row.normalized_mcp_server_url = Some("https://mcp.example.com".to_string());
        row.credential_type = Some("static_bearer".to_string());
        row.data = json!({"token_value": HELLO_WORLD, "unrelated": "invalid-envelope"});

        let record = store()
            .validate_mcp_row(row, group_id)
            .expect("unrequested invalid ciphertext must not be decrypted");

        assert_eq!(
            record.material.require("token_value").unwrap(),
            "hello-world"
        );
        assert_eq!(
            record.material.require("unrelated"),
            Err(CredentialRuntimeError::FieldMissing)
        );
    }

    #[tokio::test]
    async fn direct_credential_validation_reveals_only_requested_fields() {
        let mut row = archived_row("service", None);
        row.archived_at = None;
        row.data = json!({"API_KEY": HELLO_WORLD, "unrelated": "invalid-envelope"});
        let requested = BTreeSet::from(["API_KEY".to_string()]);

        let record = store()
            .validate_credential_row_with_selection(row, MaterialFieldSelection::Only(&requested))
            .expect("unrequested invalid ciphertext must not be decrypted");

        assert_eq!(record.material.require("API_KEY").unwrap(), "hello-world");
        assert_eq!(
            record.material.require("unrelated"),
            Err(CredentialRuntimeError::FieldMissing)
        );
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
