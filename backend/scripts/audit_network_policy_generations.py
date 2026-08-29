"""Audit and optionally repair persisted sandbox network-policy generations."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from urllib.parse import quote_plus

import psycopg

KNOWN_STATUSES = frozenset({"disabled", "pending", "ready", "nacked", "failed"})
REPAIR_REASON = "network policy generation invariant repair required"


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def classify_network_policy_state(row: Mapping[str, object]) -> tuple[str, ...]:
    status = row["networking_status"]
    if status not in KNOWN_STATUSES:
        return ("unknown_status",)

    desired_hash = row["networking_policy_hash"]
    desired_version = row["networking_policy_version"]
    applied_hash = row["networking_applied_hash"]
    applied_version = row["networking_applied_version"]
    desired_valid = (desired_hash is None and desired_version == 0) or (
        _non_empty(desired_hash) and isinstance(desired_version, int) and desired_version > 0
    )
    applied_valid = (applied_hash is None and applied_version is None) or (
        _non_empty(applied_hash) and isinstance(applied_version, int) and applied_version > 0
    )
    ready_valid = status != "ready" or (
        _non_empty(desired_hash)
        and _non_empty(applied_hash)
        and isinstance(desired_version, int)
        and isinstance(applied_version, int)
        and desired_version > 0
        and applied_version > 0
        and desired_hash == applied_hash
        and desired_version == applied_version
    )

    violations: list[str] = []
    if not desired_valid or (status == "ready" and not _non_empty(desired_hash)):
        violations.append("invalid_desired_generation")
    if not applied_valid or (status == "ready" and not _non_empty(applied_hash)):
        violations.append("invalid_applied_generation")
    if not ready_valid:
        violations.append("invalid_ready_generation")
    return tuple(violations)


def _database_url() -> str:
    if url := os.getenv("DATABASE_URL"):
        return url.replace("postgresql+asyncpg://", "postgresql://")
    user = quote_plus(os.getenv("POSTGRES_USER", "postgres"))
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "postgres"))
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "joysafeter")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def audit(*, repair: bool) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    with psycopg.connect(_database_url()) as connection:
        rows = connection.execute(
            """
            SELECT id::text, networking_status, networking_policy_hash,
                   networking_policy_version, networking_applied_hash,
                   networking_applied_version
            FROM joysafeter_sandboxes
            ORDER BY id
            FOR UPDATE
            """
        ).fetchall()
        columns = (
            "id",
            "networking_status",
            "networking_policy_hash",
            "networking_policy_version",
            "networking_applied_hash",
            "networking_applied_version",
        )
        for values in rows:
            row = dict(zip(columns, values, strict=True))
            categories = classify_network_policy_state(row)
            if not categories:
                continue
            findings.append({"sandbox_id": row["id"], "categories": categories})
            if repair:
                desired_valid = _non_empty(row["networking_policy_hash"]) and row[
                    "networking_policy_version"
                ] > 0
                applied_valid = _non_empty(row["networking_applied_hash"]) and isinstance(
                    row["networking_applied_version"], int
                ) and row["networking_applied_version"] > 0
                connection.execute(
                    """
                    UPDATE joysafeter_sandboxes
                    SET networking_status = 'failed',
                        networking_policy_hash = CASE WHEN %s THEN networking_policy_hash ELSE NULL END,
                        networking_policy_version = CASE WHEN %s THEN networking_policy_version ELSE 0 END,
                        networking_applied_hash = CASE WHEN %s THEN networking_applied_hash ELSE NULL END,
                        networking_applied_version = CASE WHEN %s THEN networking_applied_version ELSE NULL END,
                        networking_last_error = %s,
                        networking_ready_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (desired_valid, desired_valid, applied_valid, applied_valid, REPAIR_REASON, row["id"]),
                )
        if not repair:
            connection.rollback()
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true", help="repair invalid rows fail-closed")
    args = parser.parse_args()
    findings = audit(repair=args.repair)
    print(json.dumps({"count": len(findings), "findings": findings}, sort_keys=True))
    return 0 if args.repair or not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
