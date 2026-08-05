use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context};
use flate2::read::GzDecoder;
use tracing::{info, warn};

const SUPPORTED_ARCHIVE_SUFFIXES: &[&str] = &[".tar.gz", ".tgz", ".tar", ".zip"];
const MAX_EXTRACTED_FILES: usize = 10_000;
const MAX_EXTRACTED_BYTES: u64 = 1024 * 1024 * 1024;

/// Return the directory an archive should be extracted into.
///
/// Extracts into the archive's PARENT directory (not a same-named subdir), so
/// the archive's own internal structure decides the layout. This avoids double
/// nesting like `foo/foo/...` when the zip already contains a top-level `foo/`.
pub fn archive_extract_dir(path: &Path) -> Option<PathBuf> {
    let filename = path.file_name()?.to_str()?;
    let lower = filename.to_ascii_lowercase();
    for suffix in SUPPORTED_ARCHIVE_SUFFIXES {
        if lower.ends_with(suffix) {
            return Some(
                path.parent()
                    .unwrap_or_else(|| Path::new("."))
                    .to_path_buf(),
            );
        }
    }
    None
}

pub async fn auto_extract_archive(path: &Path) -> anyhow::Result<Option<PathBuf>> {
    let Some(target_dir) = archive_extract_dir(path) else {
        return Ok(None);
    };
    let archive_path = path.to_path_buf();
    let extract_dir = target_dir.clone();
    tokio::task::spawn_blocking(move || {
        extract_archive_to_dir_blocking(&archive_path, &extract_dir)
    })
    .await??;
    Ok(Some(target_dir))
}

fn extract_archive_to_dir_blocking(path: &Path, target_dir: &Path) -> anyhow::Result<()> {
    fs::create_dir_all(target_dir)
        .with_context(|| format!("create extract dir {}", target_dir.display()))?;
    let filename = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();

    if filename.ends_with(".zip") {
        extract_zip(path, target_dir)?;
    } else if filename.ends_with(".tar.gz") || filename.ends_with(".tgz") {
        let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
        extract_tar_reader(GzDecoder::new(file), target_dir)?;
    } else if filename.ends_with(".tar") {
        let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
        extract_tar_reader(file, target_dir)?;
    }

    info!(
        archive = %path.display(),
        target = %target_dir.display(),
        "Auto-extracted archive"
    );
    Ok(())
}

fn extract_zip(path: &Path, target_dir: &Path) -> anyhow::Result<()> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut archive = zip::ZipArchive::new(file)?;
    if archive.len() > MAX_EXTRACTED_FILES {
        bail!("archive has too many entries: {}", archive.len());
    }

    let mut total_bytes = 0u64;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)?;
        let mode = entry.unix_mode().unwrap_or(0);
        if (mode & 0o170000) == 0o120000 {
            warn!(entry = %entry.name(), "Skipping zip symlink entry");
            continue;
        }
        let Some(enclosed) = entry.enclosed_name().map(|path| path.to_path_buf()) else {
            warn!(entry = %entry.name(), "Skipping unsafe zip entry");
            continue;
        };
        let Some(relative) = safe_member_path(&enclosed) else {
            warn!(entry = %entry.name(), "Skipping unsafe zip entry");
            continue;
        };
        let target = target_dir.join(relative);
        if entry.is_dir() {
            fs::create_dir_all(&target)?;
            continue;
        }
        total_bytes = total_bytes.saturating_add(entry.size());
        if total_bytes > MAX_EXTRACTED_BYTES {
            bail!("archive extracted size exceeds limit");
        }
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = File::create(&target)?;
        io::copy(&mut entry, &mut out)?;
    }
    Ok(())
}

pub fn extract_tar_gz_bytes_to_dir(bytes: &[u8], target_dir: &Path) -> anyhow::Result<()> {
    extract_tar_reader(GzDecoder::new(bytes), target_dir)
}

fn extract_tar_reader<R: Read>(reader: R, target_dir: &Path) -> anyhow::Result<()> {
    let mut archive = tar::Archive::new(reader);
    let mut count = 0usize;
    let mut total_bytes = 0u64;

    for entry_result in archive.entries()? {
        count += 1;
        if count > MAX_EXTRACTED_FILES {
            bail!("archive has too many entries: {count}");
        }
        let mut entry = entry_result?;
        let entry_type = entry.header().entry_type();
        let entry_path = entry.path()?.into_owned();
        let Some(relative) = safe_member_path(&entry_path) else {
            warn!(entry = %entry_path.display(), "Skipping unsafe tar entry");
            continue;
        };
        let target = target_dir.join(relative);
        if entry_type.is_dir() {
            fs::create_dir_all(&target)?;
            continue;
        }
        if !entry_type.is_file() {
            warn!(entry = %entry_path.display(), "Skipping unsupported tar entry");
            continue;
        }
        total_bytes = total_bytes.saturating_add(entry.size());
        if total_bytes > MAX_EXTRACTED_BYTES {
            bail!("archive extracted size exceeds limit");
        }
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = File::create(&target)?;
        io::copy(&mut entry, &mut out)?;
    }
    Ok(())
}

fn safe_member_path(path: &Path) -> Option<PathBuf> {
    let raw = path.to_string_lossy();
    if raw.contains('\\') || has_windows_drive(&raw) {
        return None;
    }

    let mut relative = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(part) => relative.push(part),
            Component::CurDir => {}
            _ => return None,
        }
    }

    if relative.as_os_str().is_empty() {
        None
    } else {
        Some(relative)
    }
}

fn has_windows_drive(path: &str) -> bool {
    let bytes = path.as_bytes();
    bytes.len() >= 2 && bytes[1] == b':' && bytes[0].is_ascii_alphabetic()
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::Write;
    use tar::{Builder, EntryType, Header};

    fn tar_gz(entries: Vec<(&str, EntryType, &[u8])>) -> Vec<u8> {
        let mut raw = Vec::new();
        {
            let mut builder = Builder::new(&mut raw);
            for (path, entry_type, content) in entries {
                let mut header = Header::new_gnu();
                header.set_entry_type(entry_type);
                header.set_size(content.len() as u64);
                header.set_mode(0o644);
                header.set_cksum();
                builder.append_data(&mut header, path, content).unwrap();
            }
            builder.finish().unwrap();
        }

        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&raw).unwrap();
        encoder.finish().unwrap()
    }

    #[test]
    fn safe_member_path_rejects_traversal_and_windows_paths() {
        assert_eq!(
            safe_member_path(Path::new("safe/SKILL.md")).unwrap(),
            PathBuf::from("safe/SKILL.md")
        );
        assert!(safe_member_path(Path::new("../outside.txt")).is_none());
        assert!(safe_member_path(Path::new("/tmp/outside.txt")).is_none());
        assert!(safe_member_path(Path::new("C:/Windows/System32/pwn.txt")).is_none());
        assert!(safe_member_path(Path::new("bad\\slash.txt")).is_none());
    }

    #[test]
    fn tar_extraction_skips_symlinks() {
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("target");
        let data = tar_gz(vec![("safe/link", EntryType::Symlink, b"../outside")]);

        extract_tar_gz_bytes_to_dir(&data, &target).unwrap();

        assert!(!target.join("safe/link").exists());
    }
}
