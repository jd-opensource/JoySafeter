"""add provider_name to model_credential and model_instance (Direction A: template not in DB)

Revision ID: d7e8f9a0b1c2
Revises: 0faa0dc41210
Create Date: 2026-03-07 12:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "0faa0dc41210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # model_credential: add provider_name, make provider_id nullable
    op.add_column(
        "model_credential",
        sa.Column(
            "provider_name",
            sa.String(length=100),
            nullable=True,
            comment="Template provider name, used when provider_id is null",
        ),
    )
    op.alter_column(
        "model_credential",
        "provider_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_index("model_credential_provider_name_idx", "model_credential", ["provider_name"], unique=False)
    # Partial unique: one credential per (user_id, workspace_id, provider_name) when template
    op.execute(
        """
        CREATE UNIQUE INDEX uq_model_credential_user_workspace_provider_name
        ON model_credential (user_id, workspace_id, provider_name)
        WHERE provider_id IS NULL AND provider_name IS NOT NULL
        """
    )
    # When provider_id is set, keep existing uniqueness via application logic / existing index on provider_id

    # model_instance: add provider_name, make provider_id nullable, replace unique constraint
    op.add_column(
        "model_instance",
        sa.Column(
            "provider_name",
            sa.String(length=100),
            nullable=True,
            comment="Template provider name, used when provider_id is null",
        ),
    )
    op.drop_constraint("uq_model_instance_user_provider_model", "model_instance", type_="unique")
    op.alter_column(
        "model_instance",
        "provider_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_index("model_instance_provider_name_idx", "model_instance", ["provider_name"], unique=False)
    # Partial unique: (user_id, workspace_id, provider_id, model_name) when provider_id is not null
    op.execute(
        """
        CREATE UNIQUE INDEX uq_model_instance_user_workspace_provider_id_model
        ON model_instance (user_id, workspace_id, provider_id, model_name)
        WHERE provider_id IS NOT NULL
        """
    )
    # Partial unique: (user_id, workspace_id, provider_name, model_name) when template
    op.execute(
        """
        CREATE UNIQUE INDEX uq_model_instance_user_workspace_provider_name_model
        ON model_instance (user_id, workspace_id, provider_name, model_name)
        WHERE provider_id IS NULL AND provider_name IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("uq_model_instance_user_workspace_provider_name_model", table_name="model_instance")
    op.drop_index("uq_model_instance_user_workspace_provider_id_model", table_name="model_instance")
    op.drop_index("model_instance_provider_name_idx", table_name="model_instance")
    op.alter_column(
        "model_instance",
        "provider_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_model_instance_user_provider_model",
        "model_instance",
        ["user_id", "workspace_id", "provider_id", "model_name"],
    )
    op.drop_column("model_instance", "provider_name")

    op.drop_index("uq_model_credential_user_workspace_provider_name", table_name="model_credential")
    op.drop_index("model_credential_provider_name_idx", table_name="model_credential")
    op.alter_column(
        "model_credential",
        "provider_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("model_credential", "provider_name")
