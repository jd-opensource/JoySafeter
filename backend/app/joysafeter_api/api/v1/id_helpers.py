"""Helpers for parsing prefixed IDs in path parameters.

The Rust joysafeter API returns and accepts IDs with prefixes like
``agent_<uuid>``, ``sess_<uuid>``, ``env_<uuid>``.  These helpers
strip the prefix so that FastAPI can validate the underlying UUID.
"""

import uuid

from fastapi import Path

from app.joysafeter_shared.common.app_errors import AppError, InvalidRequestError


def _invalid_id_error(*, raw: str, field: str, prefix: str) -> AppError:
    return InvalidRequestError(
        code=f"{field.upper()}_INVALID",
        message=f"Invalid {field}: {raw}",
        data={
            "field": field,
            field: raw,
            "expected_prefix": prefix,
        },
        user_action="fix_input",
    )


def _strip_prefix(raw: str, prefix: str, field: str) -> uuid.UUID:
    s = raw.removeprefix(prefix)
    try:
        return uuid.UUID(s)
    except ValueError:
        raise _invalid_id_error(raw=raw, field=field, prefix=prefix)


def parse_agent_id(agent_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(agent_id, "agent_", "agent_id")


def parse_session_id(session_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(session_id, "sess_", "session_id")


def parse_env_id(env_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(env_id, "env_", "env_id")


def parse_secret_id(secret_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(secret_id, "secret_", "secret_id")


def parse_schedule_id(schedule_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(schedule_id, "sched_", "schedule_id")


def parse_trigger_id(trigger_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(trigger_id, "trig_", "trigger_id")


def parse_memory_store_id(store_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(store_id, "memstore_", "store_id")


def parse_memory_id(memory_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(memory_id, "mem_", "memory_id")


def parse_memory_version_id(version_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(version_id, "memver_", "version_id")


def parse_sandbox_id(sandbox_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(sandbox_id, "sbx_", "sandbox_id")


def parse_vault_id(vault_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(vault_id, "vault_", "vault_id")


def parse_cred_id(cred_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(cred_id, "cred_", "cred_id")


def parse_skill_id(skill_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(skill_id, "skill_", "skill_id")


def parse_skill_file_id(file_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(file_id, "sklfile_", "file_id")


def parse_skill_security_scan_id(scan_id: str = Path(...)) -> uuid.UUID:
    return _strip_prefix(scan_id, "sklscan_", "scan_id")
