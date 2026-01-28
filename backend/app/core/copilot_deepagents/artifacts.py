"""
Artifacts store for DeepAgents Copilot runs.

Directory layout (per run):
  $DEEPAGENTS_ARTIFACTS_DIR/{graph_id}/{run_id}/
    00_request.json
    analysis.json      (子代理产物)
    blueprint.json     (子代理产物)
    validation.json    (子代理产物)
    actions.json       (最终 GraphAction 列表)
    events.sse.jsonl   (SSE 事件流)
    index.json         (运行索引)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger


def _default_artifacts_root() -> Path:
    return Path.home() / ".agent-platform" / "deepagents"


def resolve_artifacts_root() -> Path:
    env = os.getenv("DEEPAGENTS_ARTIFACTS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return _default_artifacts_root()


def _sanitize_path_component(component: str, default: str = "unknown") -> str:
    """
    清理路径组件，防止目录遍历攻击。

    规则：
    1. 移除所有路径分隔符（/, \\）
    2. 移除所有相对路径符号（.., .）
    3. 移除控制字符和特殊字符
    4. 限制长度（防止过长的路径）
    5. 如果清理后为空，使用默认值

    Args:
        component: 要清理的路径组件
        default: 清理失败时的默认值

    Returns:
        清理后的安全路径组件
    """
    if not component:
        return default

    # 移除所有路径分隔符和相对路径符号
    sanitized = re.sub(r"[\\/\.\.]+", "", component)

    # 移除控制字符、空格和特殊字符（只保留字母、数字、下划线、连字符）
    sanitized = re.sub(r"[^\w\-]", "", sanitized)

    # 限制长度（防止过长的路径）
    sanitized = sanitized[:100]

    # 如果清理后为空，使用默认值
    if not sanitized:
        return default

    return sanitized


def _sanitize_filename(filename: str) -> str:
    """
    清理文件名，防止目录遍历攻击。

    只允许字母、数字、下划线、连字符、点号，且不能包含路径分隔符。

    Args:
        filename: 要清理的文件名

    Returns:
        清理后的安全文件名
    """
    if not filename:
        raise ValueError("Filename cannot be empty")

    # 移除所有路径分隔符
    sanitized = filename.replace("/", "").replace("\\", "")

    # 移除相对路径符号
    sanitized = sanitized.replace("..", "").replace(".", "")

    # 只保留字母、数字、下划线、连字符、点号
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
        # 如果没有指定 run_dir，自动构建
        if self.run_dir is None:
            root = resolve_artifacts_root()
            # 清理 graph_id 和 run_id，防止目录遍历
            graph_dir = _sanitize_path_component(self.graph_id or "unknown_graph", default="unknown_graph")
            run_id_sanitized = _sanitize_path_component(self.run_id, default=f"run_{uuid.uuid4().hex[:12]}")
            self.run_dir = root / graph_dir / run_id_sanitized
            # 更新 run_id 为清理后的值，保持一致性
            self.run_id = run_id_sanitized
        else:
            # 如果提供了 run_dir，验证它是否在 artifacts root 内
            root = resolve_artifacts_root()
            try:
                # 使用 resolve() 解析绝对路径，然后检查是否在 root 内
                resolved_run_dir = Path(self.run_dir).resolve()
                resolved_root = root.resolve()
                if not str(resolved_run_dir).startswith(str(resolved_root)):
                    raise ValueError(
                        f"run_dir must be within artifacts root: {resolved_run_dir} not in {resolved_root}"
                    )
            except Exception as e:
                logger.error(f"[ArtifactStore] Invalid run_dir: {e}")
                raise ValueError(f"Invalid run_dir: {e}") from e

        # 确保类型为 Path
        if isinstance(self.run_dir, str):
            self.run_dir = Path(self.run_dir)

    def ensure(self) -> None:
        """确保运行目录存在"""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # 额外验证：确保目录确实在 artifacts root 内
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
        """安全写入 JSON 文件"""
        self.ensure()
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # 清理文件名，防止目录遍历
        safe_filename = _sanitize_filename(filename)
        path = self.run_dir / safe_filename

        # 额外验证：确保最终路径仍在 run_dir 内（防御性编程）
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
        """写入运行索引"""
        # 添加时间戳
        if "created_at" not in payload:
            payload["created_at"] = datetime.utcnow().isoformat()
        self._write_json("index.json", payload)

    def append_event(self, event: Dict[str, Any]) -> None:
        """Append SSE event envelope as jsonl for replay."""
        self.ensure()
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # 使用硬编码的文件名，不需要清理
        path = self.run_dir / "events.sse.jsonl"

        # 验证路径安全性
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
        """安全读取 JSON 文件，失败返回 None"""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        # 清理文件名，防止目录遍历
        safe_filename = _sanitize_filename(filename)
        path = self.run_dir / safe_filename

        # 验证路径安全性
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
        """读取需求分析结果"""
        return self._read_json("analysis.json")

    def read_blueprint(self) -> Optional[Dict[str, Any]]:
        """读取工作流蓝图"""
        return self._read_json("blueprint.json")

    def read_validation(self) -> Optional[Dict[str, Any]]:
        """读取验证报告"""
        return self._read_json("validation.json")

    def read_actions(self) -> Optional[List[Dict[str, Any]]]:
        """读取 actions 列表"""
        data = self._read_json("actions.json")
        if isinstance(data, list):
            return data
        return None

    def read_index(self) -> Optional[Dict[str, Any]]:
        """读取运行索引"""
        return self._read_json("index.json")

    def file_exists(self, filename: str) -> bool:
        """检查文件是否存在"""
        if self.run_dir is None:
            raise ValueError("run_dir must be set")
        try:
            safe_filename = _sanitize_filename(filename)
            path = self.run_dir / safe_filename

            # 验证路径安全性
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
    """创建新的 ArtifactStore 实例"""
    # graph_id 会在 __post_init__ 中被清理
    store = ArtifactStore(graph_id=graph_id)
    try:
        store.ensure()
    except Exception as e:
        logger.error(f"[ArtifactStore] Failed to create run dir: {e}")
        raise
    return store
