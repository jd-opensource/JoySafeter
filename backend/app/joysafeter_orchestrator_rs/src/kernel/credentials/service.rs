use std::fmt;

use serde_json::{Map, Value};

use super::error::CredentialRuntimeError;
use super::record::{CredentialKind, CredentialMetadataRecord, CredentialRecord};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceUsage<'a> {
    EnvironmentInjection,
    HttpEgressField { field: &'a str },
}

#[derive(Clone, PartialEq, Eq)]
pub enum ResolvedServiceCredential {
    Environment(Value),
    HttpEgressField(String),
}

impl fmt::Debug for ResolvedServiceCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Environment(Value::Object(values)) => formatter
                .debug_struct("Environment")
                .field("fields", &values.keys().collect::<Vec<_>>())
                .field("values", &"<redacted>")
                .finish(),
            Self::Environment(_) => formatter
                .debug_tuple("Environment")
                .field(&"<redacted>")
                .finish(),
            Self::HttpEgressField(_) => formatter
                .debug_tuple("HttpEgressField")
                .field(&"<redacted>")
                .finish(),
        }
    }
}

pub fn resolve_service_credential(
    record: &CredentialRecord,
    usage: ServiceUsage<'_>,
) -> Result<ResolvedServiceCredential, CredentialRuntimeError> {
    if record.kind != CredentialKind::Service {
        return Err(CredentialRuntimeError::KindMismatch);
    }
    match usage {
        ServiceUsage::EnvironmentInjection => {
            let mut object = Map::new();
            for (field, value) in record.material.iter() {
                object.insert(field.to_string(), Value::String(value.to_string()));
            }
            Ok(ResolvedServiceCredential::Environment(Value::Object(
                object,
            )))
        }
        ServiceUsage::HttpEgressField { field } => Ok(ResolvedServiceCredential::HttpEgressField(
            record.material.require(field)?.to_string(),
        )),
    }
}

pub fn validate_service_credential_metadata(
    record: &CredentialMetadataRecord,
    usage: ServiceUsage<'_>,
) -> Result<(), CredentialRuntimeError> {
    if record.kind != CredentialKind::Service {
        return Err(CredentialRuntimeError::KindMismatch);
    }
    if let ServiceUsage::HttpEgressField { field } = usage {
        if !record.material_fields.contains(field) {
            return Err(CredentialRuntimeError::FieldMissing);
        }
    }
    Ok(())
}
