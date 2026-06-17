use serde::{Deserialize, Serialize, Serializer};

// --- ID serialization helpers ---

pub fn serialize_memory_store_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("memstore_{id}"))
}

pub fn serialize_memory_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("mem_{id}"))
}

fn serialize_memory_version_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("memver_{id}"))
}

fn serialize_session_resource_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("sesrsc_{id}"))
}

pub fn parse_memory_store_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("memstore_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

pub fn parse_memory_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("mem_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

pub fn parse_memory_version_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("memver_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryAccess {
    ReadWrite,
    ReadOnly,
}

impl Default for MemoryAccess {
    fn default() -> Self {
        Self::ReadWrite
    }
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
    SessionActor { session_id: String },
    #[serde(rename = "api_actor")]
    ApiActor { api_key_id: String },
    #[serde(rename = "user_actor")]
    UserActor { user_id: String },
}

// --- Domain types ---

fn default_memory_store_type() -> String {
    "memory_store".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryStore {
    #[serde(serialize_with = "serialize_memory_store_id")]
    pub id: uuid::Uuid,
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
    #[serde(serialize_with = "serialize_memory_id")]
    pub id: uuid::Uuid,
    #[serde(rename = "type", default = "default_memory_type")]
    pub object_type: String,
    #[serde(
        rename = "memory_store_id",
        serialize_with = "serialize_memory_store_id"
    )]
    pub store_id: uuid::Uuid,
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    pub content_sha256: String,
    #[serde(rename = "content_size_bytes")]
    pub size_bytes: i32,
    #[serde(
        rename = "memory_version_id",
        serialize_with = "serialize_memory_version_id"
    )]
    pub current_version_id: uuid::Uuid,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

fn default_memory_version_type() -> String {
    "memory_version".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryVersion {
    #[serde(serialize_with = "serialize_memory_version_id")]
    pub id: uuid::Uuid,
    #[serde(rename = "type", default = "default_memory_version_type")]
    pub object_type: String,
    #[serde(
        rename = "memory_store_id",
        serialize_with = "serialize_memory_store_id"
    )]
    pub store_id: uuid::Uuid,
    #[serde(serialize_with = "serialize_memory_id")]
    pub memory_id: uuid::Uuid,
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
    #[serde(serialize_with = "serialize_session_resource_id")]
    pub id: uuid::Uuid,
    #[serde(rename = "type", default = "default_session_memory_store_type")]
    pub object_type: String,
    pub session_id: uuid::Uuid,
    #[serde(serialize_with = "serialize_memory_store_id")]
    pub store_id: uuid::Uuid,
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
