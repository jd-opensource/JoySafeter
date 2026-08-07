use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum EntityIdParseError {
    #[error("expected {0} prefix")]
    MissingPrefix(&'static str),
    #[error(transparent)]
    InvalidUuid(#[from] uuid::Error),
}

macro_rules! entity_id {
    ($name:ident, $prefix:literal) => {
        #[derive(
            Debug,
            Clone,
            Copy,
            PartialEq,
            Eq,
            PartialOrd,
            Ord,
            Hash,
            Serialize,
            Deserialize,
            sqlx::Type,
        )]
        #[repr(transparent)]
        #[serde(transparent)]
        #[sqlx(transparent)]
        pub struct $name(Uuid);

        impl $name {
            pub const PREFIX: &'static str = $prefix;

            pub const fn from_uuid(value: Uuid) -> Self {
                Self(value)
            }

            pub const fn as_uuid(self) -> Uuid {
                self.0
            }

            pub fn from_public(value: &str) -> Result<Self, EntityIdParseError> {
                let raw = value
                    .strip_prefix(Self::PREFIX)
                    .ok_or(EntityIdParseError::MissingPrefix(Self::PREFIX))?;
                Uuid::parse_str(raw).map(Self).map_err(Into::into)
            }

            pub fn to_public(self) -> String {
                format!("{}{}", Self::PREFIX, self.0)
            }
        }

        impl From<Uuid> for $name {
            fn from(value: Uuid) -> Self {
                Self::from_uuid(value)
            }
        }

        impl From<$name> for Uuid {
            fn from(value: $name) -> Self {
                value.as_uuid()
            }
        }

        impl FromStr for $name {
            type Err = EntityIdParseError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                Self::from_public(value)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(formatter, "{}{}", Self::PREFIX, self.0)
            }
        }
    };
}

entity_id!(AgentId, "agent_");
entity_id!(SessionId, "sess_");
entity_id!(TaskId, "task_");
entity_id!(EnvironmentId, "env_");
entity_id!(VaultId, "vault_");
entity_id!(CredentialId, "cred_");
entity_id!(SandboxId, "sbx_");
entity_id!(MemoryStoreId, "memstore_");
entity_id!(MemoryId, "mem_");
entity_id!(MemoryVersionId, "memver_");
entity_id!(SkillId, "skill_");
entity_id!(SkillFileId, "sklfile_");
entity_id!(SkillSecurityScanId, "sklscan_");
entity_id!(SkillVersionId, "sklver_");
entity_id!(SkillVersionFileId, "sklvfile_");
entity_id!(SkillUsageId, "skluse_");
entity_id!(FileId, "file_");
entity_id!(SessionResourceId, "sesrsc_");
entity_id!(EventId, "evt_");

#[cfg(test)]
mod tests {
    use super::{
        AgentId, CredentialId, EnvironmentId, EventId, FileId, MemoryId, MemoryStoreId,
        MemoryVersionId, SandboxId, SessionId, SessionResourceId, SkillFileId, SkillId,
        SkillSecurityScanId, SkillUsageId, SkillVersionFileId, SkillVersionId, TaskId, VaultId,
    };
    use uuid::Uuid;

    #[test]
    fn public_round_trip_preserves_entity_prefix() {
        let uuid = Uuid::now_v7();

        let agent_id = AgentId::from_uuid(uuid);
        let session_id = SessionId::from_uuid(uuid);
        let task_id = TaskId::from_uuid(uuid);
        let environment_id = EnvironmentId::from_uuid(uuid);
        let vault_id = VaultId::from_uuid(uuid);
        let credential_id = CredentialId::from_uuid(uuid);
        let sandbox_id = SandboxId::from_uuid(uuid);
        let store_id = MemoryStoreId::from_uuid(uuid);
        let memory_id = MemoryId::from_uuid(uuid);
        let version_id = MemoryVersionId::from_uuid(uuid);
        let skill_id = SkillId::from_uuid(uuid);
        let skill_file_id = SkillFileId::from_uuid(uuid);
        let skill_scan_id = SkillSecurityScanId::from_uuid(uuid);
        let skill_version_id = SkillVersionId::from_uuid(uuid);
        let skill_version_file_id = SkillVersionFileId::from_uuid(uuid);
        let skill_usage_id = SkillUsageId::from_uuid(uuid);
        let file_id = FileId::from_uuid(uuid);
        let session_resource_id = SessionResourceId::from_uuid(uuid);
        let event_id = EventId::from_uuid(uuid);

        assert_eq!(
            AgentId::from_public(&agent_id.to_public()).unwrap(),
            agent_id
        );
        assert_eq!(
            SessionId::from_public(&session_id.to_public()).unwrap(),
            session_id
        );
        assert_eq!(TaskId::from_public(&task_id.to_public()).unwrap(), task_id);
        assert_eq!(
            EnvironmentId::from_public(&environment_id.to_public()).unwrap(),
            environment_id
        );
        assert_eq!(
            VaultId::from_public(&vault_id.to_public()).unwrap(),
            vault_id
        );
        assert_eq!(
            CredentialId::from_public(&credential_id.to_public()).unwrap(),
            credential_id
        );
        assert_eq!(
            SandboxId::from_public(&sandbox_id.to_public()).unwrap(),
            sandbox_id
        );
        assert_eq!(
            MemoryStoreId::from_public(&store_id.to_public()).unwrap(),
            store_id
        );
        assert_eq!(
            MemoryId::from_public(&memory_id.to_public()).unwrap(),
            memory_id
        );
        assert_eq!(
            MemoryVersionId::from_public(&version_id.to_public()).unwrap(),
            version_id
        );
        assert_eq!(
            SkillId::from_public(&skill_id.to_public()).unwrap(),
            skill_id
        );
        assert_eq!(
            SkillFileId::from_public(&skill_file_id.to_public()).unwrap(),
            skill_file_id
        );
        assert_eq!(
            SkillSecurityScanId::from_public(&skill_scan_id.to_public()).unwrap(),
            skill_scan_id
        );
        assert_eq!(
            SkillVersionId::from_public(&skill_version_id.to_public()).unwrap(),
            skill_version_id
        );
        assert_eq!(
            SkillVersionFileId::from_public(&skill_version_file_id.to_public()).unwrap(),
            skill_version_file_id
        );
        assert_eq!(
            SkillUsageId::from_public(&skill_usage_id.to_public()).unwrap(),
            skill_usage_id
        );
        assert_eq!(FileId::from_public(&file_id.to_public()).unwrap(), file_id);
        assert_eq!(
            SessionResourceId::from_public(&session_resource_id.to_public()).unwrap(),
            session_resource_id
        );
        assert_eq!(
            EventId::from_public(&event_id.to_public()).unwrap(),
            event_id
        );
        assert_ne!(agent_id.to_public(), session_id.to_public());
    }

    #[test]
    fn public_parser_rejects_bare_and_cross_entity_ids() {
        let uuid = Uuid::now_v7();

        assert!(AgentId::from_public(&uuid.to_string()).is_err());
        assert!(AgentId::from_public(&SessionId::from_uuid(uuid).to_public()).is_err());
        assert!(EnvironmentId::from_public(&uuid.to_string()).is_err());
        assert!(VaultId::from_public(&uuid.to_string()).is_err());
        assert!(CredentialId::from_public(&uuid.to_string()).is_err());
    }

    #[test]
    fn storage_boundary_uses_bare_uuid() {
        let uuid = Uuid::now_v7();
        let agent_id = AgentId::from_uuid(uuid);

        assert_eq!(agent_id.as_uuid(), uuid);
        assert_eq!(Uuid::from(agent_id), uuid);
        assert_eq!(serde_json::to_value(agent_id).unwrap(), uuid.to_string());
    }
}
