import uuid
from typing import Optional

from sqlalchemy import and_, delete, or_, outerjoin, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.security.credential_cipher import CredentialCipher
from app.joysafeter_shared.utils.datetime import utc_now

MASKED_SECRET_PREFIX = "********"

_cipher: Optional[CredentialCipher] = None


def _get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        from app.joysafeter_shared.config.settings import joysafeter_config

        _cipher = CredentialCipher(joysafeter_config.vault_encryption_key)
    return _cipher


def _is_display_safe_secret_key(key: str) -> bool:
    """Whether a secret key's value is safe to reveal in a masked response.

    Default-deny: only a small allowlist of non-sensitive config keys (base_url /
    model / provider / region / ...) is shown in cleartext. Every other key —
    including unconventionally-named secrets like CONNECTION_STRING or DSN — is
    masked, so a project reader can never read raw secret material via GET/list.
    """
    normalized = key.upper()
    return normalized in _DISPLAY_SAFE_SECRET_KEYS or normalized.endswith(_DISPLAY_SAFE_SECRET_SUFFIXES)


_DISPLAY_SAFE_SECRET_KEYS = frozenset(
    {"PROVIDER", "PROTOCOL", "MODEL", "BASE_URL", "REGION", "ENDPOINT", "API_VERSION", "VERSION"}
)
_DISPLAY_SAFE_SECRET_SUFFIXES = (
    "_BASE_URL",
    "_MODEL",
    "_PROVIDER",
    "_PROTOCOL",
    "_REGION",
    "_ENDPOINT",
    "_API_VERSION",
    "_VERSION",
)


def _mask_secret_value(value: str) -> str:
    if not value:
        return ""
    suffix = value[-4:] if len(value) > 4 else ""
    return f"{MASKED_SECRET_PREFIX}{suffix}"


def _secret_ref_matches(secret_ref: object, name: str) -> bool:
    return str(secret_ref).strip() == name if secret_ref is not None else False


def _environment_secret_refs(config: object) -> list[str]:
    if not isinstance(config, dict):
        return []
    refs = config.get("secret_refs")
    if not isinstance(refs, list):
        return []
    return [str(ref).strip() for ref in refs if str(ref).strip()]


class SecretService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

    def encrypt_data_for_storage(self, data: dict[str, str] | None) -> dict[str, str]:
        encrypted: dict[str, str] = {}
        for key, value in (data or {}).items():
            encrypted[str(key)] = self._cipher.encrypt(str(value))
        return encrypted

    def decrypt_data(self, data: dict | None) -> dict[str, str]:
        decrypted: dict[str, str] = {}
        for key, value in (data or {}).items():
            decrypted[str(key)] = self._cipher.decrypt_stored(str(value))
        return decrypted

    def get_secret_data(self, secret: JoySafeterSecret | None) -> dict[str, str]:
        if not secret:
            return {}
        return self.decrypt_data(secret.data or {})

    def get_masked_secret_data(self, secret: JoySafeterSecret | None) -> dict[str, str]:
        data = self.get_secret_data(secret)
        return {
            key: value if _is_display_safe_secret_key(key) else _mask_secret_value(value) for key, value in data.items()
        }

    @staticmethod
    def apply_provider_aliases(env: dict[str, str]) -> dict[str, str]:
        if "ANTHROPIC_AUTH_TOKEN" in env and "ANTHROPIC_API_KEY" not in env:
            env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]
        return env

    async def merge_secret_refs_into_env(
        self,
        env: dict[str, str],
        secret_refs: list[str] | tuple[str, ...] | None,
        project_id: Optional[str] = None,
        *,
        override: bool = False,
    ) -> dict[str, str]:
        merged = {str(k): str(v) for k, v in (env or {}).items()}
        for secret_ref in secret_refs or []:
            ref = str(secret_ref).strip()
            if not ref:
                continue
            secret = await self.get_secret_by_name(ref, project_id=project_id)
            secret_data = self.get_secret_data(secret)
            for key, value in secret_data.items():
                key_str = str(key)
                if override or key_str not in merged:
                    merged[key_str] = str(value)
        return self.apply_provider_aliases(merged)

    def merge_update_data_for_storage(
        self,
        current_data: dict | None,
        requested_data: dict[str, str] | None,
    ) -> dict[str, str]:
        """Encrypt update payload while preserving unchanged masked sensitive values."""
        existing_plain = self.decrypt_data(current_data or {})
        existing_stored = {str(k): str(v) for k, v in (current_data or {}).items()}
        next_data: dict[str, str] = {}
        for key, value in (requested_data or {}).items():
            key_str = str(key)
            value_str = str(value)
            if (
                not _is_display_safe_secret_key(key_str)
                and key_str in existing_plain
                and value_str == _mask_secret_value(existing_plain[key_str])
            ):
                next_data[key_str] = existing_stored[key_str]
            else:
                next_data[key_str] = self._cipher.encrypt(value_str)
        return next_data

    async def create_secret(self, req: CreateSecretRequest, project_id: Optional[str] = None) -> JoySafeterSecret:
        purge_conditions: list[ColumnElement[bool]] = [
            JoySafeterSecret.name == req.name,
            JoySafeterSecret.deleted_at.is_not(None),
        ]
        if project_id is not None:
            purge_conditions.append(JoySafeterSecret.project_id == project_id)
        else:
            purge_conditions.append(JoySafeterSecret.project_id.is_(None))
        await self.db.execute(delete(JoySafeterSecret).where(and_(*purge_conditions)))
        kwargs = dict(
            name=req.name,
            provider=req.provider,
            protocol=req.protocol,
            data=self.encrypt_data_for_storage(req.data),
            is_default=req.is_default,
        )
        if project_id is not None:
            kwargs["project_id"] = project_id
        if req.is_default:
            await self.clear_default_secret(project_id=project_id)
        secret = JoySafeterSecret(**kwargs)
        self.db.add(secret)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            message = str(getattr(exc, "orig", None) or exc).lower()
            if (
                "uq_joysafeter_secrets_project_name" in message
                or "uq_joysafeter_secrets_global_name" in message
                or ("joysafeter_secrets" in message and "name" in message and "unique" in message)
            ):
                raise ResourceConflictError(
                    code="SECRET_NAME_EXISTS",
                    message=f"A secret named '{req.name}' already exists in this project",
                    data={"name": req.name},
                    user_action="fix_input",
                ) from exc
            raise
        await self.db.refresh(secret)
        return secret

    async def get_secret(self, secret_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterSecret]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterSecret.id == secret_id,
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSecret).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def get_secret_by_name(self, name: str, project_id: Optional[str] = None) -> Optional[JoySafeterSecret]:
        conditions = [
            JoySafeterSecret.name == name,
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSecret).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def get_default_secret(self, project_id: Optional[str] = None) -> Optional[JoySafeterSecret]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterSecret.is_default.is_(True),
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSecret).where(and_(*conditions)).order_by(JoySafeterSecret.updated_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def clear_default_secret(self, project_id: Optional[str] = None) -> None:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterSecret.is_default.is_(True),
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterSecret.project_id == project_id)
        await self.db.execute(
            update(JoySafeterSecret).where(and_(*conditions)).values(is_default=False, updated_at=utc_now())
        )
        await self.db.flush()

    async def set_default_secret(
        self, secret_id: uuid.UUID, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSecret]:
        secret = await self.get_secret(secret_id, project_id=project_id)
        if not secret:
            return None
        await self.clear_default_secret(project_id=project_id)
        secret.is_default = True
        secret.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def list_secrets(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterSecret], bool]:
        q = select(JoySafeterSecret).where(JoySafeterSecret.deleted_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSecret.project_id == project_id)
        if after_id:
            cursor_is_default = (
                select(JoySafeterSecret.is_default).where(JoySafeterSecret.id == after_id).scalar_subquery()
            )
            cursor_created_at = (
                select(JoySafeterSecret.created_at).where(JoySafeterSecret.id == after_id).scalar_subquery()
            )
            q = q.where(
                or_(
                    JoySafeterSecret.is_default < cursor_is_default,
                    and_(
                        JoySafeterSecret.is_default == cursor_is_default,
                        or_(
                            JoySafeterSecret.created_at < cursor_created_at,
                            and_(
                                JoySafeterSecret.created_at == cursor_created_at,
                                JoySafeterSecret.id < after_id,
                            ),
                        ),
                    ),
                )
            )
        q = q.order_by(
            JoySafeterSecret.is_default.desc(),
            JoySafeterSecret.created_at.desc(),
            JoySafeterSecret.id.desc(),
        ).limit(limit + 1)
        result = await self.db.execute(q)
        secrets = list(result.scalars().all())
        has_more = len(secrets) > limit
        return secrets[:limit], has_more

    async def update_secret(
        self,
        secret_id: uuid.UUID,
        req: UpdateSecretRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterSecret]:
        secret = await self.get_secret(secret_id, project_id=project_id)
        if not secret:
            return None
        if req.provider is not None:
            secret.provider = req.provider
        if req.protocol is not None:
            secret.protocol = req.protocol
        secret.data = self.merge_update_data_for_storage(secret.data, req.data)
        secret.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def delete_secret(self, secret_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        secret = await self.get_secret(secret_id, project_id=project_id)
        if not secret:
            return False
        secret.deleted_at = utc_now()
        if secret.is_default:
            secret.is_default = False
        await self.db.commit()
        return True

    async def hard_delete_secret(self, secret_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        """Physical DELETE FROM joysafeter_secrets WHERE id = :id."""
        conditions: list[ColumnElement[bool]] = [JoySafeterSecret.id == secret_id]
        if project_id is not None:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(delete(JoySafeterSecret).where(and_(*conditions)))
        await self.db.commit()
        return bool(getattr(result, "rowcount", 0))

    async def secret_is_referenced(self, name: str, project_id: Optional[str] = None) -> bool:
        """Check if any live agent or environment references this secret name."""
        if await self.secret_is_referenced_by_agent(name, project_id=project_id):
            return True
        if await self.secret_is_referenced_by_environment(name, project_id=project_id):
            return True
        return False

    async def secret_is_referenced_by_agent(self, name: str, project_id: Optional[str] = None) -> Optional[str]:
        """Return the name of the first agent referencing this secret, or None."""
        conditions = [
            JoySafeterAgent.secret_ref == name,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent.name).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none()

    async def secret_is_referenced_by_environment(self, name: str, project_id: Optional[str] = None) -> Optional[str]:
        """Return the name of the first environment referencing this secret, or None."""
        conditions: list[ColumnElement[bool]] = [
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterEnvironment.name, JoySafeterEnvironment.config).where(and_(*conditions))
        )
        for env_name, config in result.all():
            if any(_secret_ref_matches(ref, name) for ref in _environment_secret_refs(config)):
                return str(env_name)
        return None

    async def _environment_refs_for_secret(self, name: str, project_id: Optional[str] = None) -> set[str]:
        conditions: list[ColumnElement[bool]] = [
            JoySafeterEnvironment.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterEnvironment.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterEnvironment.id, JoySafeterEnvironment.name, JoySafeterEnvironment.config).where(
                and_(*conditions)
            )
        )
        refs: set[str] = set()
        for env_id, env_name, config in result.all():
            if any(_secret_ref_matches(ref, name) for ref in _environment_secret_refs(config)):
                refs.add(str(env_name))
                refs.add(f"env_{env_id}")
        return refs

    async def active_task_secret_dependency(
        self,
        name: str,
        project_id: Optional[str] = None,
    ) -> Optional[tuple[uuid.UUID, str]]:
        """Return an active task depending on this secret, if one exists."""
        terminal_values = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]
        env_refs = await self._environment_refs_for_secret(name, project_id=project_id)
        task_agent_session = outerjoin(
            JoySafeterTask,
            JoySafeterAgent,
            JoySafeterTask.agent_id == JoySafeterAgent.id,
        ).outerjoin(
            JoySafeterSession,
            JoySafeterTask.chat_session_id == JoySafeterSession.id,
        )
        conditions: list[ColumnElement[bool]] = [JoySafeterTask.status.notin_(terminal_values)]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(
            select(
                JoySafeterTask.id,
                JoySafeterAgent.secret_ref,
                JoySafeterAgent.environment_ref,
                JoySafeterSession.environment_ref,
            )
            .select_from(task_agent_session)
            .where(and_(*conditions))
            .order_by(JoySafeterTask.created_at.asc())
        )
        for task_id, agent_secret_ref, agent_env_ref, session_env_ref in result.all():
            if _secret_ref_matches(agent_secret_ref, name):
                return task_id, "agent secret_ref"
            if env_refs:
                if session_env_ref and str(session_env_ref).strip() in env_refs:
                    return task_id, "session environment_ref"
                if agent_env_ref and str(agent_env_ref).strip() in env_refs:
                    return task_id, "agent environment_ref"
        return None
