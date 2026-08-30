use async_trait::async_trait;
use reqwest::Client;
use serde::Deserialize;
use tracing::{info, warn};

use super::file_injection::FileToInject;
use super::provider::{
    NetworkIsolation, ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig,
    SandboxProvider, SandboxStatus,
};

/// Daytona cloud sandbox provider.
///
/// Mirrors the Python `DaytonaSandboxProvider`. Uses Daytona REST API.
#[derive(Clone)]
pub struct DaytonaProvider {
    client: Client,
    api_url: String,
    api_key: String,
    target: String,
    snapshot: String,
}

#[derive(Deserialize)]
struct DaytonaSandboxResponse {
    id: Option<String>,
    state: Option<String>,
}

impl DaytonaProvider {
    pub fn new(api_url: &str, api_key: &str, target: &str, snapshot: &str) -> Self {
        Self {
            client: Client::new(),
            api_url: api_url.trim_end_matches('/').to_string(),
            api_key: api_key.to_string(),
            target: target.to_string(),
            snapshot: snapshot.to_string(),
        }
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            "Authorization",
            format!("Bearer {}", self.api_key).parse().unwrap(),
        );
        headers.insert("Content-Type", "application/json".parse().unwrap());
        headers
    }
}

#[async_trait]
impl SandboxProvider for DaytonaProvider {
    fn provider_name(&self) -> &'static str {
        "daytona"
    }

    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let env = config.provider_environment();
        let mut body = serde_json::json!({
            "labels": {
                "joysafeter": "true",
                "joysafeter.sandbox_id": config.sandbox_id.as_uuid().to_string(),
            },
            "target": self.target,
        });

        if !self.snapshot.is_empty() {
            body["snapshot"] = serde_json::json!(self.snapshot);
        }

        // Add env vars
        if !env.is_empty() {
            body["env"] = serde_json::json!(env);
        }

        let resp = self
            .client
            .post(format!("{}/sandbox", self.api_url))
            .headers(self.headers())
            .json(&body)
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Daytona create failed ({status}): {text}"));
        }

        let data: DaytonaSandboxResponse = resp.json().await?;
        let id = data.id.unwrap_or_default();

        info!(sandbox_id = %config.sandbox_id, daytona_id = %id, "Daytona sandbox created");
        Ok(id)
    }

    async fn start(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .post(format!("{}/sandbox/{external_id}/start", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() && resp.status().as_u16() != 409 {
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Daytona start failed: {text}"));
        }
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .post(format!("{}/sandbox/{external_id}/stop", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            warn!("Daytona stop warning: {text}");
        }
        Ok(())
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .delete(format!("{}/sandbox/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() && resp.status().as_u16() != 404 {
            let text = resp.text().await.unwrap_or_default();
            warn!("Daytona destroy warning: {text}");
        }
        Ok(())
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        let resp = self
            .client
            .get(format!("{}/sandbox/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if resp.status().as_u16() == 404 {
            return Ok(SandboxStatus::NotFound);
        }

        let data: DaytonaSandboxResponse = resp.json().await?;
        let state = data.state.unwrap_or_default();

        match state.as_str() {
            "started" | "running" => Ok(SandboxStatus::Running),
            "stopped" | "archived" => Ok(SandboxStatus::Stopped),
            other => Ok(SandboxStatus::Unknown(other.to_string())),
        }
    }

    async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
        // Daytona doesn't support direct exec via REST; use gRPC from runner
        Ok(String::new())
    }

    async fn provisioning_status(
        &self,
        external_id: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        Ok(self.daytona_provisioning_status(external_id).await)
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        Ok(self
            .daytona_list_active()
            .await
            .into_iter()
            .map(|value| ProviderSandboxInfo {
                id: value["id"].as_str().unwrap_or_default().to_string(),
                name: value["id"].as_str().unwrap_or_default().to_string(),
                status: value["status"].as_str().unwrap_or_default().to_string(),
                image: String::new(),
                labels: std::collections::HashMap::new(),
            })
            .collect())
    }

    fn orchestrator_url(&self, grpc_port: u16) -> String {
        // Daytona sandboxes run remotely — must use a publicly routable address.
        // Falls back to localhost which won't work in production; users must set
        // JOYSAFETER_GRPC_PUBLIC_URL.
        std::env::var("JOYSAFETER_GRPC_PUBLIC_URL")
            .unwrap_or_else(|_| format!("http://localhost:{grpc_port}"))
    }

    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            has_egress_management: false,
            network_isolation: NetworkIsolation::Platform,
            stop_preserves_state: true,
        }
    }

    async fn inject_files(&self, external_id: &str, files: &[FileToInject]) -> anyhow::Result<()> {
        let mut injected = 0usize;
        let mut failures = Vec::new();
        for file in files {
            let Some(ref content) = file.content else {
                failures.push(format!("{}: missing loaded content", file.mount_path));
                continue;
            };
            // M10 fix: Reject paths with traversal sequences or null bytes
            // to prevent writing outside the intended sandbox directory.
            let path = file.mount_path.trim_start_matches('/');
            if path.contains("..") || path.contains('\0') {
                failures.push(format!("{}: invalid mount path", file.mount_path));
                continue;
            }
            let resp = self
                .client
                .post(format!(
                    "{}/sandbox/{external_id}/files/upload/{path}",
                    self.api_url
                ))
                .headers(self.headers())
                .body(content.clone())
                .send()
                .await;
            match resp {
                Ok(r) if r.status().is_success() => {
                    injected += 1;
                }
                Ok(r) => {
                    let text = r.text().await.unwrap_or_default();
                    failures.push(format!(
                        "{}: Daytona file upload failed: {text}",
                        file.mount_path
                    ));
                }
                Err(e) => {
                    failures.push(format!(
                        "{}: Daytona file upload error: {e}",
                        file.mount_path
                    ));
                }
            }
        }
        if !failures.is_empty() {
            anyhow::bail!(
                "failed to inject {} of {} files into Daytona sandbox: {}",
                failures.len(),
                files.len(),
                failures.join("; ")
            );
        }
        info!(external_id, injected, "Injected files into Daytona sandbox");
        Ok(())
    }
}

impl DaytonaProvider {
    /// Provisioning status (Python L160-212).
    async fn daytona_provisioning_status(&self, external_id: &str) -> Option<serde_json::Value> {
        let resp = self
            .client
            .get(format!("{}/sandbox/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await
            .ok()?;

        if !resp.status().is_success() {
            return None;
        }

        let data: serde_json::Value = resp.json().await.ok()?;
        let state = data["state"].as_str().unwrap_or("unknown");

        let result = match state {
            "started" => serde_json::json!({
                "stage": "runtime_ready", "progress": 100,
                "message": "Daytona sandbox is running",
                "complete": true, "error": false,
            }),
            "creating" | "pulling_snapshot" | "building_snapshot" | "pending_build" => {
                serde_json::json!({
                    "stage": "daytona_creating", "progress": 40,
                    "message": format!("Daytona sandbox state: {state}"),
                    "complete": false, "error": false,
                })
            }
            "starting" | "restoring" => serde_json::json!({
                "stage": "daytona_starting", "progress": 70,
                "message": format!("Daytona sandbox state: {state}"),
                "complete": false, "error": false,
            }),
            "error" => serde_json::json!({
                "stage": "daytona_error", "progress": 100,
                "message": "Daytona sandbox entered error state",
                "complete": true, "error": true,
                "error_message": "Sandbox failed on Daytona side",
            }),
            _ => serde_json::json!({
                "stage": "daytona_unknown", "progress": 50,
                "message": format!("Daytona sandbox state: {state}"),
                "complete": false, "error": false,
            }),
        };
        Some(result)
    }

    /// List active sandboxes (Python L214-234).
    async fn daytona_list_active(&self) -> Vec<serde_json::Value> {
        let resp = match self
            .client
            .get(format!("{}/sandbox", self.api_url))
            .headers(self.headers())
            .query(&[("labels", r#"{"joysafeter":"true"}"#)])
            .send()
            .await
        {
            Ok(r) => r,
            Err(_) => return vec![],
        };

        if !resp.status().is_success() {
            return vec![];
        }

        let sandboxes: Vec<serde_json::Value> = resp.json().await.unwrap_or_default();
        sandboxes
            .into_iter()
            .filter(|s| {
                let state = s["state"].as_str().unwrap_or("unknown");
                matches!(state, "started" | "creating" | "starting" | "restoring")
            })
            .map(|s| {
                serde_json::json!({
                    "id": s["id"],
                    "provider": "daytona",
                    "status": s["state"],
                })
            })
            .collect()
    }
}
