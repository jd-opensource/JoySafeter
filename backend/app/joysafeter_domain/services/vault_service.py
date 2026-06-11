import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.vault import JoySafeterVault, JoySafeterVaultCredential
from app.joysafeter_domain.services.vault_cipher import VaultCipher
from app.joysafeter_shared.utils.datetime import utc_now

logger = logging.getLogger(__name__)

_cipher: Optional[VaultCipher] = None


def _get_cipher() -> VaultCipher:
    global _cipher
    if _cipher is None:
        from app.joysafeter_shared.config.settings import joysafeter_config
        _cipher = VaultCipher(joysafeter_config.vault_encryption_key)
    return _cipher


class VaultService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

    # --- Vault ---

    async def create_vault(self, name: str, description: str = "", metadata: Optional[dict] = None, project_id: Optional[str] = None) -> JoySafeterVault:
        # Purge soft-deleted rows with the same name before insert
        await self.db.execute(
            delete(JoySafeterVault).where(
                JoySafeterVault.name == name, JoySafeterVault.deleted_at.isnot(None)
            )
        )
        kwargs = dict(name=name, description=description, metadata_=metadata or {})
        if project_id is not None:
            kwargs["project_id"] = project_id
        vault = JoySafeterVault(**kwargs)
        self.db.add(vault)
        await self.db.commit()
        await self.db.refresh(vault)
        return vault

    async def get_vault(self, vault_id: uuid.UUID) -> Optional[JoySafeterVault]:
        result = await self.db.execute(
            select(JoySafeterVault).where(
                and_(JoySafeterVault.id == vault_id, JoySafeterVault.deleted_at.is_(None))
            )
        )
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
        if after_id:
            q = q.where(JoySafeterVault.id < after_id)
        q = q.order_by(JoySafeterVault.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        vaults = list(result.scalars().all())
        has_more = len(vaults) > limit
        return vaults[:limit], has_more

    async def update_vault(
        self, vault_id: uuid.UUID, name: Optional[str] = None, description: Optional[str] = None, metadata: Optional[dict] = None
    ) -> Optional[JoySafeterVault]:
        vault = await self.get_vault(vault_id)
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

    async def delete_vault(self, vault_id: uuid.UUID) -> bool:
        vault = await self.get_vault(vault_id)
        if not vault:
            return False
        await self.db.execute(
            delete(JoySafeterVaultCredential).where(JoySafeterVaultCredential.vault_id == vault_id)
        )
        await self.db.execute(
            delete(JoySafeterVault).where(JoySafeterVault.id == vault_id)
        )
        await self.db.commit()
        return True

    async def archive_vault(self, vault_id: uuid.UUID) -> bool:
        vault = await self.get_vault(vault_id)
        if not vault:
            return False
        if vault.archived_at:
            return True
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

    # --- Credentials ---

    async def create_credential(
        self,
        vault_id: uuid.UUID,
        name: str,
        credential_type: str,
        mcp_server_url: str,
        token_value: str,
        oauth_config: Optional[dict] = None,
    ) -> JoySafeterVaultCredential:
        encrypted_token = self._cipher.encrypt(token_value)
        cred = JoySafeterVaultCredential(
            vault_id=vault_id,
            name=name,
            credential_type=credential_type,
            mcp_server_url=mcp_server_url,
            token_value=encrypted_token,
            oauth_config=oauth_config,
        )
        self.db.add(cred)
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def get_credential(self, cred_id: uuid.UUID) -> Optional[JoySafeterVaultCredential]:
        result = await self.db.execute(
            select(JoySafeterVaultCredential).where(
                and_(JoySafeterVaultCredential.id == cred_id, JoySafeterVaultCredential.deleted_at.is_(None))
            )
        )
        cred = result.scalar_one_or_none()
        if cred and self._cipher.is_enabled:
            try:
                cred.token_value = self._cipher.decrypt_or_passthrough(cred.token_value)
            except Exception:
                pass
        return cred

    async def list_credentials(self, vault_id: uuid.UUID, limit: int = 20, after_id: Optional[uuid.UUID] = None, include_archived: bool = True) -> tuple[list[JoySafeterVaultCredential], bool]:
        q = select(JoySafeterVaultCredential).where(
            and_(JoySafeterVaultCredential.vault_id == vault_id, JoySafeterVaultCredential.deleted_at.is_(None))
        )
        if not include_archived:
            q = q.where(JoySafeterVaultCredential.archived_at.is_(None))
        if after_id:
            q = q.where(JoySafeterVaultCredential.id < after_id)
        q = q.order_by(JoySafeterVaultCredential.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        creds = list(result.scalars().all())
        has_more = len(creds) > limit
        return creds[:limit], has_more

    async def update_credential(
        self, cred_id: uuid.UUID, name: Optional[str] = None, token_value: Optional[str] = None, oauth_config: Optional[dict] = None
    ) -> Optional[JoySafeterVaultCredential]:
        cred = await self.get_credential(cred_id)
        if not cred:
            return None
        if name is not None:
            cred.name = name
        if token_value is not None:
            cred.token_value = self._cipher.encrypt(token_value)
        if oauth_config is not None:
            cred.oauth_config = oauth_config
        cred.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(cred)
        return cred

    async def delete_credential(self, cred_id: uuid.UUID) -> bool:
        cred = await self.get_credential(cred_id)
        if not cred:
            return False
        cred.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_credential(self, cred_id: uuid.UUID) -> bool:
        cred = await self.get_credential(cred_id)
        if not cred:
            return False
        if cred.archived_at:
            return True
        cred.archived_at = utc_now()
        await self.db.commit()
        return True

    async def update_credential_token(
        self, cred_id: uuid.UUID, new_token: str, new_expires_at: Optional[datetime] = None
    ) -> None:
        encrypted_token = self._cipher.encrypt(new_token)
        values: dict = {"token_value": encrypted_token}
        stmt = (
            update(JoySafeterVaultCredential)
            .where(JoySafeterVaultCredential.id == cred_id)
            .values(**values)
        )
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
        mcp_configs: list[dict],
    ) -> list[dict]:
        """Match MCP server URLs against vault credentials and inject auth headers."""
        if not vault_ids or not mcp_configs:
            return mcp_configs

        creds_by_url: dict[str, JoySafeterVaultCredential] = {}
        for vid_str in vault_ids:
            vid_str_clean = vid_str.replace("vault_", "")
            try:
                vid = uuid.UUID(vid_str_clean)
            except ValueError:
                continue
            creds, _ = await self.list_credentials(vid, limit=500)
            for c in creds:
                if c.mcp_server_url:
                    if self._cipher.is_enabled:
                        try:
                            c.token_value = self._cipher.decrypt_or_passthrough(c.token_value)
                        except Exception:
                            pass
                    creds_by_url[c.mcp_server_url] = c

        enriched = []
        for cfg in mcp_configs:
            cfg_copy = dict(cfg)
            url = cfg_copy.get("url", "")
            cred = creds_by_url.get(url)
            if cred and cred.token_value:
                token = cred.token_value
                if cred.credential_type == "oauth" and cred.oauth_config:
                    token = await self._maybe_refresh_oauth(cred, token)

                headers = dict(cfg_copy.get("headers", {}))
                headers["Authorization"] = f"Bearer {token}"
                cfg_copy["headers"] = headers
            enriched.append(cfg_copy)

        return enriched

    async def _maybe_refresh_oauth(
        self, cred: JoySafeterVaultCredential, current_token: str
    ) -> str:
        import time

        oauth = cred.oauth_config or {}
        expires_at = oauth.get("expires_at", 0)
        if expires_at and time.time() < expires_at - 300:
            return current_token

        refresh_token = oauth.get("refresh_token")
        token_url = oauth.get("token_url")
        client_id = oauth.get("client_id")
        client_secret = oauth.get("client_secret")
        if not (refresh_token and token_url and client_id):
            return current_token

        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
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
                    new_token = data["access_token"]
                    new_refresh = data.get("refresh_token", refresh_token)
                    new_expires = int(time.time()) + data.get("expires_in", 3600)

                    new_oauth = dict(oauth)
                    new_oauth["refresh_token"] = new_refresh
                    new_oauth["expires_at"] = new_expires

                    from app.joysafeter_shared.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as refresh_db:
                        from sqlalchemy import select
                        result = await refresh_db.execute(
                            select(JoySafeterVaultCredential).where(
                                JoySafeterVaultCredential.id == cred.id
                            )
                        )
                        db_cred = result.scalar_one_or_none()
                        if db_cred:
                            db_cred.token_value = self._cipher.encrypt(new_token)
                            db_cred.oauth_config = new_oauth
                            db_cred.updated_at = utc_now()
                            await refresh_db.commit()

                    return new_token
        except Exception as e:
            logger.warning("OAuth refresh failed for cred %s: %s", cred.id, e)

        return current_token
