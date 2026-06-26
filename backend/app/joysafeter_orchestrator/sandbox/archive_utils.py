"""Safe archive extraction for sandbox file resources."""

from __future__ import annotations

import logging
import os
import tarfile
import tempfile
import zipfile
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

SUPPORTED_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")
MAX_EXTRACTED_FILES = 10_000
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024


def archive_extract_dir(path: str) -> str | None:
    """Return the sibling extraction directory for a supported archive path."""
    filename = os.path.basename(path)
    lower = filename.lower()
    for suffix in SUPPORTED_ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return os.path.join(os.path.dirname(path), filename[: -len(suffix)])
    return None


def auto_extract_archive(path: str) -> str | None:
    """Extract a supported archive next to itself. Returns the target dir if extracted."""
    target_dir = archive_extract_dir(path)
    if not target_dir:
        return None
    extract_archive_to_dir(path, target_dir)
    return target_dir


def extract_archive_to_dir(path: str, target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    lower = os.path.basename(path).lower()
    if lower.endswith(".zip"):
        _extract_zip(path, target_dir)
    elif lower.endswith((".tar.gz", ".tgz", ".tar")):
        _extract_tar(path, target_dir)
    else:
        return
    logger.info("Auto-extracted archive %s -> %s", path, target_dir)


async def auto_extract_archive_into_container(
    exec_docker,
    external_id: str,
    archive_path: str,
    data: bytes,
) -> bool:
    """Extract archive on host safely, then docker cp extracted contents into the sandbox."""
    target_dir = archive_extract_dir(archive_path)
    if not target_dir:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        archive_tmp = os.path.join(tmp, os.path.basename(archive_path))
        extracted_tmp = os.path.join(tmp, "extracted")
        with open(archive_tmp, "wb") as fh:
            fh.write(data)
        extract_archive_to_dir(archive_tmp, extracted_tmp)
        await exec_docker("exec", external_id, "mkdir", "-p", target_dir)
        await exec_docker("cp", os.path.join(extracted_tmp, "."), f"{external_id}:{target_dir}")
    return True


def _safe_member_path(target_dir: str, name: str) -> str | None:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _has_windows_drive(normalized):
        return None

    parts: list[str] = []
    for part in PurePosixPath(normalized).parts:
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)

    if not parts:
        return None

    root = os.path.realpath(target_dir)
    candidate = os.path.realpath(os.path.join(root, *parts))
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _has_windows_drive(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


def _extract_zip(path: str, target_dir: str) -> None:
    total_bytes = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_EXTRACTED_FILES:
            raise ValueError(f"archive has too many entries: {len(infos)}")
        for info in infos:
            if _zip_is_symlink(info):
                logger.warning("Skipping zip symlink entry: %s", info.filename)
                continue
            target = _safe_member_path(target_dir, info.filename)
            if not target:
                logger.warning("Skipping unsafe zip entry: %s", info.filename)
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            total_bytes += info.file_size
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise ValueError("archive extracted size exceeds limit")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())


def _zip_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def _extract_tar(path: str, target_dir: str) -> None:
    total_bytes = 0
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if len(members) > MAX_EXTRACTED_FILES:
            raise ValueError(f"archive has too many entries: {len(members)}")
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                logger.warning("Skipping unsafe tar entry: %s", member.name)
                continue
            target = _safe_member_path(target_dir, member.name)
            if not target:
                logger.warning("Skipping unsafe tar entry: %s", member.name)
                continue
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if not member.isfile():
                continue
            total_bytes += member.size
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise ValueError("archive extracted size exceeds limit")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = archive.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as dst:
                dst.write(src.read())
