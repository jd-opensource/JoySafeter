use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;

use crate::config::JoySafeterConfig;
use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
use crate::sandbox::envoy::EnvoyManager;
use crate::sandbox::provider::SandboxProvider;
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::XdsControlPlane;

#[derive(Clone)]
pub struct RuntimeFactoryContext {
    pub xds_authority: XdsAuthority,
    pub xds_control_plane: Option<XdsControlPlane>,
}

pub struct RuntimeComponents {
    pub sandbox_provider: Arc<dyn SandboxProvider>,
    pub network_policy_runtime: Arc<dyn NetworkPolicyRuntime>,
    pub envoy_manager: Option<Arc<EnvoyManager>>,
}

#[async_trait]
pub trait ProviderFactory: Send + Sync {
    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents>;
}

enum RegistryEntry {
    Enabled(Arc<dyn ProviderFactory>),
    Disabled(String),
}

#[derive(Default)]
pub struct ProviderFactoryRegistry {
    entries: HashMap<String, RegistryEntry>,
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
            self.entries.insert(
                name.to_ascii_lowercase(),
                RegistryEntry::Enabled(factory.clone()),
            );
        }
    }

    pub fn register_disabled(&mut self, name: &'static str, reason: impl Into<String>) {
        self.entries.insert(
            name.to_ascii_lowercase(),
            RegistryEntry::Disabled(reason.into()),
        );
    }

    pub async fn build(
        &self,
        provider_name: &str,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        let normalized = if provider_name.trim().is_empty() {
            "docker"
        } else {
            provider_name.trim()
        }
        .to_ascii_lowercase();
        match self.entries.get(&normalized) {
            Some(RegistryEntry::Enabled(factory)) => factory.build(config, context).await,
            Some(RegistryEntry::Disabled(reason)) => {
                anyhow::bail!("sandbox provider {normalized} is disabled: {reason}")
            }
            None => {
                let mut supported = self.entries.keys().cloned().collect::<Vec<_>>();
                supported.sort();
                anyhow::bail!(
                    "unsupported JOYSAFETER_SANDBOX_PROVIDER={normalized}; registered providers: {}",
                    supported.join(", ")
                )
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn disabled_and_unknown_providers_fail_at_registry_boundary() {
        let mut registry = ProviderFactoryRegistry::default();
        registry.register_disabled("disabled", "not installed");
        let config = JoySafeterConfig::from_env();
        let context = RuntimeFactoryContext {
            xds_authority: XdsAuthority::standalone(),
            xds_control_plane: None,
        };

        let disabled = match registry.build("disabled", &config, &context).await {
            Ok(_) => panic!("disabled provider unexpectedly resolved"),
            Err(error) => error,
        };
        assert!(disabled.to_string().contains("not installed"));
        let unknown = match registry.build("missing", &config, &context).await {
            Ok(_) => panic!("unknown provider unexpectedly resolved"),
            Err(error) => error,
        };
        assert!(unknown.to_string().contains("registered providers"));
    }
}
