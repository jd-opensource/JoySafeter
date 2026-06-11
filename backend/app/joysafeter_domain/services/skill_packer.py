"""
SkillPacker — resolves skill references to tar.gz archives at session start time.

Supports two formats:
1. SkillRef (new): {"type": "custom", "skill_id": "uuid", "version": "latest"}
2. PackedItem (legacy): {"name": "xxx", "tar_gz_b64": "base64..."}
"""

import base64
import io
import logging
import os
import tarfile
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_orchestrator.runtime.adapter import SkillArchive
from app.joysafeter_domain.models.skill import Skill, SkillFile


class SkillPacker:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_and_pack(self, skill_items: list[dict], target: str = "skills") -> list[SkillArchive]:
        """Resolve a list of skill entries (refs or packed) into SkillArchive objects."""
        archives: list[SkillArchive] = []

        for item in skill_items:
            archive = await self._resolve_item(item, target)
            if archive:
                archives.append(archive)

        return archives

    async def _resolve_item(self, item: dict, target: str) -> Optional[SkillArchive]:
        """Resolve a single skill item to a SkillArchive."""
        # Legacy format: pre-packed tar.gz
        if item.get("tar_gz_b64"):
            try:
                data = base64.b64decode(item["tar_gz_b64"])
                return SkillArchive(
                    name=item.get("name", "unknown"),
                    data=data,
                    target=target,
                )
            except Exception as e:
                logger.warning("Failed to decode packed skill %s: %s", item.get("name"), e)
                return None

        # New format: skill reference
        if item.get("skill_id"):
            return await self._pack_custom(
                skill_id=item["skill_id"],
                version=item.get("version", "latest"),
                target=target,
            )

        logger.warning("Skill item has neither tar_gz_b64 nor skill_id: %s", item)
        return None

    async def _pack_custom(self, skill_id: str, version: str, target: str) -> Optional[SkillArchive]:
        """Resolve a custom skill by ID, fetch files from DB, and pack into tar.gz."""
        sid = skill_id.removeprefix("skill_")
        try:
            uid = uuid.UUID(sid)
        except ValueError:
            logger.warning("Invalid skill_id format: %s", skill_id)
            return None

        if version and version != "latest":
            return await self._pack_version(uid, version, target)

        # latest: use skill_files (working copy)
        result = await self.db.execute(
            select(Skill)
            .where(Skill.id == uid)
            .options(selectinload(Skill.files))
        )
        skill = result.scalar_one_or_none()
        if not skill:
            logger.warning("Skill not found: %s", skill_id)
            return None

        if not skill.files:
            logger.warning("Skill %s has no files", skill.name)
            return None

        tar_data = self._create_targz(skill.files, root_dir=skill.name)
        return SkillArchive(name=skill.name, data=tar_data, target=target)

    async def _pack_version(self, skill_id: uuid.UUID, version: str, target: str) -> Optional[SkillArchive]:
        """Pack a specific published version of a skill."""
        from app.joysafeter_domain.models.skill_version import SkillVersion, SkillVersionFile

        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id, SkillVersion.version == version)
            .options(selectinload(SkillVersion.files))
        )
        sv = result.scalar_one_or_none()
        if not sv:
            logger.warning("Skill version not found: skill=%s version=%s", skill_id, version)
            return None

        if not sv.files:
            logger.warning("Skill version %s/%s has no files", skill_id, version)
            return None

        # Get skill name
        name_result = await self.db.execute(select(Skill.name).where(Skill.id == skill_id))
        name = name_result.scalar_one_or_none() or "unknown"

        tar_data = self._create_targz(sv.files, root_dir=name)
        return SkillArchive(name=name, data=tar_data, target=target)

    def _create_targz(self, files, root_dir: Optional[str] = None) -> bytes:
        """Pack a list of SkillFile/SkillVersionFile objects into a tar.gz archive."""
        safe_root = self._safe_archive_component(root_dir) if root_dir else None
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in files:
                safe_path = self._safe_archive_path(f)
                if not safe_path:
                    continue
                if safe_root:
                    safe_path = f"{safe_root}/{safe_path}"
                content = (f.content or "").encode("utf-8")
                info = tarfile.TarInfo(name=safe_path)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def _safe_archive_component(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        component = os.path.basename(value.replace("\\", "/").strip())
        component = os.path.normpath(component).replace("\\", "/").strip("/")
        if not component or component == "." or component == ".." or "/" in component:
            logger.warning("Skill packer: unsafe archive root skipped: %s", value)
            return None
        return component

    def _safe_archive_path(self, file_obj) -> Optional[str]:
        """Return a normalized relative path for a skill file inside the archive."""
        raw_path = (getattr(file_obj, "path", None) or "").replace("\\", "/")
        file_name = (getattr(file_obj, "file_name", None) or "").replace("\\", "/")

        # Historical imports stored `path` inconsistently: some rows keep the
        # complete relative file path in `path`, while newer ZIP imports store
        # the directory in `path` and the basename in `file_name`.  Build the
        # archive path defensively so Claude always receives
        # .claude/skills/<skill>/<relative-file>.
        if raw_path in ("", "."):
            candidate = file_name
        elif raw_path.endswith("/"):
            candidate = f"{raw_path}{file_name}"
        elif file_name and os.path.basename(raw_path) != file_name:
            candidate = f"{raw_path}/{file_name}"
        else:
            candidate = raw_path

        safe_path = os.path.normpath(candidate).replace("\\", "/").lstrip("/")
        if not safe_path or safe_path == "." or safe_path.endswith("/"):
            logger.warning("Skill packer: empty archive path skipped: path=%s file_name=%s", raw_path, file_name)
            return None
        if ".." in safe_path.split("/"):
            logger.warning("Skill packer: path traversal blocked: %s", candidate)
            return None
        return safe_path
