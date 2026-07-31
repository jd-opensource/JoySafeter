use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::egress::gateway::EgressGatewayControlClient;
use crate::egress::policy::SandboxCredentials;

#[derive(Debug, Clone)]
pub struct K8sEgressManager {
    control_client: EgressGatewayControlClient,
}

impl K8sEgressManager {
    pub fn from_config(config: &JoySafeterConfig) -> anyhow::Result<Option<Self>> {
        let Some(url) = config.egress_gateway_url.as_deref() else {
            return Ok(None);
        };
        let Some(control_token) = config.egress_gateway_control_token.as_deref() else {
            return Ok(None);
        };
        Ok(Some(Self {
            control_client: EgressGatewayControlClient::new(url, control_token)?,
        }))
    }

    pub async fn setup_for_sandbox(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        let allowed_hosts = extract_allowed_hosts(networking);
        let policy = credentials.to_policy(&sandbox_id, allowed_hosts);
        self.control_client
            .install_policy(sandbox_id, sandbox_token, policy)
            .await
    }

    pub async fn teardown_for_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.control_client.revoke_policy(sandbox_id).await
    }
}

fn extract_allowed_hosts(networking_config: Option<&serde_json::Value>) -> Vec<String> {
    networking_config
        .and_then(|c| c.get("allowed_hosts"))
        .and_then(|d| d.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::egress::gateway::{
        app_with_policy_store, GatewayConfig, GatewayPolicyStore, InMemoryGatewayPolicyStore,
    };
    use crate::egress::policy::{
        CredentialRef, EgressCredentialRoute, EgressExposure, EgressKind, InjectScheme,
    };

    #[tokio::test]
    async fn k8s_egress_manager_installs_and_revokes_gateway_policy() {
        let sandbox_id = Uuid::parse_str("018ff000-0000-7000-8000-000000000010").unwrap();
        let store = Arc::new(InMemoryGatewayPolicyStore::new());
        let policy_store: Arc<dyn GatewayPolicyStore> = store.clone();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind gateway");
        let base_url = format!("http://{}", listener.local_addr().expect("local addr"));
        let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();
        let gateway = app_with_policy_store(
            GatewayConfig {
                host: "127.0.0.1".to_string(),
                port: 8088,
                require_sandbox_token: true,
                control_token_sha256: Some(crate::egress::gateway::hash_token("control-token")),
                resolve_url: None,
                resolve_token: None,
            },
            Some(policy_store),
        );
        let server = tokio::spawn(async move {
            let _ = axum::serve(listener, gateway)
                .with_graceful_shutdown(async {
                    let _ = shutdown_rx.await;
                })
                .await;
        });
        let manager = K8sEgressManager {
            control_client: EgressGatewayControlClient::new(&base_url, "control-token")
                .expect("client builds"),
        };
        let networking = serde_json::json!({
            "allowed_hosts": ["api.anthropic.com"]
        });

        manager
            .setup_for_sandbox(
                sandbox_id,
                "runner-token",
                Some(&networking),
                SandboxCredentials {
                    routes: vec![EgressCredentialRoute {
                        id: "llm".to_string(),
                        kind: EgressKind::Llm,
                        exposure: EgressExposure::Placeholder,
                        match_host: "llm-egress.internal".to_string(),
                        match_prefix: "/".to_string(),
                        exact_path: false,
                        upstream_host: "api.anthropic.com".to_string(),
                        upstream_port: 443,
                        upstream_prefix: "/".to_string(),
                        upstream_tls: true,
                        cluster_name: String::new(),
                        credential_ref: CredentialRef::Llm {
                            secret_name: "test-secret".to_string(),
                            secret_key: "ANTHROPIC_API_KEY".to_string(),
                            project_id: None,
                        },
                        inject_header: "authorization".to_string(),
                        inject_scheme: InjectScheme::Bearer,
                        remove_headers: vec!["authorization".to_string()],
                    }],
                },
            )
            .await
            .expect("policy installs");

        let installed = store.get(sandbox_id).expect("policy installed");
        assert_eq!(installed.policy.allowlist_hosts, vec!["api.anthropic.com"]);
        assert_eq!(installed.policy.credential_routes.len(), 1);

        manager
            .teardown_for_sandbox(sandbox_id)
            .await
            .expect("policy revoked");
        assert!(store.get(sandbox_id).is_none());

        let _ = shutdown_tx.send(());
        let _ = server.await;
    }
}
