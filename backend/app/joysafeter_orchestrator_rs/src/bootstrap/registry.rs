use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::agent_gateway::AgentGatewayApi;
use crate::config::JoySafeterConfig;
use crate::kernel::agent_identity_provider::AgentIdentityProvider;
use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
use crate::sandbox::envoy::process::EnvoyProcessSupervisor;
use crate::sandbox::provider::SandboxProvider;
use crate::sandbox::runtime::SandboxSocketProvisioner;
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::XdsControlPlane;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SandboxProviderKey(String);

impl SandboxProviderKey {
    pub fn parse(value: &str) -> Self {
        let normalized = value.trim().to_ascii_lowercase();
        Self(if normalized.is_empty() {
            "docker".to_string()
        } else {
            normalized
        })
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy)]
pub struct SandboxRuntimeTopology {
    pub node_visibility: crate::xds::control_plane::NodeVisibility,
    pub managed_xds_authority_in_multi: bool,
    pub xds_leader_coordination_in_multi: bool,
}

#[derive(Clone)]
pub struct RuntimeFactoryContext {
    pub xds_authority: XdsAuthority,
    pub xds_control_plane: Option<XdsControlPlane>,
    pub agent_gateway: Option<Arc<dyn AgentGatewayApi>>,
    /// When set, the agent-gateway network-policy runtime publishes policy
    /// events to the Redis Stream-backed policy stream.
    pub policy_event_publisher: Option<Arc<crate::grpc::policy_stream::RedisEventPublisher>>,
}

pub struct RuntimeComponents {
    pub sandbox_provider: Arc<dyn SandboxProvider>,
    pub network_policy_runtime: Option<Arc<dyn NetworkPolicyRuntime>>,
    pub socket_provisioner: Option<Arc<dyn SandboxSocketProvisioner>>,
    pub envoy_process: Option<Arc<EnvoyProcessSupervisor>>,
    pub placement_reconciler: Option<tokio::task::JoinHandle<()>>,
}

#[async_trait]
pub trait ProviderFactory: Send + Sync {
    fn topology(&self) -> SandboxRuntimeTopology;

    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents>;
}

pub trait IdentityProviderFactory: Send + Sync {
    fn build(
        &self,
        config: &JoySafeterConfig,
        redis: Option<&redis::Client>,
    ) -> anyhow::Result<Arc<dyn AgentIdentityProvider>>;
}

pub struct ProductionIdentityProviderFactory;

impl IdentityProviderFactory for ProductionIdentityProviderFactory {
    fn build(
        &self,
        config: &JoySafeterConfig,
        redis: Option<&redis::Client>,
    ) -> anyhow::Result<Arc<dyn AgentIdentityProvider>> {
        use crate::kernel::agent_identity_config::AgentIdentityProviderKind;

        match AgentIdentityProviderKind::parse(Some(&config.agent_identity_provider))?
            .validate_feature_availability()?
        {
            AgentIdentityProviderKind::None => Ok(Arc::new(
                crate::kernel::agent_identity_provider::NoopAgentIdentityProvider,
            )),
            AgentIdentityProviderKind::Jd => {
                #[cfg(feature = "jd-identity")]
                {
                    let redis = redis.ok_or_else(|| {
                        anyhow::anyhow!("Redis is required when AGENT_IDENTITY_PROVIDER=jd")
                    })?;
                    Ok(Arc::new(
                        jd_agent_identity::JdAgentIdentityProvider::from_env(redis.clone())?,
                    ))
                }
                #[cfg(not(feature = "jd-identity"))]
                {
                    let _ = redis;
                    anyhow::bail!(
                        "AGENT_IDENTITY_PROVIDER=jd requires a binary built with the jd-identity feature"
                    )
                }
            }
        }
    }
}

pub struct ResolvedSandboxProvider {
    pub key: SandboxProviderKey,
    pub topology: SandboxRuntimeTopology,
    factory: Arc<dyn ProviderFactory>,
}

impl ResolvedSandboxProvider {
    pub async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        self.factory.build(config, context).await
    }
}

#[derive(Default)]
pub struct ProviderFactoryRegistry {
    entries: HashMap<String, Arc<dyn ProviderFactory>>,
}

impl ProviderFactoryRegistry {
    pub fn with_defaults() -> Self {
        let mut registry = Self::default();
        super::runtime_factories::register_defaults(&mut registry);
        registry
    }

    pub fn register(
        &mut self,
        names: impl IntoIterator<Item = &'static str>,
        factory: Arc<dyn ProviderFactory>,
    ) {
        for name in names {
            self.entries
                .insert(name.to_ascii_lowercase(), factory.clone());
        }
    }

    pub fn resolve(&self, provider_name: &str) -> anyhow::Result<ResolvedSandboxProvider> {
        let key = SandboxProviderKey::parse(provider_name);
        match self.entries.get(key.as_str()) {
            Some(factory) => Ok(ResolvedSandboxProvider {
                key,
                topology: factory.topology(),
                factory: factory.clone(),
            }),
            None => {
                let mut supported = self.entries.keys().cloned().collect::<Vec<_>>();
                supported.sort();
                anyhow::bail!(
                    "unsupported JOYSAFETER_SANDBOX_PROVIDER={}; registered providers: {}",
                    key.as_str(),
                    supported.join(", ")
                )
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestFactory;

    #[async_trait]
    impl ProviderFactory for TestFactory {
        fn topology(&self) -> SandboxRuntimeTopology {
            SandboxRuntimeTopology {
                node_visibility: crate::xds::control_plane::NodeVisibility::NodeScoped,
                managed_xds_authority_in_multi: true,
                xds_leader_coordination_in_multi: false,
            }
        }

        async fn build(
            &self,
            _config: &JoySafeterConfig,
            _context: &RuntimeFactoryContext,
        ) -> anyhow::Result<RuntimeComponents> {
            anyhow::bail!("test factory build is not required")
        }
    }

    #[test]
    fn custom_factory_aliases_resolve_to_factory_owned_topology() {
        let mut registry = ProviderFactoryRegistry::default();
        registry.register(["Custom", "custom-alias"], Arc::new(TestFactory));

        let resolved = registry
            .resolve(" CUSTOM-ALIAS ")
            .expect("resolve normalized custom provider");

        assert_eq!(resolved.key.as_str(), "custom-alias");
        assert_eq!(
            resolved.topology.node_visibility,
            crate::xds::control_plane::NodeVisibility::NodeScoped
        );
        assert!(resolved.topology.managed_xds_authority_in_multi);
        assert!(!resolved.topology.xds_leader_coordination_in_multi);
    }

    #[test]
    fn unknown_provider_fails_at_registry_boundary() {
        let registry = ProviderFactoryRegistry::default();
        let unknown = match registry.resolve("missing") {
            Ok(_) => panic!("unknown provider unexpectedly resolved"),
            Err(error) => error,
        };
        assert!(unknown.to_string().contains("registered providers"));
    }
}
