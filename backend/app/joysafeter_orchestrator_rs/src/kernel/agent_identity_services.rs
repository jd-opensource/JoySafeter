//! Dynamic trust policy for Agent Identity egress targets.
//!
//! Kubernetes deployments use namespace-scoped `AgentIdentityService` objects
//! as the operator-controlled trust source. Every orchestrator replica keeps an
//! in-memory snapshot through a list/watch stream; request processing never
//! calls the Kubernetes API.

use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::Duration;

use agent_identity_trait::IdentityEgressRequestTarget;
use futures::TryStreamExt;
use kube::api::{ApiResource, DynamicObject, GroupVersionKind};
use kube::runtime::watcher::{self, Event};
use kube::{Api, Client};
use serde::Deserialize;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

const API_GROUP: &str = "security.joysafeter.io";
const API_VERSION: &str = "v1alpha1";
const KIND: &str = "AgentIdentityService";
const INITIAL_SYNC_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, PartialEq, Eq)]
struct TrustedService {
    provider: String,
    host_pattern: String,
    port: u16,
    tls: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AgentIdentityServiceSpec {
    provider: String,
    host: String,
    port: u16,
    tls: bool,
    #[serde(default = "enabled_by_default")]
    enabled: bool,
}

fn enabled_by_default() -> bool {
    true
}

/// Atomically replaceable trust snapshot shared by task-resolution paths.
#[derive(Clone, Default)]
pub(crate) struct AgentIdentityServiceRegistry {
    services: Arc<RwLock<HashMap<String, TrustedService>>>,
}

impl AgentIdentityServiceRegistry {
    pub(crate) fn from_static_hosts(provider: &str, hosts: &[String]) -> Self {
        let services = hosts
            .iter()
            .filter_map(|host| normalize_host_pattern(host).ok())
            .enumerate()
            .map(|(index, host_pattern)| {
                (
                    format!("static-{index}"),
                    TrustedService {
                        provider: provider.trim().to_ascii_lowercase(),
                        host_pattern,
                        port: 0,
                        tls: false,
                    },
                )
            })
            .collect();
        Self {
            services: Arc::new(RwLock::new(services)),
        }
    }

    pub(crate) fn allows(&self, provider: &str, target: &IdentityEgressRequestTarget) -> bool {
        let provider = provider.trim().to_ascii_lowercase();
        let host = normalize_target_host(&target.host);
        self.services
            .read()
            .expect("agent identity service registry poisoned")
            .values()
            .any(|service| {
                service.provider == provider
                    && host_matches(&host, &service.host_pattern)
                    && (service.port == 0 || service.port == target.port)
                    && (service.port == 0 || service.tls == target.tls)
            })
    }

    fn replace(&self, services: HashMap<String, TrustedService>) {
        *self
            .services
            .write()
            .expect("agent identity service registry poisoned") = services;
    }

    fn apply(&self, name: String, service: Option<TrustedService>) {
        let mut services = self
            .services
            .write()
            .expect("agent identity service registry poisoned");
        if let Some(service) = service {
            services.insert(name, service);
        } else {
            services.remove(&name);
        }
    }

    fn remove(&self, name: &str) {
        self.services
            .write()
            .expect("agent identity service registry poisoned")
            .remove(name);
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.services
            .read()
            .expect("agent identity service registry poisoned")
            .len()
    }
}

/// Start a list/watch loop and wait until the first full list has been
/// installed. An empty initial list is valid and remains fail-closed.
pub(crate) async fn start_watcher(
    client: Client,
    namespace: &str,
    provider: &str,
    registry: AgentIdentityServiceRegistry,
) -> anyhow::Result<JoinHandle<()>> {
    let gvk = GroupVersionKind::gvk(API_GROUP, API_VERSION, KIND);
    let resource = ApiResource::from_gvk(&gvk);
    let api: Api<DynamicObject> = Api::namespaced_with(client, namespace, &resource);
    let provider = provider.trim().to_ascii_lowercase();
    let (initial_tx, initial_rx) = oneshot::channel();
    let handle = tokio::spawn(watch_loop(api, provider, registry, Some(initial_tx)));

    match tokio::time::timeout(INITIAL_SYNC_TIMEOUT, initial_rx).await {
        Ok(Ok(())) => Ok(handle),
        Ok(Err(_)) => {
            handle.abort();
            anyhow::bail!("AgentIdentityService watcher exited before initial synchronization")
        }
        Err(_) => {
            handle.abort();
            anyhow::bail!("timed out waiting for initial AgentIdentityService synchronization")
        }
    }
}

async fn watch_loop(
    api: Api<DynamicObject>,
    provider: String,
    registry: AgentIdentityServiceRegistry,
    mut initial_tx: Option<oneshot::Sender<()>>,
) {
    loop {
        info!(provider, "AgentIdentityService watcher starting");
        let mut stream = Box::pin(watcher::watcher(api.clone(), watcher::Config::default()));
        let mut staging = HashMap::new();

        loop {
            match stream.try_next().await {
                Ok(Some(Event::Init)) => staging.clear(),
                Ok(Some(Event::InitApply(object))) => {
                    stage_object(&provider, &mut staging, object);
                }
                Ok(Some(Event::InitDone)) => {
                    let service_count = staging.len();
                    registry.replace(std::mem::take(&mut staging));
                    info!(
                        service_count,
                        provider, "AgentIdentityService snapshot installed"
                    );
                    if let Some(sender) = initial_tx.take() {
                        let _ = sender.send(());
                    }
                }
                Ok(Some(Event::Apply(object))) => apply_object(&provider, &registry, object),
                Ok(Some(Event::Delete(object))) => {
                    if let Some(name) = object.metadata.name.as_deref() {
                        registry.remove(name);
                        info!(
                            service = name,
                            "AgentIdentityService removed from trust snapshot"
                        );
                    }
                }
                Ok(None) => {
                    warn!("AgentIdentityService watch stream ended; restarting");
                    break;
                }
                Err(error) => {
                    warn!(error = %error, "AgentIdentityService watch failed; restarting in 5s");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                    break;
                }
            }
        }
    }
}

fn stage_object(
    provider: &str,
    staging: &mut HashMap<String, TrustedService>,
    object: DynamicObject,
) {
    let Some(name) = object.metadata.name.clone() else {
        warn!("ignoring AgentIdentityService without metadata.name");
        return;
    };
    if let Some(service) = parse_service(provider, &name, &object) {
        staging.insert(name, service);
    }
}

fn apply_object(provider: &str, registry: &AgentIdentityServiceRegistry, object: DynamicObject) {
    let Some(name) = object.metadata.name.clone() else {
        warn!("ignoring AgentIdentityService without metadata.name");
        return;
    };
    let service = parse_service(provider, &name, &object);
    let enabled = service.is_some();
    registry.apply(name.clone(), service);
    debug!(
        service = name,
        enabled, "AgentIdentityService trust snapshot updated"
    );
}

fn parse_service(
    active_provider: &str,
    name: &str,
    object: &DynamicObject,
) -> Option<TrustedService> {
    let spec = object
        .data
        .get("spec")
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("spec is missing"));
    let spec = spec.and_then(|value| {
        serde_json::from_value::<AgentIdentityServiceSpec>(value)
            .map_err(|error| anyhow::anyhow!(error))
    });
    let spec = match spec {
        Ok(spec) => spec,
        Err(error) => {
            warn!(service = name, error = %error, "ignoring invalid AgentIdentityService");
            return None;
        }
    };
    let provider = spec.provider.trim().to_ascii_lowercase();
    if !spec.enabled || provider != active_provider {
        return None;
    }
    if spec.port == 0 {
        warn!(service = name, "ignoring AgentIdentityService with port 0");
        return None;
    }
    let host_pattern = match normalize_host_pattern(&spec.host) {
        Ok(host) => host,
        Err(error) => {
            warn!(service = name, error = %error, "ignoring invalid AgentIdentityService host");
            return None;
        }
    };
    Some(TrustedService {
        provider,
        host_pattern,
        port: spec.port,
        tls: spec.tls,
    })
}

fn normalize_target_host(host: &str) -> String {
    host.trim().trim_end_matches('.').to_ascii_lowercase()
}

fn normalize_host_pattern(host: &str) -> anyhow::Result<String> {
    let normalized = normalize_target_host(host);
    let domain = normalized.strip_prefix("*.").unwrap_or(&normalized);
    if domain.is_empty()
        || domain.len() > 253
        || !domain.contains('.')
        || domain.contains('*')
        || domain.parse::<std::net::IpAddr>().is_ok()
        || domain.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        })
    {
        anyhow::bail!("host must be an exact DNS name or a leading '*.' subdomain pattern")
    }
    Ok(normalized)
}

fn host_matches(host: &str, pattern: &str) -> bool {
    if let Some(suffix) = pattern.strip_prefix("*.") {
        host != suffix && host.ends_with(&format!(".{suffix}"))
    } else {
        host == pattern
    }
}

#[cfg(test)]
#[path = "../../tests/unit/agent_identity_services_test.rs"]
mod tests;
