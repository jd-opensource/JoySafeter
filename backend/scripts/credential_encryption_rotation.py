"""Operate and inspect the credential-encryption key rotation lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.joysafeter_application.sensitive_material_cleanup import (  # noqa: E402
    rewrap_sensitive_material,
    verify_sensitive_material_integrity,
)
from app.joysafeter_infrastructure.sensitive_material import (  # noqa: E402
    VersionedMaterialProtector,
    inspect_sensitive_material_envelopes,
    validate_credential_encryption_storage_coverage,
)
from app.joysafeter_shared.config.settings import joysafeter_config  # noqa: E402
from app.joysafeter_shared.database import async_session_factory, engine  # noqa: E402
from app.joysafeter_shared.security.credential_cipher import CredentialCipher  # noqa: E402
from app.joysafeter_shared.security.credential_encryption_canary import (  # noqa: E402
    initialize_missing_credential_encryption_canaries,
    validate_credential_encryption_canaries,
)


async def _run(*, initialize_missing_canaries: bool, rewrap_batch: int) -> dict[str, object]:
    cipher = CredentialCipher(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    )
    cipher.require_enabled()
    protector = VersionedMaterialProtector(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    )
    try:
        async with async_session_factory() as db:
            if initialize_missing_canaries:
                created = await initialize_missing_credential_encryption_canaries(db, cipher)
            else:
                await validate_credential_encryption_canaries(db, cipher)
                created = ()
            before = await inspect_sensitive_material_envelopes(db)
            rewrapped = (
                await rewrap_sensitive_material(db, protector, limit_per_store=rewrap_batch) if rewrap_batch else None
            )
            await validate_credential_encryption_storage_coverage(db, cipher)
            await db.commit()
            after = await inspect_sensitive_material_envelopes(db)
        return {
            "active_write_key_id": cipher.write_key_id,
            "configured_key_ids": list(cipher.configured_key_ids),
            "created_canary_key_ids": list(created),
            "inventory_before": [asdict(entry) for entry in before],
            "rewrapped": None if rewrapped is None else asdict(rewrapped),
            "inventory_after": [asdict(entry) for entry in after],
            "status": "ok",
        }
    finally:
        await engine.dispose()


async def _run_integrity_verification(*, batch_size: int) -> dict[str, object]:
    protector = VersionedMaterialProtector(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    )
    protector.require_enabled()
    try:
        async with async_session_factory() as db:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            result = await verify_sensitive_material_integrity(db, protector, batch_size=batch_size)
            await db.rollback()
        return {
            "integrity": asdict(result),
            "status": "ok" if result.invalid_values == 0 else "failed",
        }
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--initialize-missing-canaries",
        action="store_true",
        help="Create canaries for configured key IDs after validating existing rows.",
    )
    parser.add_argument(
        "--rewrap-batch",
        type=int,
        default=0,
        help="Rewrap at most this many rows per sensitive-material store.",
    )
    parser.add_argument(
        "--verify-integrity",
        action="store_true",
        help="Decrypt-verify every persisted non-empty sensitive value without writing data.",
    )
    parser.add_argument(
        "--integrity-batch-size",
        type=int,
        default=500,
        help="Rows fetched per store page during --verify-integrity.",
    )
    args = parser.parse_args(argv)
    if args.rewrap_batch < 0:
        parser.error("--rewrap-batch must be non-negative")
    if args.integrity_batch_size < 1:
        parser.error("--integrity-batch-size must be positive")
    if args.verify_integrity and args.initialize_missing_canaries:
        parser.error("--verify-integrity cannot be combined with --initialize-missing-canaries")
    if args.verify_integrity and args.rewrap_batch:
        parser.error("--verify-integrity cannot be combined with --rewrap-batch")
    if not args.verify_integrity and args.integrity_batch_size != 500:
        parser.error("--integrity-batch-size requires --verify-integrity")

    if args.verify_integrity:
        result = asyncio.run(_run_integrity_verification(batch_size=args.integrity_batch_size))
    else:
        result = asyncio.run(
            _run(
                initialize_missing_canaries=args.initialize_missing_canaries,
                rewrap_batch=args.rewrap_batch,
            )
        )
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
