use std::collections::{BTreeMap, BTreeSet};
use std::sync::{LazyLock, Mutex};

use serde_json::{Map, Value};

use crate::ids::CredentialId;

use super::contract::CredentialReferenceContract;
use super::error::CredentialRuntimeError;

const CREDENTIAL_FIELD_MAX_LENGTH: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotSchema {
    LegacyV0,
    V1,
    V2,
}

impl SnapshotSchema {
    fn metric_label(self) -> &'static str {
        match self {
            Self::LegacyV0 => "legacy_v0",
            Self::V1 => "v1",
            Self::V2 => "v2",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncodeVersion {
    V1,
    V2,
}

impl EncodeVersion {
    fn label(self) -> &'static str {
        match self {
            Self::V1 => "v1",
            Self::V2 => "v2",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SnapshotModelReference {
    pub credential_id: CredentialId,
    pub engine_kind: String,
    pub model_id: Option<String>,
    pub source_paths: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnvironmentCredentialReference {
    pub credential_id: CredentialId,
    pub source_path: String,
    pub index: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HttpEgressReference {
    pub credential_id: CredentialId,
    pub endpoint: String,
    pub inject_kind: String,
    pub credential_field: String,
    pub header: Option<String>,
    pub cookie_name: Option<String>,
    pub source_paths: Vec<String>,
    pub index: usize,
    pub name: Option<String>,
    pub allowed_paths: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SnapshotCredentialReference {
    Model(CredentialId),
    Environment(CredentialId),
    HttpEgress {
        credential_id: CredentialId,
        field: String,
    },
}

impl SnapshotCredentialReference {
    pub fn credential_id(&self) -> CredentialId {
        match self {
            Self::Model(credential_id)
            | Self::Environment(credential_id)
            | Self::HttpEgress { credential_id, .. } => *credential_id,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodedSnapshot {
    pub schema: SnapshotSchema,
    pub model: Option<SnapshotModelReference>,
    pub model_credential_override: Option<Option<CredentialId>>,
    pub environment_references: Vec<EnvironmentCredentialReference>,
    pub environment_credential_ids: Vec<CredentialId>,
    pub http_egress: Vec<HttpEgressReference>,
    pub references: Vec<SnapshotCredentialReference>,
}

impl DecodedSnapshot {
    pub fn credential_ids(&self) -> Vec<CredentialId> {
        let mut credential_ids = self
            .references
            .iter()
            .map(SnapshotCredentialReference::credential_id)
            .collect::<Vec<_>>();
        sort_dedup_ids(&mut credential_ids);
        credential_ids
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodedEnvironment {
    pub direct_references: Vec<EnvironmentCredentialReference>,
    pub direct_credential_ids: Vec<CredentialId>,
    pub http_egress: Vec<HttpEgressReference>,
}

impl DecodedEnvironment {
    pub fn credential_ids(&self) -> Vec<CredentialId> {
        let mut credential_ids = self.direct_credential_ids.clone();
        credential_ids.extend(
            self.http_egress
                .iter()
                .map(|reference| reference.credential_id),
        );
        sort_dedup_ids(&mut credential_ids);
        credential_ids
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ReferenceMetricSnapshot {
    pub reader_versions: BTreeMap<(String, String, String), u64>,
    pub persisted_keys: BTreeMap<(String, String, String, String), u64>,
}

static METRICS: LazyLock<Mutex<ReferenceMetricSnapshot>> =
    LazyLock::new(|| Mutex::new(ReferenceMetricSnapshot::default()));

pub fn metric_snapshot() -> ReferenceMetricSnapshot {
    METRICS.lock().expect("reference metric lock").clone()
}

pub fn decode_snapshot(snapshot: &Value) -> Result<DecodedSnapshot, CredentialRuntimeError> {
    let schema_label = safe_snapshot_schema_label(snapshot);
    match decode_snapshot_inner(snapshot) {
        Ok(decoded) => {
            record_reader("snapshot", decoded.schema.metric_label(), "success");
            Ok(decoded)
        }
        Err(error) => {
            record_reader("snapshot", schema_label, "error");
            Err(error)
        }
    }
}

pub fn decode_environment(
    environment: &Value,
) -> Result<DecodedEnvironment, CredentialRuntimeError> {
    match decode_environment_inner(environment, "$") {
        Ok(decoded) => {
            record_reader("environment", "live", "success");
            Ok(decoded)
        }
        Err(error) => {
            record_reader("environment", "live", "error");
            Err(error)
        }
    }
}

pub fn encode_snapshot(
    snapshot: &Value,
    version: Option<EncodeVersion>,
) -> Result<Value, CredentialRuntimeError> {
    let version = version.unwrap_or(EncodeVersion::V1);
    let decoded = decode_snapshot(snapshot)?;
    let mut document = object(snapshot)?.clone();
    let schema = CredentialReferenceContract::embedded()
        .snapshot_schema_value(version.label())
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
    document.insert("schema".to_string(), Value::String(schema.to_string()));

    let had_model_key =
        document.contains_key("model_credential_id") || document.contains_key("secret_ref");
    document.remove("secret_ref");
    if let Some(model) = decoded.model {
        document.insert(
            "model_credential_id".to_string(),
            Value::String(model.credential_id.to_string()),
        );
    } else if had_model_key {
        document.insert("model_credential_id".to_string(), Value::Null);
    }

    let had_environment_keys =
        document.contains_key("environment_credential_ids") || document.contains_key("secret_refs");
    let mut top_level_ids = decoded
        .environment_references
        .iter()
        .filter(|reference| {
            matches!(
                reference.source_path.as_str(),
                "$.environment_credential_ids[*]" | "$.secret_refs[*]"
            )
        })
        .map(|reference| reference.credential_id)
        .collect::<Vec<_>>();
    sort_dedup_ids(&mut top_level_ids);
    document.remove("environment_credential_ids");
    document.remove("secret_refs");
    if !top_level_ids.is_empty() || had_environment_keys {
        let key = match version {
            EncodeVersion::V1 => "secret_refs",
            EncodeVersion::V2 => "environment_credential_ids",
        };
        document.insert(
            key.to_string(),
            Value::Array(
                top_level_ids
                    .into_iter()
                    .map(|credential_id| Value::String(credential_id.to_string()))
                    .collect(),
            ),
        );
    }

    if let Some(environment) = document.get("environment") {
        if !environment.is_null() {
            let mut environment = object(environment)?.clone();
            if let Some(config) = environment.get("config") {
                if !config.is_null() {
                    environment.insert(
                        "config".to_string(),
                        encode_environment_inner(config, version, false)?,
                    );
                }
            }
            document.insert("environment".to_string(), Value::Object(environment));
        }
    }

    let encoded = Value::Object(document);
    record_persisted_keys(&encoded, "snapshot", version.label());
    Ok(encoded)
}

pub fn encode_environment(
    environment: &Value,
    version: Option<EncodeVersion>,
) -> Result<Value, CredentialRuntimeError> {
    encode_environment_inner(environment, version.unwrap_or(EncodeVersion::V1), true)
}

fn decode_snapshot_inner(snapshot: &Value) -> Result<DecodedSnapshot, CredentialRuntimeError> {
    let document = object(snapshot)?;
    let raw_schema = match document.get("schema") {
        None | Some(Value::Null) => None,
        Some(Value::String(value)) => Some(value.as_str()),
        _ => return Err(CredentialRuntimeError::CorruptRecord),
    };
    let schema = match CredentialReferenceContract::embedded().snapshot_schema_name(raw_schema) {
        Some("legacy_v0") => SnapshotSchema::LegacyV0,
        Some("v1") => SnapshotSchema::V1,
        Some("v2") => SnapshotSchema::V2,
        _ => return Err(CredentialRuntimeError::CorruptRecord),
    };
    if schema == SnapshotSchema::V2
        && CredentialReferenceContract::embedded()
            .reference_paths()
            .iter()
            .filter(|entry| {
                entry.document != "environment_config"
                    && !entry.schemas.iter().any(|item| item == "v2")
            })
            .any(|entry| registered_path_key_count(snapshot, &entry.path) > 0)
    {
        return Err(CredentialRuntimeError::CorruptRecord);
    }

    let has_model_key =
        document.contains_key("model_credential_id") || document.contains_key("secret_ref");
    let model = optional_alias_id(
        document,
        &["model_credential_id", "secret_ref"],
        "Snapshot model credential id",
        "$",
    )?
    .map(|(credential_id, source_paths)| {
        Ok(SnapshotModelReference {
            credential_id,
            engine_kind: require_non_empty_string(document.get("engine_kind"))?.to_string(),
            model_id: model_id(document.get("model"))?,
            source_paths,
        })
    })
    .transpose()?;
    let model_credential_override =
        has_model_key.then(|| model.as_ref().map(|reference| reference.credential_id));

    let mut environment_references = credential_id_occurrences(
        document,
        "environment_credential_ids",
        "$.environment_credential_ids[*]",
    )?;
    environment_references.extend(credential_id_occurrences(
        document,
        "secret_refs",
        "$.secret_refs[*]",
    )?);

    let config = match document.get("environment") {
        None | Some(Value::Null) => None,
        Some(environment) => match object(environment)?.get("config") {
            None | Some(Value::Null) => None,
            Some(config) => Some(config),
        },
    };
    let decoded_environment = match config {
        Some(config) => decode_environment_inner(config, "$.environment.config")?,
        None => DecodedEnvironment {
            direct_references: Vec::new(),
            direct_credential_ids: Vec::new(),
            http_egress: Vec::new(),
        },
    };
    environment_references.extend(decoded_environment.direct_references);
    let mut environment_credential_ids = environment_references
        .iter()
        .map(|reference| reference.credential_id)
        .collect::<Vec<_>>();
    sort_dedup_ids(&mut environment_credential_ids);

    let mut references = Vec::new();
    if let Some(model) = model.as_ref() {
        references.push(SnapshotCredentialReference::Model(model.credential_id));
    }
    references.extend(
        environment_credential_ids
            .iter()
            .copied()
            .map(SnapshotCredentialReference::Environment),
    );
    references.extend(decoded_environment.http_egress.iter().map(|reference| {
        SnapshotCredentialReference::HttpEgress {
            credential_id: reference.credential_id,
            field: reference.credential_field.clone(),
        }
    }));

    Ok(DecodedSnapshot {
        schema,
        model,
        model_credential_override,
        environment_references,
        environment_credential_ids,
        http_egress: decoded_environment.http_egress,
        references,
    })
}

fn decode_environment_inner(
    environment: &Value,
    path_prefix: &str,
) -> Result<DecodedEnvironment, CredentialRuntimeError> {
    let document = object(environment)?;
    let mut direct_references = credential_id_occurrences(
        document,
        "environment_credential_ids",
        &format!("{path_prefix}.environment_credential_ids[*]"),
    )?;
    direct_references.extend(credential_id_occurrences(
        document,
        "secret_refs",
        &format!("{path_prefix}.secret_refs[*]"),
    )?);
    if let Some((credential_id, _)) = optional_alias_id(
        document,
        &["service_credential_id"],
        "Environment legacy service credential id",
        path_prefix,
    )? {
        direct_references.push(EnvironmentCredentialReference {
            credential_id,
            source_path: format!("{path_prefix}.service_credential_id"),
            index: None,
        });
    }
    let mut direct_credential_ids = direct_references
        .iter()
        .map(|reference| reference.credential_id)
        .collect::<Vec<_>>();
    sort_dedup_ids(&mut direct_credential_ids);
    Ok(DecodedEnvironment {
        direct_references,
        direct_credential_ids,
        http_egress: decode_http_egress(document, path_prefix)?,
    })
}

fn encode_environment_inner(
    environment: &Value,
    version: EncodeVersion,
    record_metrics: bool,
) -> Result<Value, CredentialRuntimeError> {
    let decoded = decode_environment_inner(environment, "$")?;
    let mut document = object(environment)?.clone();
    let had_direct_keys = [
        "environment_credential_ids",
        "secret_refs",
        "service_credential_id",
    ]
    .iter()
    .any(|key| document.contains_key(*key));
    document.remove("environment_credential_ids");
    document.remove("secret_refs");
    document.remove("service_credential_id");
    if !decoded.direct_credential_ids.is_empty() || had_direct_keys {
        let key = match version {
            EncodeVersion::V1 => "secret_refs",
            EncodeVersion::V2 => "environment_credential_ids",
        };
        document.insert(
            key.to_string(),
            Value::Array(
                decoded
                    .direct_credential_ids
                    .iter()
                    .map(|credential_id| Value::String(credential_id.to_string()))
                    .collect(),
            ),
        );
    }

    if let Some(services) = document.get("egress_services") {
        if services.is_null() {
            document.insert("egress_services".to_string(), Value::Array(Vec::new()));
        } else {
            let mut encoded_services = Vec::new();
            for service in services
                .as_array()
                .ok_or(CredentialRuntimeError::CorruptRecord)?
            {
                let mut service = object(service)?.clone();
                let credential_id = optional_alias_id(
                    &service,
                    &["service_credential_id", "credential_ref"],
                    "HTTP egress credential id",
                    "$",
                )?
                .map(|(credential_id, _)| credential_id);
                service.remove("credential_ref");
                if let Some(credential_id) = credential_id {
                    service.insert(
                        "service_credential_id".to_string(),
                        Value::String(credential_id.to_string()),
                    );
                }
                if let Some(inject) = service.get("inject") {
                    if !inject.is_null() {
                        let mut inject = object(inject)?.clone();
                        let kind = inject_kind(&inject)?;
                        let (field, _) = alias_text(
                            &inject,
                            &["credential_field", "secret_key"],
                            default_field(&kind),
                        )?;
                        inject.remove("credential_field");
                        inject.remove("secret_key");
                        let key = match version {
                            EncodeVersion::V1 => "secret_key",
                            EncodeVersion::V2 => "credential_field",
                        };
                        inject.insert(key.to_string(), Value::String(field));
                        service.insert("inject".to_string(), Value::Object(inject));
                    }
                }
                encoded_services.push(Value::Object(service));
            }
            document.insert(
                "egress_services".to_string(),
                Value::Array(encoded_services),
            );
        }
    }

    let encoded = Value::Object(document);
    if record_metrics {
        record_persisted_keys(&encoded, "environment", version.label());
    }
    Ok(encoded)
}

fn object(value: &Value) -> Result<&Map<String, Value>, CredentialRuntimeError> {
    value
        .as_object()
        .ok_or(CredentialRuntimeError::CorruptRecord)
}

fn registered_path_key_count(document: &Value, path: &str) -> u64 {
    let segments = path.trim_start_matches("$.").split('.').collect::<Vec<_>>();
    let mut parents = vec![document];
    for segment in &segments[..segments.len().saturating_sub(1)] {
        let expand = segment.ends_with("[*]");
        let key = segment.trim_end_matches("[*]");
        let mut children = Vec::new();
        for parent in parents {
            let Some(child) = parent.as_object().and_then(|value| value.get(key)) else {
                continue;
            };
            if expand {
                if let Some(values) = child.as_array() {
                    children.extend(values);
                }
            } else {
                children.push(child);
            }
        }
        parents = children;
    }
    let Some(terminal) = segments.last() else {
        return 0;
    };
    let terminal_key = terminal.trim_end_matches("[*]");
    parents
        .into_iter()
        .filter(|parent| {
            parent
                .as_object()
                .is_some_and(|value| value.contains_key(terminal_key))
        })
        .count() as u64
}

fn require_non_empty_string(value: Option<&Value>) -> Result<&str, CredentialRuntimeError> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(CredentialRuntimeError::CorruptRecord)
}

fn optional_string(value: Option<&Value>) -> Result<Option<String>, CredentialRuntimeError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(value) => Ok(Some(require_non_empty_string(Some(value))?.to_string())),
    }
}

fn model_id(value: Option<&Value>) -> Result<Option<String>, CredentialRuntimeError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => {
            Ok((!value.trim().is_empty()).then(|| value.trim().to_string()))
        }
        Some(Value::Object(model)) => optional_string(model.get("id")),
        _ => Err(CredentialRuntimeError::CorruptRecord),
    }
}

fn parse_credential_id(value: &Value) -> Result<CredentialId, CredentialRuntimeError> {
    value
        .as_str()
        .ok_or(CredentialRuntimeError::CorruptRecord)
        .and_then(|value| {
            CredentialId::from_public(value).map_err(|_| CredentialRuntimeError::CorruptRecord)
        })
}

fn optional_alias_id(
    document: &Map<String, Value>,
    keys: &[&str],
    _label: &str,
    path_prefix: &str,
) -> Result<Option<(CredentialId, Vec<String>)>, CredentialRuntimeError> {
    let mut values = Vec::new();
    let mut paths = Vec::new();
    for key in keys {
        let Some(value) = document.get(*key) else {
            continue;
        };
        if value.is_null() {
            continue;
        }
        values.push(parse_credential_id(value)?);
        paths.push(format!("{path_prefix}.{key}"));
    }
    let Some(first) = values.first().copied() else {
        return Ok(None);
    };
    if values.iter().any(|value| *value != first) {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    Ok(Some((first, paths)))
}

fn credential_id_occurrences(
    document: &Map<String, Value>,
    key: &str,
    source_path: &str,
) -> Result<Vec<EnvironmentCredentialReference>, CredentialRuntimeError> {
    let Some(value) = document.get(key) else {
        return Ok(Vec::new());
    };
    if value.is_null() {
        return Ok(Vec::new());
    }
    value
        .as_array()
        .ok_or(CredentialRuntimeError::CorruptRecord)?
        .iter()
        .enumerate()
        .map(|(index, value)| {
            Ok(EnvironmentCredentialReference {
                credential_id: parse_credential_id(value)?,
                source_path: source_path.to_string(),
                index: Some(index),
            })
        })
        .collect()
}

fn inject_kind(inject: &Map<String, Value>) -> Result<String, CredentialRuntimeError> {
    if CredentialReferenceContract::embedded().inject_type_normalization() != "trim_lowercase" {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    let kind = match inject.get("type") {
        None | Some(Value::Null) => "bearer".to_string(),
        Some(value) => require_non_empty_string(Some(value))?.to_lowercase(),
    };
    match kind.as_str() {
        "bearer" | "api_key" | "raw_header" | "cookie" => Ok(kind),
        _ => Err(CredentialRuntimeError::CorruptRecord),
    }
}

fn default_field(kind: &str) -> &'static str {
    match kind {
        "bearer" => "ACCESS_TOKEN",
        "api_key" | "raw_header" => "API_KEY",
        "cookie" => "COOKIE_HEADER",
        _ => unreachable!("inject kind validated before default field"),
    }
}

fn alias_text(
    document: &Map<String, Value>,
    keys: &[&str],
    default: &str,
) -> Result<(String, Vec<String>), CredentialRuntimeError> {
    let mut values = Vec::new();
    let mut source_keys = Vec::new();
    for key in keys {
        let Some(value) = document.get(*key) else {
            continue;
        };
        if value.is_null() {
            continue;
        }
        let value = require_non_empty_string(Some(value))?;
        if value.chars().count() > CREDENTIAL_FIELD_MAX_LENGTH {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
        values.push(value.to_string());
        source_keys.push((*key).to_string());
    }
    if values.is_empty() {
        return Ok((default.to_string(), Vec::new()));
    }
    if values.iter().any(|value| value != &values[0]) {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    Ok((values.remove(0), source_keys))
}

fn decode_http_egress(
    document: &Map<String, Value>,
    path_prefix: &str,
) -> Result<Vec<HttpEgressReference>, CredentialRuntimeError> {
    let Some(value) = document.get("egress_services") else {
        return Ok(Vec::new());
    };
    if value.is_null() {
        return Ok(Vec::new());
    }
    let services = value
        .as_array()
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
    let mut references = Vec::new();
    for (index, service) in services.iter().enumerate() {
        let service = object(service)?;
        let (credential_id, credential_paths) = optional_alias_id(
            service,
            &["service_credential_id", "credential_ref"],
            "HTTP egress credential id",
            &format!("{path_prefix}.egress_services[*]"),
        )?
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
        let endpoint = require_non_empty_string(service.get("base_url"))?.to_string();
        let empty_inject = Map::new();
        let inject = match service.get("inject") {
            None | Some(Value::Null) => &empty_inject,
            Some(inject) => object(inject)?,
        };
        let kind = inject_kind(inject)?;
        let (credential_field, field_keys) = alias_text(
            inject,
            &["credential_field", "secret_key"],
            default_field(&kind),
        )?;
        let allowed_paths = match service.get("allowed_paths") {
            None | Some(Value::Null) => Vec::new(),
            Some(Value::Array(paths)) => paths
                .iter()
                .map(|path| require_non_empty_string(Some(path)).map(ToOwned::to_owned))
                .collect::<Result<Vec<_>, _>>()?,
            _ => return Err(CredentialRuntimeError::CorruptRecord),
        };
        let mut source_paths = credential_paths;
        source_paths.extend(
            field_keys
                .into_iter()
                .map(|key| format!("{path_prefix}.egress_services[*].inject.{key}")),
        );
        references.push(HttpEgressReference {
            credential_id,
            endpoint,
            inject_kind: kind,
            credential_field,
            header: optional_string(inject.get("header"))?,
            cookie_name: optional_string(inject.get("cookie_name"))?,
            source_paths,
            index,
            name: optional_string(service.get("name"))?,
            allowed_paths,
        });
    }
    Ok(references)
}

fn sort_dedup_ids(values: &mut Vec<CredentialId>) {
    values.sort_by_key(ToString::to_string);
    values.dedup();
}

fn safe_snapshot_schema_label(snapshot: &Value) -> &'static str {
    let Some(document) = snapshot.as_object() else {
        return "unknown";
    };
    let raw_schema = match document.get("schema") {
        None | Some(Value::Null) => None,
        Some(Value::String(value)) => Some(value.as_str()),
        _ => return "unknown",
    };
    match CredentialReferenceContract::embedded().snapshot_schema_name(raw_schema) {
        Some("legacy_v0") => "legacy_v0",
        Some("v1") => "v1",
        Some("v2") => "v2",
        _ => "unknown",
    }
}

fn record_reader(document: &str, schema: &str, result: &str) {
    *METRICS
        .lock()
        .expect("reference metric lock")
        .reader_versions
        .entry((document.to_string(), schema.to_string(), result.to_string()))
        .or_default() += 1;
}

fn persisted_key_counts(
    value: &Value,
    document: &str,
    version: &str,
) -> BTreeMap<(String, String, String, String), u64> {
    let (contract_documents, contract_schema): (&[&str], &str) = match document {
        "snapshot" => (
            &["agent_version_snapshot", "active_session_snapshot"],
            version,
        ),
        "environment" => (&["environment_config"], "live"),
        _ => return BTreeMap::new(),
    };
    let registered_paths = CredentialReferenceContract::embedded()
        .reference_paths()
        .iter()
        .filter(|entry| {
            contract_documents.contains(&entry.document.as_str())
                && entry.schemas.iter().any(|schema| schema == contract_schema)
        })
        .map(|entry| entry.path.as_str())
        .collect::<BTreeSet<_>>();
    let mut counts = BTreeMap::new();
    for path in registered_paths {
        let count = registered_path_key_count(value, path);
        if count == 0 {
            continue;
        }
        let key = path
            .rsplit('.')
            .next()
            .unwrap_or(path)
            .trim_end_matches("[*]");
        counts.insert(
            (
                document.to_string(),
                version.to_string(),
                path.to_string(),
                key.to_string(),
            ),
            count,
        );
    }
    counts
}

fn record_persisted_keys(value: &Value, document: &str, version: &str) {
    let counts = persisted_key_counts(value, document, version);
    let mut metrics = METRICS.lock().expect("reference metric lock");
    for (key, count) in counts {
        *metrics.persisted_keys.entry(key).or_default() += count;
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Map, Value};

    use super::{
        decode_environment, decode_snapshot, encode_environment, encode_snapshot, metric_snapshot,
        persisted_key_counts, SnapshotSchema,
    };
    use crate::kernel::credentials::contract::{
        CredentialReferenceContract, CredentialReferenceFixtureMatrix, CredentialReferencePath,
    };
    use crate::kernel::credentials::error::CredentialRuntimeError;

    const CREDENTIAL_A: &str = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010";
    const CREDENTIAL_B: &str = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011";

    fn document_for_case(
        entry: &CredentialReferencePath,
        schema: &str,
        fixture: &CredentialReferenceFixtureMatrix,
    ) -> Value {
        fn build(segments: &[&str], fixture_value: &str) -> Value {
            let expand = segments[0].ends_with("[*]");
            let key = segments[0].trim_end_matches("[*]");
            let child = if segments.len() == 1 {
                Value::String(fixture_value.to_string())
            } else {
                build(&segments[1..], fixture_value)
            };
            let mut object = Map::new();
            object.insert(
                key.to_string(),
                if expand {
                    Value::Array(vec![child])
                } else {
                    child
                },
            );
            Value::Object(object)
        }

        let fixture_value = if entry.value_kind == "credential_field" {
            &fixture.credential_field
        } else {
            &fixture.credential_id
        };
        let mut document = build(
            &entry
                .path
                .trim_start_matches("$.")
                .split('.')
                .collect::<Vec<_>>(),
            fixture_value,
        );
        if schema != "live" {
            if let Some(schema_value) =
                CredentialReferenceContract::embedded().snapshot_schema_value(schema)
            {
                document.as_object_mut().unwrap().insert(
                    "schema".to_string(),
                    Value::String(schema_value.to_string()),
                );
            }
        }
        let path = &entry.path;
        if path.contains("model_credential_id") || path == "$.secret_ref" {
            let object = document.as_object_mut().unwrap();
            object.insert(
                "engine_kind".to_string(),
                Value::String("claude".to_string()),
            );
            object.insert("model".to_string(), json!({"id": "claude-sonnet"}));
        }
        if path.contains("egress_services") {
            let mut config = &mut document;
            if path.starts_with("$.environment.config") {
                config = config
                    .get_mut("environment")
                    .unwrap()
                    .get_mut("config")
                    .unwrap();
            }
            let service = config
                .get_mut("egress_services")
                .unwrap()
                .as_array_mut()
                .unwrap()[0]
                .as_object_mut()
                .unwrap();
            service.insert("name".to_string(), Value::String("crm".to_string()));
            service.insert(
                "base_url".to_string(),
                Value::String("https://crm.example.com".to_string()),
            );
            service
                .entry("service_credential_id".to_string())
                .or_insert_with(|| Value::String(fixture.credential_id.clone()));
            let inject = service
                .entry("inject".to_string())
                .or_insert_with(|| Value::Object(Map::new()))
                .as_object_mut()
                .unwrap();
            inject
                .entry("type".to_string())
                .or_insert_with(|| Value::String(fixture.inject_type.clone()));
            let field_key = if schema == "v2" {
                "credential_field"
            } else {
                "secret_key"
            };
            inject
                .entry(field_key.to_string())
                .or_insert_with(|| Value::String(fixture.credential_field.clone()));
        }
        document
    }

    #[test]
    fn embedded_contract_path_schema_matrix_is_all_decoded() {
        let contract = CredentialReferenceContract::embedded();
        let fixture = contract.fixture_matrix();
        assert_eq!(fixture.generator, "reference_paths_x_schemas");
        assert_ne!(fixture.credential_id, fixture.secondary_credential_id);
        let mut executed = 0;
        for entry in CredentialReferenceContract::embedded().reference_paths() {
            for schema in &entry.schemas {
                let document = document_for_case(entry, schema, fixture);
                let (credential_ids, http_egress) = match entry.document.as_str() {
                    "environment_config" => {
                        let decoded = decode_environment(&document).unwrap();
                        (decoded.credential_ids(), decoded.http_egress)
                    }
                    _ => {
                        let decoded = decode_snapshot(&document).unwrap();
                        (decoded.credential_ids(), decoded.http_egress)
                    }
                };
                if entry.value_kind == "credential_id" {
                    assert!(
                        credential_ids
                            .iter()
                            .any(|credential_id| credential_id.to_string() == fixture.credential_id),
                        "{}[{}]",
                        entry.path,
                        schema
                    );
                } else {
                    assert_eq!(
                        http_egress[0].credential_field, fixture.credential_field,
                        "{}[{}]",
                        entry.path, schema
                    );
                }
                executed += 1;
            }
        }
        assert_eq!(executed, 57);
    }

    #[test]
    fn shared_contract_parity_vectors_execute() {
        for vector in CredentialReferenceContract::embedded().parity_vectors() {
            let result = match vector.document.as_str() {
                "environment_config" => decode_environment(&vector.input).map(|decoded| {
                    (
                        decoded
                            .credential_ids()
                            .into_iter()
                            .map(|value| value.to_string())
                            .collect::<Vec<_>>(),
                        decoded
                            .http_egress
                            .into_iter()
                            .map(|reference| reference.inject_kind)
                            .collect::<Vec<_>>(),
                    )
                }),
                _ => decode_snapshot(&vector.input).map(|decoded| {
                    (
                        decoded
                            .credential_ids()
                            .into_iter()
                            .map(|value| value.to_string())
                            .collect::<Vec<_>>(),
                        decoded
                            .http_egress
                            .into_iter()
                            .map(|reference| reference.inject_kind)
                            .collect::<Vec<_>>(),
                    )
                }),
            };
            if vector.result == "corrupt_record" {
                assert_eq!(
                    result,
                    Err(CredentialRuntimeError::CorruptRecord),
                    "{}",
                    vector.name
                );
                continue;
            }
            let (credential_ids, inject_types) = result.unwrap();
            if let Some(expected) = &vector.expected_credential_ids {
                assert_eq!(&credential_ids, expected, "{}", vector.name);
            }
            if let Some(expected) = &vector.expected_inject_types {
                assert_eq!(&inject_types, expected, "{}", vector.name);
            }
            assert!(!vector.category.is_empty());
        }
    }

    #[test]
    fn contract_schema_versions_and_unknown_schema_are_fail_closed() {
        assert_eq!(
            decode_snapshot(&json!({})).unwrap().schema,
            SnapshotSchema::LegacyV0
        );
        assert_eq!(
            decode_snapshot(&json!({"schema": "joysafeter.agent_execution_snapshot.v1"}))
                .unwrap()
                .schema,
            SnapshotSchema::V1
        );
        assert_eq!(
            decode_snapshot(&json!({"schema": "joysafeter.agent_execution_snapshot.v2"}))
                .unwrap()
                .schema,
            SnapshotSchema::V2
        );
        assert_eq!(
            decode_snapshot(&json!({"schema": "joysafeter.agent_execution_snapshot.v3"})),
            Err(CredentialRuntimeError::CorruptRecord)
        );
    }

    #[test]
    fn mixed_snapshot_aliases_and_nested_egress_canonicalize() {
        let decoded = decode_snapshot(&json!({
            "schema": "joysafeter.agent_execution_snapshot.v1",
            "engine_kind": "claude",
            "model": {"id": "claude-sonnet"},
            "model_credential_id": CREDENTIAL_A,
            "secret_ref": CREDENTIAL_A,
            "environment_credential_ids": [CREDENTIAL_A, CREDENTIAL_B],
            "secret_refs": [CREDENTIAL_B],
            "environment": {"config": {
                "secret_refs": [CREDENTIAL_A],
                "egress_services": [{
                    "base_url": "https://crm.example.com",
                    "service_credential_id": CREDENTIAL_B,
                    "credential_ref": CREDENTIAL_B,
                    "inject": {
                        "type": "bearer",
                        "credential_field": "ACCESS_TOKEN",
                        "secret_key": "ACCESS_TOKEN"
                    }
                }]
            }}
        }))
        .unwrap();

        assert_eq!(
            decoded
                .credential_ids()
                .into_iter()
                .map(|value| value.to_string())
                .collect::<Vec<_>>(),
            vec![CREDENTIAL_A, CREDENTIAL_B]
        );
        assert_eq!(decoded.environment_credential_ids.len(), 2);
        assert_eq!(decoded.http_egress.len(), 1);
        assert_eq!(decoded.http_egress[0].credential_field, "ACCESS_TOKEN");
    }

    #[test]
    fn environment_reader_covers_legacy_v0_v1_v2_and_null_compatibility() {
        let decoded = decode_environment(&json!({
            "environment_credential_ids": [CREDENTIAL_A],
            "secret_refs": [CREDENTIAL_A, CREDENTIAL_B],
            "service_credential_id": CREDENTIAL_B,
            "egress_services": [{
                "base_url": "https://crm.example.com",
                "service_credential_id": CREDENTIAL_A,
                "credential_ref": CREDENTIAL_A,
                "inject": {"credential_field": "TOKEN", "secret_key": "TOKEN"}
            }]
        }))
        .unwrap();
        assert_eq!(decoded.direct_credential_ids.len(), 2);
        assert_eq!(decoded.http_egress.len(), 1);

        let empty = decode_environment(&json!({
            "environment_credential_ids": null,
            "secret_refs": [],
            "service_credential_id": null,
            "egress_services": null
        }))
        .unwrap();
        assert!(empty.credential_ids().is_empty());
    }

    #[test]
    fn malformed_ids_fields_and_conflicting_aliases_fail_closed() {
        for document in [
            json!({"model_credential_id": CREDENTIAL_A, "secret_ref": CREDENTIAL_B, "engine_kind": "claude"}),
            json!({"environment_credential_ids": [7]}),
            json!({"environment": {"config": {"egress_services": [{
                "base_url": "https://crm.example.com",
                "service_credential_id": CREDENTIAL_A,
                "credential_ref": CREDENTIAL_B,
                "inject": {"secret_key": "TOKEN"}
            }]}}}),
            json!({"environment": {"config": {"egress_services": [{
                "base_url": "https://crm.example.com",
                "service_credential_id": CREDENTIAL_A,
                "inject": {"credential_field": 7}
            }]}}}),
        ] {
            assert_eq!(
                decode_snapshot(&document),
                Err(CredentialRuntimeError::CorruptRecord)
            );
        }
    }

    #[test]
    fn explicit_v2_aliases_fail_closed_and_inject_types_normalize() {
        assert_eq!(
            decode_snapshot(&json!({
                "schema": "joysafeter.agent_execution_snapshot.v2",
                "secret_refs": [CREDENTIAL_A]
            })),
            Err(CredentialRuntimeError::CorruptRecord)
        );

        let decoded = decode_environment(&json!({
            "egress_services": [{
                "base_url": "https://crm.example.com",
                "service_credential_id": CREDENTIAL_A,
                "inject": {"type": "  BEARER  ", "credential_field": "ACCESS_TOKEN"}
            }]
        }))
        .unwrap();
        assert_eq!(decoded.http_egress[0].inject_kind, "bearer");
    }

    #[test]
    fn v1_encoding_is_default_and_metrics_never_capture_payloads() {
        let before = metric_snapshot();
        let snapshot = encode_snapshot(
            &json!({
                "environment_credential_ids": [CREDENTIAL_A],
                "environment": {"config": {"environment_credential_ids": [CREDENTIAL_B]}},
            }),
            None,
        )
        .unwrap();
        let environment =
            encode_environment(&json!({"environment_credential_ids": [CREDENTIAL_A]}), None)
                .unwrap();

        assert_eq!(snapshot["schema"], "joysafeter.agent_execution_snapshot.v1");
        assert_eq!(snapshot["secret_refs"], json!([CREDENTIAL_A]));
        assert!(snapshot.get("environment_credential_ids").is_none());
        assert_eq!(environment["secret_refs"], json!([CREDENTIAL_A]));
        assert!(environment.get("environment_credential_ids").is_none());

        let snapshot_key = (
            "snapshot".to_string(),
            "v1".to_string(),
            "$.environment.config.secret_refs[*]".to_string(),
            "secret_refs".to_string(),
        );
        let environment_key = (
            "environment".to_string(),
            "v1".to_string(),
            "$.secret_refs[*]".to_string(),
            "secret_refs".to_string(),
        );
        let metrics = metric_snapshot();
        let before_snapshot = before
            .persisted_keys
            .get(&snapshot_key)
            .copied()
            .unwrap_or_default();
        let before_environment = before
            .persisted_keys
            .get(&environment_key)
            .copied()
            .unwrap_or_default();
        assert_eq!(
            persisted_key_counts(&snapshot, "snapshot", "v1").get(&snapshot_key),
            Some(&1),
        );
        assert_eq!(
            persisted_key_counts(&environment, "environment", "v1").get(&environment_key),
            Some(&1),
        );
        assert!(
            metrics
                .persisted_keys
                .get(&snapshot_key)
                .copied()
                .unwrap_or_default()
                >= before_snapshot + 1
        );
        assert!(
            metrics
                .persisted_keys
                .get(&environment_key)
                .copied()
                .unwrap_or_default()
                >= before_environment + 1
        );
        let rendered = format!("{metrics:?}");
        assert!(!rendered.contains(CREDENTIAL_A));
        assert!(!rendered.contains(CREDENTIAL_B));
    }

    #[test]
    fn persisted_key_metrics_ignore_registered_names_outside_contract_paths() {
        let environment = encode_environment(
            &json!({
                "metadata": {
                    "credential_ref": CREDENTIAL_A,
                    "secret_key": "not-a-reference-field"
                }
            }),
            None,
        )
        .unwrap();

        assert!(persisted_key_counts(&environment, "environment", "v1").is_empty());
    }
}
