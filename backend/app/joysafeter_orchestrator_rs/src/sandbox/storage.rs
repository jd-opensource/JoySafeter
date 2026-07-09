//! Storage abstraction for reading files from different backends.
//!
//! Supports local filesystem and S3-compatible object storage (AWS S3, JD Cloud
//! OSS, MinIO, Aliyun OSS). The backend is selected by the `STORAGE_BACKEND`
//! environment variable (`local` or `s3`/`oss`).
//!
//! This module is used by both `file_injection.rs` (workspace preload) and
//! `harness_input_builder.rs` (gRPC file mount) to read file content from
//! storage before injecting it into sandbox containers.

use std::env;
use std::path::Path;
use std::sync::OnceLock;

use anyhow::Context;
use aws_config::{BehaviorVersion, Region};
use aws_credential_types::Credentials;
use aws_sdk_s3::config::Builder as S3ConfigBuilder;
use aws_sdk_s3::Client as S3Client;
use tracing::debug;

/// Read a file from the configured storage backend.
///
/// Returns the raw bytes of the file identified by `storage_key`.
/// The backend is determined by `STORAGE_BACKEND` env var:
///   - `local` (default): reads from `$STORAGE_LOCAL_PATH/{storage_key}`
///   - `s3` / `oss`: downloads from S3-compatible object storage
pub async fn read_file(storage_key: &str) -> anyhow::Result<Vec<u8>> {
    let backend = storage_backend();
    match backend.as_str() {
        "local" => read_from_local(storage_key).await,
        "s3" | "oss" => read_from_s3(storage_key).await,
        other => anyhow::bail!("Unsupported STORAGE_BACKEND={other}. Expected local, s3, or oss."),
    }
}

/// Return the configured storage backend name (lowercase).
pub fn storage_backend() -> String {
    env::var("STORAGE_BACKEND")
        .unwrap_or_else(|_| "local".to_string())
        .to_lowercase()
}

// ---------------------------------------------------------------------------
// Local filesystem backend
// ---------------------------------------------------------------------------

async fn read_from_local(storage_key: &str) -> anyhow::Result<Vec<u8>> {
    let base = env::var("STORAGE_LOCAL_PATH").unwrap_or_else(|_| "data/files".to_string());
    let base_path = Path::new(&base);
    let base_abs = if base_path.is_absolute() {
        base_path.to_path_buf()
    } else {
        env::current_dir()?.join(base_path)
    };
    let resolved_base = base_abs.canonicalize().unwrap_or(base_abs);
    let candidate = resolved_base.join(storage_key);
    let resolved = candidate
        .canonicalize()
        .with_context(|| format!("storage file not found: {storage_key}"))?;
    if !resolved.starts_with(&resolved_base) {
        anyhow::bail!("path traversal detected: {storage_key}");
    }
    Ok(tokio::fs::read(resolved).await?)
}

// ---------------------------------------------------------------------------
// S3-compatible object storage backend
// ---------------------------------------------------------------------------

/// S3 configuration parsed from environment variables (cached).
struct S3Config {
    bucket: String,
    endpoint: Option<String>,
    access_key: String,
    secret_key: String,
    region: String,
}

static S3_CONFIG: OnceLock<Option<S3Config>> = OnceLock::new();

fn get_s3_config() -> anyhow::Result<&'static S3Config> {
    let config = S3_CONFIG.get_or_init(|| {
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
        .ok_or_else(|| anyhow::anyhow!("S3 storage not configured: missing STORAGE_S3_BUCKET and/or STORAGE_S3_ACCESS_KEY"))
}

async fn build_s3_client(config: &S3Config) -> S3Client {
    let credentials = Credentials::new(
        &config.access_key,
        &config.secret_key,
        None,
        None,
        "joysafeter-env",
    );
    let base_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new(config.region.clone()))
        .credentials_provider(credentials)
        .load()
        .await;
    let mut builder = S3ConfigBuilder::from(&base_config).force_path_style(true);
    if let Some(ref endpoint) = config.endpoint {
        builder = builder.endpoint_url(endpoint);
    }
    S3Client::from_conf(builder.build())
}

async fn read_from_s3(storage_key: &str) -> anyhow::Result<Vec<u8>> {
    let config = get_s3_config()?;
    let client = build_s3_client(config).await;
    debug!(
        bucket = %config.bucket,
        key = %storage_key,
        "Downloading file from S3"
    );
    let resp = client
        .get_object()
        .bucket(&config.bucket)
        .key(storage_key)
        .send()
        .await
        .with_context(|| format!("S3 get_object failed: bucket={}, key={storage_key}", config.bucket))?;
    let bytes = resp
        .body
        .collect()
        .await
        .with_context(|| format!("S3 body read failed: {storage_key}"))?
        .into_bytes()
        .to_vec();
    debug!(
        key = %storage_key,
        size = bytes.len(),
        "Downloaded file from S3"
    );
    Ok(bytes)
}
