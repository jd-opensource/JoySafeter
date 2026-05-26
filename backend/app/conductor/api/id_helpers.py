"""Helpers for parsing prefixed IDs in path parameters.

The Rust conductor API returns and accepts IDs with prefixes like
``agent_<uuid>``, ``sess_<uuid>``, ``env_<uuid>``.  These helpers
strip the prefix so that FastAPI can validate the underlying UUID.
"""
import uuid

from fastapi import HTTPException, Path


def _strip_prefix(raw: str, prefix: str) -> uuid.UUID:
    s = raw.removeprefix(prefix)
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(400, f"Invalid ID: {raw}")


def parse_agent_id(agent_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(agent_id, "agent_")


def parse_session_id(session_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(session_id, "sess_")


def parse_env_id(env_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(env_id, "env_")


def parse_secret_id(secret_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(secret_id, "")


def parse_sandbox_id(sandbox_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(sandbox_id, "sbx_")


def parse_vault_id(vault_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(vault_id, "vault_")


def parse_cred_id(cred_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(cred_id, "cred_")
