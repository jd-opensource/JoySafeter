"""encrypt JoySafeter managed secret data

Revision ID: 20260617_000001
Revises: 20260608_000001
Create Date: 2026-06-17 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.joysafeter_domain.services.vault_cipher import VaultCipher
from app.joysafeter_shared.config.settings import joysafeter_config

revision: str = "20260617_000001"
down_revision: Union[str, tuple[str, str], None] = "20260608_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cipher = VaultCipher(joysafeter_config.vault_encryption_key)
    bind = op.get_bind()
    existing_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM joysafeter_secrets WHERE data IS NOT NULL AND data != '{}'::jsonb")
    ).scalar_one()
    if existing_count and not cipher.is_enabled:
        raise RuntimeError(
            "JOYSAFETER_VAULT_ENCRYPTION_KEY is required to encrypt existing joysafeter_secrets.data"
        )
    if not cipher.is_enabled:
        return

    rows = bind.execute(
        sa.text("SELECT id, data FROM joysafeter_secrets WHERE data IS NOT NULL")
    ).mappings()
    update_stmt = sa.text(
        "UPDATE joysafeter_secrets SET data = :data WHERE id = :id"
    ).bindparams(sa.bindparam("data", type_=postgresql.JSONB))

    for row in rows:
        stored = dict(row["data"] or {})
        encrypted: dict[str, str] = {}
        changed = False
        for key, value in stored.items():
            key_str = str(key)
            value_str = str(value)
            if value_str.startswith("enc:"):
                encrypted[key_str] = value_str
            else:
                encrypted[key_str] = cipher.encrypt(value_str)
                changed = True
        if changed:
            bind.execute(update_stmt, {"id": row["id"], "data": encrypted})


def downgrade() -> None:
    # Irreversible on purpose: do not write plaintext API keys back to the DB.
    pass
