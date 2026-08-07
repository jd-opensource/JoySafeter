/// Catalog credential-profile routing for the Envoy egress boundary.

/// Non-secret placeholder so Claude Code doesn't trigger /login flow.
pub const CLAUDE_CODE_PLACEHOLDER_API_KEY: &str = "joysafeter-placeholder-anthropic-api-key";
/// Non-secret placeholder for Codex/OpenAI-compatible CLIs.
pub const CODEX_PLACEHOLDER_OPENAI_API_KEY: &str = "joysafeter-placeholder-openai-api-key";

pub struct CredentialKeySpec {
    pub key: &'static str,
    pub header_name: &'static str,
    pub is_bearer: bool,
}

pub struct CredentialProfileSpec {
    pub profile_id: &'static str,
    pub credential_keys: &'static [CredentialKeySpec],
    pub extra_keys_to_remove: &'static [&'static str],
    pub placeholder: Option<(&'static str, &'static str)>,
}

pub fn credential_profile_registry() -> &'static [CredentialProfileSpec] {
    static ANTHROPIC_KEYS: &[CredentialKeySpec] = &[
        CredentialKeySpec {
            key: "ANTHROPIC_AUTH_TOKEN",
            header_name: "authorization",
            is_bearer: true,
        },
        CredentialKeySpec {
            key: "ANTHROPIC_API_KEY",
            header_name: "x-api-key",
            is_bearer: false,
        },
    ];
    static OPENAI_KEYS: &[CredentialKeySpec] = &[CredentialKeySpec {
        key: "OPENAI_API_KEY",
        header_name: "authorization",
        is_bearer: true,
    }];
    static REGISTRY: &[CredentialProfileSpec] = &[
        CredentialProfileSpec {
            profile_id: "anthropic_standard",
            credential_keys: ANTHROPIC_KEYS,
            extra_keys_to_remove: &["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            placeholder: Some(("ANTHROPIC_API_KEY", CLAUDE_CODE_PLACEHOLDER_API_KEY)),
        },
        CredentialProfileSpec {
            profile_id: "openai_bearer",
            credential_keys: OPENAI_KEYS,
            extra_keys_to_remove: &["OPENAI_API_KEY"],
            placeholder: Some(("OPENAI_API_KEY", CODEX_PLACEHOLDER_OPENAI_API_KEY)),
        },
    ];
    REGISTRY
}

pub fn credential_profile_spec(profile_id: &str) -> Option<&'static CredentialProfileSpec> {
    credential_profile_registry()
        .iter()
        .find(|spec| spec.profile_id == profile_id)
}

#[cfg(test)]
mod tests {
    #[test]
    fn every_catalog_credential_profile_has_runtime_routing() {
        let catalog = crate::kernel::llm_catalog::catalog().expect("catalog must parse");

        for profile in &catalog.credential_profiles {
            assert!(
                super::credential_profile_spec(&profile.id).is_some(),
                "missing runtime route for {}",
                profile.id
            );
        }
    }
}
