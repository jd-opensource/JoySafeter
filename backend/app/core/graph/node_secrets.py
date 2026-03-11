"""
Graph node secrets: encrypt a2a_auth_headers and store by reference.

- On save: if node has plain a2a_auth_headers, encrypt and store in graph_node_secrets,
  replace in node.data.config with {"__secretRef": "<secret_id>"}.
- On load for execution: resolve __secretRef to decrypted headers (in-memory only).
- GET /state never returns decrypted headers; frontend sees __secretRef or redacted.
"""

import copy
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model.utils import decrypt_credentials, encrypt_credentials
from app.models.graph import GraphNode, GraphNodeSecret

SECRET_KEY_SLUG = "a2a_auth_headers"
REF_KEY = "__secretRef"


def _normalize_headers(raw: Any) -> Optional[Dict[str, str]]:
    """Convert frontend format to dict[str, str]. Returns None if empty or invalid."""
    if isinstance(raw, dict):
        if REF_KEY in raw and len(raw) == 1:
            return None
        out = {str(k): str(v) for k, v in raw.items() if k and v and k != REF_KEY}
        return out if out else None
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if isinstance(item, dict) and item.get("key") and item.get("value"):
                out[str(item["key"])] = str(item["value"])
        return out if out else None
    return None


async def store_a2a_auth_headers(
    db: AsyncSession,
    graph_id: uuid.UUID,
    node_id: uuid.UUID,
    headers: Dict[str, str],
) -> uuid.UUID:
    """Encrypt and store headers; return the secret row id (for __secretRef)."""
    if not headers:
        raise ValueError("headers must be non-empty")
    encrypted = encrypt_credentials(headers)
    row = GraphNodeSecret(
        graph_id=graph_id,
        node_id=node_id,
        key_slug=SECRET_KEY_SLUG,
        encrypted_value=encrypted,
    )
    db.add(row)
    await db.flush()
    return row.id


async def resolve_a2a_auth_headers(db: AsyncSession, secret_id: uuid.UUID) -> Optional[Dict[str, str]]:
    """Load and decrypt headers by secret id. Returns None if not found or invalid."""
    result = await db.execute(select(GraphNodeSecret).where(GraphNodeSecret.id == secret_id))
    row = result.scalar_one_or_none()
    if not row or not row.encrypted_value:
        return None
    try:
        decrypted = decrypt_credentials(row.encrypted_value)
        return {str(k): str(v) for k, v in decrypted.items()} if isinstance(decrypted, dict) else None
    except Exception as e:
        logger.warning(f"[NodeSecrets] Failed to decrypt secret {secret_id}: {e}")
        return None


def prepare_node_data_for_save(node_data: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[Dict[str, str]]]:
    """
    If node has plain a2a_auth_headers, return (data_copy_without_plain_headers, headers_to_store).
    Caller must: store the secret, then set data_copy["config"]["a2a_auth_headers"] = {"__secretRef": str(secret_id)}.
    """
    data_copy = copy.deepcopy(node_data)
    config = (data_copy.get("config") or {}) if isinstance(data_copy.get("config"), dict) else {}
    raw = config.get("a2a_auth_headers")
    headers = _normalize_headers(raw)
    if not headers:
        return data_copy, None
    if "config" not in data_copy:
        data_copy["config"] = {}
    data_copy["config"]["a2a_auth_headers"] = {}  # Caller will set __secretRef after storing
    return data_copy, headers


async def hydrate_nodes_a2a_secrets(db: AsyncSession, nodes: List[GraphNode]) -> None:
    """Resolve __secretRef in each node's data.config.a2a_auth_headers in-place (for execution only)."""
    for node in nodes:
        data = node.data or {}
        config = data.get("config") or {}
        raw = config.get("a2a_auth_headers")
        if not isinstance(raw, dict) or REF_KEY not in raw:
            continue
        ref = raw.get(REF_KEY)
        if not ref:
            continue
        try:
            secret_uuid = uuid.UUID(str(ref))
        except (ValueError, TypeError):
            continue
        resolved = await resolve_a2a_auth_headers(db, secret_uuid)
        if resolved is not None:
            config["a2a_auth_headers"] = resolved
            if "config" not in data:
                data["config"] = config
            node.data = data
        else:
            config["a2a_auth_headers"] = {}
            node.data = data
