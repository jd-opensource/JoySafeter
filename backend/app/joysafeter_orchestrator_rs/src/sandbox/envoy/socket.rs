use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use bollard::container::{
    Config, CreateContainerOptions, RemoveContainerOptions, StartContainerOptions,
    WaitContainerOptions,
};
use bollard::exec::{CreateExecOptions, StartExecOptions};
use bollard::models::{HostConfig, Mount, MountTypeEnum};
use bollard::Docker;
use futures::TryStreamExt;
use tracing::{debug, info, warn};

use crate::ids::SandboxId;
use crate::sandbox::runtime::SandboxSocketProvisioner;

const SOCKET_READY_POLL_INTERVAL: Duration = Duration::from_millis(100);

fn socket_storage_preflight_marker() -> String {
    format!(
        ".joysafeter-socket-preflight-{}",
        SandboxId::new().as_uuid()
    )
}

#[derive(Clone)]
pub struct EgressSocketConfig {
    pub envoy_image: String,
    pub socket_volume: String,
    pub socket_host_dir: Option<String>,
    pub container_name: String,
    pub socket_ready_timeout_ms: u64,
    pub externally_provisioned: bool,
}

pub struct EgressSocketProvisioner {
    docker: Option<Arc<Docker>>,
    config: EgressSocketConfig,
}

impl EgressSocketProvisioner {
    pub fn new(docker: Option<Arc<Docker>>, config: EgressSocketConfig) -> Self {
        Self { docker, config }
    }

    fn docker(&self) -> anyhow::Result<&Docker> {
        self.docker
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("Docker client unavailable (K8s mode)"))
    }

    pub async fn prepare_socket_dir(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if self.config.externally_provisioned {
            return Ok(());
        }
        self.ensure_socket_subdir(&sandbox_id.as_uuid().to_string())
            .await
    }

    async fn ensure_socket_subdir(&self, name: &str) -> anyhow::Result<()> {
        match self.config.socket_host_dir.as_deref() {
            Some(root) => {
                let dir = PathBuf::from(root).join(name);
                tokio::fs::create_dir_all(&dir).await?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    tokio::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o755))
                        .await?;
                }
                Ok(())
            }
            None => self.mkdir_in_socket_volume(name).await,
        }
    }

    async fn mkdir_in_socket_volume(&self, name: &str) -> anyhow::Result<()> {
        self.run_socket_volume_helper(
            "init",
            name,
            format!("mkdir -p /sockets/{name} && chmod 755 /sockets/{name}"),
        )
        .await
    }

    async fn remove_socket_volume_subdir(&self, name: &str) -> anyhow::Result<()> {
        self.run_socket_volume_helper("cleanup", name, format!("rm -rf /sockets/{name}"))
            .await
    }

    async fn run_socket_volume_helper(
        &self,
        operation: &str,
        name: &str,
        command: String,
    ) -> anyhow::Result<()> {
        let helper_name = format!("joysafeter-envoy-socket-{operation}-{name}");
        let docker = self.docker()?;
        let _ = docker
            .remove_container(
                &helper_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;
        let container_config = Config {
            image: Some(self.config.envoy_image.clone()),
            user: Some("0".to_string()),
            entrypoint: Some(vec!["/bin/sh".to_string(), "-lc".to_string()]),
            cmd: Some(vec![command]),
            host_config: Some(HostConfig {
                mounts: Some(vec![Mount {
                    target: Some("/sockets".to_string()),
                    source: Some(self.config.socket_volume.clone()),
                    typ: Some(MountTypeEnum::VOLUME),
                    read_only: Some(false),
                    ..Default::default()
                }]),
                ..Default::default()
            }),
            ..Default::default()
        };
        docker
            .create_container(
                Some(CreateContainerOptions {
                    name: helper_name.as_str(),
                    platform: None,
                }),
                container_config,
            )
            .await?;
        docker
            .start_container(&helper_name, None::<StartContainerOptions<String>>)
            .await?;
        let wait = docker
            .wait_container(&helper_name, None::<WaitContainerOptions<String>>)
            .try_collect::<Vec<_>>()
            .await?;
        let status_code = wait.first().map(|result| result.status_code).unwrap_or(1);
        let _ = docker
            .remove_container(
                &helper_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;
        if status_code != 0 {
            anyhow::bail!(
                "failed to {operation} Envoy socket volume directory {name}: helper exited {status_code}"
            );
        }
        debug!(operation, name, socket_volume = %self.config.socket_volume, "Updated Envoy socket dir");
        Ok(())
    }

    async fn remove_socket_subdir(&self, name: &str) -> anyhow::Result<()> {
        match self.config.socket_host_dir.as_deref() {
            Some(root) => {
                let dir = PathBuf::from(root).join(name);
                match tokio::fs::remove_dir_all(&dir).await {
                    Ok(()) => Ok(()),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                    Err(error) => Err(error.into()),
                }
            }
            None => self.remove_socket_volume_subdir(name).await,
        }
    }

    async fn envoy_path_test(&self, flag: &str, path: &str) -> anyhow::Result<bool> {
        let docker = self.docker()?;
        let exec = docker
            .create_exec(
                &self.config.container_name,
                CreateExecOptions {
                    cmd: Some(vec!["test".to_string(), flag.to_string(), path.to_string()]),
                    attach_stdout: Some(false),
                    attach_stderr: Some(false),
                    ..Default::default()
                },
            )
            .await?;
        docker
            .start_exec(
                &exec.id,
                Some(StartExecOptions {
                    detach: true,
                    ..Default::default()
                }),
            )
            .await?;
        for _ in 0..50 {
            let inspect = docker.inspect_exec(&exec.id).await?;
            if inspect.running == Some(false) {
                return Ok(inspect.exit_code == Some(0));
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        Ok(false)
    }

    pub async fn wait_for_socket_ready(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if self.docker.is_none() || self.config.externally_provisioned {
            return Ok(());
        }
        let socket_path = format!("/sockets/{}/http.sock", sandbox_id.as_uuid());
        self.wait_for_socket_ready_with(sandbox_id, || {
            let socket_path = socket_path.clone();
            async move {
                self.envoy_path_test("-S", &socket_path)
                    .await
                    .unwrap_or(false)
            }
        })
        .await
    }

    async fn wait_for_socket_ready_with<F, Fut>(
        &self,
        sandbox_id: SandboxId,
        mut check: F,
    ) -> anyhow::Result<()>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = bool>,
    {
        let timeout = Duration::from_millis(self.config.socket_ready_timeout_ms.max(1));
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            if check().await {
                return Ok(());
            }
            if tokio::time::Instant::now() >= deadline {
                anyhow::bail!(
                    "Envoy did not create egress socket /sockets/{}/http.sock within {}ms; socket storage is {}",
                    sandbox_id.as_uuid(),
                    self.config.socket_ready_timeout_ms,
                    self.storage_description()
                );
            }
            tokio::time::sleep(SOCKET_READY_POLL_INTERVAL).await;
        }
    }

    pub async fn verify_socket_storage_consistency(&self) -> anyhow::Result<()> {
        if self.docker.is_none() || self.config.externally_provisioned {
            return Ok(());
        }
        let marker = socket_storage_preflight_marker();
        self.ensure_socket_subdir(&marker)
            .await
            .context("failed to create socket-storage preflight marker")?;
        let visible = self
            .envoy_path_test("-d", &format!("/sockets/{marker}"))
            .await
            .unwrap_or(false);
        let cleanup_result = self.remove_socket_subdir(&marker).await;
        if !visible {
            if let Err(error) = cleanup_result {
                warn!(marker, %error, "Failed to remove invisible socket-storage preflight marker");
            }
            anyhow::bail!(
                "Envoy cannot see orchestrator socket storage {}; mount the same storage at /sockets",
                self.storage_description()
            );
        }
        cleanup_result.context("failed to remove socket-storage preflight marker")?;
        info!(storage = %self.storage_description(), "Envoy socket storage verified");
        Ok(())
    }

    pub async fn remove_socket_dir(&self, sandbox_id: SandboxId) {
        if self.config.externally_provisioned {
            return;
        }
        let name = sandbox_id.as_uuid().to_string();
        if let Err(error) = self.remove_socket_subdir(&name).await {
            warn!(sandbox_id = %sandbox_id, %error, "Failed to remove Envoy socket directory");
        }
    }

    fn storage_description(&self) -> String {
        self.config.socket_host_dir.as_ref().map_or_else(
            || format!("docker volume {}", self.config.socket_volume),
            |dir| format!("host bind dir {dir}"),
        )
    }
}

#[async_trait::async_trait]
impl SandboxSocketProvisioner for EgressSocketProvisioner {
    async fn prepare_socket(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.prepare_socket_dir(sandbox_id).await
    }

    async fn verify_storage(&self) -> anyhow::Result<()> {
        self.verify_socket_storage_consistency().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn provisioner(timeout_ms: u64) -> EgressSocketProvisioner {
        EgressSocketProvisioner::new(
            None,
            EgressSocketConfig {
                envoy_image: "unused".to_string(),
                socket_volume: "test-sockets".to_string(),
                socket_host_dir: None,
                container_name: "unused".to_string(),
                socket_ready_timeout_ms: timeout_ms,
                externally_provisioned: true,
            },
        )
    }

    #[tokio::test]
    async fn socket_readiness_fails_loudly_after_timeout() {
        let sandbox_id = SandboxId::new();
        let error = provisioner(1)
            .wait_for_socket_ready_with(sandbox_id, || async { false })
            .await
            .expect_err("missing socket must fail");
        assert!(error
            .to_string()
            .contains(&sandbox_id.as_uuid().to_string()));
    }

    #[tokio::test]
    async fn socket_readiness_accepts_visible_socket() {
        provisioner(1)
            .wait_for_socket_ready_with(SandboxId::new(), || async { true })
            .await
            .expect("visible socket");
    }

    #[test]
    fn socket_storage_preflight_markers_are_unique() {
        let first = socket_storage_preflight_marker();
        let second = socket_storage_preflight_marker();

        assert!(first.starts_with(".joysafeter-socket-preflight-"));
        assert!(second.starts_with(".joysafeter-socket-preflight-"));
        assert_ne!(first, second);
    }
}
