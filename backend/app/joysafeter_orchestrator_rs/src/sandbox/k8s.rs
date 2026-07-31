use std::collections::{BTreeMap, HashMap};
use std::process::Stdio;

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tracing::warn;
use uuid::Uuid;

use super::mounts::SandboxMount;
use super::provider::{
    ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig, SandboxProvider, SandboxStatus,
};
use crate::config::JoySafeterConfig;
use crate::egress::policy::LLM_EGRESS_HOST;
use crate::kernel::llm_providers::is_real_llm_secret_env;

const K8S_EGRESS_GATEWAY_SANDBOX_TOKEN_ENV: &str = "JOYSAFETER_EGRESS_GATEWAY_SANDBOX_TOKEN";
const RUNNER_TOKEN_ENV: &str = "JOYSAFETER_RUNNER_TOKEN";

#[derive(Clone, Debug)]
pub struct K8sProvider {
    namespace: String,
    kubectl_path: String,
    orchestrator_url: Option<String>,
    egress_gateway_url: Option<String>,
    /// Whether a gateway egress manager is configured (gateway URL + control
    /// token). Gates the create-time Pod env rewrite, preserving the
    /// pre-enforcer behavior where the rewrite only needed a configured
    /// manager, not full production egress readiness.
    has_egress_manager: bool,
}

impl K8sProvider {
    pub fn new(config: &JoySafeterConfig) -> Self {
        let has_egress_manager = crate::egress::k8s_manager::K8sEgressManager::from_config(config)
            .ok()
            .flatten()
            .is_some();
        Self {
            namespace: config.k8s_namespace.clone(),
            kubectl_path: config.k8s_kubectl_path.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
            egress_gateway_url: config.egress_gateway_url.clone(),
            has_egress_manager,
        }
    }

    async fn kubectl_json(&self, args: &[&str]) -> anyhow::Result<Value> {
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(serde_json::from_slice(&output.stdout)?)
    }

    async fn kubectl_status(&self, args: &[&str]) -> anyhow::Result<()> {
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    }

    async fn kubectl_create(&self, manifest: &Value) -> anyhow::Result<()> {
        self.kubectl_write_manifest(Self::kubectl_create_args(), manifest)
            .await
    }

    async fn kubectl_write_manifest(
        &self,
        args: [&'static str; 5],
        manifest: &Value,
    ) -> anyhow::Result<()> {
        let mut child = Command::new(&self.kubectl_path)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| anyhow::anyhow!("failed to open kubectl stdin"))?;
        let bytes = serde_json::to_vec(manifest)?;
        stdin.write_all(&bytes).await?;
        drop(stdin);
        let output = child.wait_with_output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    }

    fn kubectl_create_args() -> [&'static str; 5] {
        [
            "create",
            "-f",
            "-",
            "--field-manager",
            "joysafeter-orchestrator",
        ]
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

        let env_map = self.render_pod_env(config)?;
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

        let mut volumes = Vec::new();
        let mut volume_mounts = Vec::new();
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
                "containers": [container],
                "volumes": volumes
            }
        }))
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
        let Some(gateway_url) = self.egress_gateway_url.as_deref() else {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s limited-networking LLM env requires JOYSAFETER_EGRESS_GATEWAY_URL"
            );
        };
        if !self.has_egress_manager {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s limited-networking LLM env requires an egress manager"
            );
        }
        let Some(sandbox_token) = env.get(RUNNER_TOKEN_ENV).cloned().filter(|v| !v.is_empty())
        else {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s egress gateway env rewrite requires JOYSAFETER_RUNNER_TOKEN"
            );
        };

        let anthropic =
            is_llm_placeholder_base_url(env.get("ANTHROPIC_BASE_URL").map(String::as_str));
        let openai = is_llm_placeholder_base_url(env.get("OPENAI_BASE_URL").map(String::as_str));
        let gemini =
            is_llm_placeholder_base_url(env.get("GOOGLE_GEMINI_BASE_URL").map(String::as_str));
        let azure =
            is_llm_placeholder_base_url(env.get("AZURE_OPENAI_BASE_URL").map(String::as_str));

        let gateway_route = format!(
            "{}/sandbox/{sandbox_id}/egress/llm",
            gateway_url.trim_end_matches('/')
        );
        for base_url_var in [
            "ANTHROPIC_BASE_URL",
            "OPENAI_BASE_URL",
            "GOOGLE_GEMINI_BASE_URL",
            "AZURE_OPENAI_BASE_URL",
        ] {
            if is_llm_placeholder_base_url(env.get(base_url_var).map(String::as_str)) {
                env.insert(base_url_var.to_string(), gateway_route.clone());
            }
        }

        if anthropic {
            env.insert("ANTHROPIC_AUTH_TOKEN".to_string(), sandbox_token.clone());
            env.insert("ANTHROPIC_API_KEY".to_string(), sandbox_token.clone());
        }
        if openai {
            env.insert("OPENAI_API_KEY".to_string(), sandbox_token.clone());
        }
        if gemini {
            env.insert("GEMINI_API_KEY".to_string(), sandbox_token.clone());
            env.insert("GOOGLE_API_KEY".to_string(), sandbox_token.clone());
        }
        if azure {
            env.insert("AZURE_OPENAI_API_KEY".to_string(), sandbox_token.clone());
        }

        env.insert(
            K8S_EGRESS_GATEWAY_SANDBOX_TOKEN_ENV.to_string(),
            sandbox_token,
        );
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

#[async_trait]
impl SandboxProvider for K8sProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let pod_name = Self::pod_name(config.sandbox_id);
        let manifest = self.build_manifest(config, &pod_name)?;
        self.kubectl_create(&manifest).await?;
        Ok(pod_name)
    }

    async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        self.kubectl_status(&[
            "-n",
            &self.namespace,
            "delete",
            "pod",
            external_id,
            "--ignore-not-found=true",
        ])
        .await
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        self.stop(external_id).await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        let output = self
            .kubectl_json(&[
                "-n",
                &self.namespace,
                "get",
                "pod",
                external_id,
                "-o",
                "json",
            ])
            .await;
        let pod = match output {
            Ok(value) => value,
            Err(err)
                if format!("{err}").contains("NotFound")
                    || format!("{err}").contains("not found") =>
            {
                return Ok(SandboxStatus::NotFound);
            }
            Err(err) => return Err(err),
        };
        let phase = pod
            .pointer("/status/phase")
            .and_then(|value| value.as_str())
            .unwrap_or("Unknown");
        Ok(match phase {
            "Running" => SandboxStatus::Running,
            "Succeeded" | "Failed" => SandboxStatus::Stopped,
            other => SandboxStatus::Unknown(other.to_string()),
        })
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        let mut args = vec!["-n", self.namespace.as_str(), "exec", external_id, "--"];
        args.extend_from_slice(cmd);
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl exec failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        let pods = self
            .kubectl_json(&[
                "-n",
                &self.namespace,
                "get",
                "pods",
                "-l",
                "app.kubernetes.io/name=joysafeter-sandbox",
                "-o",
                "json",
            ])
            .await?;
        let mut result = Vec::new();
        for item in pods
            .get("items")
            .and_then(|value| value.as_array())
            .into_iter()
            .flatten()
        {
            let Some(name) = item
                .pointer("/metadata/name")
                .and_then(|value| value.as_str())
            else {
                continue;
            };
            let image = item
                .pointer("/spec/containers/0/image")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string();
            let status = item
                .pointer("/status/phase")
                .and_then(|value| value.as_str())
                .unwrap_or("Unknown")
                .to_string();
            let labels = item
                .pointer("/metadata/labels")
                .and_then(|value| value.as_object())
                .map(|labels| {
                    labels
                        .iter()
                        .filter_map(|(key, value)| {
                            value.as_str().map(|v| (key.clone(), v.to_string()))
                        })
                        .collect()
                })
                .unwrap_or_default();
            result.push(ProviderSandboxInfo {
                id: name.to_string(),
                name: name.to_string(),
                status,
                image,
                labels,
            });
        }
        Ok(result)
    }

    fn provider_name(&self) -> &'static str {
        "k8s"
    }

    fn orchestrator_url(&self, grpc_port: u16) -> String {
        self.orchestrator_url
            .clone()
            .unwrap_or_else(|| format!("http://joysafeter-orchestrator:{grpc_port}"))
    }

    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
        }
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
        config.k8s_kubectl_path = "kubectl".to_string();
        K8sProvider::new(&config)
    }

    fn config_with_gateway() -> JoySafeterConfig {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        config.k8s_kubectl_path = "kubectl".to_string();
        config.k8s_orchestrator_url = Some(
            "http://joysafeter-orchestrator.joysafeter-control.svc.cluster.local:9090".to_string(),
        );
        config.egress_gateway_url =
            Some("http://joysafeter-egress-gateway.joysafeter-control.svc:8088".to_string());
        config.egress_gateway_control_token = Some("control-token".to_string());
        config
    }

    fn provider_with_gateway() -> K8sProvider {
        K8sProvider::new(&config_with_gateway())
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
    fn k8s_capability_requires_explicit_enablement_and_gateway_config() {
        use crate::egress::enforcer::build_enforcer;

        // No gateway config → no enforcer (fail-closed).
        let mut bare = JoySafeterConfig::from_env();
        bare.k8s_namespace = "joysafeter-sandboxes".to_string();
        bare.k8s_kubectl_path = "kubectl".to_string();
        assert!(build_enforcer(&bare, "k8s", None)
            .expect("build_enforcer")
            .is_none());

        // Gateway configured but egress management not explicitly enabled → no enforcer.
        assert!(build_enforcer(&config_with_gateway(), "k8s", None)
            .expect("build_enforcer")
            .is_none());

        // Gateway configured + explicit enablement → an enforcer is built.
        let mut enabled = config_with_gateway();
        enabled.k8s_egress_management_enabled = true;
        assert!(build_enforcer(&enabled, "k8s", None)
            .expect("build_enforcer")
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
            "http://joysafeter-egress-gateway/sandbox/test/llm/anthropic".to_string(),
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
    fn k8s_runtime_pod_create_does_not_require_patch_permission() {
        let args = K8sProvider::kubectl_create_args();

        assert_eq!(args[0], "create");
        assert!(args.contains(&"--field-manager"));
        assert!(!args.contains(&"apply"));
        assert!(!args.contains(&"--server-side"));
        assert!(!args.contains(&"--save-config"));
    }

    #[test]
    fn k8s_manifest_rewrites_llm_placeholder_to_gateway_route_and_sandbox_token() {
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

        let manifest = provider_with_gateway()
            .build_manifest(&config, "joysafeter-test")
            .expect("manifest builds");
        let env = pod_env(&manifest);

        assert_eq!(
            env.get("ANTHROPIC_BASE_URL").map(String::as_str),
            Some(
                "http://joysafeter-egress-gateway.joysafeter-control.svc:8088/sandbox/018ff000-0000-7000-8000-000000000021/egress/llm"
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
        assert_eq!(
            env.get(K8S_EGRESS_GATEWAY_SANDBOX_TOKEN_ENV)
                .map(String::as_str),
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

        let manifest = provider_with_gateway()
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
    fn k8s_manifest_requires_runner_token_before_gateway_env_rewrite() {
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

        let err = provider_with_gateway()
            .build_manifest(&config, "joysafeter-test")
            .expect_err("gateway env rewrite must require a sandbox token");

        assert!(format!("{err}").contains("JOYSAFETER_RUNNER_TOKEN"));
        assert!(format!("{err}").contains("SANDBOX_EGRESS_MANAGER_REQUIRED"));
    }
}
