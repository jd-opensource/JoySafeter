use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use async_trait::async_trait;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Vault {
    pub id: uuid::Uuid,
    pub name: String,
    pub description: String,
    #[serde(default)]
    pub metadata: HashMap<String, String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CredentialType {
    StaticBearer,
    McpOauth,
}

impl std::fmt::Display for CredentialType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::StaticBearer => write!(f, "static_bearer"),
            Self::McpOauth => write!(f, "mcp_oauth"),
        }
    }
}

impl std::str::FromStr for CredentialType {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "static_bearer" => Ok(Self::StaticBearer),
            "mcp_oauth" => Ok(Self::McpOauth),
            other => Err(format!("unknown credential type: {other}")),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OAuthConfig {
    pub client_id: String,
    #[serde(skip_serializing)]
    pub client_secret: String,
    #[serde(skip_serializing)]
    pub refresh_token: String,
    pub token_endpoint: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default)]
    pub scopes: Vec<String>,
}

impl OAuthConfig {
    pub fn is_expired_or_near_expiry(&self) -> bool {
        match self.expires_at {
            Some(exp) => exp < chrono::Utc::now() + chrono::Duration::minutes(5),
            None => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultCredential {
    pub id: uuid::Uuid,
    pub vault_id: uuid::Uuid,
    pub name: String,
    pub credential_type: CredentialType,
    pub mcp_server_url: String,
    #[serde(skip_serializing)]
    pub token_value: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oauth_config: Option<OAuthConfig>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl VaultCredential {
    pub fn auth_header_value(&self) -> String {
        format!("Bearer {}", self.token_value)
    }
}

// ============ VaultProvider abstraction ============

#[derive(Debug)]
pub enum VaultError {
    NotFound,
    Conflict(String),
    Unsupported(String),
    Internal(String),
}

impl std::fmt::Display for VaultError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound => write!(f, "not found"),
            Self::Conflict(msg) => write!(f, "conflict: {msg}"),
            Self::Unsupported(msg) => write!(f, "unsupported: {msg}"),
            Self::Internal(msg) => write!(f, "internal error: {msg}"),
        }
    }
}

impl std::error::Error for VaultError {}

#[derive(Debug, Clone)]
pub struct RefreshedToken {
    pub access_token: String,
    pub expires_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[async_trait]
pub trait VaultProvider: Send + Sync {
    // Core — used by kernel at SetupSandbox time
    async fn resolve_credentials(&self, vault_ids: &[uuid::Uuid]) -> Result<Vec<VaultCredential>, VaultError>;
    async fn refresh_token(&self, cred_id: uuid::Uuid, oauth: &OAuthConfig) -> Result<RefreshedToken, VaultError>;

    // Vault CRUD
    async fn create_vault(&self, vault: &Vault) -> Result<(), VaultError>;
    async fn get_vault(&self, id: uuid::Uuid) -> Result<Option<Vault>, VaultError>;
    async fn list_vaults(&self) -> Result<Vec<Vault>, VaultError>;
    async fn update_vault(&self, id: uuid::Uuid, description: Option<&str>, metadata: Option<&HashMap<String, String>>) -> Result<bool, VaultError>;
    async fn archive_vault(&self, id: uuid::Uuid) -> Result<bool, VaultError>;
    async fn delete_vault(&self, id: uuid::Uuid) -> Result<bool, VaultError>;

    // Credential CRUD
    async fn create_credential(&self, cred: &VaultCredential) -> Result<(), VaultError>;
    async fn get_credential(&self, id: uuid::Uuid) -> Result<Option<VaultCredential>, VaultError>;
    async fn list_credentials(&self, vault_id: uuid::Uuid) -> Result<Vec<VaultCredential>, VaultError>;
    async fn update_credential(&self, id: uuid::Uuid, name: Option<&str>, token: Option<&str>, oauth: Option<&serde_json::Value>) -> Result<bool, VaultError>;
    async fn delete_credential(&self, id: uuid::Uuid) -> Result<bool, VaultError>;
    async fn update_credential_token(&self, id: uuid::Uuid, token: &str, expires_at: Option<chrono::DateTime<chrono::Utc>>) -> Result<bool, VaultError>;

    fn provider_name(&self) -> &str;
}
