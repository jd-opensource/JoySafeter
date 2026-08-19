use std::collections::HashSet;
use std::sync::LazyLock;

use serde::Deserialize;
use thiserror::Error;

use super::credentials::contract::CredentialContract;
use super::credentials::error::{credential_material_field, CredentialRuntimeError};

const RAW_CATALOG: &str = include_str!("../../../../config/llm_catalog.yaml");

static CATALOG: LazyLock<Result<LlmCatalog, LlmCatalogError>> =
    LazyLock::new(|| parse_catalog(RAW_CATALOG));

fn default_true() -> bool {
    true
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LlmCatalog {
    pub(crate) version: String,
    pub(crate) protocols: Vec<Protocol>,
    pub(crate) engines: Vec<Engine>,
    pub(crate) credential_profiles: Vec<CredentialProfile>,
    pub(crate) providers: Vec<Provider>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Protocol {
    pub(crate) id: String,
    pub(crate) display_name: String,
    pub(crate) description: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Engine {
    pub(crate) id: String,
    pub(crate) display_name: String,
    #[serde(default = "default_true")]
    pub(crate) enabled: bool,
    pub(crate) supported_protocol_ids: Vec<String>,
    #[serde(default)]
    pub(crate) preferred_protocol_ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CredentialField {
    pub(crate) key: String,
    pub(crate) label: String,
    #[serde(rename = "type")]
    pub(crate) field_type: String,
    #[serde(default)]
    pub(crate) required: bool,
    pub(crate) placeholder: Option<String>,
    pub(crate) help_text: Option<String>,
    #[serde(default)]
    pub(crate) options: Vec<String>,
    #[serde(default)]
    pub(crate) advanced: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CredentialProfile {
    pub(crate) id: String,
    pub(crate) fields: Vec<CredentialField>,
    #[serde(default)]
    pub(crate) required_any_of: Vec<Vec<String>>,
    pub(crate) base_url_key: Option<String>,
    pub(crate) model_key: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Provider {
    pub(crate) id: String,
    pub(crate) display_name: String,
    #[serde(default = "default_true")]
    pub(crate) enabled: bool,
    pub(crate) protocol_bindings: Vec<ProtocolBinding>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProtocolBinding {
    pub(crate) protocol_id: String,
    pub(crate) credential_profile_id: String,
    pub(crate) default_base_url: Option<String>,
    #[serde(default)]
    pub(crate) model_suggestions: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeCredentialBinding {
    pub protocol_id: String,
    pub credential_profile_id: String,
    pub default_base_url: Option<String>,
    pub base_url_key: String,
    pub model_key: Option<String>,
    pub required_material_fields: Vec<String>,
    pub required_material_alternatives: Vec<Vec<String>>,
}

pub fn validate_runtime_secret_material(
    binding: &RuntimeCredentialBinding,
    material: &serde_json::Map<String, serde_json::Value>,
) -> Result<(), CredentialRuntimeError> {
    for field in &binding.required_material_fields {
        credential_material_field(material, field)?;
    }
    for alternatives in &binding.required_material_alternatives {
        let mut found = false;
        for field in alternatives {
            match credential_material_field(material, field) {
                Ok(_) => found = true,
                Err(CredentialRuntimeError::FieldMissing) => {}
                Err(error) => return Err(error),
            }
        }
        if !found {
            return Err(CredentialRuntimeError::FieldMissing);
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Error, PartialEq, Eq)]
pub enum LlmCatalogError {
    #[error("failed to parse embedded LLM catalog: {message}")]
    CatalogInvalid { message: String },
    #[error("unknown LLM engine: {engine_kind}")]
    EngineUnknown { engine_kind: String },
    #[error("LLM engine is disabled: {engine_kind}")]
    EngineDisabled { engine_kind: String },
    #[error("runtime LLM credential must have kind=model, got {kind}")]
    SecretKindInvalid { kind: String },
    #[error("runtime LLM secret provider is required")]
    ProviderRequired,
    #[error("runtime LLM secret protocol is required")]
    ProtocolRequired,
    #[error("unknown LLM provider: {provider_id}")]
    ProviderUnknown { provider_id: String },
    #[error("LLM provider is disabled: {provider_id}")]
    ProviderDisabled { provider_id: String },
    #[error("unknown LLM protocol: {protocol_id}")]
    ProtocolUnknown { protocol_id: String },
    #[error("provider {provider_id} does not implement protocol {protocol_id}")]
    ProviderProtocolUnsupported {
        provider_id: String,
        protocol_id: String,
    },
    #[error("engine {engine_kind} does not support protocol {protocol_id}")]
    EngineProtocolUnsupported {
        engine_kind: String,
        protocol_id: String,
    },
    #[error("credential profile {profile_id} is missing from the LLM catalog")]
    CredentialProfileMissing { profile_id: String },
}

impl From<serde_yaml::Error> for LlmCatalogError {
    fn from(error: serde_yaml::Error) -> Self {
        Self::CatalogInvalid {
            message: error.to_string(),
        }
    }
}

fn catalog_invalid(message: impl Into<String>) -> LlmCatalogError {
    LlmCatalogError::CatalogInvalid {
        message: message.into(),
    }
}

fn ensure_unique<'a>(
    label: &str,
    values: impl IntoIterator<Item = &'a str>,
) -> Result<(), LlmCatalogError> {
    let mut seen = HashSet::new();
    for value in values {
        if !seen.insert(value) {
            return Err(catalog_invalid(format!("duplicate {label} id: {value}")));
        }
    }
    Ok(())
}

impl LlmCatalog {
    fn validate(&self) -> Result<(), LlmCatalogError> {
        ensure_unique("engine", self.engines.iter().map(|item| item.id.as_str()))?;
        ensure_unique(
            "protocol",
            self.protocols.iter().map(|item| item.id.as_str()),
        )?;
        ensure_unique(
            "provider",
            self.providers.iter().map(|item| item.id.as_str()),
        )?;
        ensure_unique(
            "credential profile",
            self.credential_profiles.iter().map(|item| item.id.as_str()),
        )?;

        let engine_ids = self
            .engines
            .iter()
            .map(|engine| engine.id.as_str())
            .collect::<HashSet<_>>();
        let overlapping_engine_provider_id = self
            .providers
            .iter()
            .map(|provider| provider.id.as_str())
            .find(|provider_id| engine_ids.contains(provider_id));
        if let Some(item_id) = overlapping_engine_provider_id {
            return Err(catalog_invalid(format!(
                "engine and provider ids overlap: {item_id}"
            )));
        }

        let protocol_ids = self
            .protocols
            .iter()
            .map(|protocol| protocol.id.as_str())
            .collect::<HashSet<_>>();
        let profile_ids = self
            .credential_profiles
            .iter()
            .map(|profile| profile.id.as_str())
            .collect::<HashSet<_>>();

        for engine in &self.engines {
            for protocol_id in &engine.supported_protocol_ids {
                if !protocol_ids.contains(protocol_id.as_str()) {
                    return Err(catalog_invalid(format!(
                        "engine '{}' references unknown protocol: {protocol_id}",
                        engine.id
                    )));
                }
            }
            for protocol_id in &engine.preferred_protocol_ids {
                if !engine.supported_protocol_ids.contains(protocol_id) {
                    return Err(catalog_invalid(format!(
                        "engine '{}' preferred protocol is not supported: {protocol_id}",
                        engine.id
                    )));
                }
            }
        }

        for provider in &self.providers {
            ensure_unique(
                &format!("provider '{}' protocol binding", provider.id),
                provider
                    .protocol_bindings
                    .iter()
                    .map(|binding| binding.protocol_id.as_str()),
            )?;
            for binding in &provider.protocol_bindings {
                if !protocol_ids.contains(binding.protocol_id.as_str()) {
                    return Err(catalog_invalid(format!(
                        "provider '{}' references unknown protocol: {}",
                        provider.id, binding.protocol_id
                    )));
                }
                if !profile_ids.contains(binding.credential_profile_id.as_str()) {
                    return Err(catalog_invalid(format!(
                        "provider '{}' references unknown credential profile: {}",
                        provider.id, binding.credential_profile_id
                    )));
                }
            }
        }

        for profile in &self.credential_profiles {
            ensure_unique(
                &format!("credential profile '{}' field", profile.id),
                profile.fields.iter().map(|field| field.key.as_str()),
            )?;
            let field_keys = profile
                .fields
                .iter()
                .map(|field| field.key.as_str())
                .collect::<HashSet<_>>();
            for key in [
                profile.base_url_key.as_deref(),
                profile.model_key.as_deref(),
            ]
            .into_iter()
            .flatten()
            {
                if !field_keys.contains(key) {
                    return Err(catalog_invalid(format!(
                        "credential profile '{}' references unknown field: {key}",
                        profile.id
                    )));
                }
            }
            for group in &profile.required_any_of {
                if group.is_empty() {
                    return Err(catalog_invalid("required_any_of group must not be empty"));
                }
                for key in group {
                    if !field_keys.contains(key.as_str()) {
                        return Err(catalog_invalid(format!(
                            "credential profile '{}' references unknown field: {key}",
                            profile.id
                        )));
                    }
                }
            }
        }

        Ok(())
    }
}

fn parse_catalog(raw: &str) -> Result<LlmCatalog, LlmCatalogError> {
    let catalog: LlmCatalog = serde_yaml::from_str(raw)?;
    catalog.validate()?;
    Ok(catalog)
}

pub(crate) fn catalog() -> Result<&'static LlmCatalog, LlmCatalogError> {
    CATALOG.as_ref().map_err(Clone::clone)
}

fn validate_runtime_secret_with_catalog(
    catalog: &LlmCatalog,
    engine_kind: &str,
    kind: &str,
    provider: Option<&str>,
    protocol: Option<&str>,
) -> Result<RuntimeCredentialBinding, LlmCatalogError> {
    let engine = catalog
        .engines
        .iter()
        .find(|engine| engine.id == engine_kind)
        .ok_or_else(|| LlmCatalogError::EngineUnknown {
            engine_kind: engine_kind.to_string(),
        })?;
    if !engine.enabled {
        return Err(LlmCatalogError::EngineDisabled {
            engine_kind: engine_kind.to_string(),
        });
    }

    if !CredentialContract::embedded().is_model_kind(kind) {
        return Err(LlmCatalogError::SecretKindInvalid {
            kind: kind.to_string(),
        });
    }

    let provider_id = provider
        .filter(|value| !value.trim().is_empty())
        .ok_or(LlmCatalogError::ProviderRequired)?;
    let protocol_id = protocol
        .filter(|value| !value.trim().is_empty())
        .ok_or(LlmCatalogError::ProtocolRequired)?;

    if !catalog
        .protocols
        .iter()
        .any(|protocol| protocol.id == protocol_id)
    {
        return Err(LlmCatalogError::ProtocolUnknown {
            protocol_id: protocol_id.to_string(),
        });
    }

    let provider = catalog
        .providers
        .iter()
        .find(|provider| provider.id == provider_id)
        .ok_or_else(|| LlmCatalogError::ProviderUnknown {
            provider_id: provider_id.to_string(),
        })?;
    if !provider.enabled {
        return Err(LlmCatalogError::ProviderDisabled {
            provider_id: provider_id.to_string(),
        });
    }
    let binding = provider
        .protocol_bindings
        .iter()
        .find(|binding| binding.protocol_id == protocol_id)
        .ok_or_else(|| LlmCatalogError::ProviderProtocolUnsupported {
            provider_id: provider_id.to_string(),
            protocol_id: protocol_id.to_string(),
        })?;

    if !engine
        .supported_protocol_ids
        .iter()
        .any(|supported| supported == protocol_id)
    {
        return Err(LlmCatalogError::EngineProtocolUnsupported {
            engine_kind: engine_kind.to_string(),
            protocol_id: protocol_id.to_string(),
        });
    }

    let profile = catalog
        .credential_profiles
        .iter()
        .find(|profile| profile.id == binding.credential_profile_id)
        .ok_or_else(|| LlmCatalogError::CredentialProfileMissing {
            profile_id: binding.credential_profile_id.clone(),
        })?;

    Ok(RuntimeCredentialBinding {
        protocol_id: binding.protocol_id.clone(),
        credential_profile_id: binding.credential_profile_id.clone(),
        default_base_url: binding.default_base_url.clone(),
        base_url_key: profile
            .base_url_key
            .clone()
            .unwrap_or_else(|| "BASE_URL".to_string()),
        model_key: profile.model_key.clone(),
        required_material_fields: profile
            .fields
            .iter()
            .filter(|field| field.required)
            .map(|field| field.key.clone())
            .collect(),
        required_material_alternatives: profile.required_any_of.clone(),
    })
}

pub fn validate_runtime_secret(
    engine_kind: &str,
    kind: &str,
    provider: Option<&str>,
    protocol: Option<&str>,
) -> Result<RuntimeCredentialBinding, LlmCatalogError> {
    validate_runtime_secret_with_catalog(catalog()?, engine_kind, kind, provider, protocol)
}

#[cfg(test)]
mod tests {
    use super::{
        catalog, parse_catalog, validate_runtime_secret, validate_runtime_secret_with_catalog,
        CredentialContract,
    };

    #[test]
    fn embedded_catalog_parses_with_expected_engine_matrix() {
        let catalog = catalog().expect("embedded LLM catalog must parse");
        let matrix = catalog
            .engines
            .iter()
            .map(|engine| {
                (
                    engine.id.as_str(),
                    engine
                        .supported_protocol_ids
                        .iter()
                        .map(String::as_str)
                        .collect::<Vec<_>>(),
                )
            })
            .collect::<Vec<_>>();

        assert_eq!(
            matrix,
            vec![
                ("claude", vec!["anthropic_messages"]),
                ("codex", vec!["openai_responses"]),
                (
                    "native",
                    vec!["anthropic_messages", "openai_responses", "chat_completions"]
                ),
                (
                    "pi",
                    vec!["anthropic_messages", "openai_responses", "chat_completions"]
                ),
            ]
        );
    }

    #[test]
    fn valid_runtime_secret_resolves_profile_metadata() {
        let model_kind = CredentialContract::embedded()
            .is_model_kind("model")
            .then_some("model")
            .expect("credential domain contract must define model as its first kind");

        let binding = validate_runtime_secret(
            "codex",
            model_kind,
            Some("openai"),
            Some("openai_responses"),
        )
        .expect("OpenAI Responses must be valid for Codex");

        assert_eq!(binding.protocol_id, "openai_responses");
        assert_eq!(binding.credential_profile_id, "openai_bearer");
        assert_eq!(
            binding.default_base_url.as_deref(),
            Some("https://api.openai.com/v1")
        );
        assert_eq!(binding.base_url_key, "OPENAI_BASE_URL");
        assert_eq!(binding.model_key.as_deref(), Some("OPENAI_MODEL"));
    }

    #[test]
    fn invalid_runtime_metadata_is_rejected() {
        assert!(validate_runtime_secret(
            "codex",
            "generic",
            Some("openai"),
            Some("openai_responses")
        )
        .is_err());
        assert!(validate_runtime_secret(
            "codex",
            "model",
            Some("deepseek"),
            Some("openai_responses")
        )
        .is_err());
        assert!(validate_runtime_secret(
            "claude",
            "model",
            Some("openai"),
            Some("openai_responses")
        )
        .is_err());
    }

    #[test]
    fn validation_errors_never_include_secret_values() {
        let secret_value = "sk-never-log-this-value";
        let error =
            validate_runtime_secret("claude", "model", Some("openai"), Some("openai_responses"))
                .expect_err("OpenAI Responses must not be valid for Claude")
                .to_string();

        assert!(!error.contains(secret_value));
        assert!(error.contains("claude"));
        assert!(error.contains("openai_responses"));
    }

    #[test]
    fn disabled_catalog_entries_are_rejected_at_runtime() {
        let raw = include_str!("../../../../config/llm_catalog.yaml")
            .replace("  - id: codex\n", "  - id: codex\n    enabled: false\n")
            .replace("  - id: openai\n", "  - id: openai\n    enabled: false\n");
        let catalog = parse_catalog(&raw).expect("disabled catalog must still parse");

        assert!(validate_runtime_secret_with_catalog(
            &catalog,
            "codex",
            "model",
            Some("openai"),
            Some("openai_responses"),
        )
        .is_err());
    }

    #[test]
    fn embedded_catalog_validation_rejects_broken_references() {
        let raw = include_str!("../../../../config/llm_catalog.yaml").replace(
            "credential_profile_id: openai_bearer",
            "credential_profile_id: missing_profile",
        );

        assert!(parse_catalog(&raw).is_err());
    }

    #[test]
    fn catalog_validation_rejects_overlapping_engine_and_provider_ids() {
        let raw = include_str!("../../../../config/llm_catalog.yaml").replace(
            "  - id: anthropic\n    display_name: Anthropic",
            "  - id: claude\n    display_name: Anthropic",
        );

        let error = parse_catalog(&raw).expect_err("engine and provider ids must not overlap");
        assert!(error
            .to_string()
            .contains("engine and provider ids overlap"));
    }
}
