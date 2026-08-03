use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

use async_trait::async_trait;
use k8s_openapi::api::core::v1::Pod;
use k8s_openapi::apimachinery::pkg::apis::meta::v1::Status;
use kube::api::{AttachParams, DeleteParams, ListParams, PostParams};
use kube::{Api, Client};
use serde_json::{json, Value};
use tokio::io::AsyncReadExt;
use tokio::sync::OnceCell;
use tracing::warn;
use uuid::Uuid;

use super::mounts::SandboxMount;
use super::provider::{ProviderSandboxInfo, SandboxCreateConfig, SandboxProvider, SandboxStatus};
use crate::config::JoySafeterConfig;
use crate::egress::policy::{synthetic_credential_route_url, LLM_EGRESS_HOST};
use crate::kernel::llm_providers::is_real_llm_secret_env;

const RUNNER_TOKEN_ENV: &str = "JOYSAFETER_RUNNER_TOKEN";

#[derive(Clone)]
pub struct K8sProvider {
    namespace: String,
    orchestrator_url: Option<String>,
    egress_envoy_credential_url: Option<String>,
    egress_downstream_ca_config_map: String,
    egress_downstream_ca_mount_path: String,
    native_client: Arc<OnceCell<Result<Client, String>>>,
}

impl K8sProvider {
    pub fn new(config: &JoySafeterConfig) -> Self {
        Self {
            namespace: config.k8s_namespace.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
            egress_envoy_credential_url: config.egress_envoy_credential_url.clone(),
            egress_downstream_ca_config_map: config.egress_downstream_ca_config_map.clone(),
            egress_downstream_ca_mount_path: config.egress_downstream_ca_mount_path.clone(),
            native_client: Arc::new(OnceCell::new()),
        }
    }

    async fn native_client(&self) -> anyhow::Result<Client> {
        let result = self
            .native_client
            .get_or_init(|| async {
                Client::try_default()
                    .await
                    .map_err(|error| error.to_string())
            })
            .await;
        match result {
            Ok(client) => Ok(client.clone()),
            Err(error) => anyhow::bail!("Kubernetes API client unavailable: {error}"),
        }
    }

    fn pods_api(&self, client: Client) -> Api<Pod> {
        Api::namespaced(client, &self.namespace)
    }

    async fn native_create(&self, manifest: &Value) -> anyhow::Result<()> {
        let client = self.native_client().await?;
        let pod: Pod = serde_json::from_value(manifest.clone())?;
        self.pods_api(client)
            .create(&PostParams::default(), &pod)
            .await?;
        Ok(())
    }

    async fn native_delete_pod(&self, pod_name: &str) -> anyhow::Result<()> {
        let client = self.native_client().await?;
        match self
            .pods_api(client)
            .delete(pod_name, &DeleteParams::default())
            .await
        {
            Ok(_) => Ok(()),
            Err(error) if kube_error_is_not_found(&error) => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    async fn native_status(&self, pod_name: &str) -> anyhow::Result<SandboxStatus> {
        let client = self.native_client().await?;
        match self.pods_api(client).get(pod_name).await {
            Ok(pod) => Ok(pod_to_sandbox_status(&pod)),
            Err(error) if kube_error_is_not_found(&error) => Ok(SandboxStatus::NotFound),
            Err(error) => Err(error.into()),
        }
    }

    async fn native_list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        let client = self.native_client().await?;
        let pods = self
            .pods_api(client)
            .list(&ListParams::default().labels("app.kubernetes.io/name=joysafeter-sandbox"))
            .await?;
        Ok(pods.iter().map(pod_to_provider_info).collect())
    }

    fn pod_name(sandbox_id: Uuid) -> String {
        format!("joysafeter-{sandbox_id}")
    }

    fn build_manifest(
        &self,
        config: &SandboxCreateConfig,
        pod_name: &str,
    ) -> anyhow::Result<Value> {
        let mut labels = BTreeMap::new();
        for (key, value) in &config.labels {
            labels.insert(sanitize_label_key(key), value.clone());
        }
        labels.insert(
            "app.kubernetes.io/name".to_string(),
            "joysafeter-sandbox".to_string(),
        );
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            config.sandbox_id.to_string(),
        );

        let mut env_map = self.render_pod_env(config)?;
        let mut volumes = Vec::new();
        let mut volume_mounts = Vec::new();
        let mut init_containers = Vec::new();
        if self.shared_envoy_uses_tls() {
            anyhow::ensure!(
                !self.egress_downstream_ca_config_map.trim().is_empty(),
                "shared Envoy TLS requires JOYSAFETER_EGRESS_DOWNSTREAM_CA_CONFIG_MAP"
            );
            anyhow::ensure!(
                self.egress_downstream_ca_mount_path.starts_with('/')
                    && self.egress_downstream_ca_mount_path != "/",
                "shared Envoy TLS requires an absolute non-root downstream CA mount path"
            );
            let bundle_path = format!(
                "{}/ca-bundle.crt",
                self.egress_downstream_ca_mount_path.trim_end_matches('/')
            );
            for name in [
                "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE",
                "GIT_SSL_CAINFO",
                "NODE_EXTRA_CA_CERTS",
            ] {
                env_map.insert(name.to_string(), bundle_path.clone());
            }
            volumes.push(json!({
                "name": "egress-downstream-ca",
                "configMap": {
                    "name": self.egress_downstream_ca_config_map,
                    "items": [{ "key": "ca.crt", "path": "ca.crt" }]
                }
            }));
            volumes.push(json!({
                "name": "egress-trust-bundle",
                "emptyDir": {}
            }));
            volume_mounts.push(json!({
                "name": "egress-trust-bundle",
                "mountPath": self.egress_downstream_ca_mount_path,
                "readOnly": true
            }));
            init_containers.push(json!({
                "name": "build-egress-trust-bundle",
                "image": config.image,
                "imagePullPolicy": "IfNotPresent",
                "command": ["/bin/sh", "-ec"],
                "args": ["system_ca=''; for candidate in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/ca-bundle.pem; do if [ -s \"$candidate\" ]; then system_ca=\"$candidate\"; break; fi; done; test -n \"$system_ca\"; cat \"$system_ca\" /joysafeter-private-ca/ca.crt > /joysafeter-trust/ca-bundle.crt; chmod 0444 /joysafeter-trust/ca-bundle.crt"],
                "securityContext": {
                    "allowPrivilegeEscalation": false,
                    "readOnlyRootFilesystem": true,
                    "runAsNonRoot": true,
                    "runAsUser": 1000,
                    "runAsGroup": 1000,
                    "capabilities": { "drop": ["ALL"] }
                },
                "volumeMounts": [
                    {
                        "name": "egress-downstream-ca",
                        "mountPath": "/joysafeter-private-ca",
                        "readOnly": true
                    },
                    {
                        "name": "egress-trust-bundle",
                        "mountPath": "/joysafeter-trust"
                    }
                ]
            }));
        }
        let mut env = Vec::with_capacity(env_map.len());
        let runner_token = env_map.get(RUNNER_TOKEN_ENV).map(String::as_str);
        for (name, value) in &env_map {
            if is_real_llm_secret_env(name, value)
                && !is_sandbox_token_llm_credential(name, value, runner_token)
            {
                anyhow::bail!(
                    "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s sandbox env contains real LLM secret key '{name}'; configure an egress manager and use placeholder credentials instead"
                );
            }
            env.push(json!({ "name": name, "value": value }));
        }

        for (index, mount) in config.mounts.iter().enumerate() {
            match mount {
                SandboxMount::K8sPvc {
                    claim_name,
                    namespace,
                    mount_path,
                    sub_path,
                    read_only,
                } => {
                    if namespace.as_deref().is_some_and(|ns| ns != self.namespace) {
                        anyhow::bail!(
                            "Storage PVC namespace '{}' does not match provider namespace '{}'",
                            namespace.as_deref().unwrap_or_default(),
                            self.namespace
                        );
                    }
                    let name = format!("storage-{index}");
                    volumes.push(json!({
                        "name": name,
                        "persistentVolumeClaim": { "claimName": claim_name }
                    }));
                    let mut volume_mount = json!({
                        "name": name,
                        "mountPath": mount_path,
                        "readOnly": read_only,
                    });
                    if let Some(sub_path) = sub_path {
                        volume_mount["subPath"] = json!(sub_path);
                    }
                    volume_mounts.push(volume_mount);
                }
                SandboxMount::DockerBind { .. } => {
                    anyhow::bail!("Docker bind mount was passed to K8s provider");
                }
            }
        }

        let mut container = json!({
            "name": "runner",
            "image": config.image,
            "imagePullPolicy": "IfNotPresent",
            "workingDir": "/workspace",
            "env": env,
            "securityContext": {
                "allowPrivilegeEscalation": false,
                "readOnlyRootFilesystem": false,
                "runAsNonRoot": true,
                "runAsUser": 1000,
                "runAsGroup": 1000,
                "capabilities": { "drop": ["ALL"] }
            },
            "resources": {
                "requests": {},
                "limits": {}
            },
            "volumeMounts": volume_mounts
        });
        if let Some(cpu) = config.cpu_limit {
            container["resources"]["limits"]["cpu"] = json!(format!("{}m", (cpu * 1000.0) as u64));
        }
        if let Some(memory_mb) = config.memory_limit_mb {
            container["resources"]["limits"]["memory"] = json!(format!("{memory_mb}Mi"));
        }

        Ok(json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": self.namespace,
                "labels": labels
            },
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": false,
                "enableServiceLinks": false,
                "securityContext": {
                    "seccompProfile": { "type": "RuntimeDefault" },
                    "fsGroup": 1000,
                    "fsGroupChangePolicy": "OnRootMismatch"
                },
                "initContainers": init_containers,
                "containers": [container],
                "volumes": volumes
            }
        }))
    }

    fn shared_envoy_uses_tls(&self) -> bool {
        self.egress_envoy_credential_url
            .as_deref()
            .is_some_and(|url| url.starts_with("https://"))
    }

    fn render_pod_env(
        &self,
        config: &SandboxCreateConfig,
    ) -> anyhow::Result<HashMap<String, String>> {
        let mut env = config.env.clone();
        if config.network.as_deref() == Some("none") {
            self.rewrite_limited_networking_env(config.sandbox_id, &mut env)?;
        }
        Ok(env)
    }

    fn rewrite_limited_networking_env(
        &self,
        sandbox_id: Uuid,
        env: &mut HashMap<String, String>,
    ) -> anyhow::Result<()> {
        if !has_llm_placeholder_base_url(env) {
            return Ok(());
        }
        let base_url = self.egress_envoy_credential_url.as_deref().ok_or_else(|| {
            anyhow::anyhow!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s shared Envoy requires JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL"
            )
        })?;
        let route_url = synthetic_credential_route_url(base_url, sandbox_id, "llm");
        let Some(sandbox_token) = env.get(RUNNER_TOKEN_ENV).cloned().filter(|v| !v.is_empty())
        else {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s shared Envoy env rewrite requires JOYSAFETER_RUNNER_TOKEN"
            );
        };

        // Identity credentials (shared with the Docker provider): bind the model
        // credential env vars to the runner token BEFORE rewriting base URLs, so
        // the placeholder-host detection still matches. `apply_llm_identity_credentials`
        // is the single source of truth for this mapping across both planes.
        crate::egress::llm::apply_llm_identity_credentials(env, &sandbox_token);

        for base_url_var in [
            "ANTHROPIC_BASE_URL",
            "OPENAI_BASE_URL",
            "GOOGLE_GEMINI_BASE_URL",
            "AZURE_OPENAI_BASE_URL",
        ] {
            if is_llm_placeholder_base_url(env.get(base_url_var).map(String::as_str)) {
                env.insert(base_url_var.to_string(), route_url.clone());
            }
        }

        Ok(())
    }
}

fn has_llm_placeholder_base_url(env: &HashMap<String, String>) -> bool {
    [
        "ANTHROPIC_BASE_URL",
        "OPENAI_BASE_URL",
        "GOOGLE_GEMINI_BASE_URL",
        "AZURE_OPENAI_BASE_URL",
    ]
    .iter()
    .any(|key| is_llm_placeholder_base_url(env.get(*key).map(String::as_str)))
}

fn is_llm_placeholder_base_url(value: Option<&str>) -> bool {
    let Some(value) = value else {
        return false;
    };
    url::Url::parse(value)
        .ok()
        .and_then(|url| url.host_str().map(|host| host == LLM_EGRESS_HOST))
        .unwrap_or(false)
}

fn is_sandbox_token_llm_credential(name: &str, value: &str, runner_token: Option<&str>) -> bool {
    runner_token.is_some_and(|token| {
        !token.is_empty()
            && value == token
            && matches!(
                name,
                "ANTHROPIC_API_KEY"
                    | "ANTHROPIC_AUTH_TOKEN"
                    | "OPENAI_API_KEY"
                    | "GEMINI_API_KEY"
                    | "GOOGLE_API_KEY"
                    | "AZURE_OPENAI_API_KEY"
            )
    })
}

fn sanitize_label_key(key: &str) -> String {
    key.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' || ch == '.' || ch == '/' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}

fn phase_to_sandbox_status(phase: &str) -> SandboxStatus {
    match phase {
        "Running" => SandboxStatus::Running,
        "Succeeded" | "Failed" => SandboxStatus::Stopped,
        other => SandboxStatus::Unknown(other.to_string()),
    }
}

fn pod_to_sandbox_status(pod: &Pod) -> SandboxStatus {
    let phase = pod
        .status
        .as_ref()
        .and_then(|status| status.phase.as_deref())
        .unwrap_or("Unknown");
    phase_to_sandbox_status(phase)
}

fn pod_to_provider_info(pod: &Pod) -> ProviderSandboxInfo {
    let name = pod.metadata.name.clone().unwrap_or_default();
    let labels = pod
        .metadata
        .labels
        .clone()
        .unwrap_or_default()
        .into_iter()
        .collect();
    let image = pod
        .spec
        .as_ref()
        .and_then(|spec| spec.containers.first())
        .and_then(|container| container.image.clone())
        .unwrap_or_default();
    let status = pod
        .status
        .as_ref()
        .and_then(|status| status.phase.clone())
        .unwrap_or_else(|| "Unknown".to_string());
    ProviderSandboxInfo {
        id: name.clone(),
        name,
        status,
        image,
        labels,
    }
}

fn kube_error_is_not_found(error: &kube::Error) -> bool {
    matches!(error, kube::Error::Api(response) if response.code == 404)
}

fn exec_status_failed(status: &Status) -> bool {
    status.status.as_deref() == Some("Failure") || status.code.is_some_and(|code| code != 0)
}

fn exec_status_message(status: &Status) -> String {
    status
        .message
        .as_deref()
        .or(status.reason.as_deref())
        .unwrap_or("remote command failed")
        .to_string()
}

#[async_trait]
impl SandboxProvider for K8sProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let pod_name = Self::pod_name(config.sandbox_id);
        let manifest = self.build_manifest(config, &pod_name)?;
        self.native_create(&manifest).await?;
        Ok(pod_name)
    }

    async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        self.native_delete_pod(external_id).await
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        self.stop(external_id).await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        self.native_status(external_id).await
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        if cmd.is_empty() {
            anyhow::bail!("Kubernetes exec command cannot be empty");
        }
        let client = self.native_client().await?;
        let command = cmd
            .iter()
            .map(|part| (*part).to_string())
            .collect::<Vec<_>>();
        let attach = AttachParams::default()
            .stdin(false)
            .stdout(true)
            .stderr(true);
        let mut attached = self
            .pods_api(client)
            .exec(external_id, command, &attach)
            .await?;
        let mut stdout = attached
            .stdout()
            .ok_or_else(|| anyhow::anyhow!("Kubernetes exec stdout stream unavailable"))?;
        let mut stderr = attached
            .stderr()
            .ok_or_else(|| anyhow::anyhow!("Kubernetes exec stderr stream unavailable"))?;
        let status = attached.take_status();
        let mut stdout_bytes = Vec::new();
        let mut stderr_bytes = Vec::new();
        let stdout_read = stdout.read_to_end(&mut stdout_bytes);
        let stderr_read = stderr.read_to_end(&mut stderr_bytes);
        let status = if let Some(status) = status {
            let (stdout_result, stderr_result, status) =
                tokio::join!(stdout_read, stderr_read, status);
            stdout_result?;
            stderr_result?;
            status
        } else {
            let (stdout_result, stderr_result) = tokio::join!(stdout_read, stderr_read);
            stdout_result?;
            stderr_result?;
            None
        };
        attached.join().await?;
        if let Some(status) = status.filter(exec_status_failed) {
            let stderr = String::from_utf8_lossy(&stderr_bytes);
            anyhow::bail!(
                "Kubernetes exec failed: {}; stderr: {}",
                exec_status_message(&status),
                stderr
            );
        }
        Ok(String::from_utf8_lossy(&stdout_bytes).to_string())
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        self.native_list_active().await
    }

    fn provider_name(&self) -> &'static str {
        "k8s"
    }

    fn orchestrator_url(&self, grpc_port: u16) -> String {
        self.orchestrator_url
            .clone()
            .unwrap_or_else(|| format!("http://joysafeter-orchestrator:{grpc_port}"))
    }
}

impl Drop for K8sProvider {
    fn drop(&mut self) {
        if self.namespace.is_empty() {
            warn!("K8sProvider namespace is empty");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::llm_providers::{
        CLAUDE_CODE_PLACEHOLDER_API_KEY, CODEX_PLACEHOLDER_OPENAI_API_KEY,
    };
    use std::collections::HashMap;

    fn provider() -> K8sProvider {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        K8sProvider::new(&config)
    }

    fn config_with_envoy() -> JoySafeterConfig {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        config.k8s_orchestrator_url = Some(
            "http://joysafeter-orchestrator.joysafeter-control.svc.cluster.local:9090".to_string(),
        );
        config.egress_policy_authority_enabled = true;
        config.k8s_egress_management_enabled = true;
        config.egress_envoy_credential_url = Some(
            "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443".to_string(),
        );
        config.egress_envoy_forward_proxy_url = Some(
            "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8080".to_string(),
        );
        config
    }

    fn provider_with_envoy() -> K8sProvider {
        K8sProvider::new(&config_with_envoy())
    }

    #[test]
    fn k8s_api_phase_mapping_matches_provider_status() {
        assert_eq!(phase_to_sandbox_status("Running"), SandboxStatus::Running);
        assert_eq!(phase_to_sandbox_status("Succeeded"), SandboxStatus::Stopped);
        assert_eq!(phase_to_sandbox_status("Failed"), SandboxStatus::Stopped);
        assert_eq!(
            phase_to_sandbox_status("Pending"),
            SandboxStatus::Unknown("Pending".to_string())
        );
    }

    #[test]
    fn k8s_provider_source_has_no_cli_runtime_path() {
        let source = include_str!("k8s.rs");
        assert!(!source.contains(&["kube", "ctl"].concat()));
        assert!(!source.contains(concat!("Command", "::", "new")));
    }

    #[test]
    fn k8s_pod_manifest_has_no_client_side_apply_annotation() {
        let manifest = provider()
            .build_manifest(&create_config(HashMap::new()), "joysafeter-test")
            .expect("manifest builds");

        assert!(manifest.pointer("/metadata/annotations").is_none());
        assert_eq!(
            manifest.pointer("/metadata/name").and_then(Value::as_str),
            Some("joysafeter-test")
        );
        assert_eq!(
            manifest.pointer("/kind").and_then(Value::as_str),
            Some("Pod")
        );
    }

    fn create_config(env: HashMap<String, String>) -> SandboxCreateConfig {
        SandboxCreateConfig {
            sandbox_id: Uuid::now_v7(),
            image: "joysafeter-claudecode:latest".to_string(),
            env,
            labels: HashMap::new(),
            cpu_limit: Some(1.0),
            memory_limit_mb: Some(2048),
            network: None,
            workspace_path: None,
            memory_mounts: vec![],
            mounts: vec![],
        }
    }

    fn pod_env(manifest: &Value) -> HashMap<String, String> {
        manifest
            .pointer("/spec/containers/0/env")
            .and_then(|value| value.as_array())
            .expect("pod env")
            .iter()
            .map(|entry| {
                (
                    entry
                        .get("name")
                        .and_then(|value| value.as_str())
                        .expect("env name")
                        .to_string(),
                    entry
                        .get("value")
                        .and_then(|value| value.as_str())
                        .expect("env value")
                        .to_string(),
                )
            })
            .collect()
    }

    #[test]
    fn k8s_manifest_rejects_real_llm_secret_env() {
        let mut env = HashMap::new();
        env.insert(
            "ANTHROPIC_API_KEY".to_string(),
            "sk-real-secret".to_string(),
        );
        env.insert(
            "ANTHROPIC_BASE_URL".to_string(),
            "https://api.anthropic.com".to_string(),
        );

        let err = provider()
            .build_manifest(&create_config(env), "joysafeter-test")
            .expect_err("real provider secret must not be serialized into a K8s Pod");

        assert!(format!("{err}").contains("K8s sandbox env contains real LLM secret key"));
        assert!(format!("{err}").contains("SANDBOX_EGRESS_MANAGER_REQUIRED"));
    }

    #[test]
    fn k8s_capability_requires_shared_envoy_authority_config() {
        use crate::egress::enforcer::{build_enforcer, K8sEnvoyNetworkPreparer};

        let mut bare = JoySafeterConfig::from_env();
        bare.k8s_namespace = "joysafeter-sandboxes".to_string();
        assert!(build_enforcer(&bare, "k8s", None)
            .expect("build_enforcer")
            .is_none());

        let mut no_authority = config_with_envoy();
        no_authority.egress_policy_authority_enabled = false;
        assert!(build_enforcer(&no_authority, "k8s", None)
            .expect("build_enforcer")
            .is_none());

        assert!(K8sEnvoyNetworkPreparer::from_config(&config_with_envoy())
            .expect("from config")
            .is_some());
    }

    #[test]
    fn k8s_manifest_allows_non_secret_llm_placeholders() {
        let mut env = HashMap::new();
        env.insert(
            "ANTHROPIC_API_KEY".to_string(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY.to_string(),
        );
        env.insert(
            "OPENAI_API_KEY".to_string(),
            CODEX_PLACEHOLDER_OPENAI_API_KEY.to_string(),
        );
        env.insert(
            "ANTHROPIC_BASE_URL".to_string(),
            "http://placeholder-llm-route.local/sandbox/test/llm/anthropic".to_string(),
        );

        let manifest = provider()
            .build_manifest(&create_config(env), "joysafeter-test")
            .expect("placeholder credentials are safe for K8s Pod env");

        let pod_env = manifest
            .pointer("/spec/containers/0/env")
            .and_then(|value| value.as_array())
            .expect("pod env");
        assert!(pod_env.iter().any(|entry| {
            entry.get("name").and_then(|value| value.as_str()) == Some("ANTHROPIC_API_KEY")
                && entry.get("value").and_then(|value| value.as_str())
                    == Some(CLAUDE_CODE_PLACEHOLDER_API_KEY)
        }));
    }

    #[test]
    fn shared_envoy_tls_mounts_combined_trust_bundle() {
        let manifest = provider_with_envoy()
            .build_manifest(&create_config(HashMap::new()), "joysafeter-test")
            .expect("shared Envoy TLS manifest");
        let env = pod_env(&manifest);
        let expected_bundle = "/var/run/joysafeter-egress/trust/ca-bundle.crt";
        assert_eq!(
            env.get("SSL_CERT_FILE").map(String::as_str),
            Some(expected_bundle)
        );
        assert_eq!(
            env.get("NODE_EXTRA_CA_CERTS").map(String::as_str),
            Some(expected_bundle)
        );
        assert_eq!(
            manifest
                .pointer("/spec/initContainers/0/name")
                .and_then(Value::as_str),
            Some("build-egress-trust-bundle")
        );
        assert_eq!(
            manifest
                .pointer("/spec/volumes/0/configMap/name")
                .and_then(Value::as_str),
            Some("joysafeter-egress-downstream-ca")
        );
    }

    #[test]
    fn k8s_manifest_rewrites_llm_placeholder_to_shared_envoy_route_and_sandbox_token() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000021").expect("valid uuid");
        let mut env = HashMap::new();
        env.insert(RUNNER_TOKEN_ENV.to_string(), "runner-token".to_string());
        env.insert(
            "ANTHROPIC_API_KEY".to_string(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY.to_string(),
        );
        env.insert(
            "ANTHROPIC_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        let mut config = create_config(env);
        config.sandbox_id = sandbox_id;
        config.network = Some("none".to_string());

        let manifest = provider_with_envoy()
            .build_manifest(&config, "joysafeter-test")
            .expect("manifest builds");
        let env = pod_env(&manifest);

        assert_eq!(
            env.get("ANTHROPIC_BASE_URL").map(String::as_str),
            Some(
                "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443/v1/sandbox/018ff000-0000-7000-8000-000000000021/route/bGxt"
            )
        );
        assert_eq!(
            env.get("ANTHROPIC_API_KEY").map(String::as_str),
            Some("runner-token")
        );
        assert_eq!(
            env.get("ANTHROPIC_AUTH_TOKEN").map(String::as_str),
            Some("runner-token")
        );
        assert!(!serde_json::to_string(&manifest)
            .expect("manifest json")
            .contains("sk-real"));
    }

    #[test]
    fn k8s_manifest_rewrites_openai_gemini_and_azure_placeholders_to_sandbox_token() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000022").expect("valid uuid");
        let mut env = HashMap::new();
        env.insert(RUNNER_TOKEN_ENV.to_string(), "runner-token".to_string());
        env.insert(
            "OPENAI_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        env.insert(
            "GOOGLE_GEMINI_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        env.insert(
            "AZURE_OPENAI_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        let mut config = create_config(env);
        config.sandbox_id = sandbox_id;
        config.network = Some("none".to_string());

        let manifest = provider_with_envoy()
            .build_manifest(&config, "joysafeter-test")
            .expect("manifest builds");
        let env = pod_env(&manifest);

        assert_eq!(
            env.get("OPENAI_API_KEY").map(String::as_str),
            Some("runner-token")
        );
        assert_eq!(
            env.get("GEMINI_API_KEY").map(String::as_str),
            Some("runner-token")
        );
        assert_eq!(
            env.get("GOOGLE_API_KEY").map(String::as_str),
            Some("runner-token")
        );
        assert_eq!(
            env.get("AZURE_OPENAI_API_KEY").map(String::as_str),
            Some("runner-token")
        );
    }

    #[test]
    fn k8s_manifest_rewrites_llm_placeholder_to_shared_envoy_synthetic_route() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000025").expect("valid uuid");
        let mut env = HashMap::new();
        env.insert(RUNNER_TOKEN_ENV.to_string(), "runner-token".to_string());
        env.insert(
            "ANTHROPIC_API_KEY".to_string(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY.to_string(),
        );
        env.insert(
            "ANTHROPIC_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        let mut config = create_config(env);
        config.sandbox_id = sandbox_id;
        config.network = Some("none".to_string());

        let manifest = provider_with_envoy()
            .build_manifest(&config, "joysafeter-test")
            .expect("manifest builds");
        let env = pod_env(&manifest);

        assert_eq!(
            env.get("ANTHROPIC_BASE_URL").map(String::as_str),
            Some(
                "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443/v1/sandbox/018ff000-0000-7000-8000-000000000025/route/bGxt"
            )
        );
        assert_eq!(
            env.get("ANTHROPIC_API_KEY").map(String::as_str),
            Some("runner-token")
        );
    }

    #[test]
    fn k8s_manifest_requires_runner_token_before_shared_envoy_env_rewrite() {
        let mut env = HashMap::new();
        env.insert(
            "ANTHROPIC_API_KEY".to_string(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY.to_string(),
        );
        env.insert(
            "ANTHROPIC_BASE_URL".to_string(),
            format!("http://{LLM_EGRESS_HOST}"),
        );
        let mut config = create_config(env);
        config.network = Some("none".to_string());

        let err = provider_with_envoy()
            .build_manifest(&config, "joysafeter-test")
            .expect_err("shared Envoy env rewrite must require a sandbox token");

        assert!(format!("{err}").contains("JOYSAFETER_RUNNER_TOKEN"));
        assert!(format!("{err}").contains("SANDBOX_EGRESS_MANAGER_REQUIRED"));
    }
}
