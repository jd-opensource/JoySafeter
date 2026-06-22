import uuid
from typing import Optional

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.agent import JoySafeterAgent
from app.joysafeter_domain.models.secret import JoySafeterSecret
from app.joysafeter_domain.schemas.secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_domain.services.vault_cipher import VaultCipher
from app.joysafeter_shared.utils.datetime import utc_now

MASKED_SECRET_PREFIX = "********"

_cipher: Optional[VaultCipher] = None


def _get_cipher() -> VaultCipher:
    global _cipher
    if _cipher is None:
        from app.joysafeter_shared.config.settings import joysafeter_config

        _cipher = VaultCipher(joysafeter_config.vault_encryption_key)
    return _cipher


def _is_sensitive_secret_key(key: str) -> bool:
    normalized = key.upper()
    return any(token in normalized for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))


def _mask_secret_value(value: str) -> str:
    if not value:
        return ""
    suffix = value[-4:] if len(value) > 4 else ""
    return f"{MASKED_SECRET_PREFIX}{suffix}"


class SecretService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

    def _require_encryption_key(self, data: dict | None) -> None:
        if data and not self._cipher.is_enabled:
            raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY is required to encrypt managed secrets")

    def encrypt_data_for_storage(self, data: dict[str, str] | None) -> dict[str, str]:
        self._require_encryption_key(data)
        encrypted: dict[str, str] = {}
        for key, value in (data or {}).items():
            encrypted[str(key)] = self._cipher.encrypt(str(value))
        return encrypted

    def decrypt_data(self, data: dict | None) -> dict[str, str]:
        decrypted: dict[str, str] = {}
        for key, value in (data or {}).items():
            value_str = str(value)
            if value_str.startswith("enc:") and not self._cipher.is_enabled:
                raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY is required to decrypt managed secrets")
            decrypted[str(key)] = self._cipher.decrypt_or_passthrough(value_str)
        return decrypted

    def get_secret_data(self, secret: JoySafeterSecret | None) -> dict[str, str]:
        if not secret:
            return {}
        return self.decrypt_data(secret.data or {})

    def get_masked_secret_data(self, secret: JoySafeterSecret | None) -> dict[str, str]:
        data = self.get_secret_data(secret)
        return {
            key: _mask_secret_value(value) if _is_sensitive_secret_key(key) else value
            for key, value in data.items()
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
        self._require_encryption_key(requested_data)
        existing_plain = self.decrypt_data(current_data or {})
        existing_stored = {str(k): str(v) for k, v in (current_data or {}).items()}
        next_data: dict[str, str] = {}
        for key, value in (requested_data or {}).items():
            key_str = str(key)
            value_str = str(value)
            if (
                _is_sensitive_secret_key(key_str)
                and key_str in existing_plain
                and value_str == _mask_secret_value(existing_plain[key_str])
            ):
                stored_value = existing_stored[key_str]
                next_data[key_str] = (
                    stored_value
                    if stored_value.startswith("enc:")
                    else self._cipher.encrypt(existing_plain[key_str])
                )
            else:
                next_data[key_str] = self._cipher.encrypt(value_str)
        return next_data

    async def create_secret(
        self, req: CreateSecretRequest, project_id: Optional[str] = None
    ) -> JoySafeterSecret:
        # Purge any soft-deleted row with the same name before inserting
        await self.db.execute(
            delete(JoySafeterSecret).where(
                and_(
                    JoySafeterSecret.name == req.name,
                    JoySafeterSecret.deleted_at.is_not(None),
                )
            )
        )
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
        await self.db.commit()
        await self.db.refresh(secret)
        return secret

    async def get_secret(self, secret_id: uuid.UUID) -> Optional[JoySafeterSecret]:
        result = await self.db.execute(
            select(JoySafeterSecret).where(
                and_(
                    JoySafeterSecret.id == secret_id,
                    JoySafeterSecret.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_secret_by_name(
        self, name: str, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSecret]:
        conditions = [
            JoySafeterSecret.name == name,
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSecret).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    async def get_default_secret(
        self, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSecret]:
        conditions = [
            JoySafeterSecret.is_default.is_(True),
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterSecret.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSecret)
            .where(and_(*conditions))
            .order_by(JoySafeterSecret.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def clear_default_secret(self, project_id: Optional[str] = None) -> None:
        conditions = [
            JoySafeterSecret.is_default.is_(True),
            JoySafeterSecret.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterSecret.project_id == project_id)
        await self.db.execute(
            update(JoySafeterSecret)
            .where(and_(*conditions))
            .values(is_default=False, updated_at=utc_now())
        )
        await self.db.flush()

    async def set_default_secret(
        self, secret_id: uuid.UUID, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSecret]:
        secret = await self.get_secret(secret_id)
        if not secret:
            return None
        if project_id is not None and secret.project_id != project_id:
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
            q = q.where(JoySafeterSecret.id < after_id)
        q = q.order_by(
            JoySafeterSecret.is_default.desc(), JoySafeterSecret.created_at.desc()
        ).limit(limit + 1)
        result = await self.db.execute(q)
        secrets = list(result.scalars().all())
        has_more = len(secrets) > limit
        return secrets[:limit], has_more

    async def update_secret(
        self, secret_id: uuid.UUID, req: UpdateSecretRequest
    ) -> Optional[JoySafeterSecret]:
        secret = await self.get_secret(secret_id)
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

    async def delete_secret(self, secret_id: uuid.UUID) -> bool:
        secret = await self.get_secret(secret_id)
        if not secret:
            return False
        secret.deleted_at = utc_now()
        if secret.is_default:
            secret.is_default = False
        await self.db.commit()
        return True

    async def hard_delete_secret(self, secret_id: uuid.UUID) -> None:
        """Physical DELETE FROM joysafeter_secrets WHERE id = :id."""
        await self.db.execute(
            delete(JoySafeterSecret).where(JoySafeterSecret.id == secret_id)
        )
        await self.db.commit()

    async def secret_is_referenced(
        self, name: str, project_id: Optional[str] = None
    ) -> bool:
        """Check if any agent has secret_ref = name AND deleted_at IS NULL."""
        conditions = [
            JoySafeterAgent.secret_ref == name,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterAgent.id).where(and_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def secret_is_referenced_by_agent(
        self, name: str, project_id: Optional[str] = None
    ) -> Optional[str]:
        """Return the name of the first agent referencing this secret, or None."""
        conditions = [
            JoySafeterAgent.secret_ref == name,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterAgent.name).where(and_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none()
