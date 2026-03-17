"""
ArtifactResolver: list runs, list files, and resolve safe file paths for download.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.agent.artifacts.collector import (
    MANIFEST_FILENAME,
    resolve_artifacts_root,
)
from app.utils.path_utils import sanitize_path_component


@dataclass
class RunInfo:
    """Summary of a single run's artifacts."""

    run_id: str
    thread_id: str
    user_id: str
    path: str  # relative path under artifacts root, e.g. user_id/thread_id/run_id
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: Optional[str] = None
    agent_type: Optional[str] = None
    graph_id: Optional[str] = None
    file_count: int = 0


@dataclass
class FileInfo:
    """A single file or directory in a run's artifact tree."""

    name: str
    path: str  # relative path from run root
    type: str  # "file" | "directory"
    size: Optional[int] = None
    content_type: Optional[str] = None
    children: Optional[list["FileInfo"]] = None


class ArtifactResolver:
    """Resolves artifact paths and lists runs/files from the artifacts filesystem."""

    def __init__(self, artifacts_root: str | Path | None = None) -> None:
        self.root = Path(artifacts_root) if artifacts_root else resolve_artifacts_root()
        self.root = self.root.resolve()

    def _run_dir(self, user_id: str, thread_id: str, run_id: str) -> Path:
        """Sanitized run directory path (may not exist)."""
        uid = sanitize_path_component(user_id, default="default")
        tid = sanitize_path_component(thread_id, default="default")
        rid = sanitize_path_component(run_id, default="default")
        return self.root / uid / tid / rid

    def list_runs(self, user_id: str, thread_id: str) -> list[RunInfo]:
        """List all run directories for the given user and thread."""
        uid = sanitize_path_component(user_id, default="default")
        tid = sanitize_path_component(thread_id, default="default")
        thread_dir = self.root / uid / tid
        if not thread_dir.exists() or not thread_dir.is_dir():
            return []

        runs: list[RunInfo] = []
        for run_path in thread_dir.iterdir():
            if not run_path.is_dir():
                continue
            run_id = run_path.name
            manifest = self.read_manifest(user_id, thread_id, run_id)
            if manifest:
                runs.append(RunInfo(
                    run_id=run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    path=f"{uid}/{tid}/{run_id}",
                    started_at=manifest.get("started_at"),
                    completed_at=manifest.get("completed_at"),
                    status=manifest.get("status"),
                    agent_type=manifest.get("agent_type"),
                    graph_id=manifest.get("graph_id"),
                    file_count=len(manifest.get("files") or []),
                ))
            else:
                # No manifest: still list the run, scan file count
                file_count = sum(1 for _ in run_path.rglob("*") if _.is_file() and _.name != MANIFEST_FILENAME)
                runs.append(RunInfo(
                    run_id=run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    path=f"{uid}/{tid}/{run_id}",
                    file_count=file_count,
                ))

        # Sort by completed_at or path, newest first
        def sort_key(r: RunInfo) -> tuple:
            return (r.completed_at or r.run_id or "",)

        runs.sort(key=sort_key, reverse=True)
        return runs

    def read_manifest(self, user_id: str, thread_id: str, run_id: str) -> Optional[dict[str, Any]]:
        """Read _manifest.json for the run if it exists."""
        run_dir = self._run_dir(user_id, thread_id, run_id)
        manifest_path = run_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            return None
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def list_files(self, user_id: str, thread_id: str, run_id: str) -> list[FileInfo]:
        """List files and directories in the run as a tree (one level of children)."""
        run_dir = self._run_dir(user_id, thread_id, run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            return []

        result: list[FileInfo] = []
        seen: set[Path] = set()
        for path in sorted(run_dir.iterdir()):
            if path.name == MANIFEST_FILENAME:
                continue
            rel = path.relative_to(run_dir)
            rel_str = rel.as_posix()
            if path.is_dir():
                result.append(FileInfo(
                    name=path.name,
                    path=rel_str,
                    type="directory",
                    children=None,
                ))
            else:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                ct, _ = mimetypes.guess_type(str(path))
                result.append(FileInfo(
                    name=path.name,
                    path=rel_str,
                    type="file",
                    size=size,
                    content_type=ct,
                ))
        return result

    def list_files_tree(self, user_id: str, thread_id: str, run_id: str) -> list[FileInfo]:
        """List all files recursively as a tree (nested children)."""
        run_dir = self._run_dir(user_id, thread_id, run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            return []

        def build_node(p: Path, base: Path) -> FileInfo:
            rel = p.relative_to(base)
            rel_str = rel.as_posix()
            if p.is_dir():
                children = [build_node(c, base) for c in sorted(p.iterdir()) if c.name != MANIFEST_FILENAME]
                return FileInfo(name=p.name, path=rel_str, type="directory", children=children)
            try:
                size = p.stat().st_size
            except OSError:
                size = None
            ct, _ = mimetypes.guess_type(str(p))
            return FileInfo(name=p.name, path=rel_str, type="file", size=size, content_type=ct)

        root_children: list[FileInfo] = []
        for item in sorted(run_dir.iterdir()):
            if item.name == MANIFEST_FILENAME:
                continue
            root_children.append(build_node(item, run_dir))
        return root_children

    def get_file_path(
        self,
        user_id: str,
        thread_id: str,
        run_id: str,
        file_path: str,
    ) -> Optional[Path]:
        """
        Resolve a relative file path to an absolute path under the run directory.
        Returns None if the path escapes the run dir (security).
        """
        run_dir = self._run_dir(user_id, thread_id, run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            return None

        # Normalize: no leading slash, no ..
        parts = file_path.replace("\\", "/").strip("/").split("/")
        safe_parts: list[str] = []
        for part in parts:
            if not part or part in (".", ".."):
                continue
            safe_parts.append(sanitize_path_component(part, default=""))
        if any(p == "" for p in safe_parts):
            return None
        resolved = (run_dir / "/".join(safe_parts)).resolve()
        run_dir_resolved = run_dir.resolve()
        try:
            resolved.relative_to(run_dir_resolved)
        except ValueError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def delete_run(self, user_id: str, thread_id: str, run_id: str) -> bool:
        """Delete the entire run directory. Returns True if deleted or missing."""
        run_dir = self._run_dir(user_id, thread_id, run_id)
        run_dir_resolved = run_dir.resolve()
        try:
            run_dir_resolved.relative_to(self.root)
        except ValueError:
            return False
        if not run_dir.exists():
            return True
        try:
            shutil.rmtree(run_dir)
            return True
        except OSError:
            return False
