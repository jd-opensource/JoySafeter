use std::collections::HashMap;
use std::sync::Arc;

use chrono::{Duration, Utc};
use sqlx::PgPool;
use tracing::{info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{SandboxId, TaskId};
use crate::kernel::runtime_auth::runner_token_digest;
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxRuntimeCredentials};

use super::lifecycle::SandboxLifecycleService;
use super::model::{ResolveContext, ResolvedSandbox};
use super::networking::{
    PreparedSandboxNetworking, SandboxNetworkingService, TaskIdentityNetworkLease,
};
use super::runtime_plan::{
    apply_claude_code_sandbox_privacy, apply_sandbox_timezone, generate_runner_token,
    provisioning_config,
};

#[derive(Clone)]
pub struct SandboxProvisioningService {
    pool: PgPool,
    provider: Arc<dyn SandboxProvider>,
    config: JoySafeterConfig,
    networking: SandboxNetworkingService,
    lifecycle: SandboxLifecycleService,
}

impl SandboxProvisioningService {
    pub fn new(
        pool: PgPool,
        provider: Arc<dyn SandboxProvider>,
        config: JoySafeterConfig,
        networking: SandboxNetworkingService,
        lifecycle: SandboxLifecycleService,
    ) -> Self {
        Self {
            pool,
            provider,
            config,
            networking,
            lifecycle,
        }
    }

    #[cfg(test)]
    pub(crate) fn with_networking(
        mut self,
        networking: SandboxNetworkingService,
        lifecycle: SandboxLifecycleService,
    ) -> Self {
        self.networking = networking;
        self.lifecycle = lifecycle;
        self
    }

    pub(crate) async fn create(
        &self,
        task_id: TaskId,
        context: &ResolveContext,
    ) -> anyhow::Result<ResolvedSandbox> {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let expected = context.expected.clone();
        let image = expected.image.clone();
        let runner_session_token = generate_runner_token();
        let runner_token_digest = runner_token_digest(&runner_session_token);
        let egress_proxy_token = generate_runner_token();
        let admission_ttl = i64::try_from(self.config.runner_admission_ttl_seconds)
            .map_err(|_| anyhow::anyhow!("runner admission TTL exceeds supported duration"))?;
        let runner_auth_expires_at = Utc::now() + Duration::seconds(admission_ttl);

        let mut env = expected.env.clone();
        apply_sandbox_timezone(&mut env, &self.config.sandbox_timezone);
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_id.as_uuid().to_string(),
        );
        apply_claude_code_sandbox_privacy(&mut env);
        if !self.config.sandbox_timezone.trim().is_empty() {
            env.entry("TZ".to_string())
                .or_insert_with(|| self.config.sandbox_timezone.clone());
        }
        env.insert(
            "JOYSAFETER_ORCHESTRATOR_URL".to_string(),
            self.provider.orchestrator_url(self.config.grpc_port),
        );

        let mut labels = HashMap::new();
        labels.insert("joysafeter".to_string(), "true".to_string());
        labels.insert("joysafeter.managed".to_string(), "true".to_string());
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            sandbox_id.as_uuid().to_string(),
        );
        labels.insert(
            "joysafeter.owner_instance_id".to_string(),
            self.config.instance_id.clone(),
        );
        labels.insert(
            "joysafeter.created_at_unix".to_string(),
            chrono::Utc::now().timestamp().to_string(),
        );
        labels.insert(
            "joysafeter.engine_kind".to_string(),
            expected.engine_kind.clone(),
        );
        labels.insert("joysafeter.pool".to_string(), "false".to_string());
        labels.insert("joysafeter.claimed".to_string(), "true".to_string());
        labels.insert("joysafeter.allocation".to_string(), "session".to_string());
        if let Some(session_id) = context.session_id {
            labels.insert("joysafeter.session_id".to_string(), session_id.to_string());
        }
        if let Some(project_id) = context.project_id {
            labels.insert("joysafeter.project_id".to_string(), project_id.to_public());
        }

        let limited_networking = context.network.as_deref() == Some("none");
        let create_config = SandboxCreateConfig {
            sandbox_id,
            image: image.clone(),
            env,
            runtime_credentials: SandboxRuntimeCredentials::new(
                runner_session_token,
                egress_proxy_token.clone(),
            ),
            labels,
            cpu_limit: self.config.sandbox_cpu,
            memory_limit_mb: self.config.sandbox_memory_mb,
            network: context.network.clone(),
            start_immediately: !limited_networking,
            workspace_path: self.config.sandbox_workspace_root.as_ref().map(|root| {
                if let Some(session_id) = context.session_id {
                    format!("{root}/{session_id}")
                } else {
                    format!("{root}/{sandbox_id}")
                }
            }),
            memory_mounts: context.memory_mounts.clone(),
            mounts: context.mounts.clone(),
        };

        if let (Some(session_id), Some(workspace_root)) =
            (context.session_id, &self.config.sandbox_workspace_root)
        {
            let workspace_path = format!("{workspace_root}/{session_id}");
            let injection_context = crate::sandbox::file_injection::FileInjectionContext {
                session_id,
                external_id: String::new(),
                workspace_path: Some(workspace_path),
                runner_capabilities: vec![],
                is_pool_sandbox: false,
            };
            crate::sandbox::file_injection::inject_session_files(
                &self.pool,
                &injection_context,
                self.provider.as_ref(),
            )
            .await
            .map_err(|error| {
                anyhow::anyhow!(
                    "failed to inject session files into workspace before sandbox create for session {session_id}: {error}"
                )
            })?;
        }

        let admission_config = provisioning_config(
            "runner_admission",
            10,
            "Runner admission staged before provider creation",
            false,
            &expected,
            Some(&egress_proxy_token),
        );
        let sandbox_config = provisioning_config(
            "container_started",
            70,
            "Sandbox created, waiting for runner ready",
            false,
            &expected,
            Some(&egress_proxy_token),
        );

        queries::stage_sandbox(
            &self.pool,
            sandbox_id,
            self.config.sandbox_provider.as_str(),
            &image,
            context.session_id,
            context.project_id,
            create_config.workspace_path.as_deref(),
            Some(&admission_config),
            &runner_token_digest,
            runner_auth_expires_at,
            context
                .session_id
                .map(|_| context.runtime_config_generation),
        )
        .await?;

        let external_id = match self.provider.create(&create_config).await {
            Ok(external_id) => external_id,
            Err(error) => {
                self.lifecycle
                    .cleanup_staged_create(sandbox_id, None)
                    .await?;
                return Err(error);
            }
        };

        match queries::activate_staged_sandbox(
            &self.pool,
            sandbox_id,
            &external_id,
            &sandbox_config,
            context.session_id,
            context.project_id,
            context
                .session_id
                .map(|_| context.runtime_config_generation),
        )
        .await
        {
            Ok(true) => {}
            Ok(false) => {
                self.lifecycle
                    .cleanup_staged_create(sandbox_id, Some(&external_id))
                    .await?;
                return Err(RuntimeFreshnessError::Conflict(format!(
                    "sandbox {sandbox_id} admission expired or changed before activation"
                ))
                .into());
            }
            Err(error) => {
                self.lifecycle
                    .cleanup_staged_create(sandbox_id, Some(&external_id))
                    .await?;
                return Err(error.into());
            }
        }

        if !create_config.start_immediately {
            if let Err(error) = self.provider.start(&external_id).await {
                self.lifecycle
                    .cleanup_rejected_create(sandbox_id, &external_id, None)
                    .await?;
                return Err(error.context("failed to start sandbox after control-plane setup"));
            }
            info!(sandbox_id = %sandbox_id, external_id = %external_id, "Started sandbox before egress policy application");
        }

        if limited_networking {
            if !self.provider.capabilities().has_egress_management {
                self.lifecycle
                    .cleanup_rejected_create(sandbox_id, &external_id, None)
                    .await?;
                anyhow::bail!(
                    "limited sandbox networking requires egress management, but provider does not support it"
                );
            }

            let policy_generation = match queries::prepare_generation(
                &self.pool,
                sandbox_id,
                &context.expected.egress_policy_hash,
            )
            .await
            {
                Ok(outcome) => outcome.into_generation(),
                Err(error) => {
                    self.lifecycle
                        .cleanup_rejected_create(sandbox_id, &external_id, None)
                        .await?;
                    return Err(anyhow::anyhow!(
                        "failed to mark sandbox network policy pending: {error}"
                    ));
                }
            };

            if let Err(error) = self
                .networking
                .apply_prepared(
                    sandbox_id,
                    &policy_generation,
                    PreparedSandboxNetworking {
                        credentials: &context.credentials,
                        identity_lease: context.has_task_identity().then_some(
                            TaskIdentityNetworkLease {
                                task_id,
                                refresh_after_seconds: context.identity_refresh_after_seconds,
                            },
                        ),
                        proxy_auth_token: Some(egress_proxy_token.clone()),
                    },
                )
                .await
            {
                if self
                    .lifecycle
                    .cleanup_rejected_create(sandbox_id, &external_id, Some(&policy_generation))
                    .await?
                {
                    return Err(error.context("failed to setup Envoy networking for new sandbox"));
                }
                info!(sandbox_id = %sandbox_id, policy_version = policy_generation.policy_version, "Adopted concurrently ready network policy after stale apply result");
            }
        }

        let transitioned =
            queries::transition_sandbox_cas(&self.pool, sandbox_id, "creating", "provisioning")
                .await?;
        if !transitioned
            && self
                .lifecycle
                .active_status(sandbox_id, &external_id)
                .await?
                .is_none()
        {
            warn!(sandbox_id = %sandbox_id, "Skipped provider destroy because DB row changed before provisioning transition");
            anyhow::bail!("sandbox {sandbox_id} changed state before provisioning transition");
        }

        info!(sandbox_id = %sandbox_id, external_id = %external_id, task_id = %task_id, "Created new sandbox");
        Ok(context.resolved(sandbox_id, external_id))
    }
}
