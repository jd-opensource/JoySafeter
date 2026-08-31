use sqlx::PgPool;
use thiserror::Error;
use tracing::debug;

use crate::db::queries::{self, LoadedSkillUsage, RecordLoadedSkillUsage};
use crate::grpc::proto;
use crate::ids::{SandboxId, SkillId, SkillSecurityScanId, SkillVersionId};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct SkillLoadManifest {
    expected: Vec<LoadedSkillUsage>,
}

#[derive(Debug, Error)]
pub(crate) enum SkillMaterializationError {
    #[error("invalid Runner skill materialization receipt: {0}")]
    Protocol(String),
    #[error("sandbox {0} disappeared before skill usage persistence")]
    SandboxMissing(SandboxId),
    #[error("failed to persist Runner skill materialization receipt: {0}")]
    Store(#[source] anyhow::Error),
}

impl SkillMaterializationError {
    pub(crate) fn is_protocol(&self) -> bool {
        matches!(self, Self::Protocol(_))
    }
}

impl SkillLoadManifest {
    pub(crate) fn from_archives(archives: &[proto::SkillArchive]) -> anyhow::Result<Self> {
        let mut expected = Vec::new();
        for archive in archives {
            let Some(skill_id) = archive.skill_id.as_deref() else {
                continue;
            };
            let usage = validate_expected_skill(skill_id, archive)?;
            if expected.iter().any(|existing| existing == &usage) {
                anyhow::bail!(
                    "dispatched manifest contains duplicate managed skill receipt identity"
                );
            }
            expected.push(usage);
        }
        Ok(Self { expected })
    }

    pub(crate) fn validate_receipts(
        &self,
        loaded_skills: &[proto::LoadedSkill],
    ) -> anyhow::Result<Vec<LoadedSkillUsage>> {
        let mut matched = Vec::with_capacity(loaded_skills.len());
        for loaded in loaded_skills {
            let reported = validate_loaded_skill(loaded)?;
            let Some(expected) = self.expected.iter().find(|expected| *expected == &reported)
            else {
                anyhow::bail!(
                    "Runner skill receipt does not match dispatched manifest: skill_id={}",
                    reported.skill_id
                );
            };
            if matched.iter().any(|existing| existing == expected) {
                anyhow::bail!(
                    "Runner sent duplicate skill receipt: skill_id={}",
                    reported.skill_id
                );
            }
            matched.push(expected.clone());
        }

        if matched.len() != self.expected.len() {
            anyhow::bail!(
                "Runner skill receipt is missing {} dispatched skill(s)",
                self.expected.len() - matched.len()
            );
        }
        Ok(matched)
    }
}

pub(crate) async fn persist_skill_materialization_receipts(
    pool: &PgPool,
    sandbox_id: SandboxId,
    manifest: &SkillLoadManifest,
    loaded_skills: &[proto::LoadedSkill],
) -> Result<(), SkillMaterializationError> {
    let usages = manifest
        .validate_receipts(loaded_skills)
        .map_err(|error| SkillMaterializationError::Protocol(error.to_string()))?;
    for usage in usages {
        match queries::record_loaded_skill_usage(pool, sandbox_id, &usage)
            .await
            .map_err(SkillMaterializationError::Store)?
        {
            RecordLoadedSkillUsage::Inserted => debug!(
                sandbox_id = %sandbox_id,
                skill_id = %usage.skill_id,
                artifact_hash = %usage.artifact_hash,
                "Recorded loaded skill usage"
            ),
            RecordLoadedSkillUsage::AlreadyRecorded => debug!(
                sandbox_id = %sandbox_id,
                skill_id = %usage.skill_id,
                artifact_hash = %usage.artifact_hash,
                "Skill load usage already recorded"
            ),
            RecordLoadedSkillUsage::SandboxMissing => {
                return Err(SkillMaterializationError::SandboxMissing(sandbox_id));
            }
        }
    }
    Ok(())
}

fn validate_expected_skill(
    skill_id: &str,
    archive: &proto::SkillArchive,
) -> anyhow::Result<LoadedSkillUsage> {
    let loaded = proto::LoadedSkill {
        skill_id: skill_id.to_string(),
        skill_version: required_archive_field(skill_id, "skill_version", &archive.skill_version)?
            .to_string(),
        skill_version_id: required_archive_field(
            skill_id,
            "skill_version_id",
            &archive.skill_version_id,
        )?
        .to_string(),
        skill_name: required_archive_field(skill_id, "skill_name", &archive.skill_name)?
            .to_string(),
        skill_source_type: archive.skill_source_type.clone(),
        target: archive.target.clone(),
        security_scan_id: archive.security_scan_id.clone(),
        target_hash: archive.target_hash.clone(),
        artifact_hash: required_archive_field(skill_id, "artifact_hash", &archive.artifact_hash)?
            .to_string(),
    };
    validate_loaded_skill(&loaded)
}

fn required_archive_field<'a>(
    skill_id: &str,
    field: &str,
    value: &'a Option<String>,
) -> anyhow::Result<&'a str> {
    value
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| anyhow::anyhow!("managed skill {skill_id} is missing {field}"))
}

fn validate_loaded_skill(loaded: &proto::LoadedSkill) -> anyhow::Result<LoadedSkillUsage> {
    let skill_id =
        SkillId::from_public(&loaded.skill_id).map_err(|_| anyhow::anyhow!("invalid skill_id"))?;
    let skill_version_id = SkillVersionId::from_public(&loaded.skill_version_id)
        .map_err(|_| anyhow::anyhow!("invalid skill_version_id"))?;
    let security_scan_id = loaded
        .security_scan_id
        .as_deref()
        .map(SkillSecurityScanId::from_public)
        .transpose()
        .map_err(|_| anyhow::anyhow!("invalid security_scan_id"))?;
    require_non_empty("skill_version", &loaded.skill_version)?;
    require_non_empty("skill_name", &loaded.skill_name)?;
    require_non_empty("target", &loaded.target)?;
    validate_sha256("artifact_hash", &loaded.artifact_hash)?;
    if let Some(target_hash) = loaded.target_hash.as_deref() {
        validate_sha256("target_hash", target_hash)?;
    }

    Ok(LoadedSkillUsage {
        skill_id,
        skill_version: loaded.skill_version.clone(),
        skill_version_id,
        skill_name: loaded.skill_name.clone(),
        skill_source_type: loaded.skill_source_type.clone(),
        target: loaded.target.clone(),
        security_scan_id,
        target_hash: loaded.target_hash.clone(),
        artifact_hash: loaded.artifact_hash.clone(),
    })
}

fn require_non_empty(field: &str, value: &str) -> anyhow::Result<()> {
    if value.trim().is_empty() {
        anyhow::bail!("{field} must not be empty");
    }
    Ok(())
}

fn validate_sha256(field: &str, value: &str) -> anyhow::Result<()> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        anyhow::bail!("{field} must be a 64-character hexadecimal SHA-256 digest");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn expected_archive() -> proto::SkillArchive {
        proto::SkillArchive {
            name: "audit-skill".to_string(),
            tar_gz: b"trusted-archive".to_vec(),
            target: "skills".to_string(),
            skill_id: Some("skill_00000000-0000-0000-0000-000000000001".to_string()),
            skill_version: Some("1.2.3".to_string()),
            skill_version_id: Some("sklver_00000000-0000-0000-0000-000000000002".to_string()),
            skill_name: Some("audit-skill".to_string()),
            skill_source_type: Some("manual".to_string()),
            security_scan_id: Some("sklscan_00000000-0000-0000-0000-000000000003".to_string()),
            target_hash: Some("a".repeat(64)),
            artifact_hash: Some("b".repeat(64)),
        }
    }

    fn matching_receipts() -> Vec<proto::LoadedSkill> {
        vec![proto::LoadedSkill {
            skill_id: "skill_00000000-0000-0000-0000-000000000001".to_string(),
            skill_version: "1.2.3".to_string(),
            skill_version_id: "sklver_00000000-0000-0000-0000-000000000002".to_string(),
            skill_name: "audit-skill".to_string(),
            skill_source_type: Some("manual".to_string()),
            target: "skills".to_string(),
            security_scan_id: Some("sklscan_00000000-0000-0000-0000-000000000003".to_string()),
            target_hash: Some("a".repeat(64)),
            artifact_hash: "b".repeat(64),
        }]
    }

    #[test]
    fn skill_materialization_receipts_use_the_dispatched_manifest_as_authority() {
        let manifest = SkillLoadManifest::from_archives(&[expected_archive()]).unwrap();

        let usages = manifest.validate_receipts(&matching_receipts()).unwrap();

        assert_eq!(usages.len(), 1);
        assert_eq!(usages[0].skill_name, "audit-skill");
        assert_eq!(usages[0].skill_source_type.as_deref(), Some("manual"));
        assert_eq!(usages[0].artifact_hash, "b".repeat(64));
    }

    #[test]
    fn skill_materialization_receipts_reject_runner_metadata_not_in_the_manifest() {
        let manifest = SkillLoadManifest::from_archives(&[expected_archive()]).unwrap();
        let mut receipts = matching_receipts();
        receipts[0].skill_name = "forged-name".to_string();

        let error = manifest.validate_receipts(&receipts).unwrap_err();

        assert!(error
            .to_string()
            .contains("does not match dispatched manifest"));
    }

    #[test]
    fn skill_materialization_receipts_reject_missing_and_duplicate_receipts() {
        let manifest = SkillLoadManifest::from_archives(&[expected_archive()]).unwrap();

        let missing = manifest.validate_receipts(&[]).unwrap_err();
        assert!(missing.to_string().contains("missing 1 dispatched skill"));

        let mut duplicate = matching_receipts();
        duplicate.push(duplicate[0].clone());
        let duplicate_error = manifest.validate_receipts(&duplicate).unwrap_err();
        assert!(duplicate_error
            .to_string()
            .contains("duplicate skill receipt"));
    }

    #[test]
    fn loaded_skill_validation_preserves_versioned_artifact_identity() {
        let loaded = proto::LoadedSkill {
            skill_id: "skill_00000000-0000-0000-0000-000000000001".to_string(),
            skill_version: "1.2.3".to_string(),
            skill_version_id: "sklver_00000000-0000-0000-0000-000000000002".to_string(),
            skill_name: "audit-skill".to_string(),
            skill_source_type: Some("manual".to_string()),
            target: "skills".to_string(),
            security_scan_id: Some("sklscan_00000000-0000-0000-0000-000000000003".to_string()),
            target_hash: Some("a".repeat(64)),
            artifact_hash: "b".repeat(64),
        };

        let usage = validate_loaded_skill(&loaded).unwrap();

        assert_eq!(usage.skill_version, "1.2.3");
        assert_eq!(usage.target, "skills");
        assert_eq!(usage.artifact_hash, "b".repeat(64));
    }

    #[test]
    fn loaded_skill_validation_rejects_untrusted_artifact_hash() {
        let loaded = proto::LoadedSkill {
            skill_id: "skill_00000000-0000-0000-0000-000000000001".to_string(),
            skill_version: "1.2.3".to_string(),
            skill_version_id: "sklver_00000000-0000-0000-0000-000000000002".to_string(),
            skill_name: "audit-skill".to_string(),
            target: "skills".to_string(),
            artifact_hash: "not-a-hash".to_string(),
            ..Default::default()
        };

        assert!(validate_loaded_skill(&loaded).is_err());
    }
}
