//! Storage abstraction for reading files from different backends.
//!
//! Provides a `StorageBackend` trait with `get` / `exists` methods and concrete
//! implementations for local filesystem and S3-compatible object storage.
//!
//! The active backend is selected by `STORAGE_BACKEND` env var (`local`, `s3`,
//! `oss`). Call [`create_backend()`] to get a boxed trait object, or use the
//! convenience [`read_file()`] which creates/caches the backend automatically.
//!
//! ## Adding a new backend
//!
//! 1. Create a struct implementing `StorageBackend`.
//! 2. Add a match arm in `create_backend()`.
//! 3. Done — `read_file()` and all callers pick it up automatically.

use std::env;
use std::path::{Component, Path};
use std::sync::OnceLock;

use anyhow::Context;
use async_trait::async_trait;
use aws_config::{BehaviorVersion, Region};
use aws_credential_types::Credentials;
use aws_sdk_s3::config::Builder as S3ConfigBuilder;
use aws_sdk_s3::Client as S3Client;
use tokio::sync::OnceCell;
use tracing::debug;

// ===========================================================================
// Trait
// ===========================================================================

/// Async storage backend for file read operations.
///
/// Mirrors the Python `StorageBackend` protocol in
/// `joysafeter_shared/storage/base.py`. The Rust orchestrator only needs read
/// access (files are written by the Python API process).
#[async_trait]
pub trait StorageBackend: Send + Sync {
    /// Write full content to storage.
    async fn put(
        &self,
        key: &str,
        data: &[u8],
        content_type: &str,
    ) -> anyhow::Result<()>;

    /// Read the full content of a file by storage key.
    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>>;

    /// Check if a file exists.
    async fn exists(&self, key: &str) -> anyhow::Result<bool>;
}

// ===========================================================================
// Factory
// ===========================================================================

/// Return the configured storage backend name (lowercase).
pub fn backend_name() -> String {
    env::var("STORAGE_BACKEND")
        .unwrap_or_else(|_| "local".to_string())
        .to_lowercase()
}

/// Create a storage backend instance based on `STORAGE_BACKEND` env var.
///
/// To add a new backend, add a match arm here.
pub fn create_backend() -> anyhow::Result<Box<dyn StorageBackend>> {
    let name = backend_name();
    match name.as_str() {
        "local" => {
            let base = env::var("STORAGE_LOCAL_PATH").unwrap_or_else(|_| "data/files".to_string());
            Ok(Box::new(LocalBackend::new(&base)?))
        }
        "s3" | "oss" => {
            let config = S3Config::from_env()?;
            Ok(Box::new(S3Backend::new(config)))
        }
        other => anyhow::bail!("Unsupported STORAGE_BACKEND={other}. Expected local, s3, or oss."),
    }
}

/// Global singleton backend (lazily initialized).
static BACKEND: OnceCell<Box<dyn StorageBackend>> = OnceCell::const_new();

async fn get_backend() -> anyhow::Result<&'static dyn StorageBackend> {
    let backend = BACKEND
        .get_or_try_init(|| async { create_backend() })
        .await?;
    Ok(backend.as_ref())
}

/// Convenience: read a file from the configured storage backend.
///
/// This is the primary entry point used by `file_injection.rs` and
/// `harness_input_builder.rs`.
pub async fn read_file(storage_key: &str) -> anyhow::Result<Vec<u8>> {
    validate_storage_key(storage_key)?;
    let backend = get_backend().await?;
    backend.get(storage_key).await
}

pub async fn write_file(
    storage_key: &str,
    data: &[u8],
    content_type: &str,
) -> anyhow::Result<()> {
    validate_storage_key(storage_key)?;
    let backend = get_backend().await?;
    backend.put(storage_key, data, content_type).await
}

// ===========================================================================
// Local filesystem backend
// ===========================================================================

pub struct LocalBackend {
    base: std::path::PathBuf,
}

impl LocalBackend {
    pub fn new(base_path: &str) -> anyhow::Result<Self> {
        let path = Path::new(base_path);
        let abs = if path.is_absolute() {
            path.to_path_buf()
        } else {
            env::current_dir()?.join(path)
        };
        Ok(Self {
            base: abs.canonicalize().unwrap_or(abs),
        })
    }

    fn resolve(&self, key: &str) -> anyhow::Result<std::path::PathBuf> {
        validate_storage_key(key)?;
        let candidate = self.base.join(key);
        let resolved = candidate
            .canonicalize()
            .with_context(|| format!("storage file not found: {key}"))?;
        if !resolved.starts_with(&self.base) {
            anyhow::bail!("path traversal detected: {key}");
        }
        Ok(resolved)
    }
}

#[async_trait]
impl StorageBackend for LocalBackend {
    async fn put(
        &self,
        key: &str,
        data: &[u8],
        _content_type: &str,
    ) -> anyhow::Result<()> {
        validate_storage_key(key)?;
        let candidate = self.base.join(key);
        let parent = candidate
            .parent()
            .ok_or_else(|| anyhow::anyhow!("invalid storage key: {key}"))?;
        if !parent.starts_with(&self.base) {
            anyhow::bail!("path traversal detected: {key}");
        }
        tokio::fs::create_dir_all(parent).await?;
        let parent = tokio::fs::canonicalize(parent).await?;
        if !parent.starts_with(&self.base) {
            anyhow::bail!("path traversal detected: {key}");
        }
        if let Ok(metadata) = tokio::fs::symlink_metadata(&candidate).await {
            if metadata.file_type().is_symlink() {
                anyhow::bail!("refusing to overwrite symlink storage key: {key}");
            }
            if metadata.is_dir() {
                anyhow::bail!("refusing to overwrite directory storage key: {key}");
            }
            let resolved = candidate.canonicalize()?;
            if !resolved.starts_with(&self.base) {
                anyhow::bail!("path traversal detected: {key}");
            }
        }
        tokio::fs::write(candidate, data).await?;
        Ok(())
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let path = self.resolve(key)?;
        Ok(tokio::fs::read(path).await?)
    }

    async fn exists(&self, key: &str) -> anyhow::Result<bool> {
        match self.resolve(key) {
            Ok(path) => Ok(path.exists()),
            Err(_) => Ok(false),
        }
    }
}

fn validate_storage_key(key: &str) -> anyhow::Result<()> {
    let path = Path::new(key);
    if key.is_empty() || path.is_absolute() || key.contains('\0') {
        anyhow::bail!("invalid storage key: {key}");
    }
    for component in path.components() {
        match component {
            Component::Normal(_) => {}
            _ => anyhow::bail!("invalid storage key: {key}"),
        }
    }
    Ok(())
}

// ===========================================================================
// S3-compatible object storage backend
// ===========================================================================

struct S3Config {
    bucket: String,
    endpoint: Option<String>,
    access_key: String,
    secret_key: String,
    region: String,
}

static S3_CONFIG_CACHE: OnceLock<Option<S3Config>> = OnceLock::new();

impl S3Config {
    fn from_env() -> anyhow::Result<Self> {
        let config = S3_CONFIG_CACHE.get_or_init(|| {
            let bucket = env::var("STORAGE_S3_BUCKET")
                .or_else(|_| env::var("STORAGE_OSS_BUCKET"))
                .ok()?;
            let endpoint = env::var("STORAGE_S3_ENDPOINT")
                .or_else(|_| env::var("STORAGE_OSS_ENDPOINT"))
                .ok();
            let access_key = env::var("STORAGE_S3_ACCESS_KEY")
                .or_else(|_| env::var("STORAGE_OSS_ACCESS_KEY"))
                .ok()?;
            let secret_key = env::var("STORAGE_S3_SECRET_KEY")
                .or_else(|_| env::var("STORAGE_OSS_SECRET_KEY"))
                .ok()?;
            let region = env::var("STORAGE_S3_REGION")
                .or_else(|_| env::var("STORAGE_OSS_REGION"))
                .unwrap_or_else(|_| "us-east-1".to_string());
            Some(S3Config {
                bucket,
                endpoint,
                access_key,
                secret_key,
                region,
            })
        });
        config
            .as_ref()
            .map(|c| S3Config {
                bucket: c.bucket.clone(),
                endpoint: c.endpoint.clone(),
                access_key: c.access_key.clone(),
                secret_key: c.secret_key.clone(),
                region: c.region.clone(),
            })
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "S3 storage not configured: missing STORAGE_S3_BUCKET and/or STORAGE_S3_ACCESS_KEY"
                )
            })
    }
}

pub struct S3Backend {
    bucket: String,
    endpoint: Option<String>,
    access_key: String,
    secret_key: String,
    region: String,
    /// M8 fix: Cache the S3 client so it isn't rebuilt on every get/exists call.
    /// Uses tokio::sync::OnceCell for lazy async initialization since new() is sync.
    cached_client: OnceCell<S3Client>,
}

impl S3Backend {
    pub fn new(config: S3Config) -> Self {
        Self {
            bucket: config.bucket,
            endpoint: config.endpoint,
            access_key: config.access_key,
            secret_key: config.secret_key,
            region: config.region,
            cached_client: OnceCell::new(),
        }
    }

    async fn client(&self) -> &S3Client {
        self.cached_client
            .get_or_init(|| async {
                let credentials = Credentials::new(
                    &self.access_key,
                    &self.secret_key,
                    None,
                    None,
                    "joysafeter-env",
                );
                let base_config = aws_config::defaults(BehaviorVersion::latest())
                    .region(Region::new(self.region.clone()))
                    .credentials_provider(credentials)
                    .load()
                    .await;
                let mut builder = S3ConfigBuilder::from(&base_config).force_path_style(true);
                if let Some(ref endpoint) = self.endpoint {
                    builder = builder.endpoint_url(endpoint);
                }
                S3Client::from_conf(builder.build())
            })
            .await
    }
}

#[async_trait]
impl StorageBackend for S3Backend {
    async fn put(
        &self,
        key: &str,
        data: &[u8],
        content_type: &str,
    ) -> anyhow::Result<()> {
        let client = self.client().await;
        client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(aws_sdk_s3::primitives::ByteStream::from(data.to_vec()))
            .content_type(content_type)
            .send()
            .await
            .with_context(|| format!("S3 put_object failed: {key}"))?;
        Ok(())
    }

    async fn get(&self, key: &str) -> anyhow::Result<Vec<u8>> {
        let client = self.client().await;
        debug!(bucket = %self.bucket, key = %key, "Downloading file from S3");
        let resp = client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .with_context(|| format!("S3 get_object failed: bucket={}, key={key}", self.bucket))?;
        let bytes = resp
            .body
            .collect()
            .await
            .with_context(|| format!("S3 body read failed: {key}"))?
            .into_bytes()
            .to_vec();
        debug!(key = %key, size = bytes.len(), "Downloaded file from S3");
        Ok(bytes)
    }

    async fn exists(&self, key: &str) -> anyhow::Result<bool> {
        let client = self.client().await;
        match client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}
