# Skill Versioning, Permissions & Token API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic versioning, team collaboration permissions, and PlatformToken auth to the Skill system.

**Architecture:** 4 new DB tables (skill_versions, skill_version_files, skill_collaborators, platform_tokens) with zero changes to existing tables. New repos/services/routes follow existing layered pattern (Repository → Service → API). A unified `check_skill_access()` replaces hardcoded `owner_id` checks. Dual-mode auth dependency supports session + `sk_` PlatformToken.

**Tech Stack:** FastAPI, SQLAlchemy async (PostgreSQL), Alembic, Pydantic v2, `semver` PyPI package, `secrets` stdlib.

**Spec:** `docs/superpowers/specs/2026-03-20-skill-versioning-permissions-api-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/models/skill_version.py` | SkillVersion + SkillVersionFile ORM models |
| `backend/app/models/skill_collaborator.py` | CollaboratorRole enum + SkillCollaborator ORM model |
| `backend/app/models/platform_token.py` | PlatformToken ORM model |
| `backend/app/schemas/skill_version.py` | Pydantic schemas for version CRUD |
| `backend/app/schemas/skill_collaborator.py` | Pydantic schemas for collaborator CRUD |
| `backend/app/schemas/platform_token.py` | Pydantic schemas for token CRUD |
| `backend/app/repositories/skill_version.py` | SkillVersion + SkillVersionFile repository |
| `backend/app/repositories/skill_collaborator.py` | SkillCollaborator repository |
| `backend/app/repositories/platform_token.py` | PlatformToken repository |
| `backend/app/services/skill_version_service.py` | Version publish/list/restore logic |
| `backend/app/services/skill_collaborator_service.py` | Collaborator CRUD + transfer |
| `backend/app/services/platform_token_service.py` | Token create/list/revoke |
| `backend/app/common/skill_permissions.py` | `check_skill_access()` unified permission check |
| `backend/app/common/auth_dependency.py` | `get_current_user_or_token()` dual-mode auth |
| `backend/app/api/v1/skill_versions.py` | Version API routes |
| `backend/app/api/v1/skill_collaborators.py` | Collaborator API routes |
| `backend/app/api/v1/tokens.py` | Token API routes |
| `backend/alembic/versions/20260321_000011_add_skill_versioning_permissions_tokens.py` | Migration |
| `backend/tests/test_api/test_skill_versions.py` | Version API tests |
| `backend/tests/test_api/test_skill_collaborators.py` | Collaborator API tests |
| `backend/tests/test_api/test_platform_tokens.py` | Token API tests |
| `backend/tests/test_services/test_skill_permissions.py` | Permission utility tests |

### Modified Files
| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Register 4 new models + CollaboratorRole enum |
| `backend/app/api/v1/__init__.py` | Register 3 new routers |
| `backend/app/repositories/skill.py` | Extend `list_by_user()` with collaborator subquery |
| `backend/app/services/skill_service.py` | Replace `owner_id` checks with `check_skill_access()` |
| `backend/app/schemas/skill.py` | Add `latest_version` field to SkillSchema |

---

### Task 1: SkillCollaborator Model + CollaboratorRole Enum

**Files:**
- Create: `backend/app/models/skill_collaborator.py`
- Test: `backend/tests/test_services/test_skill_permissions.py` (placeholder)

- [ ] **Step 1: Create the SkillCollaborator model file**

```python
# backend/app/models/skill_collaborator.py
"""Skill Collaborator model — per-skill role-based access control."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .skill import Skill


class CollaboratorRole(str, enum.Enum):
    """Roles ordered by privilege: viewer < editor < publisher < admin."""
    viewer = "viewer"
    editor = "editor"
    publisher = "publisher"
    admin = "admin"

    @classmethod
    def rank(cls, role: "CollaboratorRole") -> int:
        _order = [cls.viewer, cls.editor, cls.publisher, cls.admin]
        return _order.index(role)

    def __ge__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) >= CollaboratorRole.rank(other)

    def __gt__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) > CollaboratorRole.rank(other)

    def __le__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) <= CollaboratorRole.rank(other)

    def __lt__(self, other):
        if not isinstance(other, CollaboratorRole):
            return NotImplemented
        return CollaboratorRole.rank(self) < CollaboratorRole.rank(other)


class SkillCollaborator(BaseModel):
    """Per-skill collaborator with role."""

    __tablename__ = "skill_collaborators"

    skill_id: Mapped["uuid.UUID"] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[CollaboratorRole] = mapped_column(
        Enum(CollaboratorRole, name="collaborator_role", create_constraint=True),
        nullable=False,
    )
    invited_by: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", lazy="selectin")
    user: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped["AuthUser"] = relationship("AuthUser", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="skill_collaborators_skill_user_unique"),
        Index("skill_collaborators_user_skill_idx", "user_id", "skill_id"),
    )
```

Add the missing `import uuid` at the top (after `import enum`):
```python
import uuid
```

- [ ] **Step 2: Verify the file is syntactically correct**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.models.skill_collaborator import SkillCollaborator, CollaboratorRole; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/skill_collaborator.py
git commit -m "feat(models): add SkillCollaborator model and CollaboratorRole enum"
```

---

### Task 2: SkillVersion + SkillVersionFile Models

**Files:**
- Create: `backend/app/models/skill_version.py`

- [ ] **Step 1: Create the SkillVersion model file**

```python
# backend/app/models/skill_version.py
"""Immutable skill version snapshots."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser
    from .skill import Skill


class SkillVersion(BaseModel):
    """Published immutable version snapshot of a Skill."""

    __tablename__ = "skill_versions"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    release_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot fields
    skill_name: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    meta_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    compatibility: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    published_by_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    published_at: Mapped["datetime"] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", lazy="selectin")
    published_by: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    files: Mapped[List["SkillVersionFile"]] = relationship(
        "SkillVersionFile",
        back_populates="version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="skill_versions_skill_version_unique"),
        Index("skill_versions_skill_idx", "skill_id"),
        Index("skill_versions_published_at_idx", "published_at"),
    )


class SkillVersionFile(BaseModel):
    """File snapshot belonging to a published version."""

    __tablename__ = "skill_version_files"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="database")
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    version: Mapped["SkillVersion"] = relationship("SkillVersion", back_populates="files", lazy="selectin")

    __table_args__ = (
        Index("skill_version_files_version_idx", "version_id"),
    )
```

Add `from datetime import datetime` at top (after `import uuid`).

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.models.skill_version import SkillVersion, SkillVersionFile; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/skill_version.py
git commit -m "feat(models): add SkillVersion and SkillVersionFile models"
```

---

### Task 3: PlatformToken Model

**Files:**
- Create: `backend/app/models/platform_token.py`

- [ ] **Step 1: Create the PlatformToken model file**

```python
# backend/app/models/platform_token.py
"""Universal PlatformToken for API authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .auth import AuthUser


class PlatformToken(BaseModel):
    """API token with scoped permissions."""

    __tablename__ = "platform_tokens"

    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")

    __table_args__ = (
        Index("platform_tokens_user_idx", "user_id"),
        Index("platform_tokens_hash_idx", "token_hash"),
        Index("platform_tokens_active_idx", "is_active"),
    )
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.models.platform_token import PlatformToken; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/platform_token.py
git commit -m "feat(models): add PlatformToken model"
```

---

### Task 4: Register Models in `__init__.py`

**Files:**
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Add imports and __all__ entries**

Add these imports after `from .skill import Skill, SkillFile`:
```python
from .skill_collaborator import CollaboratorRole, SkillCollaborator
from .skill_version import SkillVersion, SkillVersionFile
from .platform_token import PlatformToken
```

Add to `__all__`:
```python
    "CollaboratorRole",
    "SkillCollaborator",
    "SkillVersion",
    "SkillVersionFile",
    "PlatformToken",
```

- [ ] **Step 2: Verify import**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.models import SkillVersion, SkillVersionFile, SkillCollaborator, CollaboratorRole, PlatformToken; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/__init__.py
git commit -m "feat(models): register new models in __init__.py"
```

---

### Task 5: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/20260321_000011_add_skill_versioning_permissions_tokens.py`

- [ ] **Step 1: Generate migration**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && alembic revision --autogenerate -m "add_skill_versioning_permissions_tokens"`

If autogenerate fails, create manually. The migration must create these 4 tables:
- `skill_collaborators` (with `collaborator_role` enum type)
- `skill_versions`
- `skill_version_files`
- `platform_tokens`

- [ ] **Step 2: Review the generated migration**

Open the generated file and verify:
1. `collaborator_role` enum is created before table
2. All columns, FKs, indexes, unique constraints match the spec
3. `downgrade()` drops tables in correct order (version_files before versions) and drops the enum

- [ ] **Step 3: Test migration runs**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && alembic upgrade head`
Expected: No errors, 4 tables created.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(migration): add skill_versions, skill_collaborators, platform_tokens tables"
```

---

### Task 6: Skill Permission Utility — `check_skill_access()`

**Files:**
- Create: `backend/app/common/skill_permissions.py`
- Test: `backend/tests/test_services/test_skill_permissions.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_services/test_skill_permissions.py
"""Tests for check_skill_access unified permission check."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.common.exceptions import ForbiddenException
from app.common.skill_permissions import check_skill_access
from app.models.skill_collaborator import CollaboratorRole


def _make_skill(owner_id="owner-1", is_public=False):
    skill = MagicMock()
    skill.id = uuid.uuid4()
    skill.owner_id = owner_id
    skill.is_public = is_public
    return skill


def _make_user(user_id="user-1", is_superuser=False):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    return user


@pytest.mark.asyncio
async def test_superuser_always_passes():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    await check_skill_access(db, skill, "super-1", CollaboratorRole.admin, is_superuser=True)
    # Should not raise


@pytest.mark.asyncio
async def test_owner_always_passes():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    await check_skill_access(db, skill, "owner-1", CollaboratorRole.admin)
    # Should not raise


@pytest.mark.asyncio
async def test_collaborator_with_sufficient_role():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    mock_collab = MagicMock()
    mock_collab.role = CollaboratorRole.editor
    with patch("app.common.skill_permissions._get_collaborator", return_value=mock_collab):
        await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_collaborator_with_insufficient_role():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    mock_collab = MagicMock()
    mock_collab.role = CollaboratorRole.viewer
    with patch("app.common.skill_permissions._get_collaborator", return_value=mock_collab):
        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_public_skill_viewer_access():
    skill = _make_skill(owner_id="other", is_public=True)
    db = AsyncMock()
    with patch("app.common.skill_permissions._get_collaborator", return_value=None):
        await check_skill_access(db, skill, "user-1", CollaboratorRole.viewer)


@pytest.mark.asyncio
async def test_public_skill_editor_access_denied():
    skill = _make_skill(owner_id="other", is_public=True)
    db = AsyncMock()
    with patch("app.common.skill_permissions._get_collaborator", return_value=None):
        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_token_scope_check_passes():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    await check_skill_access(
        db, skill, "owner-1", CollaboratorRole.viewer,
        token_scopes=["skills:read"], required_scope="skills:read",
    )


@pytest.mark.asyncio
async def test_token_scope_check_fails():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    with pytest.raises(ForbiddenException):
        await check_skill_access(
            db, skill, "owner-1", CollaboratorRole.viewer,
            token_scopes=["skills:read"], required_scope="skills:write",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_services/test_skill_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.common.skill_permissions'`

- [ ] **Step 3: Implement `check_skill_access()`**

```python
# backend/app/common/skill_permissions.py
"""Unified skill permission check — replaces hardcoded owner_id comparisons."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException
from app.models.skill import Skill
from app.models.skill_collaborator import CollaboratorRole, SkillCollaborator


async def _get_collaborator(
    db: AsyncSession,
    skill_id,
    user_id: str,
) -> Optional[SkillCollaborator]:
    result = await db.execute(
        select(SkillCollaborator).where(
            and_(
                SkillCollaborator.skill_id == skill_id,
                SkillCollaborator.user_id == user_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def check_skill_access(
    db: AsyncSession,
    skill: Skill,
    user_id: str,
    min_role: CollaboratorRole,
    *,
    is_superuser: bool = False,
    token_scopes: Optional[List[str]] = None,
    required_scope: Optional[str] = None,
) -> None:
    """
    Unified permission check.

    Raises ForbiddenException if the user lacks sufficient access.
    """
    # 1. Superuser bypass
    if is_superuser:
        _check_token_scope(token_scopes, required_scope)
        return

    # 2. Owner always passes
    if skill.owner_id and skill.owner_id == user_id:
        _check_token_scope(token_scopes, required_scope)
        return

    # 3. Check collaborator role
    collab = await _get_collaborator(db, skill.id, user_id)
    if collab and collab.role >= min_role:
        _check_token_scope(token_scopes, required_scope)
        return

    # 4. Public skill + viewer access
    if skill.is_public and min_role == CollaboratorRole.viewer:
        _check_token_scope(token_scopes, required_scope)
        return

    raise ForbiddenException("You don't have permission to access this skill")


def _check_token_scope(
    token_scopes: Optional[List[str]],
    required_scope: Optional[str],
) -> None:
    """If request came via PlatformToken, verify scope."""
    if token_scopes is not None and required_scope is not None:
        if required_scope not in token_scopes:
            raise ForbiddenException(f"Token missing required scope: {required_scope}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_services/test_skill_permissions.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/common/skill_permissions.py backend/tests/test_services/test_skill_permissions.py
git commit -m "feat(permissions): add check_skill_access() unified permission utility"
```

---

### Task 7: Dual-Mode Auth Dependency — `get_current_user_or_token()`

**Files:**
- Create: `backend/app/common/auth_dependency.py`

- [ ] **Step 1: Implement the dual-mode auth dependency**

```python
# backend/app/common/auth_dependency.py
"""Dual-mode authentication: session/JWT + PlatformToken (sk_ prefix)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import UnauthorizedException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.platform_token import PlatformToken

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Debounce interval for last_used_at updates (5 minutes)
_LAST_USED_DEBOUNCE_SECONDS = 300


@dataclass
class AuthContext:
    """Result of authentication — carries user + optional token scopes."""
    user: User
    token_scopes: Optional[List[str]] = None

    @property
    def is_token_auth(self) -> bool:
        return self.token_scopes is not None


async def get_current_user_or_token(
    token: Optional[str] = Depends(oauth2_scheme),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """
    Authenticate via session/JWT or PlatformToken.

    If Bearer token starts with 'sk_', route to PlatformToken path.
    Otherwise, fall through to existing session/JWT auth.
    """
    # Try to extract token from cookie if not in header
    raw_token = token
    if not raw_token and request:
        from app.core.settings import settings
        raw_token = (
            request.cookies.get(settings.cookie_name)
            or request.cookies.get("session-token")
            or request.cookies.get("session_token")
            or request.cookies.get("access_token")
            or request.cookies.get("Authorization")
            or request.cookies.get("auth_token")
        )

    # PlatformToken path
    if raw_token and raw_token.startswith("sk_"):
        return await _authenticate_platform_token(raw_token, db)

    # Fall through to existing session/JWT auth
    user = await get_current_user(token=token, request=request, db=db)
    return AuthContext(user=user, token_scopes=None)


async def _authenticate_platform_token(
    raw_token: str,
    db: AsyncSession,
) -> AuthContext:
    """Verify a PlatformToken and return AuthContext with scopes."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    result = await db.execute(
        select(PlatformToken).where(PlatformToken.token_hash == token_hash)
    )
    pt = result.scalar_one_or_none()

    if not pt:
        raise UnauthorizedException("Invalid API token")

    if not pt.is_active:
        raise UnauthorizedException("API token has been revoked")

    if pt.expires_at and pt.expires_at < datetime.now(timezone.utc):
        raise UnauthorizedException("API token has expired")

    # Debounce last_used_at update
    now = datetime.now(timezone.utc)
    if not pt.last_used_at or (now - pt.last_used_at).total_seconds() > _LAST_USED_DEBOUNCE_SECONDS:
        pt.last_used_at = now
        await db.commit()

    # Load the user
    user_result = await db.execute(select(User).where(User.id == pt.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedException("Token owner account is inactive")

    return AuthContext(user=user, token_scopes=list(pt.scopes))
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.common.auth_dependency import get_current_user_or_token, AuthContext; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/common/auth_dependency.py
git commit -m "feat(auth): add get_current_user_or_token() dual-mode auth dependency"
```

---

### Task 8: Repositories — SkillCollaborator

**Files:**
- Create: `backend/app/repositories/skill_collaborator.py`

- [ ] **Step 1: Create SkillCollaborator repository**

```python
# backend/app/repositories/skill_collaborator.py
"""Skill Collaborator Repository."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_collaborator import CollaboratorRole, SkillCollaborator

from .base import BaseRepository


class SkillCollaboratorRepository(BaseRepository[SkillCollaborator]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillCollaborator, db)

    async def get_by_skill_and_user(
        self, skill_id: uuid.UUID, user_id: str
    ) -> Optional[SkillCollaborator]:
        result = await self.db.execute(
            select(SkillCollaborator).where(
                and_(
                    SkillCollaborator.skill_id == skill_id,
                    SkillCollaborator.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillCollaborator]:
        result = await self.db.execute(
            select(SkillCollaborator).where(SkillCollaborator.skill_id == skill_id)
        )
        return list(result.scalars().all())

    async def list_skill_ids_for_user(self, user_id: str) -> List[uuid.UUID]:
        """Return skill IDs where user is a collaborator (used by list_by_user)."""
        result = await self.db.execute(
            select(SkillCollaborator.skill_id).where(
                SkillCollaborator.user_id == user_id
            )
        )
        return [row[0] for row in result.all()]

    async def delete_by_skill_and_user(
        self, skill_id: uuid.UUID, user_id: str
    ) -> bool:
        collab = await self.get_by_skill_and_user(skill_id, user_id)
        if not collab:
            return False
        await self.db.delete(collab)
        await self.db.flush()
        return True
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.repositories.skill_collaborator import SkillCollaboratorRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/repositories/skill_collaborator.py
git commit -m "feat(repos): add SkillCollaboratorRepository"
```

---

### Task 9: Repositories — SkillVersion + SkillVersionFile

**Files:**
- Create: `backend/app/repositories/skill_version.py`

- [ ] **Step 1: Create SkillVersion repository**

```python
# backend/app/repositories/skill_version.py
"""Skill Version Repository."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.skill_version import SkillVersion, SkillVersionFile

from .base import BaseRepository


class SkillVersionRepository(BaseRepository[SkillVersion]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillVersion, db)

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .options(selectinload(SkillVersion.files))
            .order_by(SkillVersion.published_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest(self, skill_id: uuid.UUID) -> Optional[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .options(selectinload(SkillVersion.files))
            .order_by(SkillVersion.published_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_version(
        self, skill_id: uuid.UUID, version: str
    ) -> Optional[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(
                and_(
                    SkillVersion.skill_id == skill_id,
                    SkillVersion.version == version,
                )
            )
            .options(selectinload(SkillVersion.files))
        )
        return result.scalar_one_or_none()

    async def get_highest_version_str(self, skill_id: uuid.UUID) -> Optional[str]:
        """Return the highest semver version string for a skill."""
        versions = await self.list_by_skill(skill_id)
        if not versions:
            return None
        import semver
        parsed = [(v, semver.Version.parse(v.version)) for v in versions]
        parsed.sort(key=lambda x: x[1], reverse=True)
        return parsed[0][0].version


class SkillVersionFileRepository(BaseRepository[SkillVersionFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillVersionFile, db)

    async def list_by_version(self, version_id: uuid.UUID) -> List[SkillVersionFile]:
        result = await self.db.execute(
            select(SkillVersionFile).where(
                SkillVersionFile.version_id == version_id
            )
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.repositories.skill_version import SkillVersionRepository, SkillVersionFileRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/repositories/skill_version.py
git commit -m "feat(repos): add SkillVersionRepository and SkillVersionFileRepository"
```

---

### Task 10: Repository — PlatformToken

**Files:**
- Create: `backend/app/repositories/platform_token.py`

- [ ] **Step 1: Create PlatformToken repository**

```python
# backend/app/repositories/platform_token.py
"""PlatformToken Repository."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_token import PlatformToken

from .base import BaseRepository


class PlatformTokenRepository(BaseRepository[PlatformToken]):
    def __init__(self, db: AsyncSession):
        super().__init__(PlatformToken, db)

    async def get_by_hash(self, token_hash: str) -> Optional[PlatformToken]:
        result = await self.db.execute(
            select(PlatformToken).where(PlatformToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> List[PlatformToken]:
        result = await self.db.execute(
            select(PlatformToken)
            .where(PlatformToken.user_id == user_id)
            .order_by(PlatformToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_active_by_user(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(PlatformToken).where(
                and_(
                    PlatformToken.user_id == user_id,
                    PlatformToken.is_active.is_(True),
                )
            )
        )
        return result.scalar() or 0
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.repositories.platform_token import PlatformTokenRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/repositories/platform_token.py
git commit -m "feat(repos): add PlatformTokenRepository"
```

---

### Task 11: Extend `SkillRepository.list_by_user()` for Collaborator Access

**Files:**
- Modify: `backend/app/repositories/skill.py:23-66`

- [ ] **Step 1: Add collaborator subquery to list_by_user**

In `backend/app/repositories/skill.py`, add import at top:
```python
from app.models.skill_collaborator import SkillCollaborator
```

Modify the `list_by_user` method — in the `if user_id:` block where `include_public` is True, change:
```python
# OLD
conditions.append(
    or_(
        Skill.owner_id == user_id,
        Skill.is_public.is_(True),
        Skill.owner_id.is_(None),
    )
)
```
to:
```python
# NEW — include skills where user is a collaborator
collab_subquery = select(SkillCollaborator.skill_id).where(
    SkillCollaborator.user_id == user_id
).scalar_subquery()
conditions.append(
    or_(
        Skill.owner_id == user_id,
        Skill.id.in_(collab_subquery),
        Skill.is_public.is_(True),
        Skill.owner_id.is_(None),
    )
)
```

And the `include_public=False` branch:
```python
# OLD
conditions.append(Skill.owner_id == user_id)
```
to:
```python
# NEW
collab_subquery = select(SkillCollaborator.skill_id).where(
    SkillCollaborator.user_id == user_id
).scalar_subquery()
conditions.append(
    or_(
        Skill.owner_id == user_id,
        Skill.id.in_(collab_subquery),
    )
)
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.repositories.skill import SkillRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/repositories/skill.py
git commit -m "feat(repos): extend list_by_user to include collaborator skills"
```

---

### Task 12: Pydantic Schemas — SkillCollaborator

**Files:**
- Create: `backend/app/schemas/skill_collaborator.py`

- [ ] **Step 1: Create schemas**

```python
# backend/app/schemas/skill_collaborator.py
"""Pydantic schemas for Skill Collaborator API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.skill_collaborator import CollaboratorRole


class CollaboratorCreate(BaseModel):
    user_id: str = Field(..., description="User ID to add as collaborator")
    role: CollaboratorRole = Field(..., description="Role to assign")


class CollaboratorUpdate(BaseModel):
    role: CollaboratorRole = Field(..., description="New role")


class CollaboratorSchema(BaseModel):
    id: str
    skill_id: str
    user_id: str
    role: CollaboratorRole
    invited_by: str
    created_at: Optional[str] = None

    @field_validator("id", "skill_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True


class TransferOwnershipRequest(BaseModel):
    new_owner_id: str = Field(..., description="User ID of new owner")
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.schemas.skill_collaborator import CollaboratorCreate, CollaboratorSchema, TransferOwnershipRequest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/skill_collaborator.py
git commit -m "feat(schemas): add skill collaborator Pydantic schemas"
```

---

### Task 13: Pydantic Schemas — SkillVersion

**Files:**
- Create: `backend/app/schemas/skill_version.py`

- [ ] **Step 1: Create schemas**

```python
# backend/app/schemas/skill_version.py
"""Pydantic schemas for Skill Version API."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class VersionPublishRequest(BaseModel):
    version: str = Field(..., description="Semver MAJOR.MINOR.PATCH", max_length=20)
    release_notes: Optional[str] = Field(None, description="Changelog / release notes")


class VersionRestoreRequest(BaseModel):
    version: str = Field(..., description="Version to restore draft from")


class VersionFileSchema(BaseModel):
    id: str
    version_id: str
    path: str
    file_name: str
    file_type: str
    content: Optional[str] = None
    storage_type: str = "database"
    storage_key: Optional[str] = None
    size: int = 0

    @field_validator("id", "version_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class VersionSchema(BaseModel):
    id: str
    skill_id: str
    version: str
    release_notes: Optional[str] = None
    skill_name: str
    skill_description: str
    content: str
    tags: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, validation_alias="meta_data")
    allowed_tools: List[str] = Field(default_factory=list)
    compatibility: Optional[str] = None
    license: Optional[str] = None
    published_by_id: str
    published_at: Optional[str] = None
    created_at: Optional[str] = None
    files: Optional[List[VersionFileSchema]] = None

    @field_validator("id", "skill_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("published_at", "created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
        populate_by_name = True


class VersionSummarySchema(BaseModel):
    """Lightweight version info for embedding in SkillSchema."""
    version: str
    release_notes: Optional[str] = None
    published_at: Optional[str] = None

    @field_validator("published_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.schemas.skill_version import VersionPublishRequest, VersionSchema, VersionSummarySchema; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/skill_version.py
git commit -m "feat(schemas): add skill version Pydantic schemas"
```

---

### Task 14: Pydantic Schemas — PlatformToken

**Files:**
- Create: `backend/app/schemas/platform_token.py`

- [ ] **Step 1: Create schemas**

```python
# backend/app/schemas/platform_token.py
"""Pydantic schemas for PlatformToken API."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class TokenCreate(BaseModel):
    name: str = Field(..., max_length=255)
    scopes: List[str] = Field(..., description="e.g. ['skills:read', 'skills:write']")
    resource_type: Optional[str] = Field(None, max_length=50)
    resource_id: Optional[str] = None
    expires_at: Optional[datetime] = None


class TokenCreateResponse(BaseModel):
    """Returned only once at creation — contains plaintext token."""
    id: str
    name: str
    token: str  # plaintext, shown only once
    token_prefix: str
    scopes: List[str]
    expires_at: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("expires_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class TokenSchema(BaseModel):
    """List view — never contains plaintext token."""
    id: str
    name: str
    token_prefix: str
    scopes: List[str]
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("resource_id", mode="before")
    @classmethod
    def convert_resource_id(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("expires_at", "last_used_at", "created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.schemas.platform_token import TokenCreate, TokenCreateResponse, TokenSchema; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/platform_token.py
git commit -m "feat(schemas): add PlatformToken Pydantic schemas"
```

---

### Task 15: SkillCollaborator Service

**Files:**
- Create: `backend/app/services/skill_collaborator_service.py`
- Test: `backend/tests/test_api/test_skill_collaborators.py` (later in Task 21)

- [ ] **Step 1: Implement service**

```python
# backend/app/services/skill_collaborator_service.py
"""Skill Collaborator Service — add/update/remove collaborators + ownership transfer."""

from __future__ import annotations

import uuid
from typing import List

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.common.skill_permissions import check_skill_access
from app.models.skill import Skill
from app.models.skill_collaborator import CollaboratorRole, SkillCollaborator
from app.repositories.skill import SkillRepository
from app.repositories.skill_collaborator import SkillCollaboratorRepository

from .base import BaseService


class SkillCollaboratorService(BaseService[SkillCollaborator]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillCollaboratorRepository(db)
        self.skill_repo = SkillRepository(db)

    async def list_collaborators(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> List[SkillCollaborator]:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.viewer,
            is_superuser=is_superuser,
        )
        return await self.repo.list_by_skill(skill_id)

    async def add_collaborator(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        role: CollaboratorRole,
        is_superuser: bool = False,
    ) -> SkillCollaborator:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        if target_user_id == skill.owner_id:
            raise BadRequestException("Cannot add the owner as a collaborator")

        existing = await self.repo.get_by_skill_and_user(skill_id, target_user_id)
        if existing:
            raise BadRequestException("User is already a collaborator")

        collab = SkillCollaborator(
            skill_id=skill_id,
            user_id=target_user_id,
            role=role,
            invited_by=current_user_id,
        )
        self.db.add(collab)
        await self.db.commit()
        await self.db.refresh(collab)
        return collab

    async def update_collaborator_role(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        new_role: CollaboratorRole,
        is_superuser: bool = False,
    ) -> SkillCollaborator:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        collab = await self.repo.get_by_skill_and_user(skill_id, target_user_id)
        if not collab:
            raise NotFoundException("Collaborator not found")

        collab.role = new_role
        await self.db.commit()
        await self.db.refresh(collab)
        return collab

    async def remove_collaborator(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        is_superuser: bool = False,
    ) -> None:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        deleted = await self.repo.delete_by_skill_and_user(skill_id, target_user_id)
        if not deleted:
            raise NotFoundException("Collaborator not found")
        await self.db.commit()

    async def transfer_ownership(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        new_owner_id: str,
    ) -> Skill:
        """Transfer ownership. Only the current owner can do this."""
        skill = await self._get_skill_or_404(skill_id)

        if skill.owner_id != current_user_id:
            raise ForbiddenException("Only the owner can transfer ownership")

        # Check new owner doesn't have a skill with the same name
        existing = await self.skill_repo.get_by_name_and_owner(skill.name, new_owner_id)
        if existing:
            raise BadRequestException(
                f"New owner already has a skill named '{skill.name}'"
            )

        # Remove new owner from collaborators if present
        await self.repo.delete_by_skill_and_user(skill_id, new_owner_id)

        # Add old owner as admin collaborator
        old_owner_collab = SkillCollaborator(
            skill_id=skill_id,
            user_id=current_user_id,
            role=CollaboratorRole.admin,
            invited_by=current_user_id,
        )
        self.db.add(old_owner_collab)

        # Transfer
        skill.owner_id = new_owner_id
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundException("Skill not found")
        return skill
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.services.skill_collaborator_service import SkillCollaboratorService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/skill_collaborator_service.py
git commit -m "feat(services): add SkillCollaboratorService"
```

---

### Task 16: SkillVersion Service

**Files:**
- Create: `backend/app/services/skill_version_service.py`

- [ ] **Step 1: Implement service**

```python
# backend/app/services/skill_version_service.py
"""Skill Version Service — publish, list, get, delete, restore."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import semver

from app.common.exceptions import BadRequestException, NotFoundException
from app.common.skill_permissions import check_skill_access
from app.models.skill import Skill, SkillFile
from app.models.skill_collaborator import CollaboratorRole
from app.models.skill_version import SkillVersion, SkillVersionFile
from app.repositories.skill import SkillFileRepository, SkillRepository
from app.repositories.skill_version import SkillVersionFileRepository, SkillVersionRepository

from .base import BaseService


class SkillVersionService(BaseService[SkillVersion]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillVersionRepository(db)
        self.file_repo = SkillVersionFileRepository(db)
        self.skill_repo = SkillRepository(db)
        self.skill_file_repo = SkillFileRepository(db)

    async def publish_version(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        version_str: str,
        release_notes: Optional[str] = None,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> SkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.publisher,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:publish",
        )

        # Validate semver format
        try:
            new_ver = semver.Version.parse(version_str)
        except ValueError:
            raise BadRequestException(
                f"Invalid version format: '{version_str}'. Must be MAJOR.MINOR.PATCH"
            )
        # Reject pre-release / build metadata
        if new_ver.prerelease or new_ver.build:
            raise BadRequestException("Pre-release and build metadata are not supported")

        # Check > highest existing
        highest_str = await self.repo.get_highest_version_str(skill_id)
        if highest_str:
            highest = semver.Version.parse(highest_str)
            if new_ver <= highest:
                raise BadRequestException(
                    f"Version {version_str} must be greater than current highest {highest_str}"
                )

        # Snapshot
        sv = SkillVersion(
            skill_id=skill_id,
            version=version_str,
            release_notes=release_notes,
            skill_name=skill.name,
            skill_description=skill.description,
            content=skill.content,
            tags=list(skill.tags) if skill.tags else [],
            meta_data=dict(skill.meta_data) if skill.meta_data else {},
            allowed_tools=list(skill.allowed_tools) if skill.allowed_tools else [],
            compatibility=skill.compatibility,
            license=skill.license,
            published_by_id=current_user_id,
            published_at=datetime.now(timezone.utc),
        )
        self.db.add(sv)
        await self.db.flush()
        await self.db.refresh(sv)

        # Copy files
        skill_files = await self.skill_file_repo.list_by_skill(skill_id)
        for sf in skill_files:
            vf = SkillVersionFile(
                version_id=sv.id,
                path=sf.path,
                file_name=sf.file_name,
                file_type=sf.file_type,
                content=sf.content,
                storage_type=sf.storage_type,
                storage_key=sf.storage_key,
                size=sf.size,
            )
            self.db.add(vf)

        await self.db.commit()
        await self.db.refresh(sv)
        return sv

    async def list_versions(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> List[SkillVersion]:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.viewer,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:read",
        )
        return await self.repo.list_by_skill(skill_id)

    async def get_version(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> SkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.viewer,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:read",
        )
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundException(f"Version {version_str} not found")
        return sv

    async def get_latest_version(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> SkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.viewer,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:read",
        )
        sv = await self.repo.get_latest(skill_id)
        if not sv:
            raise NotFoundException("No published versions found")
        return sv

    async def delete_version(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> None:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.admin,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:admin",
        )
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundException(f"Version {version_str} not found")
        await self.db.delete(sv)
        await self.db.commit()

    async def restore_draft(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
        token_scopes: Optional[List[str]] = None,
    ) -> Skill:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db, skill, current_user_id, CollaboratorRole.publisher,
            is_superuser=is_superuser,
            token_scopes=token_scopes, required_scope="skills:write",
        )
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundException(f"Version {version_str} not found")

        # Overwrite draft
        skill.name = sv.skill_name
        skill.description = sv.skill_description
        skill.content = sv.content
        skill.tags = list(sv.tags) if sv.tags else []
        skill.meta_data = dict(sv.meta_data) if sv.meta_data else {}
        skill.allowed_tools = list(sv.allowed_tools) if sv.allowed_tools else []
        skill.compatibility = sv.compatibility
        skill.license = sv.license

        # Replace draft files
        await self.skill_file_repo.delete_by_skill(skill_id)
        version_files = await self.file_repo.list_by_version(sv.id)
        for vf in version_files:
            sf = SkillFile(
                skill_id=skill_id,
                path=vf.path,
                file_name=vf.file_name,
                file_type=vf.file_type,
                content=vf.content,
                storage_type=vf.storage_type,
                storage_key=vf.storage_key,
                size=vf.size,
            )
            self.db.add(sf)

        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundException("Skill not found")
        return skill
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.services.skill_version_service import SkillVersionService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/skill_version_service.py
git commit -m "feat(services): add SkillVersionService with publish/restore/delete"
```

---

### Task 17: PlatformToken Service

**Files:**
- Create: `backend/app/services/platform_token_service.py`

- [ ] **Step 1: Implement service**

```python
# backend/app/services/platform_token_service.py
"""PlatformToken Service — create, list, revoke."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.platform_token import PlatformToken
from app.repositories.platform_token import PlatformTokenRepository

from .base import BaseService

MAX_ACTIVE_TOKENS_PER_USER = 50
TOKEN_PREFIX = "sk_"


class PlatformTokenService(BaseService[PlatformToken]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = PlatformTokenRepository(db)

    async def create_token(
        self,
        user_id: str,
        name: str,
        scopes: List[str],
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[PlatformToken, str]:
        """Create a new token. Returns (token_record, plaintext_token)."""
        # Check limit
        active_count = await self.repo.count_active_by_user(user_id)
        if active_count >= MAX_ACTIVE_TOKENS_PER_USER:
            raise BadRequestException(
                f"Maximum of {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached"
            )

        # Generate token
        raw_secret = secrets.token_urlsafe(36)  # ~48 chars
        plaintext = f"{TOKEN_PREFIX}{raw_secret}"
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        token_prefix = plaintext[:12]

        pt = PlatformToken(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=scopes,
            resource_type=resource_type,
            resource_id=resource_id,
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(pt)
        await self.db.commit()
        await self.db.refresh(pt)
        return pt, plaintext

    async def list_tokens(self, user_id: str) -> List[PlatformToken]:
        return await self.repo.list_by_user(user_id)

    async def revoke_token(
        self,
        token_id: uuid.UUID,
        user_id: str,
    ) -> None:
        pt = await self.repo.get(token_id)
        if not pt:
            raise NotFoundException("Token not found")
        if pt.user_id != user_id:
            raise ForbiddenException("You can only revoke your own tokens")
        pt.is_active = False
        await self.db.commit()
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.services.platform_token_service import PlatformTokenService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/platform_token_service.py
git commit -m "feat(services): add PlatformTokenService with create/list/revoke"
```

---

### Task 18: Update SkillService — Replace Hardcoded Permission Checks

**Files:**
- Modify: `backend/app/services/skill_service.py`

- [ ] **Step 1: Add imports at top of skill_service.py**

Add after the existing imports:
```python
from app.common.skill_permissions import check_skill_access
from app.models.skill_collaborator import CollaboratorRole
```

- [ ] **Step 2: Replace permission checks in `get_skill()`**

Replace lines 66-68:
```python
# OLD
if skill.owner_id and skill.owner_id != current_user_id and not skill.is_public:
    raise ForbiddenException("You don't have permission to access this skill")
```
with:
```python
# NEW
if current_user_id:
    await check_skill_access(
        self.db, skill, current_user_id, CollaboratorRole.viewer,
    )
elif not skill.is_public:
    raise ForbiddenException("You don't have permission to access this skill")
```

- [ ] **Step 3: Replace permission check in `update_skill()`**

Replace lines 310-312:
```python
# OLD
if skill.owner_id != current_user_id:
    raise ForbiddenException("You can only update your own skills")
```
with:
```python
# NEW
await check_skill_access(
    self.db, skill, current_user_id, CollaboratorRole.editor,
)
```

- [ ] **Step 4: Replace permission check in `delete_skill()`**

Replace lines 473-475:
```python
# OLD
if skill.owner_id != current_user_id:
    raise ForbiddenException("You can only delete your own skills")
```
with:
```python
# NEW — only owner can delete
if skill.owner_id != current_user_id:
    raise ForbiddenException("Only the owner can delete a skill")
```

(Keep owner-only for delete — spec says owner only.)

- [ ] **Step 5: Replace permission checks in `add_file()`, `delete_file()`, `update_file()`**

In `add_file()` (around line 501-503), replace:
```python
if skill.owner_id != current_user_id:
    raise ForbiddenException("You can only add files to your own skills")
```
with:
```python
await check_skill_access(
    self.db, skill, current_user_id, CollaboratorRole.editor,
)
```

Apply the same pattern to `delete_file()` (around line 559-561) and `update_file()` (around line 583-585).

- [ ] **Step 6: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.services.skill_service import SkillService; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/skill_service.py
git commit -m "refactor(services): replace hardcoded owner_id checks with check_skill_access()"
```

---

### Task 19: Skill Versions API Routes

**Files:**
- Create: `backend/app/api/v1/skill_versions.py`

- [ ] **Step 1: Write the route file**

```python
"""Skill Version API routes."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth_dependency import AuthContext, get_current_user_or_token
from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill_version import (
    VersionPublishRequest,
    VersionRestoreRequest,
    VersionSchema,
    VersionSummarySchema,
)
from app.services.skill_version_service import SkillVersionService

router = APIRouter(prefix="/v1/skills", tags=["Skill Versions"])


@router.post("/{skill_id}/versions")
async def publish_version(
    skill_id: uuid.UUID,
    payload: VersionPublishRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    """发布新版本（快照当前 draft）。"""
    service = SkillVersionService(db)
    version = await service.publish_version(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        version_str=payload.version,
        release_notes=payload.release_notes,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(version).model_dump(),
    }


@router.get("/{skill_id}/versions")
async def list_versions(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    """列出所有已发布版本（按版本号降序）。"""
    service = SkillVersionService(db)
    versions = await service.list_versions(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": [VersionSummarySchema.model_validate(v).model_dump() for v in versions],
    }


@router.get("/{skill_id}/versions/latest")
async def get_latest_version(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    """获取最新已发布版本详情（含文件）。"""
    service = SkillVersionService(db)
    version = await service.get_latest_version(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(version).model_dump(),
    }


@router.get("/{skill_id}/versions/{version}")
async def get_version(
    skill_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    """获取特定版本详情（含文件）。"""
    service = SkillVersionService(db)
    ver = await service.get_version(
        skill_id=skill_id,
        version_str=version,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(ver).model_dump(),
    }


@router.delete("/{skill_id}/versions/{version}")
async def delete_version(
    skill_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除版本（admin+ 权限，仅 session auth）。"""
    service = SkillVersionService(db)
    await service.delete_version(
        skill_id=skill_id,
        version_str=version,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return {"success": True}


@router.post("/{skill_id}/restore")
async def restore_version(
    skill_id: uuid.UUID,
    payload: VersionRestoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于历史版本恢复 draft（仅 session auth）。"""
    service = SkillVersionService(db)
    skill = await service.restore_draft(
        skill_id=skill_id,
        version_str=payload.version,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    from app.schemas.skill import SkillSchema

    return {
        "success": True,
        "data": SkillSchema.model_validate(skill).model_dump(),
    }
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.api.v1.skill_versions import router; print(len(router.routes), 'routes')"`
Expected: `6 routes`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/skill_versions.py
git commit -m "feat(api): add skill versions API routes"
```

---

### Task 20: Skill Collaborators API Routes

**Files:**
- Create: `backend/app/api/v1/skill_collaborators.py`

- [ ] **Step 1: Write the route file**

```python
"""Skill Collaborator API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill_collaborator import (
    CollaboratorCreate,
    CollaboratorSchema,
    CollaboratorUpdate,
    TransferOwnershipRequest,
)
from app.services.skill_collaborator_service import SkillCollaboratorService

router = APIRouter(prefix="/v1/skills", tags=["Skill Collaborators"])


@router.get("/{skill_id}/collaborators")
async def list_collaborators(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出 skill 的所有协作者。"""
    service = SkillCollaboratorService(db)
    collaborators = await service.list_collaborators(
        skill_id=skill_id,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": [CollaboratorSchema.model_validate(c).model_dump() for c in collaborators],
    }


@router.post("/{skill_id}/collaborators")
async def add_collaborator(
    skill_id: uuid.UUID,
    payload: CollaboratorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加协作者（admin+ 权限）。"""
    service = SkillCollaboratorService(db)
    collaborator = await service.add_collaborator(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=payload.user_id,
        role=payload.role,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": CollaboratorSchema.model_validate(collaborator).model_dump(),
    }


@router.put("/{skill_id}/collaborators/{target_user_id}")
async def update_collaborator(
    skill_id: uuid.UUID,
    target_user_id: str,
    payload: CollaboratorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改协作者角色（admin+ 权限）。"""
    service = SkillCollaboratorService(db)
    collaborator = await service.update_collaborator_role(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=target_user_id,
        new_role=payload.role,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": CollaboratorSchema.model_validate(collaborator).model_dump(),
    }


@router.delete("/{skill_id}/collaborators/{target_user_id}")
async def remove_collaborator(
    skill_id: uuid.UUID,
    target_user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除协作者（admin+ 权限）。"""
    service = SkillCollaboratorService(db)
    await service.remove_collaborator(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=target_user_id,
        is_superuser=current_user.is_superuser,
    )
    return {"success": True}


@router.post("/{skill_id}/transfer")
async def transfer_ownership(
    skill_id: uuid.UUID,
    payload: TransferOwnershipRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """转让 ownership（仅 owner 可操作）。"""
    service = SkillCollaboratorService(db)
    await service.transfer_ownership(
        skill_id=skill_id,
        current_user_id=current_user.id,
        new_owner_id=payload.new_owner_id,
        is_superuser=current_user.is_superuser,
    )
    return {"success": True}
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.api.v1.skill_collaborators import router; print(len(router.routes), 'routes')"`
Expected: `5 routes`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/skill_collaborators.py
git commit -m "feat(api): add skill collaborators API routes"
```

---

### Task 21: Token API Routes

**Files:**
- Create: `backend/app/api/v1/tokens.py`

- [ ] **Step 1: Write the route file**

```python
"""PlatformToken API routes.

Token management is session-auth only — PlatformToken cannot manage PlatformToken.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.platform_token import (
    TokenCreate,
    TokenCreateResponse,
    TokenSchema,
)
from app.services.platform_token_service import PlatformTokenService

router = APIRouter(prefix="/v1/tokens", tags=["Tokens"])


@router.post("")
async def create_token(
    payload: TokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 token（返回明文，仅此一次）。"""
    service = PlatformTokenService(db)
    token_record, raw_token = await service.create_token(
        user_id=current_user.id,
        name=payload.name,
        scopes=payload.scopes,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        expires_at=payload.expires_at,
    )
    resp = TokenCreateResponse.model_validate(token_record)
    # Inject the raw token (not stored in DB)
    data = resp.model_dump()
    data["token"] = raw_token
    return {"success": True, "data": data}


@router.get("")
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出我的 tokens（不含明文，显示 prefix）。"""
    service = PlatformTokenService(db)
    tokens = await service.list_tokens(user_id=current_user.id)
    return {
        "success": True,
        "data": [TokenSchema.model_validate(t).model_dump() for t in tokens],
    }


@router.delete("/{token_id}")
async def revoke_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销 token（soft delete: is_active = False）。"""
    service = PlatformTokenService(db)
    await service.revoke_token(token_id=token_id, user_id=current_user.id)
    return {"success": True}
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.api.v1.tokens import router; print(len(router.routes), 'routes')"`
Expected: `3 routes`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/tokens.py
git commit -m "feat(api): add platform token API routes"
```

---

### Task 22: Register New Routers

**Files:**
- Modify: `backend/app/api/v1/__init__.py`

- [ ] **Step 1: Add imports**

After `from .skills import router as skills_router` (line 31), add:

```python
from .skill_collaborators import router as skill_collaborators_router
from .skill_versions import router as skill_versions_router
from .tokens import router as tokens_router
```

- [ ] **Step 2: Add to ROUTERS list**

After `skills_router,` (line 58), add:

```python
    skill_versions_router,
    skill_collaborators_router,
    tokens_router,
```

- [ ] **Step 3: Verify import**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.api.v1 import api_router; print(len(api_router.routes), 'total routes')"`
Expected: prints route count (should be previous count + 14 new routes)

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/__init__.py
git commit -m "feat(api): register skill versions, collaborators, and token routers"
```

---

### Task 23: Update SkillSchema — Add `latest_version` Field

**Files:**
- Modify: `backend/app/schemas/skill.py:65-133`

- [ ] **Step 1: Add `latest_version` to SkillSchema**

In `SkillSchema` class (line 65), add a new optional field after `files`:

```python
    files: Optional[List[SkillFileSchema]] = None
    latest_version: Optional[str] = None
```

- [ ] **Step 2: Update `map_meta_data_from_attributes` validator**

In the `model_validator` method (line 103-129), update the loop that gets extra attributes (line 120) to include `latest_version`:

Replace:
```python
            for key in ["id", "created_at", "updated_at", "files"]:
```
with:
```python
            for key in ["id", "created_at", "updated_at", "files", "latest_version"]:
```

- [ ] **Step 3: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.schemas.skill import SkillSchema; print(SkillSchema.model_fields.keys())"`
Expected: includes `latest_version`

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/skill.py
git commit -m "feat(schemas): add latest_version field to SkillSchema"
```

---

### Task 24: Populate `latest_version` in SkillService

**Files:**
- Modify: `backend/app/services/skill_service.py`

Note: Task 11 already handles the `list_by_user()` collaborator subquery. This task adds `latest_version` population.

- [ ] **Step 1: Add helper to populate latest_version**

In `SkillService`, add a helper method:

```python
from app.repositories.skill_version import SkillVersionRepository

async def _attach_latest_version(self, skill):
    """Attach latest_version string to skill for API response."""
    ver_repo = SkillVersionRepository(self.db)
    latest = await ver_repo.get_latest(skill.id)
    skill.latest_version = latest.version if latest else None
    return skill
```

- [ ] **Step 2: Call helper in `get_skill()`**

At the end of `get_skill()`, before returning the skill, call:
```python
skill = await self._attach_latest_version(skill)
```

- [ ] **Step 3: Verify syntax**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -c "from app.services.skill_service import SkillService; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/skill_service.py
git commit -m "feat(services): populate latest_version on skill responses"
```

---

### Task 25: Unit Tests — Skill Permissions Utility

**Files:**
- Create: `backend/tests/test_services/__init__.py`
- Create: `backend/tests/test_services/test_skill_permissions.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# (empty)
```

- [ ] **Step 2: Write tests for `check_skill_access`**

```python
"""Unit tests for check_skill_access permission utility."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.skill_permissions import check_skill_access
from app.models.skill_collaborator import CollaboratorRole


def _mock_skill(owner_id: str = "owner-1", is_public: bool = False):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.owner_id = owner_id
    s.is_public = is_public
    return s


def _mock_db(collaborator_role=None):
    """Return an AsyncMock db session.

    If collaborator_role is given, simulate a SkillCollaborator record.
    """
    db = AsyncMock()
    result_mock = MagicMock()
    if collaborator_role is not None:
        collab = MagicMock()
        collab.role = collaborator_role
        result_mock.scalar_one_or_none.return_value = collab
    else:
        result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock
    return db


class TestCheckSkillAccess:
    """Verify the unified permission checking logic."""

    @pytest.mark.asyncio
    async def test_owner_always_passes(self):
        skill = _mock_skill(owner_id="user-1")
        db = _mock_db()
        # Owner should pass even with admin requirement
        await check_skill_access(db, skill, "user-1", CollaboratorRole.admin)

    @pytest.mark.asyncio
    async def test_superuser_always_passes(self):
        skill = _mock_skill(owner_id="other")
        db = _mock_db()
        # Superuser bypasses all role checks via is_superuser param
        await check_skill_access(
            db, skill, "superadmin", CollaboratorRole.admin,
            is_superuser=True,
        )

    @pytest.mark.asyncio
    async def test_collaborator_with_sufficient_role(self):
        skill = _mock_skill(owner_id="other")
        db = _mock_db(collaborator_role=CollaboratorRole.editor)
        await check_skill_access(db, skill, "collab-1", CollaboratorRole.editor)

    @pytest.mark.asyncio
    async def test_collaborator_with_insufficient_role(self):
        skill = _mock_skill(owner_id="other")
        db = _mock_db(collaborator_role=CollaboratorRole.viewer)
        from app.common.exceptions import ForbiddenException

        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "collab-1", CollaboratorRole.editor)

    @pytest.mark.asyncio
    async def test_public_skill_viewer_access(self):
        skill = _mock_skill(owner_id="other", is_public=True)
        db = _mock_db()
        await check_skill_access(db, skill, "random-user", CollaboratorRole.viewer)

    @pytest.mark.asyncio
    async def test_public_skill_edit_denied(self):
        skill = _mock_skill(owner_id="other", is_public=True)
        db = _mock_db()
        from app.common.exceptions import ForbiddenException

        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "random-user", CollaboratorRole.editor)

    @pytest.mark.asyncio
    async def test_no_access_denied(self):
        skill = _mock_skill(owner_id="other", is_public=False)
        db = _mock_db()
        from app.common.exceptions import ForbiddenException

        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "stranger", CollaboratorRole.viewer)
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_services/test_skill_permissions.py -v`
Expected: All 7 tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_services/
git commit -m "test: add unit tests for check_skill_access permission utility"
```

---

### Task 26: Unit Tests — Skill Version Service

**Files:**
- Create: `backend/tests/test_services/test_skill_version_service.py`

- [ ] **Step 1: Write tests**

```python
"""Unit tests for SkillVersionService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_skill(owner_id="user-1", name="test-skill", content="body"):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.owner_id = owner_id
    s.name = name
    s.description = "desc"
    s.content = content
    s.tags = ["a"]
    s.meta_data = {}
    s.allowed_tools = []
    s.compatibility = None
    s.license = None
    s.is_public = False
    s.files = []
    return s


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestSkillVersionServicePublish:
    """Test version publishing logic."""

    @pytest.mark.asyncio
    async def test_publish_validates_semver_format(self):
        """Invalid semver should raise BadRequestException."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        skill = _mock_skill()
        with patch("app.services.skill_version_service.SkillRepository") as MockSkillRepo, \
             patch("app.services.skill_version_service.SkillVersionRepository") as MockVerRepo, \
             patch("app.services.skill_version_service.check_skill_access", new_callable=AsyncMock):
            MockSkillRepo.return_value.get.return_value = skill
            from app.services.skill_version_service import SkillVersionService

            service = SkillVersionService(db)
            with pytest.raises(BadRequestException, match="semver"):
                await service.publish_version(
                    skill_id=skill.id, user_id="user-1",
                    version="invalid", release_notes="",
                )

    @pytest.mark.asyncio
    async def test_publish_rejects_lower_version(self):
        """New version must be greater than existing highest."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        skill = _mock_skill()
        existing_version = MagicMock()
        existing_version.version = "2.0.0"

        with patch("app.services.skill_version_service.SkillRepository") as MockSkillRepo, \
             patch("app.services.skill_version_service.SkillVersionRepository") as MockVerRepo, \
             patch("app.services.skill_version_service.check_skill_access", new_callable=AsyncMock):
            MockSkillRepo.return_value.get.return_value = skill
            MockVerRepo.return_value.get_latest_version.return_value = existing_version
            from app.services.skill_version_service import SkillVersionService

            service = SkillVersionService(db)
            with pytest.raises(BadRequestException, match="greater"):
                await service.publish_version(
                    skill_id=skill.id, user_id="user-1",
                    version="1.0.0", release_notes="",
                )
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_services/test_skill_version_service.py -v`
Expected: All 2 tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_services/test_skill_version_service.py
git commit -m "test: add unit tests for SkillVersionService publish logic"
```

---

### Task 27: Unit Tests — Platform Token Service

**Files:**
- Create: `backend/tests/test_services/test_platform_token_service.py`

- [ ] **Step 1: Write tests**

```python
"""Unit tests for PlatformTokenService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestPlatformTokenServiceCreate:
    """Test token creation logic."""

    @pytest.mark.asyncio
    async def test_create_returns_raw_token_starting_with_sk(self):
        """Created token should start with 'sk_' prefix."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user.return_value = 0
            MockRepo.return_value.create.return_value = MagicMock(
                id=uuid.uuid4(),
                token_prefix="sk_testprefix",
            )
            db.refresh = AsyncMock()
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            record, raw_token = await service.create_token(
                user_id="user-1",
                name="test",
                scopes=["skills:read"],
            )
            assert raw_token.startswith("sk_")
            assert len(raw_token) > 12

    @pytest.mark.asyncio
    async def test_create_rejects_when_limit_exceeded(self):
        """Should raise BadRequestException when user has 50 active tokens."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user.return_value = 50
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="50"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["skills:read"],
                )


class TestPlatformTokenServiceRevoke:
    """Test token revocation logic."""

    @pytest.mark.asyncio
    async def test_revoke_sets_inactive(self):
        """Revoke should set is_active to False."""
        db = _mock_db()
        token = MagicMock()
        token.id = uuid.uuid4()
        token.user_id = "user-1"
        token.is_active = True
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.get.return_value = token
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            await service.revoke_token(token_id=token.id, user_id="user-1")
            assert token.is_active is False

    @pytest.mark.asyncio
    async def test_revoke_wrong_user_denied(self):
        """Should raise ForbiddenException when revoking another user's token."""
        from app.common.exceptions import ForbiddenException

        db = _mock_db()
        token = MagicMock()
        token.id = uuid.uuid4()
        token.user_id = "user-1"
        token.is_active = True
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.get.return_value = token
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(ForbiddenException):
                await service.revoke_token(token_id=token.id, user_id="user-2")
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter/backend && python -m pytest tests/test_services/test_platform_token_service.py -v`
Expected: All 4 tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_services/test_platform_token_service.py
git commit -m "test: add unit tests for PlatformTokenService"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | CollaboratorRole enum + SkillCollaborator model | `models/skill_collaborator.py` |
| 2 | SkillVersion + SkillVersionFile models | `models/skill_version.py` |
| 3 | PlatformToken model | `models/platform_token.py` |
| 4 | Register models in `__init__` | `models/__init__.py` |
| 5 | Alembic migration | `alembic/versions/...` |
| 6 | Skill permissions utility | `common/skill_permissions.py` |
| 7 | Dual-mode auth dependency | `common/auth_dependency.py` |
| 8 | SkillCollaborator repository | `repositories/skill_collaborator.py` |
| 9 | SkillVersion + SkillVersionFile repository | `repositories/skill_version.py` |
| 10 | PlatformToken repository | `repositories/platform_token.py` |
| 11 | Extend `list_by_user()` with collaborator subquery | `repositories/skill.py` |
| 12 | SkillCollaborator schemas | `schemas/skill_collaborator.py` |
| 13 | SkillVersion schemas | `schemas/skill_version.py` |
| 14 | PlatformToken schemas | `schemas/platform_token.py` |
| 15 | SkillCollaboratorService | `services/skill_collaborator_service.py` |
| 16 | SkillVersionService | `services/skill_version_service.py` |
| 17 | PlatformTokenService | `services/platform_token_service.py` |
| 18 | Update SkillService permission checks | `services/skill_service.py` |
| 19 | Skill Versions API routes | `api/v1/skill_versions.py` |
| 20 | Skill Collaborators API routes | `api/v1/skill_collaborators.py` |
| 21 | Token API routes | `api/v1/tokens.py` |
| 22 | Register new routers | `api/v1/__init__.py` |
| 23 | SkillSchema `latest_version` field | `schemas/skill.py` |
| 24 | Populate `latest_version` in SkillService | `services/skill_service.py` |
| 25 | Tests — skill permissions | `tests/test_services/test_skill_permissions.py` |
| 26 | Tests — version service | `tests/test_services/test_skill_version_service.py` |
| 27 | Tests — token service | `tests/test_services/test_platform_token_service.py` |
