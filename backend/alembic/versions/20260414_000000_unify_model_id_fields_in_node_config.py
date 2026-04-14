"""Unify model identifier fields in graph_nodes.data.config.

Migrate legacy model fields to the canonical (provider_name, model_name) pair:
  - "model" (combined "provider:model") → split into provider_name + model_name
  - "provider" → provider_name
  - "memoryModel" (combined) → split into memory_provider_name + memory_model_name
  - "memoryProvider" → memory_provider_name

After this migration, frontend/backend compat fallbacks for the old field names
can be removed.

Revision ID: 0f7082711f20
Revises: 4a6b5e9517ae
Create Date: 2026-04-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f7082711f20"
down_revision: Union[str, None] = "4a6b5e9517ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Migrate main model fields: split combined "model" into provider_name + model_name,
    #    and copy standalone "provider" to provider_name.
    #    Single UPDATE with CASE to avoid multiple table scans.
    op.execute("""
        UPDATE graph_nodes
        SET data = jsonb_set(
            jsonb_set(
                data,
                '{config,provider_name}',
                to_jsonb(COALESCE(
                    NULLIF(data->'config'->>'provider_name', ''),
                    NULLIF(data->'config'->>'provider', ''),
                    CASE
                        WHEN data->'config'->>'model' LIKE '%:%'
                        THEN split_part(data->'config'->>'model', ':', 1)
                        ELSE NULL
                    END,
                    ''
                ))
            ),
            '{config,model_name}',
            to_jsonb(COALESCE(
                NULLIF(data->'config'->>'model_name', ''),
                CASE
                    WHEN data->'config'->>'model' LIKE '%:%'
                    THEN substring(data->'config'->>'model' from position(':' in data->'config'->>'model') + 1)
                    WHEN data->'config'->>'model' IS NOT NULL AND data->'config'->>'model' != ''
                    THEN data->'config'->>'model'
                    ELSE NULL
                END,
                ''
            ))
        )
        WHERE data ? 'config'
          AND (
              data->'config' ? 'model'
              OR data->'config' ? 'provider'
          )
    """)

    # 2. Migrate memory model fields: split combined "memoryModel" into
    #    memory_provider_name + memory_model_name, copy "memoryProvider".
    op.execute("""
        UPDATE graph_nodes
        SET data = jsonb_set(
            jsonb_set(
                data,
                '{config,memory_provider_name}',
                to_jsonb(COALESCE(
                    NULLIF(data->'config'->>'memory_provider_name', ''),
                    NULLIF(data->'config'->>'memoryProvider', ''),
                    CASE
                        WHEN data->'config'->>'memoryModel' LIKE '%:%'
                        THEN split_part(data->'config'->>'memoryModel', ':', 1)
                        ELSE NULL
                    END,
                    ''
                ))
            ),
            '{config,memory_model_name}',
            to_jsonb(COALESCE(
                NULLIF(data->'config'->>'memory_model_name', ''),
                CASE
                    WHEN data->'config'->>'memoryModel' LIKE '%:%'
                    THEN substring(data->'config'->>'memoryModel' from position(':' in data->'config'->>'memoryModel') + 1)
                    WHEN data->'config'->>'memoryModel' IS NOT NULL AND data->'config'->>'memoryModel' != ''
                    THEN data->'config'->>'memoryModel'
                    ELSE NULL
                END,
                ''
            ))
        )
        WHERE data ? 'config'
          AND (
              data->'config' ? 'memoryModel'
              OR data->'config' ? 'memoryProvider'
          )
    """)

    # 3. Remove legacy fields from config
    op.execute("""
        UPDATE graph_nodes
        SET data = data #- '{config,model}' #- '{config,provider}' #- '{config,memoryModel}' #- '{config,memoryProvider}'
        WHERE data ? 'config'
          AND (
              data->'config' ? 'model'
              OR data->'config' ? 'provider'
              OR data->'config' ? 'memoryModel'
              OR data->'config' ? 'memoryProvider'
          )
    """)


def downgrade() -> None:
    # Reconstruct combined "model" and "provider" from provider_name + model_name
    op.execute("""
        UPDATE graph_nodes
        SET data = jsonb_set(
            jsonb_set(
                data,
                '{config,model}',
                to_jsonb(
                    CASE
                        WHEN data->'config'->>'provider_name' IS NOT NULL
                             AND data->'config'->>'provider_name' != ''
                        THEN data->'config'->>'provider_name' || ':' || COALESCE(data->'config'->>'model_name', '')
                        ELSE COALESCE(data->'config'->>'model_name', '')
                    END
                )
            ),
            '{config,provider}',
            to_jsonb(COALESCE(data->'config'->>'provider_name', ''))
        )
        WHERE data ? 'config'
          AND data->'config'->>'model_name' IS NOT NULL
          AND data->'config'->>'model_name' != ''
    """)

    # Reconstruct "memoryModel" and "memoryProvider" from memory_provider_name + memory_model_name
    op.execute("""
        UPDATE graph_nodes
        SET data = jsonb_set(
            jsonb_set(
                data,
                '{config,memoryModel}',
                to_jsonb(
                    CASE
                        WHEN data->'config'->>'memory_provider_name' IS NOT NULL
                             AND data->'config'->>'memory_provider_name' != ''
                        THEN data->'config'->>'memory_provider_name' || ':' || COALESCE(data->'config'->>'memory_model_name', '')
                        ELSE COALESCE(data->'config'->>'memory_model_name', '')
                    END
                )
            ),
            '{config,memoryProvider}',
            to_jsonb(COALESCE(data->'config'->>'memory_provider_name', ''))
        )
        WHERE data ? 'config'
          AND data->'config'->>'memory_model_name' IS NOT NULL
          AND data->'config'->>'memory_model_name' != ''
    """)

    # Remove new fields added by upgrade
    op.execute("""
        UPDATE graph_nodes
        SET data = data #- '{config,provider_name}' #- '{config,model_name}' #- '{config,memory_provider_name}' #- '{config,memory_model_name}'
        WHERE data ? 'config'
          AND (
              data->'config' ? 'provider_name'
              OR data->'config' ? 'model_name'
              OR data->'config' ? 'memory_provider_name'
              OR data->'config' ? 'memory_model_name'
          )
    """)
