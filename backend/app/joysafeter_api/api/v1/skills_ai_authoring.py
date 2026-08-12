"""AI-assisted skill authoring endpoints.

Two routes, both mounted under ``/api/v1/skills/ai-authoring/`` (the parent
``skills`` router prefixes ``/skills`` so the final paths are
``/api/v1/skills/ai-authoring/chat`` and ``.../save-draft``).

* ``POST /chat`` — SSE stream. The client sends the running conversation +
  current right-side draft, the server resolves OPENAI_* keys from a user-
  named secret (same pattern as ``quickstart.py``), and streams back
  ``text_delta`` / ``draft_patch`` / ``done`` / ``error`` events for the
  workspace UI to consume.

* ``POST /save-draft`` — Idempotent create-or-update of a real
  ``lifecycle_status='draft'`` skill row so the user can resume across
  devices and so the ``security-scans/rescan`` button has a skill_id to
  hit. localStorage holds the working state between saves.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.compatibility import (
    LlmCompatibilityError,
    validate_credential_data,
    validate_provider_protocol,
)
from app.joysafeter_domain.schemas.joysafeter_credential import CredentialKind
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_domain.services.joysafeter_skill_authoring import (
    stream_authoring_chat,
)
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialId, SkillId
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["skill-ai-authoring"])


def _authoring_base_url_error(exc: LLMBaseUrlError, *, credential_id: str) -> InvalidRequestError:
    data = {"credential_id": credential_id, "key": exc.key, "base_url": exc.base_url}
    if exc.host:
        data["host"] = exc.host
    if exc.reason == "not_allowed":
        return InvalidRequestError(
            code="SKILL_AUTHORING_BASE_URL_NOT_ALLOWED",
            message=f"{exc.key} host is not allowlisted.",
            data=data,
            user_action="fix_input",
        )
    return InvalidRequestError(
        code="SKILL_AUTHORING_BASE_URL_INVALID",
        message=f"Invalid {exc.key}.",
        data=data,
        user_action="fix_input",
    )


# ── Schemas ────────────────────────────────────────────────────────────────


class AuthoringMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str


class AuthoringDraft(BaseModel):
    """Right-side preview state, kept in sync between client and LLM."""

    name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    visibility: Optional[str] = None
    content: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)


class AuthoringChatRequest(BaseModel):
    model_credential_id: CredentialId = Field(..., description="Model credential holding OPENAI_*.")
    messages: list[AuthoringMessage] = Field(..., max_length=50)
    draft: Optional[AuthoringDraft] = None


class SaveDraftRequest(BaseModel):
    """Create-or-update a draft skill row. Idempotent on ``draft_skill_id``."""

    draft_skill_id: Optional[SkillId] = None
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    visibility: Optional[str] = None
    files: list[dict[str, Any]] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────


def _sse(event: dict[str, Any]) -> str:
    """Wire-format a single SSE event.

    Critical: the JSON payload MUST NOT contain raw newline characters,
    because SSE delimits events by ``\\n\\n`` and individual ``data:`` lines
    by ``\\n``. A draft_patch event can carry an entire SKILL.md body in its
    ``content`` field — that markdown is full of real newlines. If we let
    those leak into the wire, the frontend's line-based parser splits a
    single event into many fragments and JSON.parse fails on every one.

    ``json.dumps`` with the default settings escapes ``\\n`` → ``\\\\n`` in the
    string value, which is exactly what we need. We belt-and-suspenders
    also strip any stray carriage returns from the wire body.
    """
    payload = json.dumps(event, ensure_ascii=False)
    # Defensive: collapse any leftover newlines (shouldn't happen with the
    # default json.dumps, but a future formatter change must not silently
    # break the stream).
    payload = payload.replace("\r", "").replace("\n", "\\n")
    return f"data: {payload}\n\n"


# Map a file extension to the ``file_type`` label the skill store uses.
_EXT_TO_TYPE = {
    "py": "python",
    "md": "markdown",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "sh": "shell",
    "js": "javascript",
    "ts": "typescript",
}


def _normalize_draft_files(raw_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split the authoring draft's ``{path, content}`` items into the
    ``{path, file_name, file_type, content}`` shape the skill store expects.

    The AI workspace models each file as a single POSIX ``path`` string
    (e.g. ``references/tools.md``) with the whole path in one field. The
    skill store, however, stores ``path`` as the *directory* (``references/``)
    and ``file_name`` separately (``tools.md``). Passing the draft rows
    through verbatim made ``file_name`` empty and the full path land in
    ``path`` — so the file tree rendered every file as a folder containing a
    single 0-byte blank-named child. Normalize here so a saved draft reads
    back with the same structure the user built.
    """
    normalized: list[dict[str, Any]] = []
    for f in raw_files:
        if not isinstance(f, dict):
            continue
        raw_path = str(f.get("path") or "").replace("\\", "/").lstrip("/")
        if not raw_path:
            continue
        # Skip folder placeholders (``references/.gitkeep``) — the store
        # materializes directories from real files' paths.
        slash = raw_path.rfind("/")
        directory = raw_path[: slash + 1] if slash >= 0 else ""
        file_name = raw_path[slash + 1 :] if slash >= 0 else raw_path
        if not file_name or file_name == ".gitkeep":
            continue
        # Root SKILL.md is carried by the skill's ``content`` field, not the
        # files list — skip it here to avoid a duplicate row.
        if not directory and file_name.lower() == "skill.md":
            continue
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        normalized.append(
            {
                "path": directory,
                "file_name": file_name,
                "file_type": _EXT_TO_TYPE.get(ext, "text"),
                "content": f.get("content") or "",
            }
        )
    return normalized


async def _dedupe_skill_name(svc: SkillService, name: str, project_id: str) -> str:
    """Return ``name`` if the project has no skill by that name, else the first
    free ``name-2`` / ``name-3`` / … variant.

    Skill names are unique per ``(project_id, name)`` (not global), so the only
    possible collision is with another skill in the same project. We keep the
    first save clean and only add a numeric suffix when the base name is taken —
    so a repeated ``auto-daily-report`` becomes ``auto-daily-report-2``.
    The 64-char ``name`` cap is respected by trimming the base before the
    suffix when necessary.
    """
    if not await svc.repo.get_by_name_and_project(name, project_id):
        return name
    # Probe -2, -3, … until one is free. Capped so a pathological loop can't
    # run forever; 999 variants is far beyond any real usage.
    for n in range(2, 1000):
        suffix = f"-{n}"
        base = name[: 64 - len(suffix)]
        candidate = f"{base}{suffix}"
        if not await svc.repo.get_by_name_and_project(candidate, project_id):
            return candidate
    return name


# ── /chat (SSE) ────────────────────────────────────────────────────────────


@router.post("/chat")
async def authoring_chat(
    req: AuthoringChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    """Stream one authoring turn against the configured LLM.

    Credentials live in a JoySafeter model credential (multi-tenant) — same
    shape ``quickstart.py`` uses: ``OPENAI_API_KEY`` (required), ``OPENAI_BASE_URL``
    (optional, defaults to api.openai.com), ``OPENAI_MODEL`` (optional,
    defaults to ``gpt-5.5``).
    """
    svc = CredentialService(db)
    cred = await svc.get(req.model_credential_id, project_id=auth_ctx.project_id)
    if not cred:
        raise NotFoundError(
            code="CREDENTIAL_NOT_FOUND",
            message="Credential not found.",
            data={"credential_id": str(req.model_credential_id)},
            user_action="fix_input",
        )
    if (
        cred.kind != CredentialKind.MODEL.value
        or not cred.provider
        or cred.protocol != "openai_responses"
    ):
        raise InvalidRequestError(
            code="SKILL_AUTHORING_SECRET_INCOMPATIBLE",
            message="Skill authoring requires an OpenAI Responses compatible model configuration.",
            data={
                "credential_id": str(req.model_credential_id),
                "kind": cred.kind,
                "provider": cred.provider,
                "protocol": cred.protocol,
                "required_protocol": "openai_responses",
            },
            user_action="fix_input",
        )
    try:
        binding = validate_provider_protocol(cred.provider, cred.protocol)
        data = svc.get_credential_data(cred)
        validate_credential_data(cred.provider, cred.protocol, data)
    except LlmCompatibilityError as exc:
        if exc.code == "LLM_SECRET_CREDENTIALS_INCOMPLETE" and exc.data.get(
            "required_fields"
        ) == ["OPENAI_API_KEY"]:
            raise InvalidRequestError(
                code="SKILL_AUTHORING_SECRET_MISSING_KEY",
                message="Credential missing OPENAI_API_KEY.",
                data={"credential_id": str(req.model_credential_id), "required_key": "OPENAI_API_KEY"},
                user_action="fix_input",
            ) from exc
        raise InvalidRequestError(
            code="SKILL_AUTHORING_SECRET_INCOMPATIBLE",
            message="Skill authoring model configuration is invalid.",
            data={
                "credential_id": str(req.model_credential_id),
                "provider": cred.provider,
                "protocol": cred.protocol,
            },
            user_action="fix_input",
        ) from exc
    profile = get_llm_catalog().credential_profile(binding.credential_profile_id)
    api_key = data.get("OPENAI_API_KEY") or ""
    base_url_key = profile.base_url_key or "BASE_URL"
    base_url = data.get(base_url_key) or binding.default_base_url
    if not base_url:
        raise InvalidRequestError(
            code="SKILL_AUTHORING_BASE_URL_REQUIRED",
            message=f"{base_url_key} is required for skill authoring.",
            data={"credential_id": str(req.model_credential_id), "key": base_url_key},
            user_action="fix_input",
        )
    try:
        base_url = validate_llm_base_url(base_url, key=base_url_key)
    except LLMBaseUrlError as exc:
        raise _authoring_base_url_error(exc, credential_id=str(req.model_credential_id)) from None
    model = data.get(profile.model_key) if profile.model_key else None
    model = model or "gpt-5.5"

    history = [m.model_dump() for m in req.messages]
    draft_dict = req.draft.model_dump() if req.draft else None

    async def _gen():
        async for event in stream_authoring_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=history,
            draft=draft_dict,
        ):
            yield _sse(event)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            # Disable proxy buffering so the user sees tokens as they arrive.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ── /save-draft ────────────────────────────────────────────────────────────


@router.post("/save-draft")
async def authoring_save_draft(
    req: SaveDraftRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    """Persist the workspace state as a real draft skill row.

    Creates a fresh skill on first save; subsequent saves with the same
    ``draft_skill_id`` update name/description/content/tags. The skill is
    born with ``lifecycle_status='draft'`` (set inside ``create_skill``),
    so it's invisible to agents until the user explicitly submits it.

    The frontend stores the returned ``skill_id`` in localStorage and
    threads it back on subsequent saves. Files are persisted via the
    existing ``update_skill`` ``files`` path (one shot, replace-all).
    """
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    files = _normalize_draft_files(req.files)

    if req.draft_skill_id:
        try:
            skill = await svc.update_skill(
                req.draft_skill_id,
                current_user_id=auth_ctx.user_id,
                name=req.name,
                description=req.description,
                content=req.content,
                tags=req.tags,
                files=files or None,
            )
        except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
            raise e
        except IntegrityError:
            await db.rollback()
            raise ResourceConflictError(
                f"技能名「{req.name}」已被占用，请换一个名称。",
                code="SKILL_NAME_ALREADY_EXISTS",
            ) from None
        return {"skill_id": str(skill.id), "created": False}

    # Only-when-taken suffix: keep the first save clean, auto-bump to
    # ``name-2`` / ``-3`` only if the project already has that name. Prevents
    # the duplicate-name 500 without uglifying every new skill.
    unique_name = await _dedupe_skill_name(svc, req.name, auth_ctx.project_id)
    try:
        skill = await svc.create_skill(
            created_by_id=auth_ctx.user_id,
            name=unique_name,
            description=req.description,
            content=req.content,
            tags=req.tags or None,
            source_type="ai_authoring",
            files=files or None,
            project_id=auth_ctx.project_id,
        )
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        raise e
    except IntegrityError:
        # Backstop: a race (two saves in flight) or a frontmatter-overridden
        # name that dodged the dedup probe can still trip the DB's
        # ``(owner_id, name)`` unique constraint. Translate to a friendly
        # error instead of a 500; the session must be rolled back first.
        await db.rollback()
        raise ResourceConflictError(
            f"技能名「{unique_name}」已存在，请换一个名称，或回到该草稿继续编辑。",
            code="SKILL_NAME_ALREADY_EXISTS",
        ) from None
    return {"skill_id": str(skill.id), "created": True}
