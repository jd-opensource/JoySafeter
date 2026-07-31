/// Data-driven LLM provider credential registry.
///
/// Each entry describes how to detect, extract, and route an LLM provider's
/// credentials through the Envoy egress boundary. Adding a new provider
/// (Mistral, DeepSeek, etc.) is a one-line table entry rather than a new
/// if/else branch in `extract_llm_egress`.

/// Specification for a single LLM provider's credential handling.
pub struct LlmProviderSpec {
    /// Env var(s) whose presence signals this provider. First present one wins;
    /// order within the registry defines precedence (matches original if/else order).
    pub detection_keys: &'static [&'static str],

    /// Env var holding the base URL.
    pub base_url_var: &'static str,

    /// Default upstream host when no base URL configured. `None` means the
    /// provider requires an explicit base URL (e.g. Azure: every resource is
    /// `<name>.openai.azure.com`).
    pub default_host: Option<&'static str>,

    /// HTTP header to inject the credential into.
    pub header_name: &'static str,

    /// `true` => format as `"Bearer {key}"`, `false` => raw key value.
    pub is_bearer: bool,

    /// Extra env vars to unconditionally remove after extraction (beyond the
    /// matched detection key). For Anthropic, both `ANTHROPIC_API_KEY` and
    /// `ANTHROPIC_AUTH_TOKEN` are always removed regardless of which one matched.
    pub extra_keys_to_remove: &'static [&'static str],

    /// Placeholder `(var, value)` to insert into the container env so the
    /// agent CLI doesn't fall back to interactive login. `None` = no placeholder.
    /// The placeholder value is deliberately non-secret; Envoy replaces it at
    /// the egress boundary.
    pub placeholder: Option<(&'static str, &'static str)>,
}

/// Non-secret placeholder so Claude Code doesn't trigger /login flow.
pub const CLAUDE_CODE_PLACEHOLDER_API_KEY: &str = "joysafeter-placeholder-anthropic-api-key";
/// Non-secret placeholder for Codex/OpenAI-compatible CLIs.
pub const CODEX_PLACEHOLDER_OPENAI_API_KEY: &str = "joysafeter-placeholder-openai-api-key";

/// Returns the ordered registry of LLM providers. Precedence matches the
/// original if/else chain: first spec whose detection key is present in the
/// env wins.
pub fn llm_provider_registry() -> &'static [LlmProviderSpec] {
    static REGISTRY: &[LlmProviderSpec] = &[
        // 1. ANTHROPIC_AUTH_TOKEN — gateway/internal Bearer style.
        LlmProviderSpec {
            detection_keys: &["ANTHROPIC_AUTH_TOKEN"],
            base_url_var: "ANTHROPIC_BASE_URL",
            default_host: Some("api.anthropic.com"),
            header_name: "authorization",
            is_bearer: true,
            extra_keys_to_remove: &["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            placeholder: Some(("ANTHROPIC_API_KEY", CLAUDE_CODE_PLACEHOLDER_API_KEY)),
        },
        // 2. ANTHROPIC_API_KEY — official x-api-key style.
        LlmProviderSpec {
            detection_keys: &["ANTHROPIC_API_KEY"],
            base_url_var: "ANTHROPIC_BASE_URL",
            default_host: Some("api.anthropic.com"),
            header_name: "x-api-key",
            is_bearer: false,
            extra_keys_to_remove: &["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            placeholder: Some(("ANTHROPIC_API_KEY", CLAUDE_CODE_PLACEHOLDER_API_KEY)),
        },
        // 3. OPENAI_API_KEY — Bearer authorization.
        LlmProviderSpec {
            detection_keys: &["OPENAI_API_KEY"],
            base_url_var: "OPENAI_BASE_URL",
            default_host: Some("api.openai.com"),
            header_name: "authorization",
            is_bearer: true,
            extra_keys_to_remove: &["OPENAI_API_KEY"],
            placeholder: Some(("OPENAI_API_KEY", CODEX_PLACEHOLDER_OPENAI_API_KEY)),
        },
        // 4. GEMINI_API_KEY / GOOGLE_API_KEY — Google Generative Language API.
        LlmProviderSpec {
            detection_keys: &["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            base_url_var: "GOOGLE_GEMINI_BASE_URL",
            default_host: Some("generativelanguage.googleapis.com"),
            header_name: "x-goog-api-key",
            is_bearer: false,
            extra_keys_to_remove: &["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            placeholder: None,
        },
        // 5. AZURE_OPENAI_API_KEY — raw api-key header, no fixed endpoint.
        LlmProviderSpec {
            detection_keys: &["AZURE_OPENAI_API_KEY"],
            base_url_var: "AZURE_OPENAI_BASE_URL",
            default_host: None,
            header_name: "api-key",
            is_bearer: false,
            extra_keys_to_remove: &["AZURE_OPENAI_API_KEY"],
            placeholder: None,
        },
    ];
    REGISTRY
}

/// Returns true when an environment entry contains a real LLM provider secret
/// that must not be serialized into sandbox manifests. Non-secret placeholders
/// are explicitly allowed so CLIs can avoid interactive login while the egress
/// boundary injects real credentials.
pub fn is_real_llm_secret_env(key: &str, value: &str) -> bool {
    for spec in llm_provider_registry() {
        let sensitive = spec
            .detection_keys
            .iter()
            .chain(spec.extra_keys_to_remove.iter())
            .any(|candidate| *candidate == key);
        if !sensitive {
            continue;
        }
        if let Some((placeholder_key, placeholder_value)) = spec.placeholder {
            if key == placeholder_key && value == placeholder_value {
                return false;
            }
        }
        return true;
    }
    false
}
