use async_trait::async_trait;
use reqwest::Client;
use serde::Deserialize;
use tracing::{info, warn};

use super::file_injection::FileToInject;
use super::provider::{
    NetworkIsolation, ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig,
    SandboxProvider, SandboxStatus,
};

/// E2B cloud sandbox provider.
///
/// Mirrors the Python `E2bSandboxProvider`. Uses E2B REST API.
#[derive(Clone)]
pub struct E2bProvider {
    client: Client,
    api_url: String,
    api_key: String,
    template_id: String,
}

#[derive(Deserialize)]
struct E2bSandboxResponse {
    #[serde(alias = "sandboxID", alias = "sandboxId")]
    sandbox_id: Option<String>,
    #[serde(alias = "status", alias = "state")]
    state: Option<String>,
}

impl E2bProvider {
    pub fn new(api_url: &str, api_key: &str, template_id: &str) -> Self {
        Self {
            client: Client::new(),
            api_url: api_url.trim_end_matches('/').to_string(),
            api_key: api_key.to_string(),
            template_id: template_id.to_string(),
        }
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("X-API-Key", self.api_key.parse().unwrap());
        headers.insert("Content-Type", "application/json".parse().unwrap());
        headers
    }
}

#[async_trait]
impl SandboxProvider for E2bProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let body = serde_json::json!({
            "templateID": self.template_id,
            "timeout": 3600,
            "metadata": {
                "joysafeter": "true",
                "sandbox_id": config.sandbox_id.to_string(),
            },
        });

        let resp = self
            .client
            .post(format!("{}/sandboxes", self.api_url))
            .headers(self.headers())
            .json(&body)
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("E2B create failed ({status}): {text}"));
        }

        let data: E2bSandboxResponse = resp.json().await?;
        let id = data.sandbox_id.unwrap_or_default();

        info!(sandbox_id = %config.sandbox_id, e2b_id = %id, "E2B sandbox created");
        Ok(id)
    }

    async fn start(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .post(format!("{}/sandboxes/{external_id}/resume", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() && resp.status().as_u16() != 409 {
            let text = resp.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("E2B start/resume failed: {text}"));
        }
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .post(format!("{}/sandboxes/{external_id}/pause", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            warn!("E2B stop/pause warning: {text}");
        }
        Ok(())
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        let resp = self
            .client
            .delete(format!("{}/sandboxes/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if !resp.status().is_success() && resp.status().as_u16() != 404 {
            let text = resp.text().await.unwrap_or_default();
            warn!("E2B destroy warning: {text}");
        }
        Ok(())
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        let resp = self
            .client
            .get(format!("{}/sandboxes/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await?;

        if resp.status().as_u16() == 404 {
            return Ok(SandboxStatus::NotFound);
        }

        let data: E2bSandboxResponse = resp.json().await?;
        let status = data.state.unwrap_or_default();

        match status.as_str() {
            "running" => Ok(SandboxStatus::Running),
            "paused" => Ok(SandboxStatus::Stopped),
            other => Ok(SandboxStatus::Unknown(other.to_string())),
        }
    }

    async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
        // E2B exec via their WebSocket protocol — handled by runner
        Ok(String::new())
    }

    fn provider_name(&self) -> &'static str {
        "e2b"
    }

    async fn provisioning_status(
        &self,
        external_id: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        Ok(self.e2b_provisioning_status(external_id).await)
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        Ok(self
            .e2b_list_active()
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
        // E2B sandboxes run remotely — must use a publicly routable address.
        std::env::var("JOYSAFETER_GRPC_PUBLIC_URL")
            .unwrap_or_else(|_| format!("http://localhost:{grpc_port}"))
    }

    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            has_egress_management: false,
            network_isolation: NetworkIsolation::Platform,
        }
    }

    async fn inject_files(
        &self,
        external_id: &str,
        files: &[FileToInject],
    ) -> anyhow::Result<()> {
        let mut injected = 0usize;
        for file in files {
            let Some(ref content) = file.content else {
                continue;
            };
            let path = file.mount_path.trim_start_matches('/');
            // E2B Files API: POST /sandboxes/{id}/files with JSON body
            let body = serde_json::json!({
                "path": format!("/{path}"),
                "content": base64::Engine::encode(
                    &base64::engine::general_purpose::STANDARD,
                    content,
                ),
            });
            let resp = self
                .client
                .post(format!(
                    "{}/sandboxes/{external_id}/files",
                    self.api_url
                ))
                .headers(self.headers())
                .json(&body)
                .send()
                .await;
            match resp {
                Ok(r) if r.status().is_success() => {
                    injected += 1;
                }
                Ok(r) => {
                    let text = r.text().await.unwrap_or_default();
                    warn!(path = %file.mount_path, "E2B file upload failed: {text}");
                }
                Err(e) => {
                    warn!(path = %file.mount_path, "E2B file upload error: {e}");
                }
            }
        }
        info!(external_id, injected, "Injected files into E2B sandbox");
        Ok(())
    }
}

impl E2bProvider {
    /// Provisioning status (Python L141-177).
    async fn e2b_provisioning_status(&self, external_id: &str) -> Option<serde_json::Value> {
        let resp = self
            .client
            .get(format!("{}/sandboxes/{external_id}", self.api_url))
            .headers(self.headers())
            .send()
            .await
            .ok()?;

        if !resp.status().is_success() {
            return None;
        }

        let data: E2bSandboxResponse = resp.json().await.ok()?;
        let state = data.state.unwrap_or_default();

        let result = match state.as_str() {
            "running" => serde_json::json!({
                "stage": "runtime_ready", "progress": 100,
                "message": "E2B sandbox is running",
                "complete": true, "error": false,
            }),
            "paused" => serde_json::json!({
                "stage": "e2b_paused", "progress": 50,
                "message": "E2B sandbox is paused",
                "complete": false, "error": false,
            }),
            _ => serde_json::json!({
                "stage": "e2b_destroyed", "progress": 100,
                "message": "E2B sandbox is no longer available",
                "complete": true, "error": true,
                "error_message": "Sandbox terminated",
            }),
        };
        Some(result)
    }

    /// List active sandboxes (Python L179-199).
    async fn e2b_list_active(&self) -> Vec<serde_json::Value> {
        let resp = match self
            .client
            .get(format!("{}/sandboxes", self.api_url))
            .headers(self.headers())
            .query(&[("metadata", "joysafeter=true")])
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
                let state = s
                    .get("state")
                    .or_else(|| s.get("status"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown");
                matches!(state, "running" | "creating")
            })
            .map(|s| {
                let id = s
                    .get("sandboxId")
                    .or_else(|| s.get("sandboxID"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                serde_json::json!({
                    "id": id,
                    "provider": "e2b",
                    "status": s.get("state").or_else(|| s.get("status"))
                        .and_then(|v| v.as_str()).unwrap_or("unknown"),
                })
            })
            .collect()
    }
}
