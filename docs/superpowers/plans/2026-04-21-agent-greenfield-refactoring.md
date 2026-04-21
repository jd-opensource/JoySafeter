# Agent Greenfield Refactoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the JoySafeter agent domain from legacy flat models to a clean Agent → AgentVersion → AgentRelease → AgentRun → Execution chain, with no data migration and no compatibility layer.

**Architecture:** 5 phases executed on a feature branch, each covering one domain slice (DB + API + service + frontend). All phases merge as a single deployment. Legacy tables are deleted, not adapted. Runtime infrastructure (Docker, ContainerPool, CLI providers) is preserved with interface changes only.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async / Alembic / PostgreSQL / Next.js 16 / React 19 / TypeScript / TanStack React Query v5 / Zustand / Tailwind + Radix UI

**Spec:** `docs/superpowers/specs/2026-04-21-agent-greenfield-refactoring-spec.md`

---

## Phase 1: Agent Core (agents + agent_versions)

### Task 1.1: Alembic Migration — Create `agents` and `agent_versions` Tables

**Files:**
- Create: `backend/alembic/versions/20260421_000000_create_agents_table.py`
- Create: `backend/alembic/versions/20260421_000001_create_agent_versions_table.py`
- Reference: `backend/app/models/auth.py` (user.id is VARCHAR(255))

- [ ] **Step 1: Write migration for `agents` table (without circular FK constraints)**

```python
# backend/alembic/versions/20260421_000000_create_agents_table.py
"""create agents table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260421_000000"
down_revision = "a9a8a7a6a5a4"  # latest existing migration
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("avatar", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("current_draft_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("active_release_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
    )

def downgrade():
    op.drop_table("agents")
```

- [ ] **Step 2: Write migration for `agent_versions` table**

```python
# backend/alembic/versions/20260421_000001_create_agent_versions_table.py
"""create agent_versions table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260421_000001"
down_revision = "20260421_000000"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "agent_versions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("source_kind", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("definition_kind", sa.String(20), nullable=False),
        sa.Column("definition_payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("capability_manifest", JSONB, nullable=False, server_default="{}"),
        sa.Column("changelog", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_version"),
    )
    # Now add the circular FK from agents -> agent_versions
    op.create_foreign_key(
        "fk_agents_current_draft_version",
        "agents", "agent_versions",
        ["current_draft_version_id"], ["id"],
    )

def downgrade():
    op.drop_constraint("fk_agents_current_draft_version", "agents", type_="foreignkey")
    op.drop_table("agent_versions")
```

- [ ] **Step 3: Run migration to verify**

Run: `cd backend && alembic upgrade head`
Expected: Both tables created, FK constraint added.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/20260421_000000_create_agents_table.py backend/alembic/versions/20260421_000001_create_agent_versions_table.py
git commit -m "feat(db): create agents and agent_versions tables"
```

---

### Task 1.2: SQLAlchemy Models — Agent and AgentVersion

**Files:**
- Create: `backend/app/models/agent.py` (new file, replaces agent_profile.py)
- Modify: `backend/app/models/__init__.py`
- Reference: `backend/app/models/base.py` (Base class), `backend/app/models/agent_profile.py` (old model for reference)

- [ ] **Step 1: Write Agent and AgentVersion models**

```python
# backend/app/models/agent.py
import uuid
from datetime import datetime, timezone, timezone
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_draft_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True
    )
    active_release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True  # FK added in Phase 2 when agent_releases exists
    )
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent", foreign_keys="AgentVersion.agent_id")
    current_draft_version: Mapped["AgentVersion | None"] = relationship(foreign_keys=[current_draft_version_id])
    workspace: Mapped["Workspace"] = relationship(back_populates="agents")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    definition_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    definition_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capability_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="versions", foreign_keys=[agent_id])
```

- [ ] **Step 2: Update `__init__.py` to export new models**

Add to `backend/app/models/__init__.py`:
```python
from backend.app.models.agent import Agent, AgentVersion
```

- [ ] **Step 3: Verify models load without import errors**

Run: `cd backend && python -c "from backend.app.models.agent import Agent, AgentVersion; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/agent.py backend/app/models/__init__.py
git commit -m "feat(models): add Agent and AgentVersion SQLAlchemy models"
```

---

### Task 1.3: Pydantic Schemas — Agent and AgentVersion

**Files:**
- Create: `backend/app/schemas/agent.py`
- Create: `backend/app/schemas/agent_version.py`
- Reference: `backend/app/schemas/base.py` (BaseResponse pattern)

- [ ] **Step 1: Write Agent schemas**

```python
# backend/app/schemas/agent.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    avatar: str | None = None
    definition_kind: str = Field(..., pattern="^(prompt|graph|code|hybrid)$")
    definition_payload: dict = Field(default_factory=dict)
    capability_manifest: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    avatar: str | None = None
    status: str | None = Field(None, pattern="^(draft|active|archived)$")


class AgentSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}


class AgentResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    avatar: str | None
    status: str
    current_draft_version_id: uuid.UUID | None
    active_release_id: uuid.UUID | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Write AgentVersion schemas**

```python
# backend/app/schemas/agent_version.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AgentVersionCreate(BaseModel):
    source_kind: str = Field(default="manual", pattern="^(manual|template|clone|import|generated)$")
    definition_kind: str = Field(..., pattern="^(prompt|graph|code|hybrid)$")
    definition_payload: dict = Field(default_factory=dict)
    capability_manifest: dict = Field(default_factory=dict)
    changelog: str | None = None


class AgentVersionUpdate(BaseModel):
    definition_payload: dict | None = None
    capability_manifest: dict | None = None
    changelog: str | None = None


class AgentVersionResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version_number: int
    status: str
    source_kind: str
    definition_kind: str
    definition_payload: dict
    capability_manifest: dict
    changelog: str | None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentVersionSummary(BaseModel):
    id: uuid.UUID
    version_number: int
    status: str
    definition_kind: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/agent.py backend/app/schemas/agent_version.py
git commit -m "feat(schemas): add Agent and AgentVersion Pydantic schemas"
```

---

### Task 1.4: Service Layer — AgentService and AgentVersionService

**Files:**
- Create: `backend/app/services/agent_service.py`
- Create: `backend/app/services/agent_version_service.py`
- Reference: `backend/app/services/agent_profile_service.py` (old service for patterns), `backend/app/services/base.py`

- [ ] **Step 1: Write AgentService**

```python
# backend/app/services/agent_service.py
import re
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent import Agent, AgentVersion
from backend.app.schemas.agent import AgentCreate, AgentUpdate
from backend.app.core.exceptions import NotFoundException, ConflictException


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_agents(self, workspace_id: uuid.UUID) -> list[Agent]:
        result = await self.db.execute(
            select(Agent).where(Agent.workspace_id == workspace_id).order_by(Agent.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_agent(self, agent_id: uuid.UUID) -> Agent:
        result = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        return agent

    async def create_agent(self, workspace_id: uuid.UUID, user_id: str, data: AgentCreate) -> Agent:
        slug = self._generate_slug(data.name)
        existing = await self.db.execute(
            select(Agent).where(Agent.workspace_id == workspace_id, Agent.slug == slug)
        )
        if existing.scalar_one_or_none():
            raise ConflictException(f"Agent with slug '{slug}' already exists in this workspace")

        agent = Agent(
            workspace_id=workspace_id,
            name=data.name,
            slug=slug,
            description=data.description,
            avatar=data.avatar,
            status="draft",
            created_by=user_id,
        )
        self.db.add(agent)
        await self.db.flush()

        # Create initial draft version
        version = AgentVersion(
            agent_id=agent.id,
            version_number=1,
            status="draft",
            source_kind="manual",
            definition_kind=data.definition_kind,
            definition_payload=data.definition_payload,
            capability_manifest=data.capability_manifest,
            created_by=user_id,
        )
        self.db.add(version)
        await self.db.flush()

        agent.current_draft_version_id = version.id
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def update_agent(self, agent_id: uuid.UUID, data: AgentUpdate) -> Agent:
        agent = await self.get_agent(agent_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, field, value)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def archive_agent(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.get_agent(agent_id)
        agent.status = "archived"
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    @staticmethod
    def _generate_slug(name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
        slug = re.sub(r"[\s]+", "-", slug).strip("-")
        return slug or "agent"
```

- [ ] **Step 2: Write AgentVersionService**

```python
# backend/app/services/agent_version_service.py
import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent import Agent, AgentVersion
from backend.app.schemas.agent_version import AgentVersionCreate, AgentVersionUpdate
from backend.app.core.exceptions import NotFoundException, BadRequestException


class AgentVersionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_versions(self, agent_id: uuid.UUID) -> list[AgentVersion]:
        result = await self.db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: uuid.UUID) -> AgentVersion:
        result = await self.db.execute(select(AgentVersion).where(AgentVersion.id == version_id))
        version = result.scalar_one_or_none()
        if not version:
            raise NotFoundException(f"AgentVersion {version_id} not found")
        return version

    async def create_version(self, agent_id: uuid.UUID, user_id: str, data: AgentVersionCreate) -> AgentVersion:
        max_num = await self.db.execute(
            select(func.coalesce(func.max(AgentVersion.version_number), 0)).where(AgentVersion.agent_id == agent_id)
        )
        next_number = max_num.scalar() + 1

        version = AgentVersion(
            agent_id=agent_id,
            version_number=next_number,
            status="draft",
            source_kind=data.source_kind,
            definition_kind=data.definition_kind,
            definition_payload=data.definition_payload,
            capability_manifest=data.capability_manifest,
            changelog=data.changelog,
            created_by=user_id,
        )
        self.db.add(version)
        await self.db.flush()

        # Update agent's draft pointer
        result = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one()
        agent.current_draft_version_id = version.id
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def update_version(self, version_id: uuid.UUID, data: AgentVersionUpdate) -> AgentVersion:
        version = await self.get_version(version_id)
        if version.status == "frozen":
            raise BadRequestException("Cannot edit a frozen version")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(version, field, value)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def freeze_version(self, version_id: uuid.UUID) -> AgentVersion:
        version = await self.get_version(version_id)
        if version.status == "frozen":
            raise BadRequestException("Version is already frozen")
        version.status = "frozen"
        await self.db.commit()
        await self.db.refresh(version)
        return version
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent_service.py backend/app/services/agent_version_service.py
git commit -m "feat(services): add AgentService and AgentVersionService"
```

---

### Task 1.5: API Routes — /agents and /agents/{id}/versions

**Files:**
- Create: `backend/app/api/v1/agents.py`
- Modify: `backend/app/api/v1/__init__.py` (register router)
- Reference: `backend/app/api/v1/agent_profiles.py` (old router for patterns)

- [ ] **Step 1: Write agents API router**

```python
# backend/app/api/v1/agents.py
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.auth import get_current_user
from backend.app.schemas.base import BaseResponse
from backend.app.schemas.agent import AgentCreate, AgentUpdate, AgentResponse
from backend.app.schemas.agent_version import (
    AgentVersionCreate, AgentVersionUpdate, AgentVersionResponse,
)
from backend.app.services.agent_service import AgentService
from backend.app.services.agent_version_service import AgentVersionService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentService(db)
    agents = await service.list_agents(workspace_id)
    return BaseResponse(data=[AgentResponse.model_validate(a) for a in agents])


@router.post("")
async def create_agent(
    workspace_id: uuid.UUID, body: AgentCreate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentService(db)
    agent = await service.create_agent(workspace_id, user.id, body)
    return BaseResponse(data=AgentResponse.model_validate(agent))


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    return BaseResponse(data=AgentResponse.model_validate(agent))


@router.patch("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentService(db)
    agent = await service.update_agent(agent_id, body)
    return BaseResponse(data=AgentResponse.model_validate(agent))


@router.delete("/{agent_id}")
async def archive_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentService(db)
    agent = await service.archive_agent(agent_id)
    return BaseResponse(data=AgentResponse.model_validate(agent))


# --- AgentVersion sub-routes ---

@router.get("/{agent_id}/versions")
async def list_versions(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentVersionService(db)
    versions = await service.list_versions(agent_id)
    return BaseResponse(data=[AgentVersionResponse.model_validate(v) for v in versions])


@router.post("/{agent_id}/versions")
async def create_version(
    agent_id: uuid.UUID, body: AgentVersionCreate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentVersionService(db)
    version = await service.create_version(agent_id, user.id, body)
    return BaseResponse(data=AgentVersionResponse.model_validate(version))


@router.get("/{agent_id}/versions/{version_id}")
async def get_version(version_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentVersionService(db)
    version = await service.get_version(version_id)
    return BaseResponse(data=AgentVersionResponse.model_validate(version))


@router.patch("/{agent_id}/versions/{version_id}")
async def update_version(
    version_id: uuid.UUID, body: AgentVersionUpdate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentVersionService(db)
    version = await service.update_version(version_id, body)
    return BaseResponse(data=AgentVersionResponse.model_validate(version))


@router.post("/{agent_id}/versions/{version_id}/freeze")
async def freeze_version(version_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentVersionService(db)
    version = await service.freeze_version(version_id)
    return BaseResponse(data=AgentVersionResponse.model_validate(version))
```

- [ ] **Step 2: Register router in `__init__.py`**

In `backend/app/api/v1/__init__.py`, add:
```python
from backend.app.api.v1.agents import router as agents_router
api_router.include_router(agents_router)
```

And remove (or comment out):
```python
# from backend.app.api.v1.agent_profiles import router as agent_profiles_router
# api_router.include_router(agent_profiles_router)
```

- [ ] **Step 3: Verify server starts**

Run: `cd backend && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
Expected: Server starts without import errors. Check `/docs` shows new `/agents` routes.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/agents.py backend/app/api/v1/__init__.py
git commit -m "feat(api): add /agents and /agents/{id}/versions routes"
```

---

### Task 1.6: Frontend — Agent Service + React Query Hooks

**Files:**
- Create: `frontend/services/agentService.ts` (replaces `agentProfileService.ts`)
- Create: `frontend/services/agentVersionService.ts`
- Create: `frontend/hooks/queries/agents.ts` (replaces `agentProfiles.ts`)
- Create: `frontend/hooks/queries/agentVersions.ts`
- Reference: `frontend/services/agentProfileService.ts`, `frontend/hooks/queries/agentProfiles.ts`

- [ ] **Step 1: Write agentService.ts**

```typescript
// frontend/services/agentService.ts
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

export interface AgentCreate {
  name: string;
  description?: string;
  avatar?: string;
  definition_kind: "prompt" | "graph" | "code" | "hybrid";
  definition_payload?: Record<string, unknown>;
  capability_manifest?: Record<string, unknown>;
}

export interface AgentUpdate {
  name?: string;
  description?: string;
  avatar?: string;
  status?: "draft" | "active" | "archived";
}

export interface Agent {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  avatar: string | null;
  status: string;
  current_draft_version_id: string | null;
  active_release_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export const agentService = {
  list: (workspaceId: string) =>
    apiGet<Agent[]>(`/agents?workspace_id=${workspaceId}`),
  get: (agentId: string) =>
    apiGet<Agent>(`/agents/${agentId}`),
  create: (workspaceId: string, data: AgentCreate) =>
    apiPost<Agent>(`/agents?workspace_id=${workspaceId}`, data),
  update: (agentId: string, data: AgentUpdate) =>
    apiPatch<Agent>(`/agents/${agentId}`, data),
  archive: (agentId: string) =>
    apiDelete<Agent>(`/agents/${agentId}`),
};
```

- [ ] **Step 2: Write agentVersionService.ts**

```typescript
// frontend/services/agentVersionService.ts
import { apiGet, apiPost, apiPatch } from "@/lib/api";

export interface AgentVersionCreate {
  source_kind?: string;
  definition_kind: "prompt" | "graph" | "code" | "hybrid";
  definition_payload?: Record<string, unknown>;
  capability_manifest?: Record<string, unknown>;
  changelog?: string;
}

export interface AgentVersionUpdate {
  definition_payload?: Record<string, unknown>;
  capability_manifest?: Record<string, unknown>;
  changelog?: string;
}

export interface AgentVersion {
  id: string;
  agent_id: string;
  version_number: number;
  status: "draft" | "frozen";
  source_kind: string;
  definition_kind: string;
  definition_payload: Record<string, unknown>;
  capability_manifest: Record<string, unknown>;
  changelog: string | null;
  created_by: string;
  created_at: string;
}

export const agentVersionService = {
  list: (agentId: string) =>
    apiGet<AgentVersion[]>(`/agents/${agentId}/versions`),
  get: (agentId: string, versionId: string) =>
    apiGet<AgentVersion>(`/agents/${agentId}/versions/${versionId}`),
  create: (agentId: string, data: AgentVersionCreate) =>
    apiPost<AgentVersion>(`/agents/${agentId}/versions`, data),
  update: (agentId: string, versionId: string, data: AgentVersionUpdate) =>
    apiPatch<AgentVersion>(`/agents/${agentId}/versions/${versionId}`, data),
  freeze: (agentId: string, versionId: string) =>
    apiPost<AgentVersion>(`/agents/${agentId}/versions/${versionId}/freeze`, {}),
};
```

- [ ] **Step 3: Write React Query hooks — agents.ts**

```typescript
// frontend/hooks/queries/agents.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { agentService, AgentCreate, AgentUpdate } from "@/services/agentService";

export const agentKeys = {
  all: ["agents"] as const,
  list: (workspaceId: string) => [...agentKeys.all, "list", workspaceId] as const,
  detail: (agentId: string) => [...agentKeys.all, "detail", agentId] as const,
};

export function useAgents(workspaceId: string) {
  return useQuery({
    queryKey: agentKeys.list(workspaceId),
    queryFn: () => agentService.list(workspaceId),
  });
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: agentKeys.detail(agentId),
    queryFn: () => agentService.get(agentId),
    enabled: !!agentId,
  });
}

export function useCreateAgent(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentCreate) => agentService.create(workspaceId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: agentKeys.list(workspaceId) }),
  });
}

export function useUpdateAgent(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentUpdate) => agentService.update(agentId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
      qc.invalidateQueries({ queryKey: agentKeys.all });
    },
  });
}

export function useArchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) => agentService.archive(agentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: agentKeys.all }),
  });
}
```

- [ ] **Step 4: Write React Query hooks — agentVersions.ts**

```typescript
// frontend/hooks/queries/agentVersions.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { agentVersionService, AgentVersionCreate, AgentVersionUpdate } from "@/services/agentVersionService";
import { agentKeys } from "./agents";

export const versionKeys = {
  all: (agentId: string) => [...agentKeys.detail(agentId), "versions"] as const,
  list: (agentId: string) => [...versionKeys.all(agentId), "list"] as const,
  detail: (agentId: string, versionId: string) => [...versionKeys.all(agentId), "detail", versionId] as const,
};

export function useVersions(agentId: string) {
  return useQuery({
    queryKey: versionKeys.list(agentId),
    queryFn: () => agentVersionService.list(agentId),
    enabled: !!agentId,
  });
}

export function useVersion(agentId: string, versionId: string) {
  return useQuery({
    queryKey: versionKeys.detail(agentId, versionId),
    queryFn: () => agentVersionService.get(agentId, versionId),
    enabled: !!agentId && !!versionId,
  });
}

export function useCreateVersion(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentVersionCreate) => agentVersionService.create(agentId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: versionKeys.list(agentId) });
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
    },
  });
}

export function useUpdateVersion(agentId: string, versionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentVersionUpdate) => agentVersionService.update(agentId, versionId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: versionKeys.detail(agentId, versionId) }),
  });
}

export function useFreezeVersion(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => agentVersionService.freeze(agentId, versionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: versionKeys.list(agentId) }),
  });
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/services/agentService.ts frontend/services/agentVersionService.ts frontend/hooks/queries/agents.ts frontend/hooks/queries/agentVersions.ts
git commit -m "feat(frontend): add agent and version services + React Query hooks"
```

---

### Task 1.7: Frontend — Agent Pages (List, Create, Detail, Edit, Versions)

**Files:**
- Rewrite: `frontend/app/agents/page.tsx` (agent list)
- Create: `frontend/app/agents/new/page.tsx`
- Create: `frontend/app/agents/[agentId]/page.tsx`
- Create: `frontend/app/agents/[agentId]/edit/page.tsx`
- Create: `frontend/app/agents/[agentId]/versions/page.tsx`
- Create: `frontend/components/agents/agent-card.tsx` (rewrite)
- Create: `frontend/components/agents/agent-create-dialog.tsx`
- Create: `frontend/components/agents/agent-header.tsx`
- Create: `frontend/components/agents/version-editor.tsx`
- Create: `frontend/components/agents/version-history.tsx`
- Reference: existing `frontend/app/agents/page.tsx`, `frontend/components/agents/`

This task produces the frontend pages. Implementation adapts the existing agent page patterns to use the new Agent model. The `VersionEditor` component switches between `PromptEditor`, `GraphEditor` (reusing ReactFlow canvas), and `CodeEditor` (reusing CodeMirror) based on `definition_kind`.

- [ ] **Step 1: Rewrite agent list page**

Rewrite `frontend/app/agents/page.tsx` to use `useAgents()` hook instead of `useAgentProfiles()`. Display Agent cards with name, slug, status, definition_kind from current_draft_version.

- [ ] **Step 2: Create agent detail page**

Create `frontend/app/agents/[agentId]/page.tsx` showing AgentHeader (name, slug, status), AgentOverview (active release summary, recent runs count), and navigation to edit/versions/releases/threads/runs.

- [ ] **Step 3: Create version editor page**

Create `frontend/app/agents/[agentId]/edit/page.tsx` that loads the current draft version and renders the appropriate editor based on `definition_kind`:
- `prompt` → PromptEditor (textarea for instructions)
- `graph` → GraphEditor (ReactFlow canvas, reuse existing `frontend/components/graph/` components)
- `code` → CodeEditor (CodeMirror, reuse existing `frontend/components/code-editor/`)

- [ ] **Step 4: Create version history page**

Create `frontend/app/agents/[agentId]/versions/page.tsx` listing all versions with version_number, status (draft/frozen), definition_kind, created_at. Add freeze button for draft versions.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/agents/ frontend/components/agents/
git commit -m "feat(frontend): rewrite agent pages for new Agent model"
```

---

### Task 1.8: Delete Legacy agent_profiles Code

**Files:**
- Delete: `backend/app/models/agent_profile.py`
- Delete: `backend/app/services/agent_profile_service.py`
- Delete: `backend/app/api/v1/agent_profiles.py`
- Delete: `backend/app/schemas/agent_profile.py` (if exists)
- Delete: `frontend/services/agentProfileService.ts`
- Delete: `frontend/hooks/queries/agentProfiles.ts`
- Modify: `backend/app/api/v1/__init__.py` (remove agent_profiles router)
- Modify: `backend/app/models/__init__.py` (remove AgentProfile import)
- Create: `backend/alembic/versions/20260421_000002_drop_agent_profiles.py`

- [ ] **Step 1: Write Alembic migration to drop agent_profiles table**

```python
# backend/alembic/versions/20260421_000002_drop_agent_profiles.py
"""drop agent_profiles table"""

from alembic import op

revision = "20260421_000002"
down_revision = "20260421_000001"

def upgrade():
    op.drop_table("agent_profiles")

def downgrade():
    pass  # no data migration, no rollback
```

- [ ] **Step 2: Delete backend legacy files**

Remove: `backend/app/models/agent_profile.py`, `backend/app/services/agent_profile_service.py`, `backend/app/api/v1/agent_profiles.py`

Update `backend/app/models/__init__.py` — remove `AgentProfile` import.
Update `backend/app/api/v1/__init__.py` — remove `agent_profiles_router`.

- [ ] **Step 3: Delete frontend legacy files**

Remove: `frontend/services/agentProfileService.ts`, `frontend/hooks/queries/agentProfiles.ts`

- [ ] **Step 4: Search for remaining references**

Run: `grep -r "agent_profile" backend/app/ --include="*.py" -l`
Run: `grep -r "agentProfile\|AgentProfile" frontend/ --include="*.ts" --include="*.tsx" -l`

Fix any remaining imports/references.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy agent_profiles code and table"
```

---

## Phase 2: AgentRelease + Publish Flow

### Task 2.1: Alembic Migration — Create `agent_releases` Table + FK on agents

**Files:**
- Create: `backend/alembic/versions/20260421_000003_create_agent_releases.py`

- [ ] **Step 1: Write migration**

```python
# backend/alembic/versions/20260421_000003_create_agent_releases.py
"""create agent_releases table and add FK on agents.active_release_id"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260421_000003"
down_revision = "20260421_000002"

def upgrade():
    op.create_table(
        "agent_releases",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_version_id", UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("release_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column("runtime_kind", sa.String(20), nullable=False),
        sa.Column("builder_kind", sa.String(20), nullable=True),
        sa.Column("executable_ref", JSONB, nullable=True),
        sa.Column("runtime_binding", JSONB, nullable=False, server_default="{}"),
        sa.Column("published_by", sa.String(255), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_version_id", "release_number", name="uq_agent_releases_version_number"),
    )
    op.create_foreign_key(
        "fk_agents_active_release",
        "agents", "agent_releases",
        ["active_release_id"], ["id"],
    )

def downgrade():
    op.drop_constraint("fk_agents_active_release", "agents", type_="foreignkey")
    op.drop_table("agent_releases")
```

- [ ] **Step 2: Run migration**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/20260421_000003_create_agent_releases.py
git commit -m "feat(db): create agent_releases table"
```

---

### Task 2.2: SQLAlchemy Model — AgentRelease

**Files:**
- Modify: `backend/app/models/agent.py` (add AgentRelease class + update Agent relationship)

- [ ] **Step 1: Add AgentRelease model to agent.py**

Append to `backend/app/models/agent.py`:

```python
class AgentRelease(Base):
    __tablename__ = "agent_releases"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "release_number", name="uq_agent_releases_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=False)
    release_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="building")
    runtime_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    builder_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    executable_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    runtime_binding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_by: Mapped[str | None] = mapped_column(String(255), ForeignKey("user.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    version: Mapped["AgentVersion"] = relationship()
```

- [ ] **Step 2: Update Agent model — add active_release relationship**

Update the `active_release_id` column in Agent to include FK now:
```python
    active_release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_releases.id"), nullable=True
    )
    active_release: Mapped["AgentRelease | None"] = relationship(foreign_keys=[active_release_id])
```

- [ ] **Step 3: Update `__init__.py`**

Add `AgentRelease` to exports in `backend/app/models/__init__.py`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/agent.py backend/app/models/__init__.py
git commit -m "feat(models): add AgentRelease model"
```

---

### Task 2.3: Pydantic Schemas — AgentRelease

**Files:**
- Create: `backend/app/schemas/agent_release.py`

- [ ] **Step 1: Write release schemas**

```python
# backend/app/schemas/agent_release.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AgentReleaseCreate(BaseModel):
    agent_version_id: uuid.UUID
    runtime_kind: str = Field(..., pattern="^(graph|sandbox|hosted|external)$")
    builder_kind: str | None = None
    runtime_binding: dict = Field(default_factory=dict)


class AgentReleaseResponse(BaseModel):
    id: uuid.UUID
    agent_version_id: uuid.UUID
    release_number: int
    status: str
    runtime_kind: str
    builder_kind: str | None
    executable_ref: dict | None
    runtime_binding: dict
    published_by: str | None
    published_at: datetime | None
    retired_at: datetime | None

    model_config = {"from_attributes": True}


class AgentReleaseSummary(BaseModel):
    id: uuid.UUID
    release_number: int
    status: str
    runtime_kind: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/agent_release.py
git commit -m "feat(schemas): add AgentRelease Pydantic schemas"
```

---

### Task 2.4: Service — AgentReleaseService

**Files:**
- Create: `backend/app/services/agent_release_service.py`

- [ ] **Step 1: Write AgentReleaseService**

```python
# backend/app/services/agent_release_service.py
import uuid
from datetime import datetime, timezone, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent import Agent, AgentVersion, AgentRelease
from backend.app.schemas.agent_release import AgentReleaseCreate
from backend.app.core.exceptions import NotFoundException, BadRequestException


class AgentReleaseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_releases(self, agent_id: uuid.UUID) -> list[AgentRelease]:
        result = await self.db.execute(
            select(AgentRelease)
            .join(AgentVersion, AgentRelease.agent_version_id == AgentVersion.id)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentRelease.release_number.desc())
        )
        return list(result.scalars().all())

    async def get_release(self, release_id: uuid.UUID) -> AgentRelease:
        result = await self.db.execute(select(AgentRelease).where(AgentRelease.id == release_id))
        release = result.scalar_one_or_none()
        if not release:
            raise NotFoundException(f"AgentRelease {release_id} not found")
        return release

    async def publish_release(self, agent_id: uuid.UUID, user_id: str, data: AgentReleaseCreate) -> AgentRelease:
        # Verify version is frozen and belongs to agent
        version = await self.db.execute(
            select(AgentVersion).where(AgentVersion.id == data.agent_version_id, AgentVersion.agent_id == agent_id)
        )
        version = version.scalar_one_or_none()
        if not version:
            raise NotFoundException("Version not found for this agent")
        if version.status != "frozen":
            raise BadRequestException("Can only publish from a frozen version")

        max_num = await self.db.execute(
            select(func.coalesce(func.max(AgentRelease.release_number), 0))
            .where(AgentRelease.agent_version_id == data.agent_version_id)
        )
        next_number = max_num.scalar() + 1

        release = AgentRelease(
            agent_version_id=data.agent_version_id,
            release_number=next_number,
            status="ready",
            runtime_kind=data.runtime_kind,
            builder_kind=data.builder_kind,
            runtime_binding=data.runtime_binding,
            published_by=user_id,
            published_at=datetime.now(timezone.utc),
        )
        self.db.add(release)
        await self.db.commit()
        await self.db.refresh(release)
        return release

    async def activate_release(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> AgentRelease:
        release = await self.get_release(release_id)
        if release.status != "ready":
            raise BadRequestException("Only ready releases can be activated")

        agent = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent.scalar_one()
        agent.active_release_id = release_id
        if agent.status == "draft":
            agent.status = "active"
        await self.db.commit()
        await self.db.refresh(release)
        return release

    async def retire_release(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> AgentRelease:
        release = await self.get_release(release_id)
        release.status = "retired"
        release.retired_at = datetime.now(timezone.utc)

        # If this was the active release, clear agent's pointer
        agent = await self.db.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent.scalar_one()
        if agent.active_release_id == release_id:
            agent.active_release_id = None
        await self.db.commit()
        await self.db.refresh(release)
        return release
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/agent_release_service.py
git commit -m "feat(services): add AgentReleaseService"
```

---

### Task 2.5: API Routes — /agents/{id}/releases

**Files:**
- Modify: `backend/app/api/v1/agents.py` (add release routes)

- [ ] **Step 1: Add release routes to agents.py**

Append to `backend/app/api/v1/agents.py`:

```python
from backend.app.schemas.agent_release import AgentReleaseCreate, AgentReleaseResponse
from backend.app.services.agent_release_service import AgentReleaseService

@router.get("/{agent_id}/releases")
async def list_releases(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentReleaseService(db)
    releases = await service.list_releases(agent_id)
    return BaseResponse(data=[AgentReleaseResponse.model_validate(r) for r in releases])

@router.post("/{agent_id}/releases")
async def publish_release(
    agent_id: uuid.UUID, body: AgentReleaseCreate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentReleaseService(db)
    release = await service.publish_release(agent_id, user.id, body)
    return BaseResponse(data=AgentReleaseResponse.model_validate(release))

@router.get("/{agent_id}/releases/{release_id}")
async def get_release(release_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentReleaseService(db)
    release = await service.get_release(release_id)
    return BaseResponse(data=AgentReleaseResponse.model_validate(release))

@router.post("/{agent_id}/releases/{release_id}/activate")
async def activate_release(
    agent_id: uuid.UUID, release_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentReleaseService(db)
    release = await service.activate_release(agent_id, release_id)
    return BaseResponse(data=AgentReleaseResponse.model_validate(release))

@router.post("/{agent_id}/releases/{release_id}/retire")
async def retire_release(
    agent_id: uuid.UUID, release_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentReleaseService(db)
    release = await service.retire_release(agent_id, release_id)
    return BaseResponse(data=AgentReleaseResponse.model_validate(release))
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/v1/agents.py
git commit -m "feat(api): add /agents/{id}/releases routes"
```

---

### Task 2.6: Frontend — Release Service, Hooks, and Release Manager UI

**Files:**
- Create: `frontend/services/agentReleaseService.ts`
- Create: `frontend/hooks/queries/agentReleases.ts`
- Create: `frontend/app/agents/[agentId]/releases/page.tsx`
- Create: `frontend/components/agents/release-manager.tsx`

- [ ] **Step 1: Write agentReleaseService.ts**

```typescript
// frontend/services/agentReleaseService.ts
import { apiGet, apiPost } from "@/lib/api";

export interface AgentReleaseCreate {
  agent_version_id: string;
  runtime_kind: "graph" | "sandbox" | "hosted" | "external";
  builder_kind?: string;
  runtime_binding?: Record<string, unknown>;
}

export interface AgentRelease {
  id: string;
  agent_version_id: string;
  release_number: number;
  status: "building" | "ready" | "failed" | "retired";
  runtime_kind: string;
  builder_kind: string | null;
  executable_ref: Record<string, unknown> | null;
  runtime_binding: Record<string, unknown>;
  published_by: string | null;
  published_at: string | null;
  retired_at: string | null;
}

export const agentReleaseService = {
  list: (agentId: string) =>
    apiGet<AgentRelease[]>(`/agents/${agentId}/releases`),
  get: (agentId: string, releaseId: string) =>
    apiGet<AgentRelease>(`/agents/${agentId}/releases/${releaseId}`),
  publish: (agentId: string, data: AgentReleaseCreate) =>
    apiPost<AgentRelease>(`/agents/${agentId}/releases`, data),
  activate: (agentId: string, releaseId: string) =>
    apiPost<AgentRelease>(`/agents/${agentId}/releases/${releaseId}/activate`, {}),
  retire: (agentId: string, releaseId: string) =>
    apiPost<AgentRelease>(`/agents/${agentId}/releases/${releaseId}/retire`, {}),
};
```

- [ ] **Step 2: Write agentReleases.ts hooks**

```typescript
// frontend/hooks/queries/agentReleases.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { agentReleaseService, AgentReleaseCreate } from "@/services/agentReleaseService";
import { agentKeys } from "./agents";

export const releaseKeys = {
  all: (agentId: string) => [...agentKeys.detail(agentId), "releases"] as const,
  list: (agentId: string) => [...releaseKeys.all(agentId), "list"] as const,
};

export function useReleases(agentId: string) {
  return useQuery({
    queryKey: releaseKeys.list(agentId),
    queryFn: () => agentReleaseService.list(agentId),
    enabled: !!agentId,
  });
}

export function usePublishRelease(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentReleaseCreate) => agentReleaseService.publish(agentId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: releaseKeys.list(agentId) });
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
    },
  });
}

export function useActivateRelease(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (releaseId: string) => agentReleaseService.activate(agentId, releaseId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: releaseKeys.list(agentId) });
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
    },
  });
}

export function useRetireRelease(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (releaseId: string) => agentReleaseService.retire(agentId, releaseId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: releaseKeys.list(agentId) });
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
    },
  });
}
```

- [ ] **Step 3: Create releases page and release-manager component**

Create `frontend/app/agents/[agentId]/releases/page.tsx` — lists releases with release_number, status, runtime_kind, published_at. Buttons: publish new (from frozen version), activate, retire.

Create `frontend/components/agents/release-manager.tsx` — reusable component with publish flow: select frozen version → choose runtime_kind → set runtime_binding → publish.

- [ ] **Step 4: Commit**

```bash
git add frontend/services/agentReleaseService.ts frontend/hooks/queries/agentReleases.ts frontend/app/agents/\[agentId\]/releases/ frontend/components/agents/release-manager.tsx
git commit -m "feat(frontend): add release service, hooks, and release manager UI"
```

---

### Task 2.7: Delete Legacy graph_deployment_version Code

**Files:**
- Delete: `backend/app/models/graph_deployment_version.py`
- Delete: `backend/app/services/graph_deployment_version_service.py`
- Delete: `backend/app/api/v1/graph_deployments.py`
- Delete: `backend/app/schemas/graph_deployment_version.py`
- Delete: `frontend/services/graphDeploymentService.ts`
- Delete: `frontend/stores/deploymentStore.ts`
- Create: `backend/alembic/versions/20260421_000004_drop_graph_deployment_version.py`

- [ ] **Step 1: Write migration to drop table**

```python
revision = "20260421_000004"
down_revision = "20260421_000003"

def upgrade():
    op.drop_table("graph_deployment_version")

def downgrade():
    pass
```

- [ ] **Step 2: Delete backend files and clean up imports**

Remove the files listed above. Update `__init__.py` files to remove imports and router registrations.

- [ ] **Step 3: Delete frontend files**

Remove `frontend/services/graphDeploymentService.ts` and `frontend/stores/deploymentStore.ts`.

- [ ] **Step 4: Search for remaining references**

Run: `grep -r "graph_deployment\|GraphDeployment\|deploymentStore" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" -l`

Fix any remaining references.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy graph_deployment_version code"
```

---

## Phase 3: Thread + Message (Conversation System)

### Task 3.1: Alembic Migration — Create `threads` and `messages` Tables

**Files:**
- Create: `backend/alembic/versions/20260421_000005_create_threads_messages.py`

- [ ] **Step 1: Write migration**

```python
# backend/alembic/versions/20260421_000005_create_threads_messages.py
"""create threads and messages tables"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260421_000005"
down_revision = "20260421_000004"

def upgrade():
    op.create_table(
        "threads",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),  # FK added in Phase 4
        sa.Column("execution_id", UUID(as_uuid=True), nullable=True),  # FK added in Phase 4
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

def downgrade():
    op.drop_table("messages")
    op.drop_table("threads")
```

- [ ] **Step 2: Run migration**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/20260421_000005_create_threads_messages.py
git commit -m "feat(db): create threads and messages tables"
```

---

### Task 3.2: SQLAlchemy Models — Thread and Message

**Files:**
- Create: `backend/app/models/thread.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write Thread and Message models**

```python
# backend/app/models/thread.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(255), ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages: Mapped[list["Message"]] = relationship(back_populates="thread")
    agent: Mapped["Agent"] = relationship()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    thread: Mapped["Thread"] = relationship(back_populates="messages")
```

- [ ] **Step 2: Update `__init__.py`**

Add to `backend/app/models/__init__.py`:
```python
from backend.app.models.thread import Thread, Message
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/thread.py backend/app/models/__init__.py
git commit -m "feat(models): add Thread and Message models"
```

---

### Task 3.3: Schemas + Service + API — Threads and Messages

**Files:**
- Create: `backend/app/schemas/thread.py`
- Create: `backend/app/services/thread_service.py`
- Create: `backend/app/api/v1/threads.py`
- Modify: `backend/app/api/v1/__init__.py`

- [ ] **Step 1: Write thread schemas**

```python
# backend/app/schemas/thread.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ThreadCreate(BaseModel):
    agent_id: uuid.UUID
    title: str | None = None


class ThreadUpdate(BaseModel):
    title: str | None = None
    status: str | None = Field(None, pattern="^(active|archived)$")


class ThreadResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    workspace_id: uuid.UUID
    title: str | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system|tool)$")
    content: dict


class MessageResponse(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    run_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    role: str
    content: dict
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Write ThreadService**

```python
# backend/app/services/thread_service.py
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.thread import Thread, Message
from backend.app.schemas.thread import ThreadCreate, ThreadUpdate, MessageCreate
from backend.app.core.exceptions import NotFoundException


class ThreadService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_threads(self, agent_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None) -> list[Thread]:
        query = select(Thread).order_by(Thread.updated_at.desc())
        if agent_id:
            query = query.where(Thread.agent_id == agent_id)
        if workspace_id:
            query = query.where(Thread.workspace_id == workspace_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_thread(self, thread_id: uuid.UUID) -> Thread:
        result = await self.db.execute(select(Thread).where(Thread.id == thread_id))
        thread = result.scalar_one_or_none()
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")
        return thread

    async def create_thread(self, workspace_id: uuid.UUID, user_id: str, data: ThreadCreate) -> Thread:
        thread = Thread(
            agent_id=data.agent_id,
            workspace_id=workspace_id,
            title=data.title,
            created_by=user_id,
        )
        self.db.add(thread)
        await self.db.commit()
        await self.db.refresh(thread)
        return thread

    async def update_thread(self, thread_id: uuid.UUID, data: ThreadUpdate) -> Thread:
        thread = await self.get_thread(thread_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(thread, field, value)
        await self.db.commit()
        await self.db.refresh(thread)
        return thread

    async def list_messages(self, thread_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[Message]:
        result = await self.db.execute(
            select(Message).where(Message.thread_id == thread_id)
            .order_by(Message.created_at.asc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create_message(self, thread_id: uuid.UUID, data: MessageCreate) -> Message:
        msg = Message(thread_id=thread_id, role=data.role, content=data.content)
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg
```

- [ ] **Step 3: Write threads API router**

```python
# backend/app/api/v1/threads.py
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.auth import get_current_user
from backend.app.schemas.base import BaseResponse
from backend.app.schemas.thread import (
    ThreadCreate, ThreadUpdate, ThreadResponse,
    MessageCreate, MessageResponse,
)
from backend.app.services.thread_service import ThreadService

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("")
async def list_threads(
    agent_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = ThreadService(db)
    threads = await service.list_threads(agent_id=agent_id, workspace_id=workspace_id)
    return BaseResponse(data=[ThreadResponse.model_validate(t) for t in threads])


@router.post("")
async def create_thread(
    workspace_id: uuid.UUID, body: ThreadCreate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = ThreadService(db)
    thread = await service.create_thread(workspace_id, user.id, body)
    return BaseResponse(data=ThreadResponse.model_validate(thread))


@router.get("/{thread_id}")
async def get_thread(thread_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    return BaseResponse(data=ThreadResponse.model_validate(thread))


@router.patch("/{thread_id}")
async def update_thread(
    thread_id: uuid.UUID, body: ThreadUpdate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = ThreadService(db)
    thread = await service.update_thread(thread_id, body)
    return BaseResponse(data=ThreadResponse.model_validate(thread))


@router.get("/{thread_id}/messages")
async def list_messages(
    thread_id: uuid.UUID,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = ThreadService(db)
    messages = await service.list_messages(thread_id, limit=limit, offset=offset)
    return BaseResponse(data=[MessageResponse.model_validate(m) for m in messages])


@router.post("/{thread_id}/messages")
async def create_message(
    thread_id: uuid.UUID, body: MessageCreate,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = ThreadService(db)
    message = await service.create_message(thread_id, body)
    return BaseResponse(data=MessageResponse.model_validate(message))
```

- [ ] **Step 4: Register router**

Add to `backend/app/api/v1/__init__.py`:
```python
from backend.app.api.v1.threads import router as threads_router
api_router.include_router(threads_router)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/thread.py backend/app/services/thread_service.py backend/app/api/v1/threads.py backend/app/api/v1/__init__.py
git commit -m "feat: add Thread + Message schemas, service, and API routes"
```

---

### Task 3.4: Frontend — Thread Service, Hooks, and Conversation UI

**Files:**
- Create: `frontend/services/threadService.ts`
- Create: `frontend/hooks/queries/threads.ts`
- Create: `frontend/hooks/use-thread-stream.ts`
- Create: `frontend/app/agents/[agentId]/threads/page.tsx`
- Create: `frontend/app/agents/[agentId]/threads/[threadId]/page.tsx`
- Create: `frontend/components/threads/thread-list.tsx`
- Create: `frontend/components/threads/conversation-view.tsx`

- [ ] **Step 1: Write threadService.ts**

```typescript
// frontend/services/threadService.ts
import { apiGet, apiPost, apiPatch } from "@/lib/api";

export interface ThreadCreate { agent_id: string; title?: string; }
export interface ThreadUpdate { title?: string; status?: "active" | "archived"; }
export interface Thread {
  id: string; agent_id: string; workspace_id: string; title: string | null;
  status: string; created_by: string; created_at: string; updated_at: string;
}
export interface MessageCreate { role: string; content: Record<string, unknown>; }
export interface Message {
  id: string; thread_id: string; run_id: string | null; execution_id: string | null;
  role: string; content: Record<string, unknown>; created_at: string;
}

export const threadService = {
  list: (params: { agent_id?: string; workspace_id?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return apiGet<Thread[]>(`/threads?${qs}`);
  },
  get: (threadId: string) => apiGet<Thread>(`/threads/${threadId}`),
  create: (workspaceId: string, data: ThreadCreate) =>
    apiPost<Thread>(`/threads?workspace_id=${workspaceId}`, data),
  update: (threadId: string, data: ThreadUpdate) =>
    apiPatch<Thread>(`/threads/${threadId}`, data),
  listMessages: (threadId: string, limit = 100, offset = 0) =>
    apiGet<Message[]>(`/threads/${threadId}/messages?limit=${limit}&offset=${offset}`),
  sendMessage: (threadId: string, data: MessageCreate) =>
    apiPost<Message>(`/threads/${threadId}/messages`, data),
};
```

- [ ] **Step 2: Write threads.ts React Query hooks**

```typescript
// frontend/hooks/queries/threads.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { threadService, ThreadCreate, ThreadUpdate, MessageCreate } from "@/services/threadService";

export const threadKeys = {
  all: ["threads"] as const,
  list: (agentId: string) => [...threadKeys.all, "list", agentId] as const,
  detail: (threadId: string) => [...threadKeys.all, "detail", threadId] as const,
  messages: (threadId: string) => [...threadKeys.detail(threadId), "messages"] as const,
};

export function useThreads(agentId: string) {
  return useQuery({
    queryKey: threadKeys.list(agentId),
    queryFn: () => threadService.list({ agent_id: agentId }),
    enabled: !!agentId,
  });
}

export function useThread(threadId: string) {
  return useQuery({
    queryKey: threadKeys.detail(threadId),
    queryFn: () => threadService.get(threadId),
    enabled: !!threadId,
  });
}

export function useMessages(threadId: string) {
  return useQuery({
    queryKey: threadKeys.messages(threadId),
    queryFn: () => threadService.listMessages(threadId),
    enabled: !!threadId,
  });
}

export function useCreateThread(workspaceId: string, agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ThreadCreate) => threadService.create(workspaceId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: threadKeys.list(agentId) }),
  });
}

export function useSendMessage(threadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MessageCreate) => threadService.sendMessage(threadId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: threadKeys.messages(threadId) }),
  });
}
```

- [ ] **Step 3: Create thread pages and components**

- `frontend/app/agents/[agentId]/threads/page.tsx` — thread list with create button
- `frontend/app/agents/[agentId]/threads/[threadId]/page.tsx` — conversation UI with message list and input
- `frontend/components/threads/conversation-view.tsx` — chat-style message display

- [ ] **Step 4: Commit**

```bash
git add frontend/services/threadService.ts frontend/hooks/queries/threads.ts frontend/app/agents/\[agentId\]/threads/ frontend/components/threads/
git commit -m "feat(frontend): add thread service, hooks, and conversation UI"
```

---

### Task 3.5: Delete Legacy conversations Code

**Files:**
- Delete: `backend/app/models/conversation.py`
- Delete: `backend/app/api/v1/conversations.py`
- Delete: `backend/app/schemas/conversation.py`
- Delete: `frontend/services/conversationService.ts`
- Create: `backend/alembic/versions/20260421_000006_drop_conversations.py`

- [ ] **Step 1: Write migration**

```python
revision = "20260421_000006"
down_revision = "20260421_000005"

def upgrade():
    op.drop_table("conversations")

def downgrade():
    pass
```

- [ ] **Step 2: Delete files and clean imports**

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy conversations code and table"
```

---

## Phase 4: AgentRun + Execution (Execution Chain)

**Note:** `execution_events` is created in this phase (alongside `executions`) rather than Phase 5 as the spec suggests, because it has a direct FK dependency on `executions`. Phase 5 focuses on `artifacts` and legacy cleanup.

### Task 4.1: Alembic Migration — Create `agent_runs`, Rebuild `executions`, `execution_events`

**Files:**
- Create: `backend/alembic/versions/20260421_000007_drop_legacy_execution_tables.py`
- Create: `backend/alembic/versions/20260421_000008_create_agent_runs_executions.py`
- Create: `backend/alembic/versions/20260421_000009_add_message_fks.py`

Note: `missions.current_execution_id` removal is handled inside migration `000007` (before dropping legacy `executions` table).

- [ ] **Step 1: Drop legacy execution tables**

```python
# 20260421_000007_drop_legacy_execution_tables.py
"""drop legacy agent_runs, executions, and event/snapshot tables"""

revision = "20260421_000007"
down_revision = "20260421_000006"

def upgrade():
    # Drop in dependency order
    op.drop_table("execution_snapshots")
    op.drop_table("execution_events")
    op.drop_table("agent_run_snapshots")
    op.drop_table("agent_run_events")
    # Remove FK from missions.current_execution_id before dropping executions
    op.drop_constraint("fk_missions_current_execution", "missions", type_="foreignkey")
    op.drop_column("missions", "current_execution_id")
    op.drop_table("executions")
    op.drop_table("agent_runs")

def downgrade():
    pass
```

- [ ] **Step 2: Create new agent_runs and executions tables**

```python
# 20260421_000008_create_agent_runs_executions.py
"""create new agent_runs, executions, execution_events tables"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260421_000008"
down_revision = "20260421_000007"

def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("agent_releases.id"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("threads.id"), nullable=True),
        sa.Column("mission_id", UUID(as_uuid=True), sa.ForeignKey("missions.id"), nullable=True),
        sa.Column("trigger_source", sa.String(20), nullable=False),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("input_payload", JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("current_execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("result_summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "executions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("parent_execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=True),
        sa.Column("attempt_index", sa.Integer, nullable=False, server_default="1"),
        sa.Column("executor_kind", sa.String(20), nullable=False),
        sa.Column("runtime_session_ref", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("run_id", "attempt_index", name="uq_executions_run_attempt"),
    )

    # Add circular FK: agent_runs.current_execution_id -> executions.id
    op.create_foreign_key(
        "fk_agent_runs_current_execution",
        "agent_runs", "executions",
        ["current_execution_id"], ["id"],
    )

    op.create_table(
        "execution_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("execution_id", "sequence_no", name="uq_execution_events_seq"),
    )

def downgrade():
    op.drop_table("execution_events")
    op.drop_constraint("fk_agent_runs_current_execution", "agent_runs", type_="foreignkey")
    op.drop_table("executions")
    op.drop_table("agent_runs")
```

- [ ] **Step 3: Add FKs on messages table for run_id and execution_id**

```python
# 20260421_000009_add_message_fks.py
revision = "20260421_000009"
down_revision = "20260421_000008"

def upgrade():
    op.create_foreign_key("fk_messages_run", "messages", "agent_runs", ["run_id"], ["id"])
    op.create_foreign_key("fk_messages_execution", "messages", "executions", ["execution_id"], ["id"])

def downgrade():
    op.drop_constraint("fk_messages_execution", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_run", "messages", type_="foreignkey")
```

- [ ] **Step 4: Run all migrations**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260421_00000{7,8,9}*.py
git commit -m "feat(db): create agent_runs, executions, execution_events tables; drop legacy"
```

---

### Task 4.2: SQLAlchemy Models — AgentRun, Execution, ExecutionEvent

**Files:**
- Create: `backend/app/models/agent_run.py` (rewrite from scratch)
- Rewrite: `backend/app/models/execution.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write AgentRun model**

```python
# backend/app/models/agent_run.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_releases.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("missions.id"), nullable=True)
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    current_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    release: Mapped["AgentRelease"] = relationship()
    current_execution: Mapped["Execution | None"] = relationship(foreign_keys=[current_execution_id])
    executions: Mapped[list["Execution"]] = relationship(back_populates="run", foreign_keys="Execution.run_id")
```

- [ ] **Step 2: Rewrite Execution model**

```python
# backend/app/models/execution.py (complete rewrite)
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_index", name="uq_executions_run_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    executor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_session_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    run: Mapped["AgentRun"] = relationship(back_populates="executions", foreign_keys=[run_id])
    events: Mapped[list["ExecutionEvent"]] = relationship(back_populates="execution")
    children: Mapped[list["Execution"]] = relationship(foreign_keys=[parent_execution_id])


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_no", name="uq_execution_events_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    execution: Mapped["Execution"] = relationship(back_populates="events")
```

- [ ] **Step 3: Update `__init__.py`**

Update imports: replace old `AgentRun` and `Execution` imports with new ones.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/agent_run.py backend/app/models/execution.py backend/app/models/__init__.py
git commit -m "feat(models): rewrite AgentRun, Execution, ExecutionEvent models"
```

---

### Task 4.3: Schemas — AgentRun + Execution

**Files:**
- Create: `backend/app/schemas/agent_run.py`
- Rewrite: `backend/app/schemas/execution.py`

- [ ] **Step 1: Write AgentRun schemas**

```python
# backend/app/schemas/agent_run.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from backend.app.schemas.agent import AgentSummary
from backend.app.schemas.agent_version import AgentVersionSummary
from backend.app.schemas.agent_release import AgentReleaseSummary


class AgentRunCreate(BaseModel):
    release_id: uuid.UUID
    thread_id: uuid.UUID | None = None
    mission_id: uuid.UUID | None = None
    trigger_source: str = Field(..., pattern="^(mission|chat|api|scheduler)$")
    goal: str | None = None
    input_payload: dict | None = None


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    release_id: uuid.UUID
    workspace_id: uuid.UUID
    thread_id: uuid.UUID | None
    mission_id: uuid.UUID | None
    trigger_source: str
    goal: str | None
    input_payload: dict | None
    status: str
    current_execution_id: uuid.UUID | None
    result_summary: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunExpanded(AgentRunResponse):
    agent: AgentSummary | None = None
    version: AgentVersionSummary | None = None
    release: AgentReleaseSummary | None = None
```

- [ ] **Step 2: Rewrite execution schemas**

```python
# backend/app/schemas/execution.py (complete rewrite)
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    parent_execution_id: uuid.UUID | None
    attempt_index: int
    executor_kind: str
    runtime_session_ref: str | None
    status: str
    error_code: str | None
    error_message: str | None
    metrics: dict | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionEventResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    sequence_no: int
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/agent_run.py backend/app/schemas/execution.py
git commit -m "feat(schemas): add AgentRun schemas, rewrite Execution schemas"
```

---

### Task 4.4: Services — AgentRunService + Refactor ExecutionLifecycleService

**Files:**
- Create: `backend/app/services/agent_run_service.py`
- Rewrite: `backend/app/services/execution_lifecycle_service.py`
- Modify: `backend/app/services/execution_runner.py` (interface change)
- Modify: `backend/app/services/mission_service.py` (dispatch delegation)

- [ ] **Step 1: Write AgentRunService**

```python
# backend/app/services/agent_run_service.py
import uuid
from datetime import datetime, timezone, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun
from backend.app.models.execution import Execution
from backend.app.models.agent import AgentRelease, AgentVersion, Agent
from backend.app.schemas.agent_run import AgentRunCreate
from backend.app.core.exceptions import NotFoundException, BadRequestException


class AgentRunService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_runs(
        self, workspace_id: uuid.UUID | None = None,
        release_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
    ) -> list[AgentRun]:
        query = select(AgentRun).order_by(AgentRun.created_at.desc())
        if workspace_id:
            query = query.where(AgentRun.workspace_id == workspace_id)
        if release_id:
            query = query.where(AgentRun.release_id == release_id)
        if mission_id:
            query = query.where(AgentRun.mission_id == mission_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        result = await self.db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundException(f"AgentRun {run_id} not found")
        return run

    async def create_run(self, user_id: str | None, data: AgentRunCreate) -> AgentRun:
        # Resolve workspace_id from release -> version -> agent
        release = await self.db.execute(select(AgentRelease).where(AgentRelease.id == data.release_id))
        release = release.scalar_one_or_none()
        if not release or release.status != "ready":
            raise BadRequestException("Release not found or not ready")

        version = await self.db.execute(select(AgentVersion).where(AgentVersion.id == release.agent_version_id))
        version = version.scalar_one()
        agent = await self.db.execute(select(Agent).where(Agent.id == version.agent_id))
        agent = agent.scalar_one()

        run = AgentRun(
            release_id=data.release_id,
            workspace_id=agent.workspace_id,
            thread_id=data.thread_id,
            mission_id=data.mission_id,
            trigger_source=data.trigger_source,
            goal=data.goal,
            input_payload=data.input_payload,
            status="queued",
            created_by=user_id,
        )
        self.db.add(run)
        await self.db.flush()

        # Create initial execution
        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            executor_kind=release.runtime_binding.get("runtime_type", "claude_code"),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        run.started_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status in ("succeeded", "failed", "cancelled"):
            raise BadRequestException(f"Cannot cancel run in status {run.status}")
        run.status = "cancelled"
        run.ended_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def retry_run(self, run_id: uuid.UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status not in ("failed", "cancelled"):
            raise BadRequestException("Can only retry failed or cancelled runs")

        max_attempt = await self.db.execute(
            select(func.coalesce(func.max(Execution.attempt_index), 0)).where(Execution.run_id == run_id)
        )
        next_attempt = max_attempt.scalar() + 1

        release = await self.db.execute(select(AgentRelease).where(AgentRelease.id == run.release_id))
        release = release.scalar_one()

        execution = Execution(
            run_id=run_id,
            attempt_index=next_attempt,
            executor_kind=release.runtime_binding.get("runtime_type", "claude_code"),
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()

        run.current_execution_id = execution.id
        run.status = "queued"
        run.ended_at = None
        await self.db.commit()
        await self.db.refresh(run)
        return run
```

- [ ] **Step 2: Refactor ExecutionLifecycleService**

Modify `backend/app/services/execution_lifecycle_service.py` to:
- Accept `run_id` instead of `mission_id` as primary input
- Get runtime config from `AgentRelease.runtime_binding` instead of `AgentProfile`
- Call `ExecutionRunner.run(execution, release, prompt, credentials)` with new signature
- On completion: update `AgentRun.status` and `AgentRun.result_summary`

Key changes:
```python
# In start_execution method:
run = await agent_run_service.get_run(run_id)
release = await db.execute(select(AgentRelease).where(AgentRelease.id == run.release_id))
release = release.scalar_one()

runtime_type = release.runtime_binding.get("runtime_type")
custom_env = release.runtime_binding.get("custom_env", {})
runtime_config = release.runtime_binding.get("runtime_config", {})
```

- [ ] **Step 3: Update ExecutionRunner interface**

In `backend/app/services/execution_runner.py`, change the `run()` method signature:
```python
# Old:
async def run(self, execution: LegacyExecution, prompt: str, credentials: dict)

# New:
async def run(self, execution: Execution, release: AgentRelease, prompt: str, credentials: dict)
```

Source runtime_type and config from `release.runtime_binding` instead of loading `AgentProfile`.

- [ ] **Step 4: Update MissionService dispatch**

In `backend/app/services/mission_service.py`, change `dispatch()` to:
```python
async def dispatch(self, mission_id, user_id):
    mission = await self.get_mission(mission_id)
    agent = await agent_service.get_agent(mission.assignee_id)
    if not agent.active_release_id:
        raise BadRequestException("Agent has no active release")

    run_data = AgentRunCreate(
        release_id=agent.active_release_id,
        mission_id=mission_id,
        trigger_source="mission",
        goal=mission.objective or mission.title,
    )
    run = await agent_run_service.create_run(user_id, run_data)
    await execution_lifecycle_service.start_execution(run.id)
    return run
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_run_service.py backend/app/services/execution_lifecycle_service.py backend/app/services/execution_runner.py backend/app/services/mission_service.py
git commit -m "feat(services): add AgentRunService, refactor execution lifecycle and runner"
```

---

### Task 4.5: API Routes — /runs and /executions (rewrite)

**Files:**
- Create: `backend/app/api/v1/agent_runs.py`
- Rewrite: `backend/app/api/v1/executions.py`
- Modify: `backend/app/api/v1/missions.py` (add /missions/{id}/runs)
- Modify: `backend/app/api/v1/__init__.py`

- [ ] **Step 1: Write /runs routes**

```python
# backend/app/api/v1/agent_runs.py
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.auth import get_current_user
from backend.app.schemas.base import BaseResponse
from backend.app.schemas.agent_run import AgentRunCreate, AgentRunResponse
from backend.app.services.agent_run_service import AgentRunService
from backend.app.services.execution_lifecycle_service import ExecutionLifecycleService

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs(
    workspace_id: uuid.UUID | None = None,
    release_id: uuid.UUID | None = None,
    mission_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    service = AgentRunService(db)
    runs = await service.list_runs(workspace_id=workspace_id, release_id=release_id, mission_id=mission_id)
    return BaseResponse(data=[AgentRunResponse.model_validate(r) for r in runs])


@router.post("")
async def create_run(body: AgentRunCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    run_service = AgentRunService(db)
    run = await run_service.create_run(user.id, body)
    lifecycle = ExecutionLifecycleService(db)
    await lifecycle.start_execution(run.id)
    return BaseResponse(data=AgentRunResponse.model_validate(run))


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    return BaseResponse(data=AgentRunResponse.model_validate(run))


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    service = AgentRunService(db)
    run = await service.cancel_run(run_id)
    return BaseResponse(data=AgentRunResponse.model_validate(run))


@router.post("/{run_id}/retry")
async def retry_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    run_service = AgentRunService(db)
    run = await run_service.retry_run(run_id)
    lifecycle = ExecutionLifecycleService(db)
    await lifecycle.start_execution(run.id)
    return BaseResponse(data=AgentRunResponse.model_validate(run))
```

- [ ] **Step 2: Rewrite /executions routes**

Rewrite `backend/app/api/v1/executions.py` with new model:
- `GET /executions` — list by run_id filter
- `GET /executions/{id}` — detail
- `GET /executions/{id}/events` — event stream
- `POST /executions/{id}/approve` — approve tool call
- `POST /executions/{id}/message` — inject message

- [ ] **Step 3: Add /missions/{id}/runs to missions router**

Add to `backend/app/api/v1/missions.py`:
```python
@router.get("/{mission_id}/runs")
async def list_mission_runs(mission_id: uuid.UUID, db=Depends(get_db), user=Depends(get_current_user)):
    service = AgentRunService(db)
    runs = await service.list_runs(mission_id=mission_id)
    return BaseResponse(data=[AgentRunResponse.model_validate(r) for r in runs])
```

- [ ] **Step 4: Register routes, remove old**

In `backend/app/api/v1/__init__.py`:
- Add `agent_runs_router`
- Remove old `runs_router` (legacy LangGraph)
- Remove `mission_execution_router` (replaced by /runs + /executions)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/agent_runs.py backend/app/api/v1/executions.py backend/app/api/v1/missions.py backend/app/api/v1/__init__.py
git commit -m "feat(api): add /runs routes, rewrite /executions, add /missions/{id}/runs"
```

---

### Task 4.6: Frontend — Run + Execution Services, Hooks, Pages

**Files:**
- Create: `frontend/services/agentRunService.ts`
- Rewrite: `frontend/services/executionService.ts`
- Create: `frontend/hooks/queries/agentRuns.ts`
- Rewrite: `frontend/hooks/queries/executions.ts`
- Create: `frontend/app/runs/page.tsx`
- Create: `frontend/app/runs/[runId]/page.tsx`
- Rewrite: `frontend/app/executions/[executionId]/page.tsx`
- Modify: `frontend/hooks/use-execution-stream.ts` (adapt to new model)
- Modify: `frontend/app/missions/[missionId]/page.tsx` (wire to runs)

- [ ] **Step 1: Write agentRunService.ts**

```typescript
// frontend/services/agentRunService.ts
import { apiGet, apiPost } from "@/lib/api";

export interface AgentRunCreate {
  release_id: string;
  thread_id?: string;
  mission_id?: string;
  trigger_source: "mission" | "chat" | "api" | "scheduler";
  goal?: string;
  input_payload?: Record<string, unknown>;
}

export interface AgentRun {
  id: string; release_id: string; workspace_id: string;
  thread_id: string | null; mission_id: string | null;
  trigger_source: string; goal: string | null;
  input_payload: Record<string, unknown> | null;
  status: string; current_execution_id: string | null;
  result_summary: string | null;
  started_at: string | null; ended_at: string | null;
  created_by: string | null; created_at: string;
}

export const agentRunService = {
  list: (params: { workspace_id?: string; release_id?: string; mission_id?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return apiGet<AgentRun[]>(`/runs?${qs}`);
  },
  get: (runId: string) => apiGet<AgentRun>(`/runs/${runId}`),
  create: (data: AgentRunCreate) => apiPost<AgentRun>("/runs", data),
  cancel: (runId: string) => apiPost<AgentRun>(`/runs/${runId}/cancel`, {}),
  retry: (runId: string) => apiPost<AgentRun>(`/runs/${runId}/retry`, {}),
};
```

- [ ] **Step 2: Write agentRuns.ts hooks**

```typescript
// frontend/hooks/queries/agentRuns.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { agentRunService, AgentRunCreate } from "@/services/agentRunService";

export const runKeys = {
  all: ["runs"] as const,
  list: (params: Record<string, string>) => [...runKeys.all, "list", params] as const,
  detail: (runId: string) => [...runKeys.all, "detail", runId] as const,
};

export function useRuns(params: { workspace_id?: string; release_id?: string; mission_id?: string }) {
  return useQuery({
    queryKey: runKeys.list(params as Record<string, string>),
    queryFn: () => agentRunService.list(params),
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: runKeys.detail(runId),
    queryFn: () => agentRunService.get(runId),
    enabled: !!runId,
  });
}

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AgentRunCreate) => agentRunService.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: runKeys.all }),
  });
}

export function useCancelRun(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => agentRunService.cancel(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  });
}

export function useRetryRun(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => agentRunService.retry(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  });
}
```

- [ ] **Step 3: Rewrite executionService.ts and hooks**

Update `frontend/services/executionService.ts` and `frontend/hooks/queries/executions.ts` to match new API shape (`run_id` instead of `mission_id`, `attempt_index` field, etc).

- [ ] **Step 4: Create Run pages**

- `frontend/app/runs/page.tsx` — global run list with workspace filter
- `frontend/app/runs/[runId]/page.tsx` — run detail showing goal, status, execution stream

- [ ] **Step 5: Update Mission detail to show runs**

In `frontend/app/missions/[missionId]/page.tsx`, replace direct execution stream with a list of AgentRuns for the mission. Each run links to `/runs/{runId}`.

- [ ] **Step 6: Adapt use-execution-stream.ts**

Update `frontend/hooks/use-execution-stream.ts` to work with new execution model (events come from `/ws/executions` with new `execution_id`).

- [ ] **Step 7: Commit**

```bash
git add frontend/services/agentRunService.ts frontend/services/executionService.ts frontend/hooks/queries/agentRuns.ts frontend/hooks/queries/executions.ts frontend/app/runs/ frontend/app/missions/ frontend/hooks/use-execution-stream.ts
git commit -m "feat(frontend): add run service/hooks/pages, rewrite execution layer"
```

---

### Task 4.7: Delete Legacy Run/Execution Code

**Files:**
- Delete: `backend/app/services/run_service.py`
- Delete: `backend/app/api/v1/runs.py` (legacy LangGraph)
- Delete: `backend/app/api/v1/mission_execution.py`
- Delete: `backend/app/services/execution_reducer.py`
- Delete: `frontend/services/runService.ts`
- Delete: `frontend/hooks/queries/runs.ts` (legacy)

- [ ] **Step 1: Delete backend files**

Remove files listed above. Update `__init__.py` to remove router registrations.

- [ ] **Step 2: Delete frontend files**

Remove `frontend/services/runService.ts`, `frontend/hooks/queries/runs.ts`.

- [ ] **Step 3: Search and fix remaining references**

Run: `grep -r "run_service\|RunService\|mission_execution" backend/ --include="*.py" -l`
Run: `grep -r "runService\|from.*runs" frontend/ --include="*.ts" --include="*.tsx" -l`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy run and mission_execution code"
```

---

## Phase 5: Cleanup + Supporting Objects

### Task 5.1: Alembic Migration — Create `artifacts`, Drop Legacy Graph Tables

**Files:**
- Create: `backend/alembic/versions/20260421_000010_create_artifacts.py`
- Create: `backend/alembic/versions/20260421_000011_drop_legacy_graph_tables.py`

- [ ] **Step 1: Write artifacts table migration**

```python
# 20260421_000010_create_artifacts.py
"""create artifacts table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260421_000010"
down_revision = "20260421_000009"

def upgrade():
    op.create_table(
        "artifacts",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

def downgrade():
    op.drop_table("artifacts")
```

- [ ] **Step 2: Write migration to drop legacy graph tables**

```python
# 20260421_000011_drop_legacy_graph_tables.py
"""drop legacy graph tables"""

from alembic import op

revision = "20260421_000011"
down_revision = "20260421_000010"

def upgrade():
    op.drop_table("graph_node_secrets")
    op.drop_table("graph_executions")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("graphs")

def downgrade():
    pass
```

- [ ] **Step 3: Run migrations**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/20260421_0000{10,11}*.py
git commit -m "feat(db): create artifacts table, drop legacy graph tables"
```

---

### Task 5.2: Artifact Model, Schema, Service + Execution Detail Page

**Files:**
- Modify: `backend/app/models/execution.py` (add Artifact class)
- Create: `backend/app/schemas/artifact.py`
- Modify: `backend/app/api/v1/executions.py` (add /artifacts route implementation)
- Modify: `backend/app/models/__init__.py`
- Create: `frontend/app/executions/[executionId]/page.tsx`

- [ ] **Step 1: Add Artifact model**

Append to `backend/app/models/execution.py`:

```python
class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    execution: Mapped["Execution"] = relationship(back_populates="artifacts")
```

Add to Execution class:
```python
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="execution")
```

- [ ] **Step 2: Update `__init__.py`**

Add `Artifact` export.

- [ ] **Step 3: Write Artifact schema**

```python
# backend/app/schemas/artifact.py
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    kind: str
    uri: str
    metadata: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Implement GET /executions/{id}/artifacts in executions.py**

Add to `backend/app/api/v1/executions.py`:
```python
from backend.app.schemas.artifact import ArtifactResponse
from backend.app.models.execution import Artifact

@router.get("/{execution_id}/artifacts")
async def list_artifacts(execution_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(Artifact).where(Artifact.execution_id == execution_id).order_by(Artifact.created_at.asc())
    )
    artifacts = result.scalars().all()
    return BaseResponse(data=[ArtifactResponse.model_validate(a) for a in artifacts])
```

- [ ] **Step 5: Create execution detail page**

Create `frontend/app/executions/[executionId]/page.tsx` — displays execution detail (status, attempt_index, executor_kind, metrics, error info), execution events stream, and artifacts list. Links back to parent run via `run_id`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/execution.py backend/app/models/__init__.py
git commit -m "feat(models): add Artifact model"
```

---

### Task 5.3: Delete Legacy Graph Backend Code

**Files:**
- Delete: `backend/app/models/graph.py`
- Delete: `backend/app/models/graph_execution.py`
- Delete: `backend/app/services/graph_service.py`
- Delete: `backend/app/services/openapi_graph_service.py`
- Delete: `backend/app/api/v1/graphs.py`
- Delete: `backend/app/api/v1/graph_code.py`
- Delete: `backend/app/api/v1/openapi_graph.py`
- Delete: `backend/app/schemas/graph*.py` (if any remain)
- Modify: `backend/app/api/v1/__init__.py` (remove graph routers)
- Modify: `backend/app/models/__init__.py` (remove graph model imports)

- [ ] **Step 1: Delete all graph-related backend files**

- [ ] **Step 2: Clean up imports and router registrations**

Remove from `__init__.py` files:
- `graphs_router`, `graph_code_router`, `graph_deployments_router`, `openapi_graph_router`
- `AgentGraph`, `GraphNode`, `GraphEdge`, `GraphNodeSecret`, `GraphExecution` imports

- [ ] **Step 3: Search for remaining references**

Run: `grep -r "graph_service\|GraphService\|AgentGraph\|graph_code\|graph_deployment" backend/ --include="*.py" -l`

Fix any remaining imports in services that reference graph objects (e.g., `copilot_service.py` may reference graph execution).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: delete all legacy graph backend code"
```

---

### Task 5.4: Delete Legacy Frontend Code (Graph, Chat, Old Hooks)

**Important:** Do NOT delete `frontend/app/runs/` — Phase 4 already rewrote it in-place with new content. Only delete files that are truly legacy and have not been rewritten.

**Files:**
- Delete: `frontend/app/chat/` (entire directory — absorbed into agents/[agentId]/threads/)
- Delete: `frontend/services/chatBackend.ts` (replaced by threadService.ts)
- Delete: `frontend/hooks/queries/graphs.ts`
- Delete: `frontend/hooks/use-skill-creator-run.ts` (if graph-dependent)
- Modify: `frontend/components/` — remove graph-specific components no longer used at top level

- [ ] **Step 1: Delete old route directories**

Remove `frontend/app/chat/` and verify `frontend/app/agents/[agentId]/threads/` exists as replacement.

- [ ] **Step 2: Delete old services**

Remove `frontend/services/chatBackend.ts`.

- [ ] **Step 3: Delete old hooks**

Remove `frontend/hooks/queries/graphs.ts`.

- [ ] **Step 4: Search for remaining dead references**

Run: `grep -r "chatBackend\|graphService\|from.*graphs\|/chat" frontend/ --include="*.ts" --include="*.tsx" -l`

Fix any remaining imports.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy chat, graph, and old runs frontend code"
```

---

### Task 5.5: WebSocket Endpoint Cleanup

**Files:**
- Modify: `backend/app/main.py` or wherever WS routes are registered
- Delete or rename: `/ws/chat` → refactor to `/ws/threads/{threadId}`
- Delete: `/ws/runs` (legacy LangGraph run stream)
- Preserve: `/ws/executions` (adapt to new model)

- [ ] **Step 1: Remove /ws/runs registration**

- [ ] **Step 2: Refactor /ws/chat to /ws/threads/{threadId}**

Update the WebSocket handler to accept `thread_id` in the URL, send/receive messages against the new `threads`/`messages` tables.

- [ ] **Step 3: Verify /ws/executions works with new execution model**

The existing execution WS handler should query the new `executions` and `execution_events` tables. Update any references to old column names.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: clean up WebSocket endpoints for new model"
```

---

### Task 5.6: Sidebar Navigation Update

**Files:**
- Modify: `frontend/components/` (sidebar/navigation component)

- [ ] **Step 1: Update navigation links**

Replace:
- "Agents" → `/agents` (already correct)
- "Chat" → remove (absorbed into agents)
- "Runs" → `/runs` (new global view)
- "Missions" → `/missions` (preserved)

Add:
- Agent detail sub-navigation: Overview | Edit | Versions | Releases | Threads | Runs

- [ ] **Step 2: Commit**

```bash
git add frontend/components/
git commit -m "refactor: update sidebar navigation for new domain model"
```

---

### Task 5.7: Final Cleanup Sweep

- [ ] **Step 1: Full grep for any remaining legacy references**

```bash
grep -r "agent_profile\|AgentProfile\|agentProfile" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" -l
grep -r "graph_deployment\|GraphDeployment" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" -l
grep -r "copilot_chat\|CopilotChat" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" -l
```

- [ ] **Step 2: Verify all new tables exist**

Run: `cd backend && alembic upgrade head && alembic current`

- [ ] **Step 3: Verify backend starts**

Run: `cd backend && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
Expected: No import errors, `/docs` shows all new routes.

- [ ] **Step 4: Verify frontend builds**

Run: `cd frontend && bun run build`
Expected: Build succeeds with no type errors.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup sweep for greenfield refactoring"
```

---

## Validation Checklist

After all phases are complete, verify against the spec's acceptance criteria:

- [ ] **AC1:** Every user-facing entry path starts from an Agent — check all frontend routes start from `/agents`
- [ ] **AC2:** Every runnable target resolves through an AgentRelease — check `AgentRunService.create_run` requires `release_id`
- [ ] **AC3:** Every task is represented by an AgentRun — check `/runs` API and Mission dispatch both create `AgentRun`
- [ ] **AC4:** Every retry or branch is a distinct Execution — check `retry_run` creates new `Execution` with incremented `attempt_index`
- [ ] **AC5:** Frontend never needs runtime/graph identifiers — grep frontend for `graph_id`, `runtime_session`, `container_id`
- [ ] **AC6:** Database write model is normalized — no cross-layer IDs (no `agent_id` on `executions`, no `workspace_id` on `executions`)
- [ ] **AC7:** API expansions don't change write-model ownership — verify `GET /runs/{id}` expansion uses joins, not stored fields
- [ ] **AC8:** LangGraph/Canvas = definition_kind: graph — verify `agent_versions.definition_kind` supports `graph` and GraphEditor component loads
- [ ] **AC9:** Mission Kanban functional — verify mission board loads, dispatch creates AgentRun, status updates flow through
- [ ] **AC10:** All legacy tables deleted — verify: `agent_profiles`, `graphs`, `graph_nodes`, `graph_edges`, `graph_node_secrets`, `graph_deployment_version`, `graph_executions`, `conversations`, old `agent_runs`, old `executions` are all gone

## Cross-Reference Matrix

| Spec Entity | DB Table | Model File | Schema File | Service File | API Route File | Frontend Service | Frontend Hook | Frontend Page |
|---|---|---|---|---|---|---|---|---|
| Agent | agents | models/agent.py | schemas/agent.py | services/agent_service.py | api/v1/agents.py | agentService.ts | queries/agents.ts | app/agents/ |
| AgentVersion | agent_versions | models/agent.py | schemas/agent_version.py | services/agent_version_service.py | api/v1/agents.py | agentVersionService.ts | queries/agentVersions.ts | app/agents/[id]/edit, /versions |
| AgentRelease | agent_releases | models/agent.py | schemas/agent_release.py | services/agent_release_service.py | api/v1/agents.py | agentReleaseService.ts | queries/agentReleases.ts | app/agents/[id]/releases |
| Thread | threads | models/thread.py | schemas/thread.py | services/thread_service.py | api/v1/threads.py | threadService.ts | queries/threads.ts | app/agents/[id]/threads |
| Message | messages | models/thread.py | schemas/thread.py | services/thread_service.py | api/v1/threads.py | threadService.ts | queries/threads.ts | app/agents/[id]/threads/[id] |
| AgentRun | agent_runs | models/agent_run.py | schemas/agent_run.py | services/agent_run_service.py | api/v1/agent_runs.py | agentRunService.ts | queries/agentRuns.ts | app/runs/ |
| Execution | executions | models/execution.py | schemas/execution.py | services/execution_lifecycle_service.py | api/v1/executions.py | executionService.ts | queries/executions.ts | app/runs/[id] |
| ExecutionEvent | execution_events | models/execution.py | schemas/execution.py | services/execution_lifecycle_service.py | api/v1/executions.py | executionService.ts | use-execution-stream.ts | app/runs/[id] |
| Artifact | artifacts | models/execution.py | schemas/artifact.py | inline query in API | api/v1/executions.py | executionService.ts | queries/executions.ts | app/executions/[id] |
