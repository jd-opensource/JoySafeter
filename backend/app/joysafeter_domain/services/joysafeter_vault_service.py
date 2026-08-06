import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault, JoySafeterVaultCredential
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.services.joysafeter_vault_cipher import VaultCipher
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.utils.datetime import utc_now

logger = logging.getLogger(__name__)

_cipher: Optional[VaultCipher] = None
_OAUTH_SECRET_FIELDS = {"client_secret", "refresh_token"}


def _get_cipher() -> VaultCipher:
    global _cipher
    if _cipher is None:
        from app.joysafeter_shared.config.settings import joysafeter_config

        _cipher = VaultCipher(joysafeter_config.vault_encryption_key)
    return _cipher


def _is_redacted_secret(value: object) -> bool:
    return isinstance(value, str) and value.endswith("***")


class VaultService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

    def _encrypt_token_value(self, value: str) -> str:
        return self._cipher.encrypt(value)

    def _decrypt_token_value(self, value: str) -> str:
        try:
            return self._cipher.decrypt_or_passthrough(value)
        except Exception:
            return value

    def _encrypt_oauth_config_for_storage(
        self,
        oauth_config: Optional[dict],
        *,
        current_stored: Optional[dict] = None,
    ) -> Optional[dict]:
        if oauth_config is None:
            return None
        current_stored = current_stored or {}
        encrypted: dict[str, Any] = dict(oauth_config)
        for key in _OAUTH_SECRET_FIELDS:
            if key not in encrypted:
                continue
            raw_value = encrypted.get(key)
            if raw_value in (None, ""):
                continue
            if _is_redacted_secret(raw_value) and current_stored.get(key):
                encrypted[key] = current_stored[key]
                continue
            value = str(raw_value)
            encrypted[key] = value if value.startswith("enc:") else self._cipher.encrypt(value)
        return encrypted

    def _decrypt_oauth_config(self, oauth_config: Optional[dict]) -> dict:
        decrypted: dict[str, Any] = dict(oauth_config or {})
        for key in _OAUTH_SECRET_FIELDS:
            value = decrypted.get(key)
            if not value:
                continue
            decrypted[key] = self._decrypt_token_value(str(value))
        return decrypted

    @staticmethod
    def _oauth_expires_at_seconds(value: object) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        try:
            return float(str(value))
        except (TypeError, ValueError):
            pass
        try:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (TypeError, ValueError):
            return None

    # --- Vault ---

    async def create_vault(
        self, name: str, description: str = "", metadata: Optional[dict] = None, project_id: Optional[str] = None
    ) -> JoySafeterVault:
        purge_conditions = [
            JoySafeterVault.name == name,
            JoySafeterVault.deleted_at.isnot(None),
        ]
        if project_id is not None:
            purge_conditions.append(JoySafeterVault.project_id == project_id)
        else:
            purge_conditions.append(JoySafeterVault.project_id.is_(None))
        await self.db.execute(delete(JoySafeterVault).where(and_(*purge_conditions)))
        kwargs = dict(name=name, description=description, metadata_=metadata or {})
        if project_id is not None:
            kwargs["project_id"] = project_id
        vault = JoySafeterVault(**kwargs)
        self.db.add(vault)
        await self.db.commit()
        await self.db.refresh(vault)
        return vault

    async def get_vault(self, vault_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterVault]:
        conditions = [JoySafeterVault.id == vault_id, JoySafeterVault.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterVault.project_id == project_id)
        result = await self.db.execute(select(JoySafeterVault).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_vaults(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> tuple[list[JoySafeterVault], bool]:
        q = select(JoySafeterVault).where(JoySafeterVault.deleted_at.is_(None))
        if not include_archived:
            q = q.where(JoySafeterVault.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterVault.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterVault, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        vaults = list(result.scalars().all())
        has_more = len(vaults) > limit
        return vaults[:limit], has_more

    async def update_vault(
        self,
        vault_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterVault]:
        vault = await self.get_vault(vault_id, project_id=project_id)
        if not vault:
            return None
        if name is not None:
            vault.name = name
        if description is not None:
            vault.description = description
        if metadata is not None:
            vault.metadata_ = metadata
        vault.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(vault)
        return vault

    async def delete_vault(self, vault_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        vault = await self.get_vault(vault_id, project_id=project_id)
        if not vault:
            return False
        if await self.vault_is_referenced_by_sessions(vault_id, project_id=project_id):
            raise ValueError("Vault is referenced by one or more active sessions.")
        await self.db.execute(delete(JoySafeterVaultCredential).where(JoySafeterVaultCredential.vault_id == vault_id))
        await self.db.execute(delete(JoySafeterVault).where(JoySafeterVault.id == vault_id))
        await self.db.commit()
        return True

    async def archive_vault(self, vault_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        vault = await self.get_vault(vault_id, project_id=project_id)
        if not vault:
            return False
        if vault.archived_at:
            return True
        if await self.vault_is_referenced_by_sessions(vault_id, project_id=project_id):
            raise ValueError("Vault is referenced by one or more active sessions.")
        vault.archived_at = utc_now()
        # Archive all credentials in the vault so they remain visible behind the archived filter.
        await self.db.execute(
            update(JoySafeterVaultCredential)
            .where(
                JoySafeterVaultCredential.vault_id == vault_id,
                JoySafeterVaultCredential.deleted_at.is_(None),
                JoySafeterVaultCredential.archived_at.is_(None),
            )
            .values(archived_at=func.now())
        )
        await self.db.commit()
        return True

    async def vault_is_referenced_by_sessions(
        self,
        vault_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> bool:
        vault_refs = [f"vault_{vault_id}", str(vault_id)]
        conditions = [
            or_(*(JoySafeterSession.vault_ids.contains([vault_ref]) for vault_ref in vault_refs)),
            JoySafeterSession.archived_at.is_(None),
            JoySafeterSession.status != "terminated",
        ]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSession.id).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none() is not None

    # --- Credentials ---

    async def create_credential(
        self,
        vault_id: uuid.UUID,
        name: str,
        credential_type: str,
        mcp_server_url: str,
        token_value: str,
        oauth_config: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterVaultCredential]:
        vault = await self.get_vault(vault_id, project_id=project_id)
        if not vault or vault.archived_at is not None:
            return None
        encrypted_token = self._encrypt_token_value(token_value)
        cred = JoySafeterVaultCredential(
            vault_id=vault_id,
            name=name,
            credential_type=credential_type,
            mcp_server_url=mcp_server_url,
            token_value=encrypted_token,
            oauth_config=self._encrypt_oauth_config_for_storage(oauth_config),
        )
        self.db.add(cred)
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def get_credential(
        self,
        cred_id: uuid.UUID,
        vault_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterVaultCredential]:
        if project_id is not None and vault_id is not None:
            vault = await self.get_vault(vault_id, project_id=project_id)
            if not vault:
                return None
        conditions = [
            JoySafeterVaultCredential.id == cred_id,
            JoySafeterVaultCredential.deleted_at.is_(None),
        ]
        if vault_id is not None:
            conditions.append(JoySafeterVaultCredential.vault_id == vault_id)
        q = select(JoySafeterVaultCredential)
        if project_id is not None and vault_id is None:
            q = q.join(JoySafeterVault, JoySafeterVaultCredential.vault_id == JoySafeterVault.id)
            conditions.extend(
                [
                    JoySafeterVault.project_id == project_id,
                    JoySafeterVault.deleted_at.is_(None),
                ]
            )
        result = await self.db.execute(q.where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_credentials(
        self,
        vault_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        include_archived: bool = True,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterVaultCredential], bool]:
        if project_id is not None and not await self.get_vault(vault_id, project_id=project_id):
            return [], False
        q = select(JoySafeterVaultCredential).where(
            and_(JoySafeterVaultCredential.vault_id == vault_id, JoySafeterVaultCredential.deleted_at.is_(None))
        )
        if not include_archived:
            q = q.where(JoySafeterVaultCredential.archived_at.is_(None))
        q = apply_created_at_desc_cursor(q, JoySafeterVaultCredential, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        creds = list(result.scalars().all())
        has_more = len(creds) > limit
        return creds[:limit], has_more

    async def update_credential(
        self,
        cred_id: uuid.UUID,
        name: Optional[str] = None,
        token_value: Optional[str] = None,
        oauth_config: Optional[dict] = None,
        vault_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterVaultCredential]:
        cred = await self.get_credential(cred_id, vault_id=vault_id, project_id=project_id)
        if not cred:
            return None
        vault = await self.get_vault(cred.vault_id, project_id=project_id)
        if not vault or vault.archived_at is not None:
            return None
        current_oauth = dict(cred.oauth_config or {})
        if name is not None:
            cred.name = name
        if token_value is not None:
            cred.token_value = self._encrypt_token_value(token_value)
        if oauth_config is not None:
            cred.oauth_config = self._encrypt_oauth_config_for_storage(oauth_config, current_stored=current_oauth)
        cred.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def delete_credential(
        self,
        cred_id: uuid.UUID,
        vault_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> bool:
        cred = await self.get_credential(cred_id, vault_id=vault_id, project_id=project_id)
        if not cred:
            return False
        vault = await self.get_vault(cred.vault_id, project_id=project_id)
        if not vault or vault.archived_at is not None:
            return False
        cred.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_credential(
        self,
        cred_id: uuid.UUID,
        vault_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> bool:
        cred = await self.get_credential(cred_id, vault_id=vault_id, project_id=project_id)
        if not cred:
            return False
        vault = await self.get_vault(cred.vault_id, project_id=project_id)
        if not vault or vault.archived_at is not None:
            return False
        if cred.archived_at:
            return True
        cred.archived_at = utc_now()
        await self.db.commit()
        return True

    async def update_credential_token(
        self, cred_id: uuid.UUID, new_token: str, new_expires_at: Optional[datetime] = None
    ) -> None:
        encrypted_token = self._encrypt_token_value(new_token)
        values: dict = {"token_value": encrypted_token}
        stmt = update(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred_id).values(**values)
        await self.db.execute(stmt)
        if new_expires_at is not None:
            from sqlalchemy import cast, literal
            from sqlalchemy.types import Text as TextType

            expires_str = new_expires_at.isoformat()
            await self.db.execute(
                update(JoySafeterVaultCredential)
                .where(JoySafeterVaultCredential.id == cred_id)
                .values(
                    oauth_config=func.jsonb_set(
                        JoySafeterVaultCredential.oauth_config,
                        "{expires_at}",
                        func.to_jsonb(cast(literal(expires_str), TextType)),
                    )
                )
            )
        await self.db.commit()

    # --- MCP Credential Resolution ---

    async def resolve_mcp_credentials(
        self,
        vault_ids: list[str],
        mcp_servers: list[dict],
        project_id: Optional[str] = None,
    ) -> list[dict]:
        """Match MCP server URLs against vault credentials and inject auth headers."""
        if not vault_ids or not mcp_servers:
            return mcp_servers

        creds_by_url: dict[str, tuple[JoySafeterVaultCredential, str, dict]] = {}
        for vid_str in vault_ids:
            vid_str_clean = vid_str.replace("vault_", "")
            try:
                vid = uuid.UUID(vid_str_clean)
            except ValueError:
                continue
            vault = await self.get_vault(vid, project_id=project_id)
            if not vault or vault.archived_at is not None:
                continue
            creds, _ = await self.list_credentials(vid, limit=500, include_archived=False, project_id=project_id)
            for c in creds:
                if c.mcp_server_url:
                    token_value = self._decrypt_token_value(c.token_value)
                    oauth_config = self._decrypt_oauth_config(c.oauth_config)
                    creds_by_url[c.mcp_server_url] = (c, token_value, oauth_config)

        enriched = []
        for cfg in mcp_servers:
            cfg_copy = dict(cfg)
            url = cfg_copy.get("url", "")
            resolved = creds_by_url.get(url)
            if resolved:
                cred, token, oauth_config = resolved
                if cred.credential_type in {"oauth", "mcp_oauth"} and oauth_config:
                    token = await self._maybe_refresh_oauth(cred, token, oauth_config)

                headers = dict(cfg_copy.get("headers", {}))
                headers["Authorization"] = f"Bearer {token}"
                cfg_copy["headers"] = headers
            enriched.append(cfg_copy)

        return enriched

    async def _maybe_refresh_oauth(
        self,
        cred: JoySafeterVaultCredential,
        current_token: str,
        oauth: dict,
    ) -> str:
        import time

        expires_at = self._oauth_expires_at_seconds(oauth.get("expires_at"))
        if expires_at and time.time() < expires_at - 300:
            return current_token

        refresh_token = oauth.get("refresh_token")
        token_url = oauth.get("token_url") or oauth.get("token_endpoint")
        client_id = oauth.get("client_id")
        client_secret = oauth.get("client_secret")
        if not (refresh_token and token_url and client_id):
            return current_token

        try:
            import httpx

            from app.joysafeter_shared.security.ssrf_guard import validate_url

            validate_url(token_url, context="vault OAuth token_url")

            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                resp = await client.post(
                    token_url,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret or "",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_token: str = data["access_token"]
                    new_refresh = data.get("refresh_token", refresh_token)
                    new_expires = int(time.time()) + data.get("expires_in", 3600)

                    new_oauth = dict(oauth)
                    new_oauth["refresh_token"] = new_refresh
                    new_oauth["expires_at"] = new_expires

                    from app.joysafeter_shared.database import AsyncSessionLocal

                    async with AsyncSessionLocal() as refresh_db:
                        from sqlalchemy import select

                        result = await refresh_db.execute(
                            select(JoySafeterVaultCredential).where(JoySafeterVaultCredential.id == cred.id)
                        )
                        db_cred = result.scalar_one_or_none()
                        if db_cred:
                            db_cred.token_value = self._encrypt_token_value(new_token)
                            db_cred.oauth_config = self._encrypt_oauth_config_for_storage(
                                new_oauth,
                                current_stored=dict(db_cred.oauth_config or {}),
                            )
                            db_cred.updated_at = utc_now()
                            await refresh_db.commit()

                    return new_token
        except Exception as e:
            log_boundary_failure(
                logger,
                boundary="vault_service",
                code="VAULT_OAUTH_REFRESH_FAILED",
                message="OAuth credential refresh failed",
                operation="refresh_oauth_credential",
                error=e,
                data={"credential_id": str(cred.id), "vault_id": str(cred.vault_id)},
            )

        return current_token
