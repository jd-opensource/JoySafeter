use std::path::{Component, Path, PathBuf};

use anyhow::{anyhow, Context};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SandboxMount {
    DockerBind {
        source: String,
        target: String,
        read_only: bool,
    },
    K8sPvc {
        claim_name: String,
        namespace: Option<String>,
        mount_path: String,
        sub_path: Option<String>,
        read_only: bool,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SandboxMountFingerprint {
    pub kind: String,
    pub volume_ref: String,
    pub mount_path: String,
    pub sub_path: String,
    pub access: String,
}

#[derive(Debug, Deserialize)]
struct MountResourceSpec {
    #[serde(default = "default_storage")]
    r#type: String,
    name: String,
    volume_ref: String,
    #[serde(default)]
    sub_path: String,
    mount_path: String,
    #[serde(default = "default_read_only")]
    access: String,
    #[serde(default = "default_required")]
    required: bool,
}

#[derive(Debug, Deserialize)]
struct StorageVolumeSpec {
    #[serde(default = "default_read_only")]
    max_access: String,
    #[serde(default)]
    allowed_prefixes: Vec<String>,
    #[serde(default)]
    docker: Option<StorageDockerSpec>,
    #[serde(default)]
    k8s: Option<StorageK8sSpec>,
}

#[derive(Debug, Deserialize)]
struct StorageDockerSpec {
    host_path: String,
}

#[derive(Debug, Deserialize)]
struct StorageK8sSpec {
    pvc: String,
    #[serde(default)]
    namespace: Option<String>,
}

fn default_storage() -> String {
    "storage".to_string()
}

fn default_read_only() -> String {
    "read_only".to_string()
}

fn default_required() -> bool {
    true
}

pub fn resolve_mount_resources(
    environment_config: Option<&Value>,
    storage_catalog: &Value,
    sandbox_provider: &str,
) -> anyhow::Result<(Vec<SandboxMount>, Vec<SandboxMountFingerprint>)> {
    let Some(resources_value) = environment_config
        .and_then(|config| config.get("mount_resources"))
        .and_then(|value| value.as_array())
    else {
        return Ok((vec![], vec![]));
    };

    if resources_value.is_empty() {
        return Ok((vec![], vec![]));
    }
    let catalog = storage_catalog
        .as_object()
        .ok_or_else(|| anyhow!("Storage volume catalog must be a JSON object"))?;

    let mut mounts = Vec::new();
    let mut fingerprints = Vec::new();
    let mut mount_paths: Vec<String> = Vec::new();
    for item in resources_value {
        let resource: MountResourceSpec =
            serde_json::from_value(item.clone()).context("invalid mount_resources entry")?;
        if resource.r#type != "storage" {
            anyhow::bail!("unsupported mount resource type: {}", resource.r#type);
        }
        validate_safe_token(&resource.name, "mount name")?;
        validate_safe_token(&resource.volume_ref, "volume_ref")?;
        let mount_path = normalize_mount_path(&resource.mount_path)?;
        for existing in &mount_paths {
            if paths_overlap(&mount_path, existing) {
                anyhow::bail!("mount_path overlaps with another mount: {mount_path}");
            }
        }
        mount_paths.push(mount_path.clone());

        let sub_path = normalize_relative_path(&resource.sub_path, "sub_path")?;
        let access = normalize_access(&resource.access)?;
        let read_only = access == "read_only";
        let volume = catalog
            .get(&resource.volume_ref)
            .ok_or_else(|| anyhow!("Storage volume is not allowed: {}", resource.volume_ref))?;
        let volume: StorageVolumeSpec =
            serde_json::from_value(volume.clone()).with_context(|| {
                format!(
                    "invalid Storage volume catalog entry: {}",
                    resource.volume_ref
                )
            })?;
        if access == "read_write" && volume.max_access != "read_write" {
            anyhow::bail!(
                "Storage volume {} does not allow read_write access",
                resource.volume_ref
            );
        }
        if !prefix_allows(&sub_path, &volume.allowed_prefixes)? {
            anyhow::bail!(
                "Storage sub_path '{}' is outside allowed prefixes for {}",
                sub_path,
                resource.volume_ref
            );
        }

        let mount = match sandbox_provider {
            "docker" | "" => {
                let docker = volume.docker.as_ref().ok_or_else(|| {
                    anyhow!(
                        "Storage volume {} is not configured for Docker",
                        resource.volume_ref
                    )
                })?;
                let source =
                    resolve_docker_source(&docker.host_path, &sub_path, resource.required)?;
                SandboxMount::DockerBind {
                    source,
                    target: mount_path.clone(),
                    read_only,
                }
            }
            "k8s" | "kubernetes" => {
                let k8s = volume.k8s.as_ref().ok_or_else(|| {
                    anyhow!(
                        "Storage volume {} is not configured for K8s",
                        resource.volume_ref
                    )
                })?;
                validate_k8s_name(&k8s.pvc, "pvc")?;
                if let Some(namespace) = &k8s.namespace {
                    validate_k8s_name(namespace, "namespace")?;
                }
                SandboxMount::K8sPvc {
                    claim_name: k8s.pvc.clone(),
                    namespace: k8s.namespace.clone(),
                    mount_path: mount_path.clone(),
                    sub_path: if sub_path.is_empty() {
                        None
                    } else {
                        Some(sub_path.clone())
                    },
                    read_only,
                }
            }
            other => {
                anyhow::bail!("Storage mounts are not supported by sandbox provider: {other}");
            }
        };

        fingerprints.push(SandboxMountFingerprint {
            kind: "storage".to_string(),
            volume_ref: resource.volume_ref,
            mount_path,
            sub_path,
            access,
        });
        mounts.push(mount);
    }

    Ok((mounts, fingerprints))
}

fn validate_safe_token(value: &str, field: &str) -> anyhow::Result<()> {
    if value.is_empty()
        || !value
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
    {
        anyhow::bail!("{field} must contain only letters, numbers, '-' or '_'");
    }
    Ok(())
}

fn normalize_access(value: &str) -> anyhow::Result<String> {
    let access = value.trim().to_ascii_lowercase();
    match access.as_str() {
        "read_only" | "read_write" => Ok(access),
        _ => anyhow::bail!("unsupported mount access: {access}"),
    }
}

fn normalize_relative_path(value: &str, field: &str) -> anyhow::Result<String> {
    let raw = value.trim().trim_matches('/').replace('\\', "/");
    if raw.is_empty() {
        return Ok(String::new());
    }
    let path = Path::new(&raw);
    if path.is_absolute() {
        anyhow::bail!("{field} must be relative");
    }
    let mut parts = Vec::new();
    for component in path.components() {
        match component {
            Component::Normal(part) => parts.push(part.to_string_lossy().to_string()),
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                anyhow::bail!("{field} must not contain path traversal");
            }
        }
    }
    Ok(parts.join("/"))
}

fn normalize_mount_path(value: &str) -> anyhow::Result<String> {
    let raw = value.trim().replace('\\', "/");
    if raw.is_empty() || !raw.starts_with('/') {
        anyhow::bail!("mount_path must be an absolute path under /workspace/");
    }
    let path = Path::new(&raw);
    let mut parts = Vec::new();
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(part) => parts.push(part.to_string_lossy().to_string()),
            Component::CurDir => {}
            Component::ParentDir | Component::Prefix(_) => {
                anyhow::bail!("mount_path must not contain path traversal");
            }
        }
    }
    let normalized = format!("/{}", parts.join("/"));
    let forbidden = [
        "/",
        "/workspace",
        "/etc",
        "/root",
        "/home",
        "/proc",
        "/sys",
        "/dev",
        "/var",
        "/var/run",
        "/sockets",
    ];
    if forbidden.contains(&normalized.as_str()) || !normalized.starts_with("/workspace/") {
        anyhow::bail!("mount_path must be under /workspace/ and not a reserved path");
    }
    Ok(normalized)
}

fn paths_overlap(left: &str, right: &str) -> bool {
    let left = left.trim_end_matches('/');
    let right = right.trim_end_matches('/');
    left == right
        || left.starts_with(&format!("{right}/"))
        || right.starts_with(&format!("{left}/"))
}

fn prefix_allows(sub_path: &str, prefixes: &[String]) -> anyhow::Result<bool> {
    if prefixes.is_empty() {
        return Ok(sub_path.is_empty());
    }
    for prefix in prefixes {
        let prefix = normalize_relative_path(prefix, "allowed_prefix")?;
        if prefix.is_empty() || sub_path == prefix || sub_path.starts_with(&format!("{prefix}/")) {
            return Ok(true);
        }
    }
    Ok(false)
}

fn validate_k8s_name(value: &str, field: &str) -> anyhow::Result<()> {
    if value.is_empty()
        || value.len() > 253
        || !value
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-')
        || !value.chars().next().unwrap().is_ascii_alphanumeric()
        || !value.chars().last().unwrap().is_ascii_alphanumeric()
    {
        anyhow::bail!("invalid Kubernetes {field}: {value}");
    }
    Ok(())
}

fn resolve_docker_source(
    base_host_path: &str,
    sub_path: &str,
    required: bool,
) -> anyhow::Result<String> {
    let base_raw = Path::new(base_host_path);
    if !base_raw.is_absolute() {
        anyhow::bail!("Storage Docker host_path must be absolute");
    }
    let base = canonicalize_required(base_raw, "Storage Docker host_path")?;
    let joined = if sub_path.is_empty() {
        base.clone()
    } else {
        base.join(sub_path)
    };
    let target = if joined.exists() {
        canonicalize_required(&joined, "Storage Docker sub_path")?
    } else if required {
        anyhow::bail!(
            "Storage Docker sub_path does not exist: {}",
            joined.display()
        );
    } else {
        joined
    };
    if !target.starts_with(&base) {
        anyhow::bail!("Storage Docker sub_path escapes configured host_path");
    }
    let resolved = path_to_string(target)?;
    if resolved.contains(':') || resolved.contains('\n') || resolved.contains('\r') {
        anyhow::bail!("Storage Docker host path contains unsupported bind-mount characters");
    }
    Ok(resolved)
}

fn canonicalize_required(path: &Path, label: &str) -> anyhow::Result<PathBuf> {
    path.canonicalize()
        .with_context(|| format!("{label} is not accessible: {}", path.display()))
}

fn path_to_string(path: PathBuf) -> anyhow::Result<String> {
    path.into_os_string()
        .into_string()
        .map_err(|_| anyhow!("path contains non-utf8 bytes"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_mount_escape() {
        assert!(normalize_mount_path("/workspace/data").is_ok());
        assert!(normalize_mount_path("/workspace/../etc").is_err());
        assert!(normalize_mount_path("/etc/passwd").is_err());
    }

    #[test]
    fn prefix_scope_is_enforced() {
        assert!(prefix_allows(
            "tenant-a/project-x/assets",
            &["tenant-a/project-x".to_string()]
        )
        .unwrap());
        assert!(!prefix_allows("tenant-a/project-y", &["tenant-a/project-x".to_string()]).unwrap());
    }

    #[test]
    fn resolves_k8s_mount_without_credentials() {
        let env = serde_json::json!({
            "mount_resources": [{
                "type": "storage",
                "name": "assets",
                "volume_ref": "storage-assets-prod",
                "sub_path": "tenant-a/project-x/assets",
                "mount_path": "/workspace/storage/assets",
                "access": "read_only"
            }]
        });
        let catalog = serde_json::json!({
            "storage-assets-prod": {
                "max_access": "read_only",
                "allowed_prefixes": ["tenant-a/project-x"],
                "k8s": {"namespace": "joysafeter-sandboxes", "pvc": "pvc-storage-assets-prod"}
            }
        });
        let (mounts, fps) = resolve_mount_resources(Some(&env), &catalog, "k8s").unwrap();
        assert_eq!(fps.len(), 1);
        assert!(
            matches!(mounts[0], SandboxMount::K8sPvc { ref claim_name, read_only: true, .. } if claim_name == "pvc-storage-assets-prod")
        );
    }
}
