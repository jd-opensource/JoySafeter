use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum EntityIdParseError {
    #[error("expected {0} prefix")]
    MissingPrefix(&'static str),
    #[error("expected canonical {0}<uuid> entity ID")]
    NonCanonical(&'static str),
    #[error(transparent)]
    InvalidUuid(#[from] uuid::Error),
}

macro_rules! entity_id {
    ($name:ident, $prefix:literal) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
        #[cfg_attr(feature = "sqlx", derive(sqlx::Type))]
        #[repr(transparent)]
        #[cfg_attr(feature = "sqlx", sqlx(transparent))]
        pub struct $name(Uuid);

        impl $name {
            pub const PREFIX: &'static str = $prefix;

            pub fn new() -> Self {
                Self(Uuid::now_v7())
            }

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
                let parsed = Uuid::parse_str(raw)?;
                if parsed.to_string() != raw {
                    return Err(EntityIdParseError::NonCanonical(Self::PREFIX));
                }
                Ok(Self(parsed))
            }

            pub fn to_public(self) -> String {
                self.to_string()
            }
        }

        impl Serialize for $name {
            fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
            where
                S: serde::Serializer,
            {
                serializer.serialize_str(&self.to_string())
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: serde::Deserializer<'de>,
            {
                let value = String::deserialize(deserializer)?;
                Self::from_public(&value).map_err(serde::de::Error::custom)
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
entity_id!(AgentVersionId, "agentver_");
entity_id!(ApiKeyId, "apikey_");
entity_id!(UserId, "user_");
entity_id!(OrganizationId, "org_");
entity_id!(OrganizationMemberId, "orgmem_");
entity_id!(ProjectId, "proj_");
entity_id!(ProjectMemberId, "projmem_");
entity_id!(OAuthAccountId, "oauthacct_");
entity_id!(AuthSessionId, "authsess_");
entity_id!(SessionId, "sess_");
entity_id!(TaskId, "task_");
entity_id!(EnvironmentId, "env_");
entity_id!(TriggerId, "trig_");
entity_id!(MemoryStoreId, "memstore_");
entity_id!(MemoryId, "mem_");
entity_id!(MemoryVersionId, "memver_");
entity_id!(SandboxId, "sbx_");
entity_id!(CredentialId, "cred_");
entity_id!(CredentialGroupId, "credgrp_");
entity_id!(SkillId, "skill_");
entity_id!(SkillFileId, "sklfile_");
entity_id!(SkillSecurityScanId, "sklscan_");
entity_id!(SkillVersionId, "sklver_");
entity_id!(SkillVersionFileId, "sklvfile_");
entity_id!(SkillUsageId, "skluse_");
entity_id!(EventId, "evt_");
entity_id!(FileId, "file_");
entity_id!(SessionResourceId, "sesrsc_");
entity_id!(StorageVolumeId, "vol_");
entity_id!(StorageGrantId, "stgrant_");
entity_id!(StorageMountAuditId, "staudit_");
entity_id!(CredentialAccessAuditId, "credaudit_");
entity_id!(SecurityAuditId, "secaudit_");
entity_id!(SandboxNetworkPolicyId, "sbxnetpol_");

#[cfg(test)]
mod tests {
    use super::{
        AgentId, AuthSessionId, CredentialAccessAuditId, CredentialId, EntityIdParseError,
        OAuthAccountId, OrganizationId, OrganizationMemberId, ProjectId, ProjectMemberId,
        SandboxNetworkPolicyId, SecurityAuditId, UserId,
    };
    use uuid::Uuid;

    #[test]
    fn canonical_public_value_round_trips() {
        let id = AgentId::from_uuid(Uuid::now_v7());
        assert_eq!(AgentId::from_public(&id.to_public()).unwrap(), id);
        assert_eq!(
            serde_json::from_str::<AgentId>(&serde_json::to_string(&id).unwrap()).unwrap(),
            id
        );
    }

    #[test]
    fn bare_uuid_is_rejected() {
        let error = AgentId::from_public(&Uuid::now_v7().to_string()).unwrap_err();
        assert!(matches!(error, EntityIdParseError::MissingPrefix("agent_")));
    }

    #[test]
    fn wrong_entity_prefix_is_rejected() {
        let credential_id = CredentialId::new();
        let error = AgentId::from_public(&credential_id.to_public()).unwrap_err();
        assert!(matches!(error, EntityIdParseError::MissingPrefix("agent_")));
    }

    #[test]
    fn non_canonical_uuid_spellings_are_rejected() {
        let value = Uuid::now_v7();
        let variants = [
            format!("agent_{}", value.to_string().to_uppercase()),
            format!("agent_{}", value.simple()),
            format!("agent_{{{value}}}"),
        ];

        for variant in variants {
            assert!(
                AgentId::from_public(&variant).is_err(),
                "accepted {variant}"
            );
        }
    }

    #[test]
    fn tenant_auth_and_internal_record_ids_have_canonical_prefixes() {
        let value = Uuid::now_v7();
        let cases = [
            UserId::from_uuid(value).to_public(),
            OrganizationId::from_uuid(value).to_public(),
            OrganizationMemberId::from_uuid(value).to_public(),
            ProjectId::from_uuid(value).to_public(),
            ProjectMemberId::from_uuid(value).to_public(),
            OAuthAccountId::from_uuid(value).to_public(),
            AuthSessionId::from_uuid(value).to_public(),
            CredentialAccessAuditId::from_uuid(value).to_public(),
            SecurityAuditId::from_uuid(value).to_public(),
            SandboxNetworkPolicyId::from_uuid(value).to_public(),
        ];

        assert_eq!(
            cases,
            [
                format!("user_{value}"),
                format!("org_{value}"),
                format!("orgmem_{value}"),
                format!("proj_{value}"),
                format!("projmem_{value}"),
                format!("oauthacct_{value}"),
                format!("authsess_{value}"),
                format!("credaudit_{value}"),
                format!("secaudit_{value}"),
                format!("sbxnetpol_{value}"),
            ]
        );
    }
}
