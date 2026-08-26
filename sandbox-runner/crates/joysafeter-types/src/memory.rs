use serde::{Deserialize, Serialize};

use crate::{ApiKeyId, MemoryId, MemoryStoreId, MemoryVersionId, SessionId, SessionResourceId};

// --- Enums ---

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryOperation {
    Created,
    Modified,
    Deleted,
}

impl std::fmt::Display for MemoryOperation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Created => write!(f, "created"),
            Self::Modified => write!(f, "modified"),
            Self::Deleted => write!(f, "deleted"),
        }
    }
}

impl MemoryOperation {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "created" | "create" => Self::Created,
            "modified" | "update" => Self::Modified,
            "deleted" | "delete" => Self::Deleted,
            _ => Self::Created,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryAccess {
    #[default]
    ReadWrite,
    ReadOnly,
}

impl std::fmt::Display for MemoryAccess {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ReadWrite => write!(f, "read_write"),
            Self::ReadOnly => write!(f, "read_only"),
        }
    }
}

impl MemoryAccess {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "read_only" => Self::ReadOnly,
            _ => Self::ReadWrite,
        }
    }
}

// --- Actor types (for created_by / redacted_by) ---

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Actor {
    #[serde(rename = "session_actor")]
    SessionActor { session_id: SessionId },
    #[serde(rename = "api_actor")]
    ApiActor { api_key_id: ApiKeyId },
    #[serde(rename = "user_actor")]
    UserActor { user_id: String },
}

// --- Domain types ---

fn default_memory_store_type() -> String {
    "memory_store".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryStore {
    pub id: MemoryStoreId,
    #[serde(rename = "type", default = "default_memory_store_type")]
    pub object_type: String,
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(default = "default_metadata")]
    pub metadata: serde_json::Value,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

fn default_metadata() -> serde_json::Value {
    serde_json::json!({})
}

fn default_memory_type() -> String {
    "memory".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Memory {
    pub id: MemoryId,
    #[serde(rename = "type", default = "default_memory_type")]
    pub object_type: String,
    #[serde(rename = "memory_store_id")]
    pub store_id: MemoryStoreId,
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    pub content_sha256: String,
    #[serde(rename = "content_size_bytes")]
    pub size_bytes: i32,
    #[serde(rename = "memory_version_id")]
    pub current_version_id: MemoryVersionId,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

fn default_memory_version_type() -> String {
    "memory_version".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryVersion {
    pub id: MemoryVersionId,
    #[serde(rename = "type", default = "default_memory_version_type")]
    pub object_type: String,
    #[serde(rename = "memory_store_id")]
    pub store_id: MemoryStoreId,
    pub memory_id: MemoryId,
    pub operation: MemoryOperation,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content_sha256: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content_size_bytes: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub created_by: Option<Actor>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub redacted_at: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub redacted_by: Option<Actor>,
}

fn default_session_memory_store_type() -> String {
    "session_memory_store".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMemoryStore {
    pub id: SessionResourceId,
    #[serde(rename = "type", default = "default_session_memory_store_type")]
    pub object_type: String,
    pub session_id: SessionId,
    pub store_id: MemoryStoreId,
    pub access: MemoryAccess,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instructions: Option<String>,
    pub mount_name: String,
    pub created_at: chrono::DateTime<chrono::Utc>,
}

/// Rollup marker for directory listing when `depth` is set.
#[derive(Debug, Clone, Serialize)]
pub struct MemoryPrefix {
    pub path: String,
    #[serde(rename = "type")]
    pub object_type: String,
}
