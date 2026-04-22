"""
Graph node secrets: encrypt a2a_auth_headers and store inline.

The GraphNode / GraphNodeSecret ORM models have been removed.
Node secrets are now stored inline in AgentVersion.definition_payload
under definition_payload["node_secrets"][str(node_id)] as an encrypted
string.  No database table or UUID secret reference is involved.

The helper functions below operate on plain dicts (node data payloads)
and are used by the graph builder at compile time.
"""

import copy
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

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


def store_a2a_auth_headers(
    payload_secrets: Dict[str, Any],
    node_id: str | uuid.UUID,
    headers: Dict[str, str],
) -> None:
    """Encrypt *headers* and store them inline in *payload_secrets*.

    ``payload_secrets`` is ``definition_payload["node_secrets"]`` — a plain
    dict that lives inside AgentVersion.definition_payload.  The encrypted
    string is keyed by ``str(node_id)``.

    Example::

        payload_secrets = definition_payload.setdefault("node_secrets", {})
        store_a2a_auth_headers(payload_secrets, node_id, headers)
    """
    if not headers:
        return
    encrypted = encrypt_credentials(headers)
    payload_secrets[str(node_id)] = encrypted
    logger.debug(f"[NodeSecrets] Stored encrypted a2a_auth_headers for node_id={node_id}")


def resolve_a2a_auth_headers(
    payload_secrets: Dict[str, Any],
    node_id: str | uuid.UUID,
) -> Optional[Dict[str, str]]:
    """Decrypt and return a2a_auth_headers for *node_id* from *payload_secrets*.

    ``payload_secrets`` is ``definition_payload.get("node_secrets", {})``.
    Returns ``None`` when no secret is stored for the given node.
    """
    encrypted = payload_secrets.get(str(node_id))
    if not encrypted:
        return None
    try:
        result = decrypt_credentials(encrypted)
        return {str(k): str(v) for k, v in result.items()} if isinstance(result, dict) else None
    except Exception as exc:
        logger.warning(f"[NodeSecrets] Failed to decrypt a2a_auth_headers for node_id={node_id}: {exc}")
        return None


def prepare_node_data_for_save(node_data: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[Dict[str, str]]]:
    """
    If node has plain a2a_auth_headers, return (data_copy_without_plain_headers, headers_to_store).

    Caller must call ``store_a2a_auth_headers(payload_secrets, node_id, headers_to_store)``
    after receiving the returned headers dict, then set::

        data_copy["config"]["a2a_auth_headers"] = {"__secretRef": str(node_id)}
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


def hydrate_nodes_a2a_secrets(payload_secrets: Dict[str, Any], nodes: List[Any]) -> None:
    """Resolve ``__secretRef`` in each node's a2a_auth_headers in-place (for execution only).

    Accepts either plain dicts (from definition_payload["nodes"]) or any
    object with a ``data`` dict attribute.

    ``payload_secrets`` is ``definition_payload.get("node_secrets", {})``.
    """
    for node in nodes:
        # Support both plain dicts and data-holder objects.
        if isinstance(node, dict):
            node_id = node.get("id", "")
            data = node.get("data") or {}
        else:
            node_id = getattr(node, "id", "")
            data = getattr(node, "data", None) or {}

        config = data.get("config") or {}
        raw = config.get("a2a_auth_headers")
        if not isinstance(raw, dict) or REF_KEY not in raw:
            continue

        resolved = resolve_a2a_auth_headers(payload_secrets, node_id)
        config["a2a_auth_headers"] = resolved if resolved is not None else {}

        # Write back — handle both dict nodes and object nodes.
        if "config" not in data:
            data["config"] = config
        if isinstance(node, dict):
            node["data"] = data
        else:
            node.data = data
