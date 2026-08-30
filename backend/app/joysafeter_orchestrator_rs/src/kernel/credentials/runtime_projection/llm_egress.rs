use std::collections::HashMap;
use std::net::IpAddr;

use tracing::warn;
use url::Url;

use crate::kernel::llm_catalog::RuntimeCredentialBinding;
use crate::kernel::llm_providers::credential_profile_spec;
use crate::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode,
};

/// Extract LLM egress credentials from the resolved env, removing the real
/// key from the env map and repointing the base URL at the Envoy egress
/// boundary. After this, the container env holds no LLM API key — the key is
/// injected by Envoy at the egress boundary instead.
///
/// Credential handling is selected by the Catalog-resolved profile, and
/// provider defaults come from the validated Provider/Protocol binding.
pub(crate) fn extract_llm_egress(
    env: &mut HashMap<String, String>,
    binding: Option<&RuntimeCredentialBinding>,
    allowed_hosts: &[String],
) -> Vec<EgressCredentialRoute> {
    let Some(binding) = binding else {
        return vec![];
    };
    let Some(spec) = credential_profile_spec(&binding.credential_profile_id) else {
        warn!(
            credential_profile_id = %binding.credential_profile_id,
            protocol_id = %binding.protocol_id,
            "LLM credential profile has no runtime routing implementation"
        );
        return vec![];
    };
    let Some(credential_key) = spec
        .credential_keys
        .iter()
        .find(|credential| env.contains_key(credential.key))
    else {
        return vec![];
    };

    let Some(key_value) = env.remove(credential_key.key) else {
        return vec![];
    };

    // Remove all extra keys associated with this provider (unconditional —
    // mirrors the original behavior where Anthropic vars are always removed
    // regardless of which one matched).
    for extra in spec.extra_keys_to_remove {
        env.remove(*extra);
    }

    let base_url_var = binding.base_url_key.as_str();

    // Parse the configured base URL to learn the real upstream
    // host/port/scheme/path. The sandbox is then repointed at the placeholder
    // egress host over plaintext http:// — it never learns the real address.
    // Envoy matches the placeholder, injects the key, host_rewrites to the
    // real upstream, and forwards via that upstream's STRICT_DNS cluster.
    let configured = env
        .get(base_url_var)
        .cloned()
        .or_else(|| binding.default_base_url.clone());
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
            let host = match url.host_str() {
                Some(host) => host.to_string(),
                None => return vec![],
            };
            let tls = url.scheme() == "https";
            let port = url.port().unwrap_or(if tls { 443 } else { 80 });
            let prefix = normalize_llm_upstream_prefix(url.path());
            (host, port, prefix, tls)
        }
        None => {
            warn!(
                base_url_var,
                credential_profile_id = %binding.credential_profile_id,
                protocol_id = %binding.protocol_id,
                "LLM binding requires an explicit base URL"
            );
            return vec![];
        }
    };

    if !is_llm_egress_host_allowed(&upstream_host, allowed_hosts) {
        warn!(
            base_url_var,
            upstream_host = %upstream_host,
            "LLM base URL host is not allowlisted; skipping credential injection"
        );
        return vec![];
    }

    // Insert non-secret placeholder so the agent CLI doesn't fall back to
    // interactive login. Envoy overwrites/removes auth headers at the egress
    // boundary and injects the real credential there.
    if let Some((placeholder_var, placeholder_val)) = spec.placeholder {
        env.insert(placeholder_var.to_string(), placeholder_val.to_string());
    }

    // Repoint the agent at the real upstream host but downgrade to plaintext
    // http:// so the request goes through the HTTP proxy as a normal request
    // (not a CONNECT tunnel). This lets Envoy see and inject headers. Envoy
    // does TLS origination via the shared dynamic_forward_proxy_tls cluster.
    let base_url_for_sandbox = if upstream_tls {
        format!(
            "http://{}:{}{}",
            upstream_host, upstream_port, upstream_prefix
        )
    } else {
        format!(
            "http://{}:{}{}",
            upstream_host, upstream_port, upstream_prefix
        )
    };
    env.insert(base_url_var.to_string(), base_url_for_sandbox);

    let header_value = if credential_key.is_bearer {
        format!("Bearer {key_value}")
    } else {
        key_value
    };

    vec![EgressCredentialRoute {
        id: "llm".to_string(),
        kind: EgressKind::Llm,
        exposure: EgressExposure::Transparent,
        match_host: upstream_host.clone(),
        path_mapping: EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        },
        retry_mode: EgressRetryMode::SafeIdempotent,
        upstream_host,
        upstream_port,
        upstream_tls,
        cluster_name: String::new(),
        vetted_addresses: vec![],
        inject_headers: vec![(credential_key.header_name.to_string(), header_value)],
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
