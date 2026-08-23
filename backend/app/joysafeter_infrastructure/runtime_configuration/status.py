from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.credentials.dependencies import CredentialImpact
from app.joysafeter_domain.credentials.references import CredentialReferenceCodec
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.ids import SandboxId, SessionId
from app.joysafeter_shared.utils.datetime import utc_now

_REFERENCE_CODEC = CredentialReferenceCodec()
_LIVE_SANDBOX_STATUSES = ("creating", "provisioning", "idle", "running")


def _snapshot_environment_refs(snapshot: object) -> frozenset[str]:
    if not isinstance(snapshot, Mapping):
        return frozenset()
    environment = snapshot.get("environment")
    if not isinstance(environment, Mapping):
        return frozenset()
    return frozenset(
        str(value).strip()
        for key in ("id", "ref", "name")
        if (value := environment.get(key)) is not None and str(value).strip()
    )


async def _active_environments(
    db: AsyncSession,
    impact: CredentialImpact,
) -> list[tuple[str, str, object]]:
    rows = await db.execute(
        select(
            JoySafeterEnvironment.id,
            JoySafeterEnvironment.name,
            JoySafeterEnvironment.config,
        ).where(
            JoySafeterEnvironment.project_id == str(impact.project_id),
            JoySafeterEnvironment.deleted_at.is_(None),
            JoySafeterEnvironment.archived_at.is_(None),
        )
    )
    return [(str(environment_id), name, config) for environment_id, name, config in rows.all()]


def _session_matches_environment(
    session: JoySafeterSession,
    *,
    environment_refs: frozenset[str],
) -> bool:
    explicit_ref = (session.environment_ref or "").strip()
    if explicit_ref:
        return explicit_ref in environment_refs
    return bool(_snapshot_environment_refs(session.agent_snapshot) & environment_refs)


def _snapshot_references_direct_credential(snapshot: object, cred_id_str: str) -> bool:
    if snapshot is None:
        return False
    return any(
        str(candidate) == cred_id_str
        for candidate in _REFERENCE_CODEC.decode_snapshot(snapshot).environment_credential_ids
    )


async def _affected_session_ids(db: AsyncSession, impact: CredentialImpact) -> list[SessionId]:
    environments = await _active_environments(db, impact)
    if impact.source == "environment":
        environment_refs = frozenset(
            value
            for environment_id, environment_name, _config in environments
            if environment_id == impact.source_id
            for value in (environment_id, environment_name)
        )
        if not environment_refs:
            return []

        def is_affected(session: JoySafeterSession) -> bool:
            return _session_matches_environment(session, environment_refs=environment_refs)

    elif impact.source == "credential":
        credential_id = impact.source_id or ""
        environment_refs = frozenset(
            value
            for environment_id, environment_name, config in environments
            if any(
                str(candidate) == credential_id
                for candidate in _REFERENCE_CODEC.decode_environment(config).direct_credential_ids
            )
            for value in (environment_id, environment_name)
        )

        def is_affected(session: JoySafeterSession) -> bool:
            explicit_ref = (session.environment_ref or "").strip()
            if explicit_ref:
                return explicit_ref in environment_refs
            return _snapshot_references_direct_credential(session.agent_snapshot, credential_id)

    else:
        raise ValueError(f"unsupported runtime configuration impact source: {impact.source}")

    candidates = list(
        (
            await db.execute(
                select(JoySafeterSession).where(
                    JoySafeterSession.project_id == str(impact.project_id),
                    JoySafeterSession.archived_at.is_(None),
                    JoySafeterSession.status != "terminated",
                )
            )
        )
        .scalars()
        .all()
    )
    candidate_ids = sorted((session.id for session in candidates if is_affected(session)), key=str)
    if not candidate_ids:
        return []
    locked = list(
        (
            await db.execute(
                select(JoySafeterSession)
                .where(
                    JoySafeterSession.id.in_(candidate_ids),
                    JoySafeterSession.project_id == str(impact.project_id),
                    JoySafeterSession.archived_at.is_(None),
                    JoySafeterSession.status != "terminated",
                )
                .order_by(JoySafeterSession.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    return [
        session.id
        for session in locked
        if session.archived_at is None and session.status != "terminated" and is_affected(session)
    ]


async def mark_live_sandboxes_restart_required(
    db: AsyncSession,
    impact: CredentialImpact,
    *,
    already_advanced_session_ids: frozenset[str] = frozenset(),
) -> tuple[list[SessionId], list[SandboxId]]:
    if impact.source_id is None:
        raise ValueError("credential impact source_id is required")
    session_ids = await _affected_session_ids(db, impact)
    if not session_ids:
        return [], []
    session_ids_to_advance = [
        session_id for session_id in session_ids if str(session_id) not in already_advanced_session_ids
    ]
    changed_at = utc_now()
    if session_ids_to_advance:
        await db.execute(
            update(JoySafeterSession)
            .where(JoySafeterSession.id.in_(session_ids_to_advance))
            .values(
                runtime_config_generation=JoySafeterSession.runtime_config_generation + 1,
                runtime_config_generation_reason=impact.reason or "credential_changed",
                runtime_config_generation_updated_at=changed_at,
            )
            .execution_options(synchronize_session=False)
        )
    marked = await db.execute(
        update(JoySafeterSandbox)
        .where(
            JoySafeterSandbox.project_id == str(impact.project_id),
            JoySafeterSandbox.chat_session_id.in_(session_ids),
            JoySafeterSandbox.destroyed_at.is_(None),
            JoySafeterSandbox.status.in_(_LIVE_SANDBOX_STATUSES),
        )
        .values(
            runtime_config_status="restart_required",
            runtime_config_last_reason=impact.reason or "credential_changed",
            runtime_config_required_at=changed_at,
        )
        .returning(JoySafeterSandbox.id)
        .execution_options(synchronize_session=False)
    )
    return session_ids, [row[0] for row in marked.all()]
