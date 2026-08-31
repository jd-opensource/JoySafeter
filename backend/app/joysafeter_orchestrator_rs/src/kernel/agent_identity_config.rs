#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AgentIdentityProviderKind {
    None,
    Jd,
}

impl AgentIdentityProviderKind {
    pub fn parse(value: Option<&str>) -> anyhow::Result<Self> {
        match value
            .unwrap_or_default()
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "" | "none" => Ok(Self::None),
            "jd" => Ok(Self::Jd),
            _ => anyhow::bail!("AGENT_IDENTITY_PROVIDER must be one of: none, jd"),
        }
    }

    pub fn validate_feature_availability(self) -> anyhow::Result<Self> {
        if self == Self::Jd && !cfg!(feature = "jd-identity") {
            anyhow::bail!(
                "AGENT_IDENTITY_PROVIDER=jd requires a binary built with the jd-identity feature"
            );
        }
        Ok(self)
    }

    pub fn validate_runtime_policy(self, allowed_hosts: &[String]) -> anyhow::Result<Self> {
        if self == Self::Jd && allowed_hosts.is_empty() {
            anyhow::bail!(
                "AGENT_IDENTITY_PROVIDER=jd requires AGENT_IDENTITY_ALLOWED_HOSTS to contain at least one trusted host"
            );
        }
        Ok(self)
    }
}

#[cfg(test)]
mod tests {
    use super::AgentIdentityProviderKind;

    #[test]
    fn identity_provider_defaults_to_none() {
        assert_eq!(
            AgentIdentityProviderKind::parse(None).unwrap(),
            AgentIdentityProviderKind::None
        );
        assert_eq!(
            AgentIdentityProviderKind::parse(Some("")).unwrap(),
            AgentIdentityProviderKind::None
        );
        assert_eq!(
            AgentIdentityProviderKind::parse(Some("  ")).unwrap(),
            AgentIdentityProviderKind::None
        );
    }

    #[test]
    fn identity_provider_accepts_none_and_jd_case_insensitively() {
        assert_eq!(
            AgentIdentityProviderKind::parse(Some("none")).unwrap(),
            AgentIdentityProviderKind::None
        );
        assert_eq!(
            AgentIdentityProviderKind::parse(Some(" JD ")).unwrap(),
            AgentIdentityProviderKind::Jd
        );
    }

    #[test]
    fn identity_provider_rejects_legacy_and_unknown_values() {
        for value in ["true", "1", "enabled", "unknown"] {
            let error = AgentIdentityProviderKind::parse(Some(value)).unwrap_err();
            assert!(
                error.to_string().contains("AGENT_IDENTITY_PROVIDER"),
                "{value}: {error}"
            );
        }
    }

    #[test]
    fn jd_provider_requires_an_explicit_identity_injection_allowlist() {
        let error = AgentIdentityProviderKind::Jd
            .validate_runtime_policy(&[])
            .unwrap_err();

        assert!(error.to_string().contains("AGENT_IDENTITY_ALLOWED_HOSTS"));
        AgentIdentityProviderKind::Jd
            .validate_runtime_policy(&["crm.example.com".to_string()])
            .unwrap();
        AgentIdentityProviderKind::None
            .validate_runtime_policy(&[])
            .unwrap();
    }

    #[cfg(not(feature = "jd-identity"))]
    #[test]
    fn jd_provider_requires_compiled_feature() {
        let error = AgentIdentityProviderKind::Jd
            .validate_feature_availability()
            .unwrap_err();
        assert!(error.to_string().contains("jd-identity"));
        assert_eq!(
            AgentIdentityProviderKind::None
                .validate_feature_availability()
                .unwrap(),
            AgentIdentityProviderKind::None
        );
    }

    #[cfg(feature = "jd-identity")]
    #[test]
    fn compiled_jd_provider_accepts_both_provider_modes() {
        assert_eq!(
            AgentIdentityProviderKind::Jd
                .validate_feature_availability()
                .unwrap(),
            AgentIdentityProviderKind::Jd
        );
        assert_eq!(
            AgentIdentityProviderKind::None
                .validate_feature_availability()
                .unwrap(),
            AgentIdentityProviderKind::None
        );
    }
}
