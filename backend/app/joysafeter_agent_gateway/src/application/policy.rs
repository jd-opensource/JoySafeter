use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, CredentialRoute, EgressExposure as ContractExposure,
    EgressKind as ContractKind, PathMapping, RetryMode,
};

use crate::domain::egress_policy::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode, SandboxCredentials, SandboxEgressPolicy,
};
use crate::ids::SandboxId;
use crate::xds::model::DeliveryGeneration;

const MAX_ALLOWLIST_HOSTS: usize = 256;
const MAX_CREDENTIAL_ROUTES: usize = 128;
const MAX_HEADERS_PER_ROUTE: usize = 32;
const MAX_HEADER_VALUE_BYTES: usize = 16 * 1024;
/// Upper bound on the per-sandbox Envoy listener auth token. It is base64 at
/// render time so not an injection vector, but an unbounded value should not be
/// accepted from the management plane. (E4)
const MAX_PROXY_AUTH_TOKEN_BYTES: usize = 4 * 1024;

#[derive(Debug)]
pub struct ValidatedPolicy {
    pub generation: DeliveryGeneration,
    pub policy: SandboxEgressPolicy,
}

impl ValidatedPolicy {
    pub fn from_request(
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> Result<Self, String> {
        validate_generation(&request)?;
        if request.allowlist_hosts.len() > MAX_ALLOWLIST_HOSTS {
            return Err("allowlist contains too many hosts".to_string());
        }
        if request.credential_routes.len() > MAX_CREDENTIAL_ROUTES {
            return Err("policy contains too many credential routes".to_string());
        }
        if request
            .proxy_auth_token
            .as_ref()
            .is_some_and(|token| token.len() > MAX_PROXY_AUTH_TOKEN_BYTES)
        {
            return Err("proxy auth token is too long".to_string());
        }
        let routes = request
            .credential_routes
            .into_iter()
            .map(into_route)
            .collect::<Result<Vec<_>, _>>()?;
        let policy = SandboxCredentials {
            routes,
            proxy_auth_token: request.proxy_auth_token,
        }
        .to_policy(&sandbox_id, request.allowlist_hosts);
        crate::domain::egress_policy::validate_egress_policy(&sandbox_id, &policy)
            .map_err(|error| error.to_string())?;

        Ok(Self {
            generation: DeliveryGeneration {
                policy_hash: request.generation.policy_hash,
                policy_version: request.generation.policy_version,
            },
            policy,
        })
    }
}

fn validate_generation(request: &ApplySandboxPolicyRequest) -> Result<(), String> {
    validate_generation_fields(
        &request.generation.policy_hash,
        request.generation.policy_version,
    )
}

/// Shared generation-field validation so apply and remove enforce the same
/// `(policy_hash, policy_version)` contract. (E4)
pub fn validate_generation_fields(policy_hash: &str, policy_version: i64) -> Result<(), String> {
    if policy_hash.len() != 64
        || !policy_hash
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("policy_hash must be a lowercase SHA-256 hex digest".to_string());
    }
    if policy_version <= 0 {
        return Err("policy_version must be positive".to_string());
    }
    Ok(())
}

fn into_route(route: CredentialRoute) -> Result<EgressCredentialRoute, String> {
    if route.inject_headers.len() > MAX_HEADERS_PER_ROUTE
        || route.remove_headers.len() > MAX_HEADERS_PER_ROUTE
    {
        return Err("credential route contains too many headers".to_string());
    }
    let inject_header_names = route
        .inject_headers
        .iter()
        .map(|header| header.name.as_str())
        .collect::<Vec<_>>();
    if has_duplicate_header_names(&inject_header_names)
        || has_duplicate_header_names(&route.remove_headers)
    {
        return Err("credential route contains duplicate headers".to_string());
    }
    for header in &route.inject_headers {
        if header.value.is_empty() || header.value.len() > MAX_HEADER_VALUE_BYTES {
            return Err("direct-xDS credential header value has an invalid length".to_string());
        }
        if header
            .value
            .bytes()
            .any(|byte| matches!(byte, b'\r' | b'\n' | b'\0'))
        {
            return Err(
                "direct-xDS credential header value contains control characters".to_string(),
            );
        }
    }
    let inject_headers = route
        .inject_headers
        .into_iter()
        .map(|header| (header.name, header.value))
        .collect();
    Ok(EgressCredentialRoute {
        id: route.id,
        kind: match route.kind {
            ContractKind::Llm => EgressKind::Llm,
            ContractKind::Mcp => EgressKind::Mcp,
            ContractKind::Git => EgressKind::Git,
            ContractKind::External => EgressKind::External,
        },
        exposure: match route.exposure {
            ContractExposure::Placeholder => EgressExposure::Placeholder,
            ContractExposure::Transparent => EgressExposure::Transparent,
        },
        match_host: route.match_host,
        path_mapping: into_path_mapping(route.path_mapping),
        retry_mode: match route.retry_mode {
            RetryMode::Disabled => EgressRetryMode::Disabled,
            RetryMode::SafeIdempotent => EgressRetryMode::SafeIdempotent,
        },
        upstream_host: route.upstream_host,
        upstream_port: route.upstream_port,
        upstream_tls: route.upstream_tls,
        cluster_name: String::new(),
        vetted_addresses: route.vetted_addresses,
        inject_headers,
        remove_headers: route.remove_headers,
    })
}

fn has_duplicate_header_names<T: AsRef<str>>(names: &[T]) -> bool {
    let mut seen = std::collections::HashSet::with_capacity(names.len());
    names
        .iter()
        .any(|name| !seen.insert(name.as_ref().to_ascii_lowercase()))
}

fn into_path_mapping(mapping: PathMapping) -> EgressPathMapping {
    match mapping {
        PathMapping::PassthroughAny => EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        },
        PathMapping::PassthroughExact { path } => EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Exact(path),
        },
        PathMapping::PassthroughPrefix { path } => EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Prefix(path),
        },
        PathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } => EgressPathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        },
        PathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        } => EgressPathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        },
    }
}

#[cfg(test)]
#[path = "../../tests/unit/application/policy_test.rs"]
mod tests;
