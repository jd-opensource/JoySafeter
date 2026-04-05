"""
Artifacts store for DeepAgents Copilot runs.

Directory layout (per run):
  $DEEPAGENTS_ARTIFACTS_DIR/{graph_id}/{run_id}/
    00_request.json
    analysis.json      (sub-agent artifact)
    blueprint.json     (sub-agent artifact)
    validation.json    (sub-agent artifact)
    actions.json       (final GraphAction list)
    events.sse.jsonl   (SSE event stream)
    index.json         (run index)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from app.utils.datetime import utc_now


def _default_artifacts_root() -> Path:
    return Path.home() / ".agent-platform" / "deepagents"


def resolve_artifacts_root() -> Path:
    env = os.getenv("DEEPAGENTS_ARTIFACTS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return _default_artifacts_root()


def _sanitize_path_component(component: str, default: str = "unknown") -> str:
    """
    Sanitize a path component to prevent directory traversal attacks.

    Rules:
    1. Remove all path separators (/, \\)
    2. Remove relative path symbols (.., .)
    3. Remove control characters and special characters
    4. Limit length (prevent excessively long paths)
    5. Fall back to default if sanitized result is empty

    Args:
        component: path component to sanitize
        default: fallback value if sanitization yields empty string

    Returns:
        Sanitized path component safe for filesystem use.
    """
    if not component:
        return default

    # remove all path separators and relative path symbols
    sanitized = re.sub(r"[\\/\.\.]+", "", component)

    # remove control characters, spaces, and special characters (keep letters, digits, underscores, hyphens)
    sanitized = re.sub(r"[^\w\-]", "", sanitized)

    # limit length (prevent excessively long paths)
    sanitized = sanitized[:100]

    # fall back to default if empty
    if not sanitized:
        return default

    return sanitized


def _sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent directory traversal attacks.

    Only allow letters, digits, underscores, hyphens, and dots; no path separators.

    Args:
        filename: filename to sanitize

    Returns:
        Sanitized filename safe for filesystem use.
    """
    if not filename:
        raise ValueError("Filename cannot be empty")

    # remove all path separators
    sanitized = filename.replace("/", "").replace("\\", "")

    # remove relative path symbols
    sanitized = sanitized.replace("..", "").replace(".", "")

    # keep only letters, digits, underscores, hyphens, dots
    sanitized = re.sub(r"[^\w\-\.]", "", sanitized)

    if not sanitized:
        raise ValueError(f"Invalid filename after sanitization: {filename}")

    return sanitized


@dataclass
class ArtifactStore:
    """Manages run directory and writing artifact files."""

    graph_id: Optional[str] = None
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    run_dir: Optional[Path] = None

    def __post_init__(self):
        # if run_dir is not specified, build it automatically
        if self.run_dir is None:
            root = resolve_artifacts_root()
            # sanitize graph_id and run_id to prevent directory traversal
            graph_dir = _sanitize_path_component(self.graph_id or "unknown_graph", default="unknown_graph")
            run_id_sanitized = _sanitize_path_component(self.run_id, default=f"run_{uuid.uuid4().hex[:12]}")
            self.run_dir = root / graph_dir / run_id_sanitized
            # update run_id to the sanitized value for consistency
            self.run_id = run_id_sanitized
        else:
            # if run_dir is provided, verify it is within the artifacts root
            root = resolve_artifacts_root()
            try:
                # use resolve() to get absolute path, then check containment
                resolved_run_dir = Path(self.run_dir).resolve()
                resolved_root = root.resolve()
                if not str(resolved_run_dir).startswith(str(resolved_root)):
                    raise ValueError(
                        f"run_dir must be within artifacts root: {resolved_run_dir} not in {resolved_root}"
                    )
            except Exception as e:
                logger.error(f"[ArtifactStore] Invalid run_dir: {e}")
                raise ValueError(f"Invalid run_dir: {e}") from e

        # ensure type is Path
        if isinstance(self.run_dir, str):
            self.run_dir = Path(self.run_dir)

    def ensure(self) -> None:
        """Ensure the run directory exists."""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # extra validation: ensure directory is within artifacts root
        root = resolve_artifacts_root()
        try:
            resolved_run_dir = self.run_dir.resolve()
            resolved_root = root.resolve()
            if not str(resolved_run_dir).startswith(str(resolved_root)):
                raise ValueError(f"run_dir escaped from artifacts root: {resolved_run_dir} not in {resolved_root}")
        except Exception as e:
            logger.error(f"[ArtifactStore] Security check failed: {e}")
            raise

    def _write_json(self, filename: str, data: Any) -> None:
        """Safely write a JSON file."""
        self.ensure()
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # sanitize filename to prevent directory traversal
        safe_filename = _sanitize_filename(filename)
        path = self.run_dir / safe_filename

        # extra validation: ensure final path is still within run_dir (defense in depth)
        try:
            resolved_path = path.resolve()
            resolved_run_dir = self.run_dir.resolve()
            if not str(resolved_path).startswith(str(resolved_run_dir)):
                raise ValueError(f"Path traversal detected: {resolved_path} not in {resolved_run_dir}")
        except Exception as e:
            logger.error(f"[ArtifactStore] Path traversal detected in filename: {filename}")
            raise ValueError(f"Invalid filename: {filename}") from e

        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def write_request(self, payload: Dict[str, Any]) -> None:
        self._write_json("00_request.json", payload)

    def write_analysis(self, payload: Dict[str, Any]) -> None:
        self._write_json("analysis.json", payload)

    def write_blueprint(self, payload: Dict[str, Any]) -> None:
        self._write_json("blueprint.json", payload)

    def write_validation(self, payload: Dict[str, Any]) -> None:
        self._write_json("validation.json", payload)

    def write_actions(self, payload: Union[List[Dict[str, Any]], Dict[str, Any]]) -> None:
        self._write_json("actions.json", payload)

    def write_index(self, payload: Dict[str, Any]) -> None:
        """Write the run index."""
        # add timestamp
        if "created_at" not in payload:
            payload["created_at"] = utc_now().isoformat()
        self._write_json("index.json", payload)

    def append_event(self, event: Dict[str, Any]) -> None:
        """Append SSE event envelope as jsonl for replay."""
        self.ensure()
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # use hardcoded filename; no sanitization needed
        path = self.run_dir / "events.sse.jsonl"

        # verify path safety
        try:
            resolved_path = path.resolve()
            resolved_run_dir = self.run_dir.resolve()
            if not str(resolved_path).startswith(str(resolved_run_dir)):
                raise ValueError("Path traversal detected in append_event")
        except Exception as e:
            logger.error(f"[ArtifactStore] Security check failed in append_event: {e}")
            raise

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    # ==================== Read Methods ====================

    def _read_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """Safely read a JSON file; return None on failure."""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # sanitize filename to prevent directory traversal
        safe_filename = _sanitize_filename(filename)
        path = self.run_dir / safe_filename

        # verify path safety
        try:
            resolved_path = path.resolve()
            resolved_run_dir = self.run_dir.resolve()
            if not str(resolved_path).startswith(str(resolved_run_dir)):
                logger.warning(f"[ArtifactStore] Path traversal detected in read: {filename}")
                return None
        except Exception as e:
            logger.warning(f"[ArtifactStore] Security check failed in read: {e}")
            return None

        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                result = json.load(f)
                return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[ArtifactStore] Failed to read {filename}: {e}")
            return None

    def read_analysis(self) -> Optional[Dict[str, Any]]:
        """Read the requirement analysis result."""
        return self._read_json("analysis.json")

    def read_blueprint(self) -> Optional[Dict[str, Any]]:
        """Read the workflow blueprint."""
        return self._read_json("blueprint.json")

    def read_validation(self) -> Optional[Dict[str, Any]]:
        """Read the validation report."""
        return self._read_json("validation.json")

    def read_actions(self) -> Optional[List[Dict[str, Any]]]:
        """Read the actions list."""
        data = self._read_json("actions.json")
        if isinstance(data, list):
            return data
        return None

    def read_index(self) -> Optional[Dict[str, Any]]:
        """Read the run index."""
        return self._read_json("index.json")

    def file_exists(self, filename: str) -> bool:
        """Check whether a file exists."""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        try:
            safe_filename = _sanitize_filename(filename)
            path = self.run_dir / safe_filename

            # verify path safety
            resolved_path = path.resolve()
            resolved_run_dir = self.run_dir.resolve()
            if not str(resolved_path).startswith(str(resolved_run_dir)):
                logger.warning(f"[ArtifactStore] Path traversal detected in file_exists: {filename}")
                return False
        except Exception as e:
            logger.warning(f"[ArtifactStore] Security check failed in file_exists: {e}")
            return False

        return path.exists()


def new_run_store(graph_id: str) -> ArtifactStore:
    """Create a new ArtifactStore instance."""
    # graph_id will be sanitized in __post_init__
    store = ArtifactStore(graph_id=graph_id)
    try:
        store.ensure()
    except Exception as e:
        logger.error(f"[ArtifactStore] Failed to create run dir: {e}")
        raise
    return store
