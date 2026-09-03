use std::collections::HashSet;
use std::fmt;
use std::time::Duration;

use anyhow::Context;
use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, AssignSandboxPlacementRequest, CompleteRecoveryRequest,
    ErrorResponse, GatewayStatusResponse, PolicyAcceptedResponse, PolicyGeneration,
    PruneSandboxPoliciesRequest, PruneSandboxPoliciesResponse, ReconcilePlacementsRequest,
    RemoveSandboxPolicyRequest,
};
use reqwest::{Method, StatusCode, Url};
use thiserror::Error;

use crate::ids::SandboxId;

const MAX_ERROR_BODY_BYTES: usize = 64 * 1024;
const MAX_IDEMPOTENT_ATTEMPTS: u32 = 4;
const INITIAL_RETRY_BACKOFF: Duration = Duration::from_millis(50);

#[derive(Debug, Error)]
#[error("Agent Gateway {operation} failed with HTTP {status} ({code})")]
pub struct AgentGatewayResponseError {
    operation: &'static str,
    status: StatusCode,
    code: String,
}

impl AgentGatewayResponseError {
    pub fn code(&self) -> &str {
        &self.code
    }

    /// Construct an error from a gRPC status (used by the gRPC client).
    pub fn from_grpc(operation: &'static str, status: StatusCode, code: String) -> Self {
        Self {
            operation,
            status,
            code,
        }
    }
}

#[derive(Debug, Error)]
#[error("Agent Gateway {operation} exceeded its {timeout:?} total request deadline")]
pub struct AgentGatewayRequestTimeout {
    operation: &'static str,
    timeout: Duration,
}

#[derive(Clone)]
pub struct AgentGatewayClientConfig {
    pub base_url: Url,
    pub management_token: String,
    pub request_timeout: Duration,
    pub connect_timeout: Duration,
}

impl fmt::Debug for AgentGatewayClientConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentGatewayClientConfig")
            .field("base_url", &self.base_url)
            .field("management_token", &"<redacted>")
            .field("request_timeout", &self.request_timeout)
            .field("connect_timeout", &self.connect_timeout)
            .finish()
    }
}

impl AgentGatewayClientConfig {
    pub fn new(base_url: &str, management_token: String) -> anyhow::Result<Self> {
        let mut base_url = Url::parse(base_url).context("invalid Agent Gateway base URL")?;
        if !matches!(base_url.scheme(), "http" | "https") {
            anyhow::bail!("Agent Gateway base URL must use http or https");
        }
        if base_url.host_str().is_none()
            || !base_url.username().is_empty()
            || base_url.password().is_some()
            || base_url.query().is_some()
            || base_url.fragment().is_some()
        {
            anyhow::bail!("Agent Gateway base URL must be an origin or path without credentials, query, or fragment");
        }
        if !base_url.path().ends_with('/') {
            base_url.set_path(&format!("{}/", base_url.path()));
        }
        validate_management_token(&management_token)?;
        Ok(Self {
            base_url,
            management_token,
            request_timeout: Duration::from_secs(25),
            connect_timeout: Duration::from_secs(3),
        })
    }

    pub fn with_request_timeout(mut self, timeout: Duration) -> anyhow::Result<Self> {
        if timeout.is_zero() || timeout > Duration::from_secs(600) {
            anyhow::bail!("Agent Gateway request timeout must be between 1 and 600 seconds");
        }
        self.request_timeout = timeout;
        Ok(self)
    }
}

fn validate_management_token(token: &str) -> anyhow::Result<()> {
    if !(32..=512).contains(&token.len()) {
        anyhow::bail!("Agent Gateway management token must contain between 32 and 512 bytes");
    }
    if !token.is_ascii() || token.bytes().any(|byte| byte.is_ascii_whitespace()) {
        anyhow::bail!("Agent Gateway management token must be non-whitespace ASCII");
    }
    Ok(())
}

#[async_trait]
pub trait AgentGatewayApi: Send + Sync {
    async fn check_ready(&self) -> anyhow::Result<()>;

    async fn status(&self) -> anyhow::Result<GatewayStatusResponse>;

    async fn complete_recovery(&self, request: CompleteRecoveryRequest) -> anyhow::Result<()>;

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> anyhow::Result<PolicyAcceptedResponse>;

    async fn remove_policy(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> anyhow::Result<()>;

    async fn prune_policies(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<Vec<SandboxId>>;

    async fn assign_placement(
        &self,
        sandbox_id: SandboxId,
        request: AssignSandboxPlacementRequest,
    ) -> anyhow::Result<()>;

    async fn remove_placement(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;

    async fn reconcile_placements(&self, request: ReconcilePlacementsRequest)
        -> anyhow::Result<()>;
}

#[derive(Clone)]
pub struct AgentGatewayClient {
    http: reqwest::Client,
    base_url: Url,
    management_token: String,
    request_timeout: Duration,
}

impl fmt::Debug for AgentGatewayClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentGatewayClient")
            .field("base_url", &self.base_url)
            .field("management_token", &"<redacted>")
            .finish_non_exhaustive()
    }
}

impl AgentGatewayClient {
    pub fn new(config: AgentGatewayClientConfig) -> anyhow::Result<Self> {
        let http = reqwest::Client::builder()
            .connect_timeout(config.connect_timeout)
            .timeout(config.request_timeout)
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .context("failed to build Agent Gateway HTTP client")?;
        Ok(Self {
            http,
            base_url: config.base_url,
            management_token: config.management_token,
            request_timeout: config.request_timeout,
        })
    }

    fn endpoint(&self, relative_path: &str) -> anyhow::Result<Url> {
        self.base_url
            .join(relative_path)
            .context("failed to construct Agent Gateway endpoint")
    }

    fn authenticated(&self, method: Method, endpoint: Url) -> reqwest::RequestBuilder {
        self.http
            .request(method, endpoint)
            .bearer_auth(&self.management_token)
    }

    async fn expect_status(
        &self,
        response: reqwest::Response,
        expected: StatusCode,
        operation: &'static str,
    ) -> anyhow::Result<reqwest::Response> {
        if response.status() == expected {
            return Ok(response);
        }
        let status = response.status();
        let error = bounded_error(response).await;
        match error {
            Some(error) => Err(AgentGatewayResponseError {
                operation,
                status,
                code: error.code,
            }
            .into()),
            None => anyhow::bail!("Agent Gateway {operation} failed with HTTP {status}"),
        }
    }

    async fn send_idempotent(
        &self,
        request: reqwest::RequestBuilder,
        operation: &'static str,
    ) -> anyhow::Result<reqwest::Response> {
        tokio::time::timeout(
            self.request_timeout,
            self.send_idempotent_with_retries(request, operation),
        )
        .await
        .map_err(|_| {
            anyhow::Error::new(AgentGatewayRequestTimeout {
                operation,
                timeout: self.request_timeout,
            })
        })?
    }

    async fn send_idempotent_with_retries(
        &self,
        request: reqwest::RequestBuilder,
        operation: &'static str,
    ) -> anyhow::Result<reqwest::Response> {
        for attempt in 0..MAX_IDEMPOTENT_ATTEMPTS {
            let attempt_request = request.try_clone().ok_or_else(|| {
                anyhow::anyhow!("Agent Gateway {operation} request is not replayable")
            })?;
            match attempt_request.send().await {
                Ok(response)
                    if attempt + 1 < MAX_IDEMPOTENT_ATTEMPTS
                        && retryable_status(response.status()) =>
                {
                    drop(response);
                }
                Ok(response) => return Ok(response),
                Err(error)
                    if attempt + 1 < MAX_IDEMPOTENT_ATTEMPTS
                        && retryable_transport_error(&error) => {}
                Err(error) => {
                    return Err(error)
                        .with_context(|| format!("Agent Gateway {operation} request failed"));
                }
            }
            tokio::time::sleep(INITIAL_RETRY_BACKOFF * (1 << attempt)).await;
        }
        unreachable!("bounded Agent Gateway retry loop always returns")
    }
}

fn retryable_status(status: StatusCode) -> bool {
    matches!(
        status,
        StatusCode::TOO_MANY_REQUESTS | StatusCode::SERVICE_UNAVAILABLE
    )
}

fn retryable_transport_error(error: &reqwest::Error) -> bool {
    error.is_connect() || error.is_timeout() || error.is_request()
}

#[async_trait]
impl AgentGatewayApi for AgentGatewayClient {
    async fn check_ready(&self) -> anyhow::Result<()> {
        let response = self
            .send_idempotent(self.http.get(self.endpoint("health/ready")?), "readiness")
            .await?;
        self.expect_status(response, StatusCode::OK, "readiness check")
            .await?;
        Ok(())
    }

    async fn status(&self) -> anyhow::Result<GatewayStatusResponse> {
        let response = self
            .send_idempotent(
                self.authenticated(Method::GET, self.endpoint("internal/v1/status")?),
                "status query",
            )
            .await?;
        self.expect_status(response, StatusCode::OK, "status query")
            .await?
            .json::<GatewayStatusResponse>()
            .await
            .context("Agent Gateway returned an invalid status response")
    }

    async fn complete_recovery(&self, request: CompleteRecoveryRequest) -> anyhow::Result<()> {
        let response = self
            .send_idempotent(
                self.authenticated(Method::PUT, self.endpoint("internal/v1/recovery/complete")?)
                    .json(&request),
                "recovery completion",
            )
            .await?;
        self.expect_status(response, StatusCode::NO_CONTENT, "recovery completion")
            .await?;
        Ok(())
    }

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> anyhow::Result<PolicyAcceptedResponse> {
        let expected_generation = request.generation.clone();
        let request = self
            .authenticated(
                Method::PUT,
                self.endpoint(&format!("internal/v1/sandboxes/{sandbox_id}/policy"))?,
            )
            .json(&request);
        let response = self.send_idempotent(request, "policy apply").await?;
        let accepted = self
            .expect_status(response, StatusCode::OK, "policy apply")
            .await?
            .json::<PolicyAcceptedResponse>()
            .await
            .context("Agent Gateway returned an invalid policy response")?;
        if accepted.sandbox_id != sandbox_id.to_string()
            || accepted.generation.policy_hash != expected_generation.policy_hash
            || accepted.generation.policy_version != expected_generation.policy_version
            || accepted.status != "ready"
        {
            anyhow::bail!("Agent Gateway returned a mismatched policy acknowledgement");
        }
        Ok(accepted)
    }

    async fn remove_policy(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> anyhow::Result<()> {
        let request = self
            .authenticated(
                Method::DELETE,
                self.endpoint(&format!("internal/v1/sandboxes/{sandbox_id}/policy"))?,
            )
            .json(&RemoveSandboxPolicyRequest { generation });
        let response = self.send_idempotent(request, "policy removal").await?;
        self.expect_status(response, StatusCode::NO_CONTENT, "policy removal")
            .await?;
        Ok(())
    }

    async fn prune_policies(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<Vec<SandboxId>> {
        let mut live_sandbox_ids = live_sandbox_ids
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        live_sandbox_ids.sort();
        let request = self
            .authenticated(Method::PUT, self.endpoint("internal/v1/policies/prune")?)
            .json(&PruneSandboxPoliciesRequest { live_sandbox_ids });
        let response = self.send_idempotent(request, "policy pruning").await?;
        let response = self
            .expect_status(response, StatusCode::OK, "policy pruning")
            .await?
            .json::<PruneSandboxPoliciesResponse>()
            .await
            .context("Agent Gateway returned an invalid prune response")?;
        response
            .removed_sandbox_ids
            .into_iter()
            .map(|sandbox_id| {
                sandbox_id
                    .parse()
                    .context("Agent Gateway prune response contained an invalid sandbox id")
            })
            .collect()
    }

    async fn assign_placement(
        &self,
        sandbox_id: SandboxId,
        request: AssignSandboxPlacementRequest,
    ) -> anyhow::Result<()> {
        let request = self
            .authenticated(
                Method::PUT,
                self.endpoint(&format!("internal/v1/sandboxes/{sandbox_id}/placement"))?,
            )
            .json(&request);
        let response = self
            .send_idempotent(request, "placement assignment")
            .await?;
        self.expect_status(response, StatusCode::NO_CONTENT, "placement assignment")
            .await?;
        Ok(())
    }

    async fn remove_placement(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let request = self.authenticated(
            Method::DELETE,
            self.endpoint(&format!("internal/v1/sandboxes/{sandbox_id}/placement"))?,
        );
        let response = self.send_idempotent(request, "placement removal").await?;
        self.expect_status(response, StatusCode::NO_CONTENT, "placement removal")
            .await?;
        Ok(())
    }

    async fn reconcile_placements(
        &self,
        request: ReconcilePlacementsRequest,
    ) -> anyhow::Result<()> {
        let request = self
            .authenticated(Method::PUT, self.endpoint("internal/v1/placements")?)
            .json(&request);
        let response = self
            .send_idempotent(request, "placement reconciliation")
            .await?;
        self.expect_status(response, StatusCode::NO_CONTENT, "placement reconciliation")
            .await?;
        Ok(())
    }
}

async fn bounded_error(mut response: reqwest::Response) -> Option<ErrorResponse> {
    let mut body = Vec::new();
    while let Ok(Some(chunk)) = response.chunk().await {
        if body.len().saturating_add(chunk.len()) > MAX_ERROR_BODY_BYTES {
            return None;
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body).ok()
}

#[cfg(test)]
#[path = "client_test.rs"]
mod tests;
