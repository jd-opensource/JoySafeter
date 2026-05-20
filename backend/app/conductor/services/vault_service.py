import logging
import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.vault import ConductorVault, ConductorVaultCredential
from app.conductor.services.vault_cipher import VaultCipher
from app.utils.datetime import utc_now

logger = logging.getLogger(__name__)

_cipher: Optional[VaultCipher] = None


def _get_cipher() -> VaultCipher:
    global _cipher
    if _cipher is None:
        from app.conductor.config import conductor_config
        _cipher = VaultCipher(conductor_config.vault_encryption_key)
    return _cipher


class VaultService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._cipher = _get_cipher()

    # --- Vault ---

    async def create_vault(self, name: str, description: str = "", metadata: Optional[dict] = None) -> ConductorVault:
        vault = ConductorVault(name=name, description=description, metadata_=metadata or {})
        self.db.add(vault)
        await self.db.commit()
        await self.db.refresh(vault)
        return vault

    async def get_vault(self, vault_id: uuid.UUID) -> Optional[ConductorVault]:
        result = await self.db.execute(
            select(ConductorVault).where(
                and_(ConductorVault.id == vault_id, ConductorVault.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def list_vaults(self, limit: int = 20, after_id: Optional[uuid.UUID] = None) -> tuple[list[ConductorVault], bool]:
        q = select(ConductorVault).where(ConductorVault.deleted_at.is_(None))
        if after_id:
            q = q.where(ConductorVault.id < after_id)
        q = q.order_by(ConductorVault.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        vaults = list(result.scalars().all())
        has_more = len(vaults) > limit
        return vaults[:limit], has_more

    async def update_vault(
        self, vault_id: uuid.UUID, name: Optional[str] = None, description: Optional[str] = None, metadata: Optional[dict] = None
    ) -> Optional[ConductorVault]:
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
        vault.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_vault(self, vault_id: uuid.UUID) -> bool:
        vault = await self.get_vault(vault_id)
        if not vault:
            return False
        if vault.archived_at:
            return True
        vault.archived_at = utc_now()
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
    ) -> ConductorVaultCredential:
        encrypted_token = self._cipher.encrypt(token_value)
        cred = ConductorVaultCredential(
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

    async def get_credential(self, cred_id: uuid.UUID) -> Optional[ConductorVaultCredential]:
        result = await self.db.execute(
            select(ConductorVaultCredential).where(
                and_(ConductorVaultCredential.id == cred_id, ConductorVaultCredential.deleted_at.is_(None))
            )
        )
        cred = result.scalar_one_or_none()
        if cred and self._cipher.is_enabled:
            try:
                cred.token_value = self._cipher.decrypt(cred.token_value)
            except Exception:
                pass
        return cred

    async def list_credentials(self, vault_id: uuid.UUID, limit: int = 20, after_id: Optional[uuid.UUID] = None) -> tuple[list[ConductorVaultCredential], bool]:
        q = select(ConductorVaultCredential).where(
            and_(ConductorVaultCredential.vault_id == vault_id, ConductorVaultCredential.deleted_at.is_(None))
        )
        if after_id:
            q = q.where(ConductorVaultCredential.id < after_id)
        q = q.order_by(ConductorVaultCredential.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        creds = list(result.scalars().all())
        has_more = len(creds) > limit
        return creds[:limit], has_more

    async def update_credential(
        self, cred_id: uuid.UUID, name: Optional[str] = None, token_value: Optional[str] = None, oauth_config: Optional[dict] = None
    ) -> Optional[ConductorVaultCredential]:
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

    # --- MCP Credential Resolution ---

    async def resolve_mcp_credentials(
        self,
        vault_ids: list[str],
        mcp_configs: list[dict],
    ) -> list[dict]:
        """Match MCP server URLs against vault credentials and inject auth headers."""
        if not vault_ids or not mcp_configs:
            return mcp_configs

        creds_by_url: dict[str, ConductorVaultCredential] = {}
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
                            c.token_value = self._cipher.decrypt(c.token_value)
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
        self, cred: ConductorVaultCredential, current_token: str
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

                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as refresh_db:
                        from sqlalchemy import select
                        result = await refresh_db.execute(
                            select(ConductorVaultCredential).where(
                                ConductorVaultCredential.id == cred.id
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
