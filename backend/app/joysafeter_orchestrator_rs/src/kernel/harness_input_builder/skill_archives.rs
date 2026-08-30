use std::path::{Component, Path};

use base64::Engine as _;
use flate2::write::GzEncoder;
use flate2::Compression;
use sha2::{Digest, Sha256};
use sqlx::{FromRow, PgPool};
use tar::{Builder, Header};
use tracing::warn;
use uuid::Uuid;

use crate::ids::{
    OrganizationId, ProjectId, SkillId, SkillSecurityScanId, SkillUsageId, SkillVersionId,
};
use crate::kernel::harness_contract::{HarnessInput, HarnessSkillArchive};

pub(super) async fn resolve(
    pool: &PgPool,
    agent: &crate::db::models::JoySafeterAgent,
    task: &crate::db::models::JoySafeterTask,
    input: &mut HarnessInput,
) -> anyhow::Result<()> {
    for (target, items) in [
        ("skills", agent.skills.as_ref()),
        ("agents", agent.agents.as_ref()),
        ("commands", agent.commands.as_ref()),
    ] {
        let Some(arr) = items.and_then(|v| v.as_array()) else {
            continue;
        };
        for item in arr {
            let archive = resolve_skill_item(pool, target, item, agent, task).await?;
            input.skills.push(archive);
        }
    }
    Ok(())
}

async fn resolve_skill_item(
    pool: &PgPool,
    target: &str,
    item: &serde_json::Value,
    agent: &crate::db::models::JoySafeterAgent,
    task: &crate::db::models::JoySafeterTask,
) -> anyhow::Result<HarnessSkillArchive> {
    if target != "skills" {
        let encoded = item
            .get("tar_gz_b64")
            .and_then(|value| value.as_str())
            .ok_or_else(|| anyhow::anyhow!("packed {target} item is missing tar_gz_b64"))?;
        let data = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|error| {
                anyhow::anyhow!("failed to decode packed {target} archive: {error}")
            })?;
        let name = item
            .get("name")
            .and_then(|value| value.as_str())
            .ok_or_else(|| anyhow::anyhow!("packed {target} item is missing name"))?;
        return Ok(HarnessSkillArchive {
            name: name.to_string(),
            tar_gz: data,
            target: target.to_string(),
        });
    }

    let Some(skill_id) = item.get("skill_id").and_then(|v| v.as_str()) else {
        anyhow::bail!("skill item is missing skill_id");
    };
    let version = item
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("latest");
    let skill_id = SkillId::from_public(skill_id)
        .map_err(|_| anyhow::anyhow!("invalid skill_id for target {target}: {skill_id}"))?;
    pack_skill(pool, skill_id, version, target, agent, task).await
}

async fn pack_skill(
    pool: &PgPool,
    skill_id: SkillId,
    version: &str,
    target: &str,
    agent: &crate::db::models::JoySafeterAgent,
    task: &crate::db::models::JoySafeterTask,
) -> anyhow::Result<HarnessSkillArchive> {
    let skill = load_skill_for_archive(pool, skill_id, agent.project_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("skill not found: {skill_id}"))?;
    let project_latest = if version == "latest" && skill.same_project() {
        highest_published_version(pool, skill_id).await
    } else {
        None
    };
    let resolved_version =
        resolve_skill_version_request(&skill, version, project_latest.as_deref())?;
    let version_meta = load_skill_version_meta(pool, skill_id, &resolved_version)
        .await?
        .ok_or_else(|| {
            anyhow::anyhow!("skill version not found: skill={skill_id} version={resolved_version}")
        })?;
    let mut files = load_skill_version_files(pool, skill_id, &resolved_version).await?;
    ensure_skill_entrypoint(&mut files, &version_meta.content).map_err(|error| {
        anyhow::anyhow!(
            "skill {skill_id} version {resolved_version} has no usable root SKILL.md: {error}"
        )
    })?;

    let skill_name = version_meta.skill_name.clone();
    let data = create_targz(&skill_name, &files)?;
    let artifact_hash = hex::encode(Sha256::digest(&data));
    record_skill_usage(
        pool,
        skill_id,
        &resolved_version,
        &version_meta,
        &skill,
        &artifact_hash,
        target,
        agent,
        task,
    )
    .await;

    Ok(HarnessSkillArchive {
        name: skill_name,
        tar_gz: data,
        target: target.to_string(),
    })
}

async fn load_skill_for_archive(
    pool: &PgPool,
    skill_id: SkillId,
    consumer_project_id: Option<ProjectId>,
) -> anyhow::Result<Option<SkillForArchive>> {
    sqlx::query_as::<_, SkillForArchive>(
        r#"
        SELECT s.source_type,
               s.project_id,
               skill_project.org_id AS skill_org_id,
               $2::uuid AS consumer_project_id,
               consumer_project.org_id AS consumer_org_id,
               org_version.version AS org_version,
               public_version.version AS public_version
        FROM joysafeter_skills s
        JOIN joysafeter_organization_projects skill_project
          ON skill_project.id = s.project_id
        LEFT JOIN joysafeter_organization_projects consumer_project
          ON consumer_project.id = $2
        LEFT JOIN joysafeter_skill_versions org_version
          ON org_version.id = s.org_version_id
        LEFT JOIN joysafeter_skill_versions public_version
          ON public_version.id = s.public_version_id
        WHERE s.id = $1
        "#,
    )
    .bind(skill_id)
    .bind(consumer_project_id)
    .fetch_optional(pool)
    .await
    .map_err(Into::into)
}

async fn load_skill_version_meta(
    pool: &PgPool,
    skill_id: SkillId,
    version: &str,
) -> anyhow::Result<Option<SkillVersionForArchive>> {
    sqlx::query_as::<_, SkillVersionForArchive>(
        r#"
        SELECT id, skill_name, content, security_scan_id, target_hash
        FROM joysafeter_skill_versions
        WHERE skill_id = $1 AND version = $2
        "#,
    )
    .bind(skill_id)
    .bind(version)
    .fetch_optional(pool)
    .await
    .map_err(Into::into)
}

async fn record_skill_usage(
    pool: &PgPool,
    skill_id: SkillId,
    skill_version: &str,
    version_meta: &SkillVersionForArchive,
    skill: &SkillForArchive,
    artifact_hash: &str,
    target: &str,
    agent: &crate::db::models::JoySafeterAgent,
    task: &crate::db::models::JoySafeterTask,
) {
    let skill_version_id = Some(version_meta.id);
    let (security_scan_id, target_hash) = published_version_scan_audit(version_meta);
    if let Err(e) = sqlx::query(
        r#"
        INSERT INTO joysafeter_skill_usage_log
          (id, skill_id, skill_name, skill_source_type, skill_version, skill_version_id,
           target, security_scan_id, target_hash, artifact_hash,
           session_id, agent_id, project_id, user_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5,
                CASE WHEN $6::uuid IS NULL THEN NULL
                     WHEN EXISTS (SELECT 1 FROM joysafeter_skill_versions WHERE id = $6) THEN $6
                     ELSE NULL END,
                $7, $8, $9, $10, $11, $12, $13, NULL, NOW(), NOW())
        "#,
    )
    .bind(SkillUsageId::from_uuid(Uuid::now_v7()))
    .bind(skill_id)
    .bind(&version_meta.skill_name)
    .bind(skill.source_type.as_deref())
    .bind(skill_version)
    .bind(skill_version_id)
    .bind(target)
    .bind(security_scan_id)
    .bind(target_hash)
    .bind(artifact_hash)
    .bind(task.session_id.map(|id| id.as_uuid()))
    .bind(agent.id.as_uuid())
    .bind(agent.project_id)
    .execute(pool)
    .await
    {
        warn!(skill_id = %skill_id, "Failed to write skill usage audit row: {e}");
    }
}

/// Return the highest published version string for a skill, or None if it
/// has never been published. Versions are MAJOR.MINOR.PATCH (the publish
/// API rejects prerelease/build), so a numeric tuple sort is exact.
async fn highest_published_version(pool: &PgPool, skill_id: SkillId) -> Option<String> {
    let versions: Vec<String> = sqlx::query_scalar::<_, String>(
        "SELECT version FROM joysafeter_skill_versions WHERE skill_id = $1",
    )
    .bind(skill_id)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    versions
        .into_iter()
        .filter_map(|v| parse_semver(&v).map(|key| (key, v)))
        .max_by(|a, b| a.0.cmp(&b.0))
        .map(|(_, v)| v)
}

async fn load_skill_version_files(
    pool: &PgPool,
    skill_id: SkillId,
    version: &str,
) -> anyhow::Result<Vec<SkillFileForArchive>> {
    sqlx::query_as::<_, SkillFileForArchive>(
        r#"
        SELECT vf.path, vf.file_name, vf.content
        FROM joysafeter_skill_version_files vf
        JOIN joysafeter_skill_versions sv ON sv.id = vf.version_id
        WHERE sv.skill_id = $1 AND sv.version = $2
        ORDER BY vf.path, vf.file_name
        "#,
    )
    .bind(skill_id)
    .bind(version)
    .fetch_all(pool)
    .await
    .map_err(Into::into)
}

pub(super) fn parse_semver(v: &str) -> Option<(u64, u64, u64)> {
    let mut parts = v.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    let patch = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some((major, minor, patch))
}

fn create_targz(root_dir: &str, files: &[SkillFileForArchive]) -> anyhow::Result<Vec<u8>> {
    let safe_root = safe_archive_component(root_dir).unwrap_or_else(|| "unknown".to_string());
    let encoder = GzEncoder::new(Vec::new(), Compression::default());
    let mut tar = Builder::new(encoder);

    for file in files {
        let Some(path) = safe_archive_path(file) else {
            continue;
        };
        let archive_path = format!("{safe_root}/{path}");
        let content = file.content.clone().unwrap_or_default().into_bytes();
        let mut header = Header::new_gnu();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        tar.append_data(&mut header, archive_path, content.as_slice())?;
    }

    let encoder = tar.into_inner()?;
    Ok(encoder.finish()?)
}

pub(super) fn ensure_skill_entrypoint(
    files: &mut Vec<SkillFileForArchive>,
    version_content: &str,
) -> anyhow::Result<()> {
    let roots = files
        .iter()
        .filter(|file| {
            safe_archive_path(file).is_some_and(|path| path.eq_ignore_ascii_case("SKILL.md"))
        })
        .collect::<Vec<_>>();
    if roots.len() > 1 {
        anyhow::bail!("multiple root SKILL.md files");
    }
    if let Some(root) = roots.first() {
        if root
            .content
            .as_deref()
            .is_none_or(|content| content.trim().is_empty())
        {
            anyhow::bail!("root SKILL.md is empty");
        }
        return Ok(());
    }
    if version_content.trim().is_empty() {
        anyhow::bail!("published version content is empty");
    }
    files.push(SkillFileForArchive {
        path: Some(String::new()),
        file_name: Some("SKILL.md".to_string()),
        content: Some(version_content.to_string()),
    });
    Ok(())
}

fn safe_archive_component(value: &str) -> Option<String> {
    let normalized = value.replace('\\', "/");
    let component = Path::new(&normalized)
        .file_name()?
        .to_string_lossy()
        .to_string();
    if component.is_empty() || component == "." || component == ".." || component.contains('/') {
        return None;
    }
    Some(component)
}

pub(super) fn safe_archive_path(file: &SkillFileForArchive) -> Option<String> {
    let raw_path = file.path.clone().unwrap_or_default().replace('\\', "/");
    let file_name = file
        .file_name
        .clone()
        .unwrap_or_default()
        .replace('\\', "/");
    let candidate = if raw_path.is_empty() || raw_path == "." {
        file_name
    } else if raw_path.ends_with('/') {
        format!("{raw_path}{file_name}")
    } else if !file_name.is_empty()
        && Path::new(&raw_path).file_name().and_then(|v| v.to_str()) != Some(file_name.as_str())
    {
        format!("{raw_path}/{file_name}")
    } else {
        raw_path
    };

    let mut parts = Vec::new();
    for component in Path::new(&candidate).components() {
        match component {
            Component::Normal(v) => parts.push(v.to_string_lossy().to_string()),
            Component::CurDir => {}
            _ => return None,
        }
    }
    if parts.is_empty() {
        None
    } else {
        Some(parts.join("/"))
    }
}

#[derive(Debug, FromRow)]
pub(super) struct SkillForArchive {
    pub(super) source_type: Option<String>,
    pub(super) project_id: ProjectId,
    pub(super) skill_org_id: OrganizationId,
    pub(super) consumer_project_id: Option<ProjectId>,
    pub(super) consumer_org_id: Option<OrganizationId>,
    pub(super) org_version: Option<String>,
    pub(super) public_version: Option<String>,
}

impl SkillForArchive {
    fn same_project(&self) -> bool {
        self.consumer_project_id == Some(self.project_id)
    }

    fn same_org(&self) -> bool {
        self.consumer_org_id == Some(self.skill_org_id)
    }

    fn exposed_versions(&self) -> Vec<&str> {
        if self.same_project() {
            return Vec::new();
        }
        let mut versions = Vec::new();
        if let Some(version) = self.public_version.as_deref() {
            versions.push(version);
        }
        if self.same_org() {
            if let Some(version) = self.org_version.as_deref() {
                if !versions.contains(&version) {
                    versions.push(version);
                }
            }
        }
        versions
    }
}

pub(super) fn resolve_skill_version_request(
    skill: &SkillForArchive,
    requested: &str,
    project_latest: Option<&str>,
) -> anyhow::Result<String> {
    if skill.same_project() {
        if requested == "latest" {
            return project_latest
                .map(str::to_string)
                .ok_or_else(|| anyhow::anyhow!("skill has no published version"));
        }
        return Ok(requested.to_string());
    }

    let exposed = skill.exposed_versions();
    if requested == "latest" {
        return exposed
            .into_iter()
            .filter_map(|version| parse_semver(version).map(|key| (key, version)))
            .max_by(|left, right| left.0.cmp(&right.0))
            .map(|(_, version)| version.to_string())
            .ok_or_else(|| anyhow::anyhow!("skill has no version exposed to this project"));
    }
    if exposed.contains(&requested) {
        return Ok(requested.to_string());
    }
    anyhow::bail!("skill version {requested} is not exposed to this project")
}

#[derive(Debug, FromRow)]
pub(super) struct SkillVersionForArchive {
    pub(super) id: SkillVersionId,
    pub(super) skill_name: String,
    pub(super) content: String,
    pub(super) security_scan_id: Option<SkillSecurityScanId>,
    pub(super) target_hash: Option<String>,
}

pub(super) fn published_version_scan_audit(
    version_meta: &SkillVersionForArchive,
) -> (Option<SkillSecurityScanId>, Option<&str>) {
    (
        version_meta.security_scan_id,
        version_meta.target_hash.as_deref(),
    )
}

#[derive(Debug, FromRow)]
pub(super) struct SkillFileForArchive {
    pub(super) path: Option<String>,
    pub(super) file_name: Option<String>,
    pub(super) content: Option<String>,
}
