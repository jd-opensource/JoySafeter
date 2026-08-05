use std::fs;
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use anyhow::{bail, Context};
use zip::write::FileOptions;

use crate::proto;

const WORKSPACE_ROOT: &str = "/workspace";
const DEFAULT_MAX_RAW_BYTES: u64 = 8 * 1024 * 1024;
const MAX_TEXT_BYTES: u64 = 2 * 1024 * 1024;
const DEFAULT_MAX_ARCHIVE_BYTES: u64 = 8 * 1024 * 1024;
const HARD_MAX_ARCHIVE_BYTES: u64 = 100 * 1024 * 1024;
const MAX_ARCHIVE_FILES: usize = 5000;

pub async fn handle_request(request: proto::SandboxFileRequest) -> proto::SandboxFileResponse {
    let request_id = request.request_id.clone();
    let result = tokio::task::spawn_blocking(move || handle_request_blocking(request)).await;
    match result {
        Ok(Ok(response)) => response,
        Ok(Err(err)) => error_response(request_id, "SANDBOX_FILE_ERROR", err.to_string()),
        Err(err) => error_response(request_id, "SANDBOX_FILE_JOIN_ERROR", err.to_string()),
    }
}

fn handle_request_blocking(
    request: proto::SandboxFileRequest,
) -> anyhow::Result<proto::SandboxFileResponse> {
    let (root, path) = resolve_workspace_path(&request.path)?;
    let max_bytes = if request.max_bytes == 0 {
        match request.operation.as_str() {
            "archive" | "zip" => DEFAULT_MAX_ARCHIVE_BYTES,
            _ => DEFAULT_MAX_RAW_BYTES,
        }
    } else {
        request.max_bytes.min(HARD_MAX_ARCHIVE_BYTES)
    };
    match request.operation.as_str() {
        "list" => list_path(&request.request_id, &root, &path),
        "content" => read_content(&request.request_id, &root, &path),
        "raw" => read_raw(&request.request_id, &root, &path, max_bytes),
        "archive" | "zip" => archive_path(&request.request_id, &root, &path, max_bytes),
        other => Ok(error_response(
            request.request_id,
            "INVALID_OPERATION",
            format!("unsupported sandbox file operation: {other}"),
        )),
    }
}

fn resolve_workspace_path(raw: &str) -> anyhow::Result<(PathBuf, PathBuf)> {
    if raw.contains('\0') {
        bail!("path contains NUL byte");
    }
    let root = fs::canonicalize(workspace_root()).context("workspace root not found")?;
    let candidate = if raw.trim().is_empty() || raw == WORKSPACE_ROOT {
        root.clone()
    } else if let Some(rest) = raw.strip_prefix("/workspace/") {
        root.join(rest)
    } else if Path::new(raw).is_absolute() {
        PathBuf::from(raw)
    } else {
        root.join(raw)
    };
    let resolved = fs::canonicalize(&candidate)
        .with_context(|| format!("path not found: {}", display_user_path(raw)))?;
    ensure_under_root(&root, &resolved)?;
    Ok((root, resolved))
}

fn workspace_root() -> String {
    #[cfg(test)]
    if let Ok(root) = std::env::var("JOYSAFETER_TEST_WORKSPACE_ROOT") {
        return root;
    }
    WORKSPACE_ROOT.to_string()
}

fn ensure_under_root(root: &Path, path: &Path) -> anyhow::Result<()> {
    if path == root || path.starts_with(root) {
        Ok(())
    } else {
        bail!("path must stay under /workspace")
    }
}

fn display_user_path(raw: &str) -> String {
    if raw.is_empty() {
        WORKSPACE_ROOT.to_string()
    } else {
        raw.to_string()
    }
}

fn workspace_path(root: &Path, path: &Path) -> String {
    if path == root {
        return WORKSPACE_ROOT.to_string();
    }
    let rel = path.strip_prefix(root).unwrap_or(path);
    format!("/workspace/{}", rel.to_string_lossy())
}

fn file_mtime(metadata: &fs::Metadata) -> i64 {
    metadata
        .modified()
        .ok()
        .and_then(|mtime| mtime.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}

fn entry_for(root: &Path, path: &Path) -> anyhow::Result<proto::SandboxFileEntry> {
    let metadata = fs::metadata(path)?;
    Ok(proto::SandboxFileEntry {
        name: path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("workspace")
            .to_string(),
        path: workspace_path(root, path),
        file_type: if metadata.is_dir() {
            "directory"
        } else {
            "file"
        }
        .to_string(),
        size: metadata.len(),
        mtime: file_mtime(&metadata),
    })
}

fn is_hidden_entry(path: &Path) -> bool {
    path.file_name()
        .and_then(|value| value.to_str())
        .is_some_and(|name| name.starts_with('.'))
}

fn list_path(
    request_id: &str,
    root: &Path,
    path: &Path,
) -> anyhow::Result<proto::SandboxFileResponse> {
    let metadata = fs::metadata(path)?;
    let mut entries = Vec::new();
    if metadata.is_dir() {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            if is_hidden_entry(&entry.path()) {
                continue;
            }
            if entry.file_type()?.is_symlink() {
                continue;
            }
            let child = fs::canonicalize(entry.path())?;
            if ensure_under_root(root, &child).is_ok() {
                entries.push(entry_for(root, &child)?);
            }
        }
        entries.sort_by(|a, b| {
            let kind = (a.file_type != "directory").cmp(&(b.file_type != "directory"));
            kind.then_with(|| a.name.cmp(&b.name))
        });
    } else {
        entries.push(entry_for(root, path)?);
    }
    Ok(proto::SandboxFileResponse {
        request_id: request_id.to_string(),
        ok: true,
        path: workspace_path(root, path),
        entries,
        ..Default::default()
    })
}

fn read_raw(
    request_id: &str,
    root: &Path,
    path: &Path,
    max_bytes: u64,
) -> anyhow::Result<proto::SandboxFileResponse> {
    let metadata = fs::metadata(path)?;
    if !metadata.is_file() {
        return Ok(error_response(
            request_id.to_string(),
            "NOT_FILE",
            "path is not a file",
        ));
    }
    if metadata.len() > max_bytes {
        return Ok(error_response(
            request_id.to_string(),
            "FILE_TOO_LARGE",
            "file exceeds download size limit",
        ));
    }
    let data = fs::read(path)?;
    Ok(proto::SandboxFileResponse {
        request_id: request_id.to_string(),
        ok: true,
        path: workspace_path(root, path),
        content_bytes: data,
        filename: path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("download")
            .to_string(),
        content_type: "application/octet-stream".to_string(),
        size: metadata.len(),
        ..Default::default()
    })
}

fn read_content(
    request_id: &str,
    root: &Path,
    path: &Path,
) -> anyhow::Result<proto::SandboxFileResponse> {
    let metadata = fs::metadata(path)?;
    if !metadata.is_file() {
        return Ok(error_response(
            request_id.to_string(),
            "NOT_FILE",
            "path is not a file",
        ));
    }
    if metadata.len() > MAX_TEXT_BYTES {
        return Ok(error_response(
            request_id.to_string(),
            "FILE_TOO_LARGE",
            "file exceeds preview size limit",
        ));
    }
    let data = fs::read(path)?;
    match String::from_utf8(data.clone()) {
        Ok(content) => Ok(proto::SandboxFileResponse {
            request_id: request_id.to_string(),
            ok: true,
            path: workspace_path(root, path),
            encoding: "utf-8".to_string(),
            content,
            size: metadata.len(),
            ..Default::default()
        }),
        Err(_) => Ok(proto::SandboxFileResponse {
            request_id: request_id.to_string(),
            ok: true,
            path: workspace_path(root, path),
            encoding: "base64".to_string(),
            content_bytes: data,
            size: metadata.len(),
            ..Default::default()
        }),
    }
}

fn archive_path(
    request_id: &str,
    root: &Path,
    path: &Path,
    max_bytes: u64,
) -> anyhow::Result<proto::SandboxFileResponse> {
    let metadata = fs::metadata(path)?;
    if !(metadata.is_file() || metadata.is_dir()) {
        return Ok(error_response(
            request_id.to_string(),
            "INVALID_FILE_TYPE",
            "unsupported file type",
        ));
    }

    let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let mut stats = ArchiveStats::default();
    if metadata.is_file() {
        add_file(
            root,
            path,
            path.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("download"),
            &mut zip,
            &mut stats,
        )?;
    } else {
        let base_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("workspace")
            .to_string();
        walk_archive(root, path, &base_name, &mut zip, &mut stats)?;
    }
    let cursor = zip.finish()?;
    let data = cursor.into_inner();
    let data_len = data.len() as u64;
    if data.is_empty() {
        return Ok(error_response(
            request_id.to_string(),
            "ARCHIVE_EMPTY",
            "archive is empty",
        ));
    }
    if data.len() as u64 > max_bytes {
        return Ok(error_response(
            request_id.to_string(),
            "ARCHIVE_TOO_LARGE",
            "archive exceeds size limit",
        ));
    }
    let filename = format!(
        "{}.zip",
        path.file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("workspace")
    );
    Ok(proto::SandboxFileResponse {
        request_id: request_id.to_string(),
        ok: true,
        path: workspace_path(root, path),
        content_bytes: data,
        filename,
        content_type: "application/zip".to_string(),
        size: data_len,
        ..Default::default()
    })
}

#[derive(Default)]
struct ArchiveStats {
    files: usize,
    bytes: u64,
}

fn walk_archive(
    root: &Path,
    dir: &Path,
    base_name: &str,
    zip: &mut zip::ZipWriter<Cursor<Vec<u8>>>,
    stats: &mut ArchiveStats,
) -> anyhow::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        if is_hidden_entry(&entry.path()) {
            continue;
        }
        if entry.file_type()?.is_symlink() {
            continue;
        }
        let path = fs::canonicalize(entry.path())?;
        ensure_under_root(root, &path)?;
        let metadata = fs::metadata(&path)?;
        if metadata.is_dir() {
            let child_base = format!("{}/{}", base_name, entry.file_name().to_string_lossy());
            walk_archive(root, &path, &child_base, zip, stats)?;
        } else if metadata.is_file() {
            let rel = path.strip_prefix(dir).unwrap_or(&path).to_string_lossy();
            add_file(root, &path, &format!("{base_name}/{rel}"), zip, stats)?;
        }
    }
    Ok(())
}

fn add_file(
    root: &Path,
    path: &Path,
    archive_path: &str,
    zip: &mut zip::ZipWriter<Cursor<Vec<u8>>>,
    stats: &mut ArchiveStats,
) -> anyhow::Result<()> {
    ensure_under_root(root, path)?;
    let metadata = fs::metadata(path)?;
    if !metadata.is_file() {
        return Ok(());
    }
    stats.files += 1;
    stats.bytes += metadata.len();
    if stats.files > MAX_ARCHIVE_FILES || stats.bytes > HARD_MAX_ARCHIVE_BYTES {
        bail!("archive exceeds size or file count limit");
    }
    let options: FileOptions<'_, ()> = FileOptions::default().unix_permissions(0o600);
    zip.start_file(archive_path.replace('\\', "/"), options)?;
    let data = fs::read(path)?;
    zip.write_all(&data)?;
    Ok(())
}

fn error_response(
    request_id: String,
    code: &str,
    error: impl Into<String>,
) -> proto::SandboxFileResponse {
    proto::SandboxFileResponse {
        request_id,
        ok: false,
        code: code.to_string(),
        error: error.into(),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    static TEST_WORKSPACE_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    #[tokio::test(flavor = "current_thread")]
    async fn lists_reads_and_archives_workspace_files() {
        let _guard = TEST_WORKSPACE_LOCK.lock().await;
        let temp = tempdir().expect("temp workspace");
        std::env::set_var("JOYSAFETER_TEST_WORKSPACE_ROOT", temp.path());
        fs::write(temp.path().join("hello.txt"), b"hello artifact").expect("write file");
        fs::write(temp.path().join(".claude.json"), b"hidden config").expect("write hidden file");
        fs::create_dir(temp.path().join(".cache")).expect("mkdir hidden dir");
        fs::write(temp.path().join(".cache/token.txt"), b"hidden cache")
            .expect("write hidden cache");
        fs::create_dir(temp.path().join("artifacts")).expect("mkdir artifacts");
        fs::write(temp.path().join("artifacts/result.txt"), b"artifact-result")
            .expect("write artifact");
        fs::write(temp.path().join("artifacts/.secret"), b"hidden artifact")
            .expect("write hidden artifact");

        let list = handle_request(proto::SandboxFileRequest {
            request_id: "list-1".to_string(),
            operation: "list".to_string(),
            path: "/workspace".to_string(),
            max_bytes: 0,
        })
        .await;
        assert!(list.ok, "list failed: {}", list.error);
        assert!(list.entries.iter().any(|entry| entry.name == "hello.txt"));
        assert!(list
            .entries
            .iter()
            .any(|entry| entry.name == "artifacts" && entry.file_type == "directory"));
        assert!(!list.entries.iter().any(|entry| entry.name.starts_with('.')));

        let raw = handle_request(proto::SandboxFileRequest {
            request_id: "raw-1".to_string(),
            operation: "raw".to_string(),
            path: "/workspace/hello.txt".to_string(),
            max_bytes: 1024,
        })
        .await;
        assert!(raw.ok, "raw failed: {}", raw.error);
        assert_eq!(raw.content_bytes, b"hello artifact");

        let archive = handle_request(proto::SandboxFileRequest {
            request_id: "archive-1".to_string(),
            operation: "archive".to_string(),
            path: "/workspace/artifacts".to_string(),
            max_bytes: 1024 * 1024,
        })
        .await;
        assert!(archive.ok, "archive failed: {}", archive.error);
        assert_eq!(archive.content_type, "application/zip");
        assert!(!archive.content_bytes.is_empty());
        let zip = zip::ZipArchive::new(Cursor::new(archive.content_bytes)).expect("open archive");
        let names: Vec<String> = zip.file_names().map(ToString::to_string).collect();
        assert!(names.iter().any(|name| name == "artifacts/result.txt"));
        assert!(!names.iter().any(|name| name.contains("/.")));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn rejects_workspace_escape_and_oversized_downloads() {
        let _guard = TEST_WORKSPACE_LOCK.lock().await;
        let temp = tempdir().expect("temp workspace");
        std::env::set_var("JOYSAFETER_TEST_WORKSPACE_ROOT", temp.path());
        let outside = tempdir().expect("outside");
        let outside_file = outside.path().join("secret.txt");
        fs::write(&outside_file, b"secret").expect("write outside");
        fs::write(temp.path().join("big.txt"), b"too-big").expect("write big");

        let escaped = handle_request(proto::SandboxFileRequest {
            request_id: "escape-1".to_string(),
            operation: "raw".to_string(),
            path: outside_file.to_string_lossy().to_string(),
            max_bytes: 1024,
        })
        .await;
        assert!(!escaped.ok);

        let oversized = handle_request(proto::SandboxFileRequest {
            request_id: "big-1".to_string(),
            operation: "raw".to_string(),
            path: "/workspace/big.txt".to_string(),
            max_bytes: 3,
        })
        .await;
        assert!(!oversized.ok);
        assert_eq!(oversized.code, "FILE_TOO_LARGE");
    }
}
