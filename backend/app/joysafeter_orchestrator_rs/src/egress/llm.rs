use std::collections::HashMap;
use std::net::IpAddr;

use tracing::warn;
use url::Url;

use crate::egress::policy::{
    normalize_rewrite_base_prefix, CredentialRef, EgressCredentialRoute, EgressExposure,
    EgressKind, InjectScheme, LLM_EGRESS_HOST,
};
use crate::kernel::llm_providers::llm_provider_registry;

/// Where a Secret-backed LLM credential env var came from. Built by the
/// resolver's env merge (see `SandboxResolver::merge_secret_ref_into_env`) and
/// consumed here so the credential value never rides the sandbox env: instead of
/// injecting the decrypted key, we emit a non-secret [`CredentialRef::Llm`].
#[derive(Debug, Clone)]
pub(crate) struct LlmSecretSource {
    pub secret_name: String,
    pub project_id: Option<String>,
}

/// Maps an LLM credential env-var name (e.g. `"ANTHROPIC_API_KEY"`) to the
/// managed Secret it was sourced from. A credential key absent from this map was
/// not sourced from a Secret (a plaintext literal) and is refused.
pub(crate) type LlmCredentialProvenance = HashMap<String, LlmSecretSource>;

/// Extract the LLM egress route from the resolved env, removing any real key
/// from the env map and repointing the base URL at the platform egress
/// boundary. After this, the sandbox env holds no real LLM API key — only a
/// non-secret placeholder — and the returned route carries a non-secret
/// [`CredentialRef::Llm`] that the `CredentialBroker` resolves at request time.
///
/// Provider detection is data-driven via [`llm_provider_registry`]: the first
/// spec whose detection key is present in `env` wins. The upstream host is
/// derived from the corresponding `*_BASE_URL` (using the spec's default when
/// unset), then the base URL is rewritten to the plaintext egress placeholder.
///
/// **LLM credentials must be Secret-backed.** If the matched credential key has
/// no entry in `provenance` (it was a plaintext literal from `agent.env` /
/// `environment.env_vars`, not a managed Secret), this refuses to inject and
/// returns no route (fail closed) — the real key is still stripped from `env`.
pub(crate) fn extract_llm_egress(
    env: &mut HashMap<String, String>,
    provenance: &LlmCredentialProvenance,
    allowed_hosts: &[String],
) -> Vec<EgressCredentialRoute> {
    let registry = llm_provider_registry();
    let (spec, matched_key) = match registry.iter().find_map(|spec| {
        spec.detection_keys
            .iter()
            .find(|k| env.contains_key(**k))
            .map(|k| (spec, *k))
    }) {
        Some(pair) => pair,
        None => return vec![],
    };

    // Strip the real key (and provider aliases) from the sandbox env regardless
    // of outcome: the sandbox must never hold the credential value.
    if env.remove(matched_key).is_none() {
        return vec![];
    }
    for extra in spec.extra_keys_to_remove {
        env.remove(*extra);
    }

    // The LLM credential must come from a managed Secret so we can emit a
    // non-secret reference. A plaintext literal has no resolvable identity.
    let Some(source) = provenance.get(matched_key) else {
        warn!(
            credential_key = matched_key,
            "LLM credential is not Secret-backed (plaintext literal); refusing to \
             inject. Configure the model API key as a managed Secret."
        );
        return vec![];
    };

    let base_url_var = spec.base_url_var;
    let default_host = spec.default_host;
    let configured = env.get(base_url_var).cloned();
    let (upstream_host, upstream_port, upstream_prefix, upstream_tls) = match configured.as_deref()
    {
        Some(raw) => {
            let url = match Url::parse(raw) {
                Ok(url) => url,
                Err(e) => {
                    warn!(base_url_var, error = %e, "Invalid LLM base URL; skipping credential injection");
                    return vec![];
                }
            };
            if url.scheme() != "http" && url.scheme() != "https" {
                warn!(
                    base_url_var,
                    scheme = url.scheme(),
                    "Unsupported LLM base URL scheme; skipping credential injection"
                );
                return vec![];
            }
            let host = match (url.host_str(), default_host) {
                (Some(h), _) => h.to_string(),
                (None, Some(d)) => d.to_string(),
                (None, None) => return vec![],
            };
            let tls = url.scheme() == "https";
            let port = url.port().unwrap_or(if tls { 443 } else { 80 });
            let prefix = normalize_llm_upstream_prefix(url.path());
            (host, port, prefix, tls)
        }
        None => match default_host {
            Some(d) => (d.to_string(), 443, "/".to_string(), true),
            None => {
                warn!(
                    base_url_var,
                    "LLM provider requires an explicit base URL (no fixed \
                     endpoint); skipping credential injection"
                );
                return vec![];
            }
        },
    };

    if !is_llm_egress_host_allowed(&upstream_host, allowed_hosts) {
        warn!(
            base_url_var,
            upstream_host = %upstream_host,
            "LLM base URL host is not allowlisted; skipping credential injection"
        );
        return vec![];
    }

    if let Some((placeholder_var, placeholder_val)) = spec.placeholder {
        env.insert(placeholder_var.to_string(), placeholder_val.to_string());
    }

    env.insert(
        base_url_var.to_string(),
        format!("http://{LLM_EGRESS_HOST}"),
    );

    let inject_scheme = if spec.is_bearer {
        InjectScheme::Bearer
    } else {
        InjectScheme::Raw
    };

    vec![EgressCredentialRoute {
        id: "llm".to_string(),
        kind: EgressKind::Llm,
        exposure: EgressExposure::Placeholder,
        match_host: LLM_EGRESS_HOST.to_string(),
        match_prefix: "/".to_string(),
        exact_path: false,
        upstream_host,
        upstream_port,
        upstream_prefix: normalize_rewrite_base_prefix(&upstream_prefix),
        upstream_tls,
        cluster_name: String::new(),
        credential_ref: CredentialRef::Llm {
            secret_name: source.secret_name.clone(),
            secret_key: matched_key.to_string(),
            project_id: source.project_id.clone(),
        },
        inject_header: spec.header_name.to_string(),
        inject_scheme,
        remove_headers: vec![],
    }]
}

fn normalize_llm_upstream_prefix(path: &str) -> String {
    if path.is_empty() || path == "/" {
        return "/".to_string();
    }

    let mut prefix = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

fn is_llm_egress_host_allowed(host: &str, allowed_hosts: &[String]) -> bool {
    let Some(host) = normalize_llm_host(host) else {
        return false;
    };

    if is_blocked_llm_host(&host) {
        return false;
    }

    allowed_hosts
        .iter()
        .filter_map(|entry| normalize_llm_host_pattern(entry))
        .any(|pattern| llm_host_matches_pattern(&host, &pattern))
}

fn normalize_llm_host(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, false)
}

fn normalize_llm_host_pattern(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, true)
}

fn normalize_llm_host_inner(raw: &str, allow_wildcard: bool) -> Option<String> {
    let mut value = raw.trim().to_ascii_lowercase();
    if value.is_empty() {
        return None;
    }

    if value.contains("://") {
        value = Url::parse(&value).ok()?.host_str()?.to_string();
    } else {
        if let Some((before_path, _)) = value.split_once('/') {
            value = before_path.to_string();
        }
        if value.starts_with('[') {
            let end = value.find(']')?;
            value = value[1..end].to_string();
        } else if let Some((host, port)) = value.rsplit_once(':') {
            if !host.contains(':') && port.parse::<u16>().is_ok() {
                value = host.to_string();
            }
        }
    }

    value = value.trim_matches('.').to_string();
    if value.is_empty() {
        return None;
    }

    if value.starts_with("*.") {
        if !allow_wildcard {
            return None;
        }
        let suffix = value.trim_start_matches("*.");
        if suffix.is_empty() || suffix.contains('*') {
            return None;
        }
        return Some(format!("*.{suffix}"));
    }

    if value.contains('*') {
        return None;
    }

    Some(value)
}

fn llm_host_matches_pattern(host: &str, pattern: &str) -> bool {
    if let Some(suffix) = pattern.strip_prefix("*.") {
        return host != suffix && host.ends_with(&format!(".{suffix}"));
    }

    host == pattern
}

fn is_blocked_llm_host(host: &str) -> bool {
    if host == "localhost" || host.ends_with(".localhost") {
        return true;
    }

    host.parse::<IpAddr>()
        .map(is_blocked_llm_ip)
        .unwrap_or(false)
}

fn is_blocked_llm_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let octets = ip.octets();
            octets[0] == 0
                || octets[0] == 10
                || octets[0] == 127
                || (octets[0] == 100 && (64..=127).contains(&octets[1]))
                || (octets[0] == 169 && octets[1] == 254)
                || (octets[0] == 172 && (16..=31).contains(&octets[1]))
                || (octets[0] == 192 && octets[1] == 168)
                || (octets[0] == 198 && (18..=19).contains(&octets[1]))
                || octets[0] >= 224
        }
        IpAddr::V6(ip) => {
            let segments = ip.segments();
            let first = segments[0];
            ip.is_loopback()
                || ip.is_unspecified()
                || (first & 0xfe00) == 0xfc00
                || (first & 0xffc0) == 0xfe80
                || (first & 0xff00) == 0xff00
        }
    }
}
