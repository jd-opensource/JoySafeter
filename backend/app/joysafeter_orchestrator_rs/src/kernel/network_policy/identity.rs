use agent_identity_trait::AgentIdentityInjection;

use super::envoy_model::EgressCredentialRoute;

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub(crate) enum IdentityRouteMergeError {
    #[error("task identity injection does not match the desired network route")]
    RouteMismatch,
}

pub(crate) fn merge_identity_injection(
    routes: &mut [EgressCredentialRoute],
    injection: AgentIdentityInjection,
) -> Result<(), IdentityRouteMergeError> {
    for target in injection.targets {
        let route = routes
            .iter_mut()
            .find(|route| route.id == target.route_id)
            .ok_or(IdentityRouteMergeError::RouteMismatch)?;
        if !route.upstream_host.eq_ignore_ascii_case(&target.host)
            || route.upstream_port != target.port
            || route.upstream_tls != target.tls
        {
            return Err(IdentityRouteMergeError::RouteMismatch);
        }
        for (name, value) in &target.inject_headers {
            route
                .inject_headers
                .retain(|(existing, _)| !existing.eq_ignore_ascii_case(name));
            route.inject_headers.push((name.clone(), value.clone()));
        }
        for header in &target.remove_headers {
            if !route
                .remove_headers
                .iter()
                .any(|existing| existing.eq_ignore_ascii_case(header))
            {
                route.remove_headers.push(header.clone());
            }
        }
    }
    Ok(())
}
