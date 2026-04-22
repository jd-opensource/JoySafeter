"""
Graph node secrets: encrypt a2a_auth_headers and store by reference.

The GraphNode / GraphNodeSecret ORM models have been removed.
Node secrets are now stored inline in AgentVersion.definition_payload.
The helper functions below operate on plain dicts (node data payloads)
and are used by the graph builder at compile time.
"""

import copy
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model.utils import decrypt_credentials, encrypt_credentials

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
    """Encrypt and store headers.

    The GraphNodeSecret table has been removed. Secrets are now stored
    inline in AgentVersion.definition_payload. This function raises
    RuntimeError to surface any call-sites that still rely on the old
    storage path.
    """
    raise RuntimeError(
        "store_a2a_auth_headers: GraphNodeSecret table removed. "
        "Secrets should be stored in AgentVersion.definition_payload."
    )


async def resolve_a2a_auth_headers(db: AsyncSession, secret_id: uuid.UUID) -> Optional[Dict[str, str]]:
    """Load and decrypt headers by secret id.

    The GraphNodeSecret table has been removed. Returns None so that
    callers degrade gracefully.
    """
    logger.warning(
        f"[NodeSecrets] resolve_a2a_auth_headers called with secret_id={secret_id} "
        "but GraphNodeSecret table no longer exists"
    )
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


async def hydrate_nodes_a2a_secrets(db: AsyncSession, nodes: List[Any]) -> None:
    """Resolve __secretRef in each node's data.config.a2a_auth_headers in-place (for execution only).

    Accepts any object with a ``data`` dict attribute (previously GraphNode ORM instances,
    now plain data-holder objects from AgentVersion.definition_payload).
    """
    for node in nodes:
        data = getattr(node, "data", None) or {}
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
