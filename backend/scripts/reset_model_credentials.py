"""
Script to reset the model credentials table (model_credential).

Use cases:
- CREDENTIAL_ENCRYPTION_KEY / ENCRYPTION_KEY was not pinned in environment variables,
  causing a new random key to be generated on each restart.
- The old key is lost, so historically encrypted model credentials cannot be decrypted,
  causing default model / model loading failures.

This script clears all records from the model_credential table in confirmation mode,
so that after configuring a new fixed key, model credentials can be re-entered via the frontend.

Warning:
- This script deletes all model credential records (model_credential table only),
  but does NOT delete model provider or model instance configurations.
- After deletion, historical credentials cannot be recovered, but if the key is lost
  they were already undecryptable anyway.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.settings import settings


def _mask_database_url(url: str | None) -> str:
    """Simple masking of database URL (hides password)"""
    if not url:
        return "<unknown>"
    # e.g.: postgresql+asyncpg://user:password@host:port/db
    try:
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        # user:password@host...
        if "@" not in rest or ":" not in rest.split("@", 1)[0]:
            return f"{scheme}://***@{rest.split('@', 1)[-1]}" if "@" in rest else f"{scheme}://{rest}"
        auth, tail = rest.split("@", 1)
        user = auth.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    except Exception:
        return "<masked>"


async def reset_model_credentials(dry_run: bool = True) -> None:
    """
    Reset the model_credential table.

    - dry_run=True: only preview how many records would be deleted, no actual deletion.
    - dry_run=False: actually delete all records.
    """
    key = getattr(settings, "credential_encryption_key", None)
    if not key:
        print(
            "[ERROR] credential_encryption_key is not configured.\n"
            "Please set CREDENTIAL_ENCRYPTION_KEY (or alias ENCRYPTION_KEY) in your environment "
            "variables or .env file, and make sure not to change it afterwards."
        )
        return

    # Read database URL from env vars (not relying on settings) for logging purposes
    import os

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        # If DATABASE_URL is not set directly, build from POSTGRES_* env vars
        user = os.getenv("POSTGRES_USER", "")
        password = os.getenv("POSTGRES_PASSWORD", "")
        host = os.getenv("POSTGRES_HOST", "")
        port = os.getenv("POSTGRES_PORT", "")
        db_name = os.getenv("POSTGRES_DB", "")
        if all([user, host, port, db_name]):
            if password:
                db_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
            else:
                db_url = f"postgresql+asyncpg://{user}@{host}:{port}/{db_name}"
        else:
            db_url = None

    masked_db_url = _mask_database_url(db_url)
    print(f"[INFO] Current database connection (masked): {masked_db_url}")

    async with AsyncSessionLocal() as session:
        # Use raw SQL to avoid triggering full ORM mapper initialization (bypass UserSandbox dependencies)
        result = await session.execute(text("SELECT COUNT(*) FROM model_credential"))
        total: int = result.scalar_one()
        print(f"[INFO] Current model_credential record count: {total}")

        if dry_run:
            print("[DRY-RUN] Preview mode: no deletions will be performed.")
            print("[DRY-RUN] If you proceed with the actual reset, all model credential records above will be deleted.")
            return

        if total == 0:
            print("[INFO] model_credential table is already empty, nothing to delete.")
            return

        print(
            "[WARN] About to delete all model credential records (model_credential table).\n"
            "       This operation is irreversible, but since the old key is lost, the encrypted data\n"
            "       was already undecryptable.\n"
            "       After deletion, you will need to re-enter API keys and other credentials via the frontend."
        )

        await session.execute(text("DELETE FROM model_credential"))
        await session.commit()

        print("[DONE] model_credential table has been cleared.")
        print("[NEXT] Please re-configure model provider credentials and set the default model via the admin UI.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reset the model credentials table (model_credential). Runs in dry-run preview mode by default; use --force for actual deletion."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only: show how many records would be deleted (default behavior).",
    )
    group.add_argument(
        "--force",
        action="store_true",
        help="Actually perform the deletion, clearing the model_credential table.",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> None:
    # Default to dry-run unless --force is explicitly specified
    dry_run = not args.force
    if args.dry_run:
        dry_run = True

    mode = "DRY-RUN (preview)" if dry_run else "FORCE (actual deletion)"
    print(f"[INFO] Run mode: {mode}")

    await reset_model_credentials(dry_run=dry_run)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
