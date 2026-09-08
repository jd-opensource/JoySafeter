"""Quickstart transport endpoints.

The application layer owns recommendation orchestration. This module validates
HTTP input and translates the design stream to the SSE transport contract.
"""

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import credential_audit_actor
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAccessContext
from app.joysafeter_application.quickstart import (
    compose_quickstart_application,
    compose_quickstart_design_application,
)
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.compatibility import validate_credential_data
from app.joysafeter_domain.llm.model_inference_policy import (
    ModelInferenceMaterialFieldMissingError,
    build_model_inference_policy,
)
from app.joysafeter_domain.quickstart import QuickstartPhase
from app.joysafeter_domain.schemas.joysafeter_quickstart import (
    QuickstartAgentContext,
    QuickstartRecommendation,
)
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    require_joysafeter_read,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialId, SkillId
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url
from app.joysafeter_shared.llm.model_stream import stream_model

router = APIRouter(tags=["joysafeter-quickstart"])


class QuickstartMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=50000)


class QuickstartAvailableSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: SkillId
    name: str = Field(..., min_length=1, max_length=200)
    display_title: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=1000)
    latest_version: str = Field(..., min_length=1, max_length=100)


class QuickstartChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[QuickstartMessage] = Field(..., max_length=50)
    phase: Literal[QuickstartPhase.DESIGN] = QuickstartPhase.DESIGN
    engine_kind: Literal["claude", "claude_code", "codex", "native", "pi"]
    model_credential_id: CredentialId
    agent_context: Optional[QuickstartAgentContext] = None
    available_skills: list[QuickstartAvailableSkill] = Field(default_factory=list, max_length=20)


_design_service = compose_quickstart_design_application()


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _quickstart_base_url_error(exc: LLMBaseUrlError, *, provider: str) -> InvalidRequestError:
    data = {"provider": provider, "key": exc.key, "base_url": exc.base_url}
    if exc.host:
        data["host"] = exc.host
    if exc.reason == "not_allowed":
        return InvalidRequestError(
            code="QUICKSTART_BASE_URL_NOT_ALLOWED",
            message=f"{exc.key} host is not allowlisted.",
            data=data,
            user_action="fix_input",
        )
    return InvalidRequestError(
        code="QUICKSTART_BASE_URL_INVALID",
        message=f"Invalid {exc.key}",
        data=data,
        user_action="fix_input",
    )


@router.post("/chat")
async def quickstart_chat(
    req: QuickstartChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    actor = credential_audit_actor(request, auth_ctx)
    application = compose_credential_application(
        db,
        auto_commit=False,
        audit_actor=actor,
    )
    try:
        binding = build_model_inference_policy(
            get_llm_catalog(),
            project_id=auth_ctx.project_id,
            credential_id=req.model_credential_id,
            engine_kind=req.engine_kind,
            model_id=req.agent_context.model_id if req.agent_context is not None else None,
        )
        material, resolution = await application.material_access_service.resolve_model_inference(
            binding,
            context=CredentialAccessContext(
                consumer_type="quickstart_chat",
                consumer_id="quickstart",
                actor=actor,
            ),
        )
    except ModelInferenceMaterialFieldMissingError as exc:
        validate_credential_data(
            exc.provider_id,
            exc.protocol_id,
            {},
        )
        raise AssertionError("Catalog profile with missing required material must fail validation") from exc
    except Exception as exc:
        raise_public_credential_error(
            exc,
            credential_id=req.model_credential_id,
            data={"engine_kind": req.engine_kind},
            not_found_user_action="fix_input",
        )
    data = {str(field_name): value for field_name, value in material.fields.items()}
    provider = resolution.provider_id
    protocol = resolution.protocol_id
    validate_credential_data(provider, protocol, data)
    base_url_key = resolution.base_url_key or "BASE_URL"
    base_url = data.get(base_url_key) or resolution.default_base_url
    if not base_url:
        raise InvalidRequestError(
            code="QUICKSTART_BASE_URL_REQUIRED",
            message=f"{base_url_key} is required for this provider",
            data={"provider": provider, "protocol": protocol, "key": base_url_key},
            user_action="fix_input",
        )
    try:
        base_url = validate_llm_base_url(base_url, key=base_url_key)
    except LLMBaseUrlError as exc:
        raise _quickstart_base_url_error(exc, provider=provider) from None
    model = data.get(resolution.model_key) if resolution.model_key else None
    if not model:
        raise InvalidRequestError(
            code="QUICKSTART_MODEL_REQUIRED",
            message=f"{resolution.model_key or 'model'} is required for this provider",
            data={"provider": provider, "protocol": protocol, "key": resolution.model_key},
            user_action="fix_input",
        )

    system_prompt = _design_service.build_system_prompt(
        agent_context=(req.agent_context.model_dump(mode="json", exclude_none=True) if req.agent_context else None),
        available_skills=[skill.model_dump() for skill in req.available_skills],
    )
    tools = _design_service.build_tools()

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    if protocol == "anthropic_messages":
        auth_token = data.get("ANTHROPIC_AUTH_TOKEN") or ""
        api_key = auth_token or data.get("ANTHROPIC_API_KEY") or ""
        bearer_token = bool(auth_token)
    elif protocol in {"openai_responses", "chat_completions"}:
        api_key = data.get("OPENAI_API_KEY") or ""
        bearer_token = False
    else:
        raise InvalidRequestError(
            code="QUICKSTART_PROTOCOL_UNSUPPORTED",
            message=f"Quickstart does not support protocol '{protocol}'",
            data={"provider": provider, "protocol": protocol},
            user_action="fix_input",
        )

    async def event_generator():
        events = stream_model(
            protocol=protocol,
            base_url=base_url,
            api_key=api_key,
            bearer_token=bearer_token,
            model=model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            force_tool_name=str(tools[0]["name"]),
            max_tokens=4096,
        )
        async for event in _design_service.stream_events(events):
            yield _sse_event(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class QuickstartRecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal[QuickstartPhase.UNDERSTAND, QuickstartPhase.SECURE]
    intent: str = Field(default="", max_length=50000)
    agent_context: Optional[QuickstartAgentContext] = None


@router.post("/recommendations")
async def quickstart_recommendations(
    req: QuickstartRecommendRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_read),
) -> QuickstartRecommendation:
    """Rules-first quickstart recommendations (synchronous, read-only).

    Additive: creates no resources and does not touch the SSE ``/chat`` flow. The
    ``understand`` phase ranks catalog engines against the project's model
    connections; ``secure`` deterministically derives sandbox/allowlist and
    credential-bearing external-tool suggestions from the intent and Agent draft.
    """
    if auth_ctx.project_id is None:
        raise InvalidRequestError(
            code="PROJECT_SCOPE_REQUIRED",
            message="Quickstart recommendations require a project scope",
            user_action="select_project",
        )
    service = compose_quickstart_application(
        db,
        audit_actor=credential_audit_actor(None, auth_ctx),
    )
    agent_config = req.agent_context.model_dump(mode="json", exclude_none=True) if req.agent_context else None
    return await service.recommend(
        phase=QuickstartPhase(req.phase),
        project_id=auth_ctx.project_id,
        intent_text=req.intent,
        agent_config=agent_config,
    )
