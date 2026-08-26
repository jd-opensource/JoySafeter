use std::{collections::BTreeSet, fmt};

use anyhow::Context as _;
use sqlx::PgPool;

use crate::ids::{CredentialAccessAuditId, CredentialId, ProjectId, SessionId, TaskId};

use super::audit::{
    CredentialAccessAuditEntry, CredentialAccessAuditWriter, CredentialAccessFailure,
    CredentialAccessUsage,
};
use super::error::CredentialRuntimeError;
use super::material::ManagedCredentialMaterialAdapter;
use super::mcp::{resolve_mcp_member_urls, resolve_mcp_members, ResolvedMcpCredential};
use super::model::{
    model_material_fields, resolve_model_credential, validate_model_credential_metadata,
    ResolvedModelCredential,
};
use super::record::{CredentialKind, McpCredentialMetadataRecord};
use super::service::{
    resolve_service_credential, validate_service_credential_metadata, ResolvedServiceCredential,
    ServiceUsage,
};
use super::store::CredentialStore;
use crate::kernel::llm_catalog::RuntimeCredentialBinding;

#[derive(Debug, Clone)]
pub struct CredentialAccessContext {
    pub consumer_type: String,
    pub consumer_id: Option<String>,
    pub principal_type: String,
    pub principal_id: String,
    pub session_id: Option<SessionId>,
    pub task_id: Option<TaskId>,
    pub generation: Option<i64>,
}

impl CredentialAccessContext {
    pub fn runtime(
        session_id: Option<SessionId>,
        task_id: Option<TaskId>,
        generation: Option<i64>,
    ) -> Self {
        Self {
            consumer_type: "sandbox".to_string(),
            consumer_id: None,
            principal_type: "system".to_string(),
            principal_id: "runtime".to_string(),
            session_id,
            task_id,
            generation,
        }
    }
}

#[derive(Clone)]
pub struct CredentialMaterialAccessService {
    store: CredentialStore,
    audit: CredentialAccessAuditWriter,
}

#[derive(Clone, PartialEq, Eq)]
pub struct ResolvedModelRuntimeConfig {
    pub binding: RuntimeCredentialBinding,
    pub model: Option<String>,
}

impl fmt::Debug for ResolvedModelRuntimeConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedModelRuntimeConfig")
            .field("binding", &self.binding)
            .field("model", &"<redacted>")
            .finish()
    }
}

impl CredentialMaterialAccessService {
    pub fn new(pool: PgPool) -> Self {
        Self {
            store: CredentialStore::new(pool.clone()),
            audit: CredentialAccessAuditWriter::new(pool),
        }
    }

    pub fn with_material_adapter(pool: PgPool, material: ManagedCredentialMaterialAdapter) -> Self {
        Self {
            store: CredentialStore::with_material_adapter(pool.clone(), material),
            audit: CredentialAccessAuditWriter::new(pool),
        }
    }

    pub async fn resolve_model(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        engine_kind: &str,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<ResolvedModelCredential> {
        let mut field_names = BTreeSet::new();
        let mut policy_validated = false;
        let record = match self
            .store
            .get_active_with_field_selector(project_id, credential_id, |metadata| {
                let selected = model_material_fields(metadata, engine_kind)?;
                field_names = selected.clone();
                policy_validated = true;
                Ok(selected)
            })
            .await
        {
            Ok(record) => record,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Model,
                    CredentialAccessUsage::ModelInference,
                    context,
                    field_names,
                    classify_load_failure(error, policy_validated),
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        let resolved = match resolve_model_credential(&record, engine_kind) {
            Ok(resolved) => resolved,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Model,
                    CredentialAccessUsage::ModelInference,
                    context,
                    field_names,
                    CredentialAccessFailure::Failed,
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        self.append_success(
            project_id,
            credential_id,
            CredentialKind::Model,
            CredentialAccessUsage::ModelInference,
            context,
            field_names,
        )
        .await?;
        Ok(resolved)
    }

    pub async fn resolve_model_runtime_config(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        engine_kind: &str,
        needs_model_value: bool,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<ResolvedModelRuntimeConfig> {
        let mut binding = None;
        let mut field_names = BTreeSet::new();
        let mut policy_validated = false;
        let record = match self
            .store
            .get_active_with_field_selector(project_id, credential_id, |metadata| {
                let resolved = validate_model_credential_metadata(metadata, engine_kind)?;
                if needs_model_value {
                    if let Some(model_key) = resolved
                        .model_key
                        .as_ref()
                        .filter(|key| metadata.material_fields.contains(*key))
                    {
                        field_names.insert(model_key.clone());
                    }
                }
                binding = Some(resolved);
                policy_validated = true;
                Ok(field_names.clone())
            })
            .await
        {
            Ok(record) => record,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Model,
                    CredentialAccessUsage::ModelInference,
                    context,
                    field_names,
                    classify_load_failure(error, policy_validated),
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        let binding = binding.ok_or(CredentialRuntimeError::CorruptRecord)?;
        let model = match field_names.first() {
            Some(model_key) => match record.material.require(model_key) {
                Ok(value) => Some(value.to_string()),
                Err(error) => {
                    self.append_failure(
                        project_id,
                        credential_id,
                        CredentialKind::Model,
                        CredentialAccessUsage::ModelInference,
                        context,
                        field_names,
                        CredentialAccessFailure::Failed,
                        error,
                    )
                    .await?;
                    return Err(error.into());
                }
            },
            None => None,
        };
        if !field_names.is_empty() {
            self.append_success(
                project_id,
                credential_id,
                CredentialKind::Model,
                CredentialAccessUsage::ModelInference,
                context,
                field_names,
            )
            .await?;
        }
        Ok(ResolvedModelRuntimeConfig { binding, model })
    }

    pub async fn resolve_environment(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<ResolvedServiceCredential> {
        let mut field_names = BTreeSet::new();
        let mut policy_validated = false;
        let record = match self
            .store
            .get_active_with_field_selector(project_id, credential_id, |metadata| {
                validate_service_credential_metadata(metadata, ServiceUsage::EnvironmentInjection)?;
                field_names = metadata.material_fields.clone();
                policy_validated = true;
                Ok(field_names.clone())
            })
            .await
        {
            Ok(record) => record,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Service,
                    CredentialAccessUsage::EnvironmentInjection,
                    context,
                    field_names,
                    classify_load_failure(error, policy_validated),
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        let resolved = match resolve_service_credential(&record, ServiceUsage::EnvironmentInjection)
        {
            Ok(resolved) => resolved,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Service,
                    CredentialAccessUsage::EnvironmentInjection,
                    context,
                    field_names,
                    CredentialAccessFailure::Failed,
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        self.append_success(
            project_id,
            credential_id,
            CredentialKind::Service,
            CredentialAccessUsage::EnvironmentInjection,
            context,
            field_names,
        )
        .await?;
        Ok(resolved)
    }

    pub async fn resolve_http_egress_field(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        field: &str,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<String> {
        let mut field_names = BTreeSet::new();
        let mut policy_validated = false;
        let record = match self
            .store
            .get_active_with_field_selector(project_id, credential_id, |metadata| {
                validate_service_credential_metadata(
                    metadata,
                    ServiceUsage::HttpEgressField { field },
                )?;
                field_names.insert(field.to_string());
                policy_validated = true;
                Ok(field_names.clone())
            })
            .await
        {
            Ok(record) => record,
            Err(error) => {
                self.append_failure(
                    project_id,
                    credential_id,
                    CredentialKind::Service,
                    CredentialAccessUsage::HttpEgress,
                    context,
                    field_names,
                    classify_load_failure(error, policy_validated),
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        let value =
            match resolve_service_credential(&record, ServiceUsage::HttpEgressField { field }) {
                Ok(ResolvedServiceCredential::HttpEgressField(value)) => value,
                Ok(ResolvedServiceCredential::Environment(_)) => {
                    let error = CredentialRuntimeError::CorruptRecord;
                    self.append_failure(
                        project_id,
                        credential_id,
                        CredentialKind::Service,
                        CredentialAccessUsage::HttpEgress,
                        context,
                        field_names,
                        CredentialAccessFailure::Failed,
                        error,
                    )
                    .await?;
                    return Err(error.into());
                }
                Err(error) => {
                    self.append_failure(
                        project_id,
                        credential_id,
                        CredentialKind::Service,
                        CredentialAccessUsage::HttpEgress,
                        context,
                        field_names,
                        CredentialAccessFailure::Failed,
                        error,
                    )
                    .await?;
                    return Err(error.into());
                }
            };
        self.append_success(
            project_id,
            credential_id,
            CredentialKind::Service,
            CredentialAccessUsage::HttpEgress,
            context,
            field_names,
        )
        .await?;
        Ok(value)
    }

    pub async fn resolve_mcp_members(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<Vec<ResolvedMcpCredential>> {
        let metadata = self
            .load_mcp_member_metadata(project_id, session_id)
            .await?;
        if let Err(error) = resolve_mcp_member_urls(&metadata) {
            for member in &metadata {
                self.append_failure(
                    project_id,
                    member.id,
                    CredentialKind::Mcp,
                    CredentialAccessUsage::McpEgress,
                    context,
                    member.material_fields.clone(),
                    CredentialAccessFailure::Denied,
                    error,
                )
                .await?;
            }
            return Err(error.into());
        }

        let mut resolved = Vec::with_capacity(metadata.len());
        for member in metadata {
            resolved.push(
                self.resolve_mcp_member(project_id, &member, context)
                    .await?,
            );
        }
        Ok(resolved)
    }

    pub async fn load_mcp_member_metadata(
        &self,
        project_id: &ProjectId,
        session_id: SessionId,
    ) -> anyhow::Result<Vec<McpCredentialMetadataRecord>> {
        self.store
            .load_session_mcp_member_metadata(project_id, session_id)
            .await
            .map_err(Into::into)
    }

    pub async fn resolve_mcp_member(
        &self,
        project_id: &ProjectId,
        member: &McpCredentialMetadataRecord,
        context: &CredentialAccessContext,
    ) -> anyhow::Result<ResolvedMcpCredential> {
        let record = match self
            .store
            .get_active_mcp_member(project_id, member.id, member.group_id)
            .await
        {
            Ok(record) => record,
            Err(error) => {
                self.append_failure(
                    project_id,
                    member.id,
                    CredentialKind::Mcp,
                    CredentialAccessUsage::McpEgress,
                    context,
                    member.material_fields.clone(),
                    classify_runtime_error(error),
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        let credential = match resolve_mcp_members(std::slice::from_ref(&record)) {
            Ok(mut credentials) => credentials
                .pop()
                .ok_or(CredentialRuntimeError::CorruptRecord)?,
            Err(error) => {
                self.append_failure(
                    project_id,
                    member.id,
                    CredentialKind::Mcp,
                    CredentialAccessUsage::McpEgress,
                    context,
                    member.material_fields.clone(),
                    CredentialAccessFailure::Failed,
                    error,
                )
                .await?;
                return Err(error.into());
            }
        };
        self.append_success(
            project_id,
            member.id,
            CredentialKind::Mcp,
            CredentialAccessUsage::McpEgress,
            context,
            member.material_fields.clone(),
        )
        .await?;
        Ok(credential)
    }

    async fn append_success(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        credential_kind: CredentialKind,
        usage: CredentialAccessUsage,
        context: &CredentialAccessContext,
        field_names: BTreeSet<String>,
    ) -> anyhow::Result<()> {
        self.audit
            .append_success(&audit_entry(
                project_id,
                credential_id,
                credential_kind,
                usage,
                context,
                field_names,
            ))
            .await
            .context("failed to persist successful credential material access")?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    async fn append_failure(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
        credential_kind: CredentialKind,
        usage: CredentialAccessUsage,
        context: &CredentialAccessContext,
        field_names: BTreeSet<String>,
        result: CredentialAccessFailure,
        error: CredentialRuntimeError,
    ) -> anyhow::Result<()> {
        self.audit
            .append_failure(
                &audit_entry(
                    project_id,
                    credential_id,
                    credential_kind,
                    usage,
                    context,
                    field_names,
                ),
                result,
                error.contract_code(),
            )
            .await
            .context("failed to persist rejected credential material access")?;
        Ok(())
    }
}

fn audit_entry(
    project_id: &ProjectId,
    credential_id: CredentialId,
    credential_kind: CredentialKind,
    usage: CredentialAccessUsage,
    context: &CredentialAccessContext,
    field_names: BTreeSet<String>,
) -> CredentialAccessAuditEntry {
    CredentialAccessAuditEntry {
        id: CredentialAccessAuditId::new(),
        project_id: *project_id,
        credential_id,
        credential_kind,
        usage,
        consumer_type: context.consumer_type.clone(),
        consumer_id: context.consumer_id.clone(),
        principal_type: context.principal_type.clone(),
        principal_id: context.principal_id.clone(),
        session_id: context.session_id,
        task_id: context.task_id,
        generation: context.generation,
        field_names,
    }
}

fn classify_load_failure(
    error: CredentialRuntimeError,
    policy_validated: bool,
) -> CredentialAccessFailure {
    if policy_validated
        || matches!(
            error,
            CredentialRuntimeError::CorruptRecord | CredentialRuntimeError::EnvelopeInvalid
        )
    {
        CredentialAccessFailure::Failed
    } else {
        CredentialAccessFailure::Denied
    }
}

fn classify_runtime_error(error: CredentialRuntimeError) -> CredentialAccessFailure {
    match error {
        CredentialRuntimeError::CorruptRecord | CredentialRuntimeError::EnvelopeInvalid => {
            CredentialAccessFailure::Failed
        }
        _ => CredentialAccessFailure::Denied,
    }
}
