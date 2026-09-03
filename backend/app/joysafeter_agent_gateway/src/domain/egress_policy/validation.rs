use super::credentials::{domains_for_credential_host, group_credentials_by_host};
use super::model::{EgressPathMapping, EgressPathMatcher, SandboxEgressPolicy};
use crate::ids::SandboxId;

pub fn validate_egress_policy(
    sandbox_id: &SandboxId,
    policy: &SandboxEgressPolicy,
) -> anyhow::Result<()> {
    let mut route_ids = std::collections::HashSet::new();
    const SHARED_CLUSTERS: &[&str] = &["dynamic_forward_proxy", "dynamic_forward_proxy_tls"];
    let pinned_clusters = policy
        .clusters(sandbox_id)
        .into_iter()
        .map(|cluster| cluster.name)
        .collect::<std::collections::HashSet<_>>();

    for host in &policy.allowlist_hosts {
        validate_route_host(host)
            .map_err(|e| anyhow::anyhow!("invalid allowlist host {host}: {e}"))?;
    }

    for route in &policy.credential_routes {
        if !route_ids.insert(route.id.as_str()) {
            anyhow::bail!("duplicate egress route id: {}", route.id);
        }
        validate_route_host(&route.match_host)
            .map_err(|e| anyhow::anyhow!("invalid egress match_host {}: {e}", route.match_host))?;
        validate_route_host(&route.upstream_host).map_err(|e| {
            anyhow::anyhow!("invalid egress upstream_host {}: {e}", route.upstream_host)
        })?;
        match &route.path_mapping {
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any,
            } => {}
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Exact(path),
            }
            | EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix(path),
            } => validate_route_path(path)
                .map_err(|e| anyhow::anyhow!("invalid egress path {path}: {e}"))?,
            EgressPathMapping::RewriteExact {
                exposed_path,
                upstream_path,
            }
            | EgressPathMapping::RewritePrefix {
                exposed_prefix: exposed_path,
                upstream_prefix: upstream_path,
            } => {
                validate_route_path(exposed_path).map_err(|e| {
                    anyhow::anyhow!("invalid exposed egress path {exposed_path}: {e}")
                })?;
                validate_route_path(upstream_path).map_err(|e| {
                    anyhow::anyhow!("invalid upstream egress path {upstream_path}: {e}")
                })?;
            }
        }
        if route.cluster_name.is_empty()
            || (!SHARED_CLUSTERS.contains(&route.cluster_name.as_str())
                && !pinned_clusters.contains(&route.cluster_name))
        {
            anyhow::bail!(
                "egress route {} references unknown cluster {}",
                route.id,
                route.cluster_name
            );
        }
        for address in &route.vetted_addresses {
            address.parse::<std::net::IpAddr>().map_err(|_| {
                anyhow::anyhow!("invalid vetted address {address} on route {}", route.id)
            })?;
        }
        for (header, _) in &route.inject_headers {
            validate_header_name(header).map_err(|e| {
                anyhow::anyhow!(
                    "invalid injected header {header} on route {}: {e}",
                    route.id
                )
            })?;
        }
        for header in &route.remove_headers {
            validate_header_name(header).map_err(|e| {
                anyhow::anyhow!("invalid removed header {header} on route {}: {e}", route.id)
            })?;
        }
    }

    let mut domains = std::collections::HashMap::<String, String>::new();
    let credential_match_hosts: Vec<String> = policy
        .credential_routes
        .iter()
        .map(|route| canonical_policy_host(&route.match_host))
        .collect::<anyhow::Result<Vec<_>>>()?;
    for (host, routes) in group_credentials_by_host(&policy.credential_routes) {
        for domain in domains_for_credential_host(&host, &routes) {
            let domain = canonical_policy_domain(&domain)?;
            if let Some(existing) = domains.insert(domain.clone(), format!("credential:{host}")) {
                anyhow::bail!("duplicate Envoy virtual-host domain {domain} between {existing} and credential:{host}");
            }
        }
    }
    for host in &policy.allowlist_hosts {
        for credential_host in &credential_match_hosts {
            if allowlist_host_covers_credential_host(host, credential_host)? {
                anyhow::bail!(
                    "allowlist host {host} overlaps credential-injection host {credential_host}; remove it to prevent CONNECT/plain egress bypass"
                );
            }
        }
        for domain in domains_for_allowlist_host(host) {
            let domain = canonical_policy_domain(&domain)?;
            if let Some(existing) = domains.insert(domain.clone(), "allowlist".to_string()) {
                anyhow::bail!(
                    "duplicate Envoy virtual-host domain {domain} between {existing} and allowlist"
                );
            }
        }
    }
    Ok(())
}

fn domains_for_allowlist_host(host: &str) -> Vec<String> {
    let mut domains = vec![host.to_string()];
    if !host.contains(':') {
        domains.push(format!("{host}:443"));
        domains.push(format!("{host}:80"));
    }
    domains
}

fn canonical_policy_domain(domain: &str) -> anyhow::Result<String> {
    let trimmed = domain.trim().trim_end_matches('.').to_ascii_lowercase();
    validate_route_host(&trimmed)?;
    Ok(trimmed)
}

fn canonical_policy_host(host: &str) -> anyhow::Result<String> {
    let domain = canonical_policy_domain(host)?;
    Ok(domain
        .rsplit_once(':')
        .and_then(|(base, port)| port.parse::<u16>().ok().map(|_| base.to_string()))
        .unwrap_or(domain))
}

fn allowlist_host_covers_credential_host(
    allowlist_host: &str,
    credential_host: &str,
) -> anyhow::Result<bool> {
    let allow = canonical_policy_host(allowlist_host)?;
    let credential = canonical_policy_host(credential_host)?;
    if allow == credential {
        return Ok(true);
    }
    if let Some(suffix) = allow.strip_prefix("*.") {
        return Ok(credential == suffix || credential.ends_with(&format!(".{suffix}")));
    }
    Ok(false)
}

fn validate_route_host(host: &str) -> anyhow::Result<()> {
    let trimmed = host.trim();
    if trimmed.is_empty() {
        anyhow::bail!("host is empty");
    }
    if trimmed.contains('/') || trimmed.contains(' ') || trimmed.contains('\t') {
        anyhow::bail!("host must not contain path, whitespace, or scheme");
    }
    if trimmed.contains("://") {
        anyhow::bail!("host must not include scheme");
    }
    Ok(())
}

fn validate_route_path(path: &str) -> anyhow::Result<()> {
    if !path.starts_with('/') {
        anyhow::bail!("path must start with '/'");
    }
    if path.contains('\n') || path.contains('\r') || path.contains('\0') {
        anyhow::bail!("path contains control characters");
    }
    Ok(())
}

fn validate_header_name(name: &str) -> anyhow::Result<()> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        anyhow::bail!("header name is empty");
    }
    if !trimmed.bytes().all(|byte| {
        byte.is_ascii_alphanumeric()
            || matches!(
                byte,
                b'!' | b'#'
                    | b'$'
                    | b'%'
                    | b'&'
                    | b'\''
                    | b'*'
                    | b'+'
                    | b'-'
                    | b'.'
                    | b'^'
                    | b'_'
                    | b'`'
                    | b'|'
                    | b'~'
            )
    }) {
        anyhow::bail!("header name is not a valid HTTP token");
    }
    Ok(())
}
