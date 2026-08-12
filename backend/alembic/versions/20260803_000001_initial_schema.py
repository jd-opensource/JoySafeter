"""initial JoySafeter schema

Revision ID: 20260803_000001
Revises:
Create Date: 2026-08-03 00:00:00.000000

This migration creates the complete pre-release schema, including indexes,
constraints, runtime sequences, and cluster membership objects.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260803_000001"
down_revision: Union[str, None] = None
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("joysafeter_task_owner_epoch_seq")))

    op.create_table('joysafeter_agent_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_agent_versions')),
    sa.UniqueConstraint('agent_id', 'version', name=op.f('uq_joysafeter_agent_versions_agent_id'))
    )
    op.create_table('joysafeter_agents',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('engine_kind', sa.Text(), nullable=False),
    sa.Column('model', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('system_prompt', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('env', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('mcp_servers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('skills', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('tools', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('agents', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('commands', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('permission_mode', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('multiagent', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('environment_ref', sa.Text(), nullable=True),
    sa.Column('model_credential_id', sa.UUID(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_agents'))
    )
    op.create_index('idx_ca_created_at', 'joysafeter_agents', ['created_at'], unique=False)
    op.create_index('idx_ca_project', 'joysafeter_agents', ['project_id'], unique=False)
    op.create_index(op.f('ix_joysafeter_agents_model_credential_id'), 'joysafeter_agents', ['model_credential_id'], unique=False)
    op.create_index(op.f('ix_joysafeter_agents_project_id'), 'joysafeter_agents', ['project_id'], unique=False)
    op.create_index('uq_joysafeter_agents_global_name', 'joysafeter_agents', ['name'], unique=True, postgresql_where=sa.text('project_id IS NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NULL AND deleted_at IS NULL'))
    op.create_index('uq_joysafeter_agents_project_name', 'joysafeter_agents', ['project_id', 'name'], unique=True, postgresql_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_table('joysafeter_api_keys',
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('org_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key_hash', sa.Text(), nullable=False),
    sa.Column('key_prefix', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_api_keys'))
    )
    op.create_index('idx_cak_key_hash', 'joysafeter_api_keys', ['key_hash'], unique=False)
    op.create_index('idx_cak_org', 'joysafeter_api_keys', ['org_id'], unique=False)
    op.create_index('idx_cak_project', 'joysafeter_api_keys', ['project_id'], unique=False)
    op.create_table('joysafeter_auth_sessions',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('token', sa.String(length=255), nullable=False),
    sa.Column('ip_address', sa.String(length=255), nullable=True),
    sa.Column('user_agent', sa.String(length=1024), nullable=True),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('active_organization_id', sa.String(length=255), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device_fingerprint', sa.String(length=255), nullable=True),
    sa.Column('device_name', sa.String(length=255), nullable=True),
    sa.Column('is_trusted', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_auth_sessions')),
    sa.UniqueConstraint('token', name=op.f('uq_joysafeter_auth_sessions_token'))
    )
    op.create_index('idx_joysafeter_auth_sessions_expires', 'joysafeter_auth_sessions', ['expires_at'], unique=False)
    op.create_index('idx_joysafeter_auth_sessions_last_activity', 'joysafeter_auth_sessions', ['last_activity_at'], unique=False)
    op.create_index('ix_joysafeter_auth_sessions_token', 'joysafeter_auth_sessions', ['token'], unique=True)
    op.create_index('ix_joysafeter_auth_sessions_user_id', 'joysafeter_auth_sessions', ['user_id'], unique=False)
    op.create_table('joysafeter_environments',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('image_tag', sa.Text(), nullable=True),
    sa.Column('image_version', sa.Integer(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_environments'))
    )
    op.create_index(op.f('ix_joysafeter_environments_project_id'), 'joysafeter_environments', ['project_id'], unique=False)
    op.create_index('uq_joysafeter_environments_global_name', 'joysafeter_environments', ['name'], unique=True, postgresql_where=sa.text('project_id IS NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NULL AND deleted_at IS NULL'))
    op.create_index('uq_joysafeter_environments_project_name', 'joysafeter_environments', ['project_id', 'name'], unique=True, postgresql_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_table('joysafeter_files',
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('purpose', sa.String(length=50), nullable=False),
    sa.Column('content_type', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('downloadable', sa.Boolean(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_files'))
    )
    op.create_index('idx_joysafeter_files_deleted', 'joysafeter_files', ['deleted_at'], unique=False)
    op.create_index('idx_joysafeter_files_project_created', 'joysafeter_files', ['project_id', 'created_at'], unique=False)
    op.create_index('idx_joysafeter_files_session', 'joysafeter_files', ['session_id'], unique=False)
    op.create_index(op.f('ix_joysafeter_files_project_id'), 'joysafeter_files', ['project_id'], unique=False)
    op.create_table('joysafeter_memories',
    sa.Column('store_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_sha256', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_memories')),
    sa.UniqueConstraint('store_id', 'path', name=op.f('uq_joysafeter_memories_store_id'))
    )
    op.create_table('joysafeter_memory_stores',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_memory_stores'))
    )
    op.create_index(op.f('ix_joysafeter_memory_stores_project_id'), 'joysafeter_memory_stores', ['project_id'], unique=False)
    op.create_table('joysafeter_memory_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('store_id', sa.UUID(), nullable=False),
    sa.Column('memory_id', sa.UUID(), nullable=False),
    sa.Column('operation', sa.Text(), nullable=False),
    sa.Column('path', sa.Text(), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('content_sha256', sa.Text(), nullable=True),
    sa.Column('content_size_bytes', sa.Integer(), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('api_key_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('redacted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('redacted_by', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_memory_versions'))
    )
    op.create_index('idx_joysafeter_memory_versions_session_created', 'joysafeter_memory_versions', ['session_id', 'created_at'], unique=False)
    op.create_index('idx_joysafeter_memory_versions_store_created', 'joysafeter_memory_versions', ['store_id', 'created_at'], unique=False)
    op.create_table('joysafeter_oauth_account',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('provider_account_id', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('access_token', sa.Text(), nullable=True),
    sa.Column('refresh_token', sa.Text(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('raw_userinfo', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_oauth_account'))
    )
    op.create_index('ix_joysafeter_oauth_account_provider_account', 'joysafeter_oauth_account', ['provider', 'provider_account_id'], unique=True)
    op.create_index('ix_joysafeter_oauth_account_user_id', 'joysafeter_oauth_account', ['user_id'], unique=False)
    op.create_table('joysafeter_organization_members',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('organization_id', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_organization_members')),
    sa.UniqueConstraint('organization_id', 'user_id', name='uq_joysafeter_organization_members_org_user')
    )
    op.create_index('ix_joysafeter_organization_members_organization_id', 'joysafeter_organization_members', ['organization_id'], unique=False)
    op.create_index('ix_joysafeter_organization_members_user_id', 'joysafeter_organization_members', ['user_id'], unique=False)
    op.create_table('joysafeter_organization_projects',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('org_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('triggers_paused', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('max_concurrent_tasks', sa.Integer(), nullable=True),
    sa.Column('max_cpu', sa.Float(), nullable=True),
    sa.Column('max_memory_mb', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_organization_projects')),
    sa.UniqueConstraint('org_id', 'slug', name='uq_joysafeter_organization_projects_org_slug')
    )
    op.create_index('ix_joysafeter_organization_projects_org_id', 'joysafeter_organization_projects', ['org_id'], unique=False)
    op.create_index('uq_joysafeter_organization_projects_active_default', 'joysafeter_organization_projects', ['org_id'], unique=True, postgresql_where=sa.text('is_default IS TRUE AND archived_at IS NULL'), sqlite_where=sa.text('is_default = 1 AND archived_at IS NULL'))
    op.create_table('joysafeter_organizations',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('logo', sa.String(length=500), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('org_usage_limit', sa.Numeric(), nullable=True),
    sa.Column('storage_used_bytes', sa.BigInteger(), nullable=False),
    sa.Column('departed_member_usage', sa.Numeric(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_organizations'))
    )
    op.create_table('joysafeter_project_members',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_project_members')),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_joysafeter_project_members_project_user')
    )
    op.create_index('ix_joysafeter_project_members_project_id', 'joysafeter_project_members', ['project_id'], unique=False)
    op.create_index('ix_joysafeter_project_members_user_id', 'joysafeter_project_members', ['user_id'], unique=False)
    op.create_table('joysafeter_sandbox_network_policies',
    sa.Column('sandbox_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('task_id', sa.UUID(), nullable=True),
    sa.Column('policy_hash', sa.Text(), nullable=False),
    sa.Column('policy_version', sa.BigInteger(), nullable=False),
    sa.Column('desired_policy_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('rendered_summary_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_nack_reason', sa.Text(), nullable=True),
    sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_sandbox_network_policies')),
    sa.UniqueConstraint('sandbox_id', 'policy_version', name='uq_jsnp_sandbox_policy_version')
    )
    op.create_index('idx_jsnp_acked_at', 'joysafeter_sandbox_network_policies', ['acked_at'], unique=False)
    op.create_index('idx_jsnp_created_at', 'joysafeter_sandbox_network_policies', ['created_at'], unique=False)
    op.create_index('idx_jsnp_policy_hash', 'joysafeter_sandbox_network_policies', ['policy_hash'], unique=False)
    op.create_index('idx_jsnp_pushed_at', 'joysafeter_sandbox_network_policies', ['pushed_at'], unique=False)
    op.create_index('idx_jsnp_sandbox_status', 'joysafeter_sandbox_network_policies', ['sandbox_id', 'status'], unique=False)
    op.create_index('idx_jsnp_status_updated_at', 'joysafeter_sandbox_network_policies', ['status', 'updated_at'], unique=False)
    op.create_table('joysafeter_sandboxes',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('chat_session_id', sa.UUID(), nullable=True),
    sa.Column('image', sa.Text(), nullable=False),
    sa.Column('last_task_id', sa.UUID(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('idle_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('destroyed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_path', sa.Text(), nullable=True),
    sa.Column('networking_status', sa.Text(), server_default='disabled', nullable=False),
    sa.Column('networking_policy_hash', sa.Text(), nullable=True),
    sa.Column('networking_policy_version', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('networking_last_error', sa.Text(), nullable=True),
    sa.Column('networking_ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_sandboxes'))
    )
    op.create_index('idx_csb_active_session_unique', 'joysafeter_sandboxes', ['chat_session_id'], unique=True, postgresql_where="chat_session_id IS NOT NULL AND destroyed_at IS NULL AND status IN ('creating', 'provisioning', 'idle', 'running', 'stopped', 'error')")
    op.create_index('idx_csb_destroyed', 'joysafeter_sandboxes', ['destroyed_at'], unique=False)
    op.create_index('idx_csb_last_used', 'joysafeter_sandboxes', ['last_used_at'], unique=False)
    op.create_index('idx_csb_pool', 'joysafeter_sandboxes', ['created_at'], unique=False, postgresql_where="status = 'pooled'")
    op.create_index('idx_csb_project', 'joysafeter_sandboxes', ['project_id'], unique=False)
    op.create_index('idx_csb_session', 'joysafeter_sandboxes', ['chat_session_id'], unique=False, postgresql_where='chat_session_id IS NOT NULL')
    op.create_index('idx_csb_status', 'joysafeter_sandboxes', ['status'], unique=False)
    op.create_index('idx_csb_updated', 'joysafeter_sandboxes', ['updated_at'], unique=False)
    op.create_index(op.f('ix_joysafeter_sandboxes_project_id'), 'joysafeter_sandboxes', ['project_id'], unique=False)
    op.create_table('joysafeter_credential_groups',
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_credential_groups')),
    sa.UniqueConstraint('id', 'project_id', name='uq_credential_groups_id_project')
    )
    op.create_index(op.f('ix_joysafeter_credential_groups_project_id'), 'joysafeter_credential_groups', ['project_id'], unique=False)
    op.create_index('uq_credential_groups_project_name', 'joysafeter_credential_groups', ['project_id', 'name'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'), sqlite_where=sa.text('deleted_at IS NULL'))
    op.create_table('joysafeter_credentials',
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=True),
    sa.Column('protocol', sa.String(length=64), nullable=True),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('mcp_server_url', sa.Text(), nullable=True),
    sa.Column('normalized_mcp_server_url', sa.Text(), nullable=True),
    sa.Column('credential_type', sa.Text(), nullable=True),
    sa.Column('oauth_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('group_id', sa.UUID(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'model' AND provider IS NOT NULL AND protocol IS NOT NULL AND mcp_server_url IS NULL AND group_id IS NULL) OR (kind = 'mcp' AND mcp_server_url IS NOT NULL AND group_id IS NOT NULL AND provider IS NULL AND protocol IS NULL AND is_default = false) OR (kind = 'service' AND provider IS NULL AND protocol IS NULL AND mcp_server_url IS NULL AND group_id IS NULL AND is_default = false)", name='ck_joysafeter_credentials_kind_identity'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_credentials'))
    )
    op.create_index(op.f('ix_joysafeter_credentials_project_id'), 'joysafeter_credentials', ['project_id'], unique=False)
    op.create_index('ix_joysafeter_credentials_group_id', 'joysafeter_credentials', ['group_id'], unique=False)
    op.create_index('uq_credentials_project_kind_name', 'joysafeter_credentials', ['project_id', 'kind', 'name'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'), sqlite_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_credentials_default_protocol', 'joysafeter_credentials', ['project_id', 'protocol'], unique=True, postgresql_where=sa.text("is_default = true AND kind = 'model' AND archived_at IS NULL AND deleted_at IS NULL"), sqlite_where=sa.text("is_default = true AND kind = 'model' AND archived_at IS NULL AND deleted_at IS NULL"))
    op.create_index('uq_credentials_group_url', 'joysafeter_credentials', ['group_id', 'normalized_mcp_server_url'], unique=True, postgresql_where=sa.text("kind = 'mcp' AND deleted_at IS NULL"), sqlite_where=sa.text("kind = 'mcp' AND deleted_at IS NULL"))
    op.create_table('joysafeter_session_credential_groups',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('credential_group_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('session_id', 'credential_group_id', name=op.f('pk_joysafeter_session_credential_groups'))
    )
    op.create_table('joysafeter_security_audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=True),
    sa.Column('user_email', sa.String(length=255), nullable=True),
    sa.Column('event_type', sa.String(length=50), nullable=False, comment='event type: login, logout, password_change, password_reset, 2fa_enable, account_lock, etc.'),
    sa.Column('event_status', sa.String(length=20), nullable=False, comment='event status: success, failure, blocked'),
    sa.Column('ip_address', sa.String(length=255), nullable=False),
    sa.Column('user_agent', sa.String(length=1024), nullable=True),
    sa.Column('device_fingerprint', sa.String(length=255), nullable=True),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('country', sa.String(length=10), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='extra info such as error reason, target entity, etc.'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_security_audit_logs'))
    )
    op.create_index('ix_joysafeter_security_audit_logs_created_at', 'joysafeter_security_audit_logs', ['created_at'], unique=False)
    op.create_index('ix_joysafeter_security_audit_logs_event_status', 'joysafeter_security_audit_logs', ['event_status'], unique=False)
    op.create_index('ix_joysafeter_security_audit_logs_event_type', 'joysafeter_security_audit_logs', ['event_type'], unique=False)
    op.create_index('ix_joysafeter_security_audit_logs_user_event', 'joysafeter_security_audit_logs', ['user_id', 'event_type'], unique=False)
    op.create_index('ix_joysafeter_security_audit_logs_user_id', 'joysafeter_security_audit_logs', ['user_id'], unique=False)
    op.create_table('joysafeter_session_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_session_events')),
    sa.UniqueConstraint('session_id', 'seq', name=op.f('uq_joysafeter_session_events_session_id'))
    )
    op.create_index('idx_cse_created_at', 'joysafeter_session_events', ['created_at'], unique=False)
    op.create_index('idx_cse_event_created', 'joysafeter_session_events', ['event_type', 'created_at'], unique=False)
    op.create_index('idx_cse_session_event_seq', 'joysafeter_session_events', ['session_id', 'event_type', 'seq'], unique=False)
    op.create_index('idx_cse_session_processed_event', 'joysafeter_session_events', ['session_id', 'processed_at', 'event_type'], unique=False)
    op.create_index('idx_cse_session_seq', 'joysafeter_session_events', ['session_id', 'seq'], unique=False)
    op.create_table('joysafeter_session_files',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=False),
    sa.Column('mount_path', sa.Text(), nullable=False),
    sa.Column('access', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_session_files'))
    )
    op.create_index('idx_session_files_created', 'joysafeter_session_files', ['created_at'], unique=False)
    op.create_index('idx_session_files_file', 'joysafeter_session_files', ['file_id'], unique=False)
    op.create_index('idx_session_files_session', 'joysafeter_session_files', ['session_id'], unique=False)
    op.create_table('joysafeter_session_memory_stores',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('store_id', sa.UUID(), nullable=False),
    sa.Column('access', sa.Text(), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('mount_name', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_session_memory_stores')),
    sa.UniqueConstraint('session_id', 'store_id', name=op.f('uq_joysafeter_session_memory_stores_session_id'))
    )
    op.create_index('idx_joysafeter_session_memory_stores_created', 'joysafeter_session_memory_stores', ['created_at'], unique=False)
    op.create_table('joysafeter_session_repos',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('mount_path', sa.Text(), nullable=False),
    sa.Column('mount_name', sa.String(length=255), nullable=False),
    sa.Column('encrypted_token', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_session_repos'))
    )
    op.create_index('idx_session_repos_session', 'joysafeter_session_repos', ['session_id'], unique=False)
    op.create_table('joysafeter_session_storage_mounts',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('volume_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('sub_path', sa.Text(), server_default='', nullable=False),
    sa.Column('mount_path', sa.Text(), nullable=False),
    sa.Column('access', sa.String(length=16), server_default='read_only', nullable=False),
    sa.Column('required', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('detached_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_session_storage_mounts')),
    sa.UniqueConstraint('session_id', 'mount_path', name='uq_joysafeter_session_storage_mount_path')
    )
    op.create_index('idx_joysafeter_session_storage_mounts_created', 'joysafeter_session_storage_mounts', ['created_at'], unique=False)
    op.create_index('idx_joysafeter_session_storage_mounts_detached', 'joysafeter_session_storage_mounts', ['detached_at'], unique=False)
    op.create_index('idx_joysafeter_session_storage_mounts_project', 'joysafeter_session_storage_mounts', ['project_id'], unique=False)
    op.create_index('idx_joysafeter_session_storage_mounts_session', 'joysafeter_session_storage_mounts', ['session_id'], unique=False)
    op.create_index('idx_joysafeter_session_storage_mounts_volume', 'joysafeter_session_storage_mounts', ['volume_id'], unique=False)
    op.create_index(op.f('ix_joysafeter_session_storage_mounts_project_id'), 'joysafeter_session_storage_mounts', ['project_id'], unique=False)
    op.create_table('joysafeter_sessions',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('stop_reason', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), server_default='{"input_tokens":0,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}', nullable=False),
    sa.Column('active_seconds', sa.Float(), nullable=True),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('vault_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('agent_version', sa.Integer(), nullable=True),
    sa.Column('agent_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('environment_ref', sa.Text(), nullable=True),
    sa.Column('last_harness_session_id', sa.Text(), nullable=True),
    sa.Column('last_work_dir', sa.Text(), nullable=True),
    sa.Column('last_sandbox_id', sa.UUID(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_sessions'))
    )
    op.create_index('idx_csess_agent', 'joysafeter_sessions', ['agent_id'], unique=False)
    op.create_index('idx_csess_archived', 'joysafeter_sessions', ['archived_at'], unique=False)
    op.create_index('idx_csess_created', 'joysafeter_sessions', ['created_at'], unique=False)
    op.create_index('idx_csess_project', 'joysafeter_sessions', ['project_id'], unique=False)
    op.create_index('idx_csess_updated', 'joysafeter_sessions', ['updated_at'], unique=False)
    op.create_index(op.f('ix_joysafeter_sessions_project_id'), 'joysafeter_sessions', ['project_id'], unique=False)
    op.create_table('joysafeter_skill_files',
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.String(length=512), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=50), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('storage_type', sa.String(length=20), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=True),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skill_files'))
    )
    op.create_index('skill_files_path_idx', 'joysafeter_skill_files', ['skill_id', 'path'], unique=False)
    op.create_index('skill_files_skill_idx', 'joysafeter_skill_files', ['skill_id'], unique=False)
    op.create_table('joysafeter_skill_security_scans',
    sa.Column('skill_id', sa.UUID(), nullable=True),
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('owner_id', sa.String(length=255), nullable=True),
    sa.Column('created_by_id', sa.String(length=255), nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('target_name', sa.String(length=128), nullable=True),
    sa.Column('target_hash', sa.String(length=64), nullable=False),
    sa.Column('scanner', sa.String(length=64), nullable=False),
    sa.Column('scanner_version', sa.String(length=64), nullable=True),
    sa.Column('ruleset_version', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('severity', sa.String(length=32), nullable=True),
    sa.Column('recommendation', sa.String(length=32), nullable=True),
    sa.Column('issues_count', sa.Integer(), nullable=False),
    sa.Column('critical_count', sa.Integer(), nullable=False),
    sa.Column('high_count', sa.Integer(), nullable=False),
    sa.Column('medium_count', sa.Integer(), nullable=False),
    sa.Column('low_count', sa.Integer(), nullable=False),
    sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skill_security_scans'))
    )
    op.create_index('skill_security_scans_owner_created_idx', 'joysafeter_skill_security_scans', ['owner_id', 'created_at'], unique=False)
    op.create_index('skill_security_scans_project_created_idx', 'joysafeter_skill_security_scans', ['project_id', 'created_at'], unique=False)
    op.create_index('skill_security_scans_recommendation_created_idx', 'joysafeter_skill_security_scans', ['recommendation', 'created_at'], unique=False)
    op.create_index('skill_security_scans_severity_created_idx', 'joysafeter_skill_security_scans', ['severity', 'created_at'], unique=False)
    op.create_index('skill_security_scans_skill_created_idx', 'joysafeter_skill_security_scans', ['skill_id', 'created_at'], unique=False)
    op.create_index('skill_security_scans_status_created_idx', 'joysafeter_skill_security_scans', ['status', 'created_at'], unique=False)
    op.create_index('skill_security_scans_target_hash_idx', 'joysafeter_skill_security_scans', ['target_hash'], unique=False)
    op.create_table('joysafeter_skill_usage_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=True),
    sa.Column('skill_version', sa.String(length=64), nullable=False),
    sa.Column('skill_version_id', sa.UUID(), nullable=True),
    sa.Column('skill_name', sa.String(length=64), nullable=True),
    sa.Column('skill_source_type', sa.String(length=50), nullable=True),
    sa.Column('target', sa.String(length=255), nullable=True),
    sa.Column('security_scan_id', sa.UUID(), nullable=True),
    sa.Column('target_hash', sa.String(length=64), nullable=True),
    sa.Column('artifact_hash', sa.String(length=64), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skill_usage_log'))
    )
    op.create_index('skill_usage_log_artifact_hash_idx', 'joysafeter_skill_usage_log', ['artifact_hash'], unique=False)
    op.create_index('skill_usage_log_created_idx', 'joysafeter_skill_usage_log', ['created_at'], unique=False)
    op.create_index('skill_usage_log_project_artifact_created_idx', 'joysafeter_skill_usage_log', ['project_id', 'artifact_hash', 'created_at'], unique=False)
    op.create_index('skill_usage_log_project_created_idx', 'joysafeter_skill_usage_log', ['project_id', 'created_at'], unique=False)
    op.create_index('skill_usage_log_project_scan_created_idx', 'joysafeter_skill_usage_log', ['project_id', 'security_scan_id', 'created_at'], unique=False)
    op.create_index('skill_usage_log_project_target_created_idx', 'joysafeter_skill_usage_log', ['project_id', 'target_hash', 'created_at'], unique=False)
    op.create_index('skill_usage_log_security_scan_idx', 'joysafeter_skill_usage_log', ['security_scan_id'], unique=False)
    op.create_index('skill_usage_log_session_created_idx', 'joysafeter_skill_usage_log', ['session_id', 'created_at'], unique=False)
    op.create_index('skill_usage_log_skill_created_idx', 'joysafeter_skill_usage_log', ['skill_id', 'created_at'], unique=False)
    op.create_index('skill_usage_log_target_hash_idx', 'joysafeter_skill_usage_log', ['target_hash'], unique=False)
    op.create_table('joysafeter_skill_version_files',
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.String(length=512), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=50), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('storage_type', sa.String(length=20), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=True),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skill_version_files'))
    )
    op.create_index('skill_version_files_version_idx', 'joysafeter_skill_version_files', ['version_id'], unique=False)
    op.create_table('joysafeter_skill_versions',
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('release_notes', sa.Text(), nullable=True),
    sa.Column('skill_name', sa.String(length=64), nullable=False),
    sa.Column('skill_description', sa.String(length=1024), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('allowed_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('compatibility', sa.String(length=500), nullable=True),
    sa.Column('license', sa.String(length=100), nullable=True),
    sa.Column('published_by_id', sa.String(length=255), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('security_scan_id', sa.UUID(), nullable=True),
    sa.Column('target_hash', sa.String(length=64), nullable=True),
    sa.Column('lifecycle_status', sa.String(length=16), nullable=False),
    sa.Column('approved_by_id', sa.String(length=255), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_target_visibility', sa.String(length=16), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skill_versions')),
    sa.UniqueConstraint('skill_id', 'version', name='skill_versions_skill_version_unique')
    )
    op.create_index('skill_versions_lifecycle_status_idx', 'joysafeter_skill_versions', ['lifecycle_status'], unique=False)
    op.create_index('skill_versions_published_at_idx', 'joysafeter_skill_versions', ['published_at'], unique=False)
    op.create_index('skill_versions_security_scan_idx', 'joysafeter_skill_versions', ['security_scan_id'], unique=False)
    op.create_index('skill_versions_skill_idx', 'joysafeter_skill_versions', ['skill_id'], unique=False)
    op.create_table('joysafeter_skills',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=1024), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_type', sa.String(length=50), nullable=False),
    sa.Column('source_url', sa.String(length=1024), nullable=True),
    sa.Column('owner_id', sa.String(length=255), nullable=True),
    sa.Column('created_by_id', sa.String(length=255), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('license', sa.String(length=100), nullable=True),
    sa.Column('compatibility', sa.String(length=500), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('allowed_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('security_status', sa.String(length=32), nullable=False),
    sa.Column('security_score', sa.Integer(), nullable=True),
    sa.Column('security_severity', sa.String(length=32), nullable=True),
    sa.Column('security_recommendation', sa.String(length=32), nullable=True),
    sa.Column('security_scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('security_scan_id', sa.UUID(), nullable=True),
    sa.Column('security_scan_hash', sa.String(length=64), nullable=True),
    sa.Column('security_issues_count', sa.Integer(), nullable=False),
    sa.Column('security_critical_count', sa.Integer(), nullable=False),
    sa.Column('security_high_count', sa.Integer(), nullable=False),
    sa.Column('security_medium_count', sa.Integer(), nullable=False),
    sa.Column('security_low_count', sa.Integer(), nullable=False),
    sa.Column('lifecycle_status', sa.String(length=16), nullable=False),
    sa.Column('org_version_id', sa.UUID(), nullable=True),
    sa.Column('public_version_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_skills')),
    sa.UniqueConstraint('project_id', 'name', name='skills_project_name_unique')
    )
    op.create_index('skills_created_by_idx', 'joysafeter_skills', ['created_by_id'], unique=False)
    op.create_index('skills_lifecycle_status_idx', 'joysafeter_skills', ['lifecycle_status'], unique=False)
    op.create_index('skills_owner_idx', 'joysafeter_skills', ['owner_id'], unique=False)
    op.create_index('skills_project_idx', 'joysafeter_skills', ['project_id'], unique=False)
    op.create_index('skills_security_recommendation_idx', 'joysafeter_skills', ['security_recommendation'], unique=False)
    op.create_index('skills_security_severity_idx', 'joysafeter_skills', ['security_severity'], unique=False)
    op.create_index('skills_security_status_idx', 'joysafeter_skills', ['security_status'], unique=False)
    op.create_index('skills_tags_idx', 'joysafeter_skills', ['tags'], unique=False, postgresql_using='gin')
    op.create_index('skills_visibility_idx', 'joysafeter_skills', ['visibility'], unique=False)
    op.create_table('joysafeter_storage_mount_audit',
    sa.Column('volume_id', sa.UUID(), nullable=True),
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('environment_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.String(length=255), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('volume_ref', sa.String(length=128), nullable=True),
    sa.Column('mount_path', sa.Text(), nullable=True),
    sa.Column('sub_path', sa.Text(), nullable=True),
    sa.Column('access', sa.String(length=16), nullable=True),
    sa.Column('bytes_used', sa.BigInteger(), nullable=True),
    sa.Column('result', sa.String(length=32), server_default='success', nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_storage_mount_audit'))
    )
    op.create_index('idx_joysafeter_storage_audit_action', 'joysafeter_storage_mount_audit', ['action'], unique=False)
    op.create_index('idx_joysafeter_storage_audit_created', 'joysafeter_storage_mount_audit', ['created_at'], unique=False)
    op.create_index('idx_joysafeter_storage_audit_project_created', 'joysafeter_storage_mount_audit', ['project_id', 'created_at'], unique=False)
    op.create_index('idx_joysafeter_storage_audit_result_created', 'joysafeter_storage_mount_audit', ['result', 'created_at'], unique=False)
    op.create_index('idx_joysafeter_storage_audit_session', 'joysafeter_storage_mount_audit', ['session_id'], unique=False)
    op.create_index('idx_joysafeter_storage_audit_volume', 'joysafeter_storage_mount_audit', ['volume_id'], unique=False)
    op.create_table('joysafeter_storage_organization_grants',
    sa.Column('volume_id', sa.UUID(), nullable=False),
    sa.Column('org_id', sa.String(length=255), nullable=False),
    sa.Column('max_access', sa.String(length=16), server_default='read_only', nullable=False),
    sa.Column('allowed_prefixes', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('quota_bytes', sa.BigInteger(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_storage_organization_grants')),
    sa.UniqueConstraint('volume_id', 'org_id', name='uq_joysafeter_storage_org_grants_volume_org')
    )
    op.create_index('idx_joysafeter_storage_org_grants_org', 'joysafeter_storage_organization_grants', ['org_id'], unique=False)
    op.create_index('idx_joysafeter_storage_org_grants_volume', 'joysafeter_storage_organization_grants', ['volume_id'], unique=False)
    op.create_table('joysafeter_storage_project_grants',
    sa.Column('volume_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('max_access', sa.String(length=16), server_default='read_only', nullable=False),
    sa.Column('allowed_prefixes', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('quota_bytes', sa.BigInteger(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_storage_project_grants')),
    sa.UniqueConstraint('volume_id', 'project_id', name='uq_joysafeter_storage_grants_volume_project')
    )
    op.create_index('idx_joysafeter_storage_grants_project', 'joysafeter_storage_project_grants', ['project_id'], unique=False)
    op.create_index('idx_joysafeter_storage_grants_volume', 'joysafeter_storage_project_grants', ['volume_id'], unique=False)
    op.create_table('joysafeter_storage_volumes',
    sa.Column('volume_ref', sa.String(length=128), nullable=False),
    sa.Column('backend_type', sa.String(length=32), server_default='generic', nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('max_access', sa.String(length=16), server_default='read_only', nullable=False),
    sa.Column('allowed_prefixes', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('docker', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('k8s', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('quota_bytes', sa.BigInteger(), nullable=True),
    sa.Column('used_bytes', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_storage_volumes'))
    )
    op.create_index('idx_joysafeter_storage_volumes_enabled', 'joysafeter_storage_volumes', ['enabled'], unique=False)
    op.create_index('uq_joysafeter_storage_volumes_ref_active', 'joysafeter_storage_volumes', ['volume_ref'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'), sqlite_where=sa.text('deleted_at IS NULL'))
    op.create_table('joysafeter_tasks',
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.String(length=255), nullable=True),
    sa.Column('org_id', sa.String(length=255), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('chat_session_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('system_prompt', sa.Text(), nullable=True),
    sa.Column('sandbox_id', sa.UUID(), nullable=True),
    sa.Column('output', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('timeout_sec', sa.Integer(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('schedule_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_schedule_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_schedule_error', sa.Text(), nullable=True),
    sa.Column('last_schedule_error_type', sa.Text(), nullable=True),
    sa.Column('scheduling_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.BigInteger(), nullable=True),
    sa.Column('owner_instance_id', sa.Text(), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_epoch', sa.BigInteger(), nullable=True),
    sa.Column('trigger_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_tasks')),
    sa.UniqueConstraint('idempotency_key', name='uq_joysafeter_tasks_idempotency_key')
    )
    op.create_index('idx_ct_agent', 'joysafeter_tasks', ['agent_id'], unique=False)
    op.create_index('idx_ct_completed', 'joysafeter_tasks', ['completed_at'], unique=False)
    op.create_index('idx_ct_created', 'joysafeter_tasks', ['created_at'], unique=False)
    op.create_index('idx_ct_project', 'joysafeter_tasks', ['project_id'], unique=False)
    op.create_index('idx_ct_project_status_created', 'joysafeter_tasks', ['project_id', 'status', 'created_at'], unique=False)
    op.create_index('idx_ct_running_lease', 'joysafeter_tasks', ['lease_expires_at'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index('idx_ct_sandbox_status', 'joysafeter_tasks', ['sandbox_id', 'status'], unique=False)
    op.create_index('idx_ct_sandbox_status_created', 'joysafeter_tasks', ['sandbox_id', 'status', 'created_at'], unique=False)
    op.create_index('idx_ct_started', 'joysafeter_tasks', ['started_at'], unique=False)
    op.create_index('idx_ct_status', 'joysafeter_tasks', ['status'], unique=False)
    op.create_index('idx_ct_status_created', 'joysafeter_tasks', ['status', 'created_at'], unique=False)
    op.create_index('idx_ct_status_next_schedule', 'joysafeter_tasks', ['status', 'next_schedule_at'], unique=False)
    op.create_index('idx_ct_status_updated', 'joysafeter_tasks', ['status', 'updated_at'], unique=False)
    op.create_index('idx_ct_trigger', 'joysafeter_tasks', ['trigger_id'], unique=False)
    op.create_index('idx_ct_user_status', 'joysafeter_tasks', ['user_id', 'status'], unique=False)
    op.create_index(op.f('ix_joysafeter_tasks_project_id'), 'joysafeter_tasks', ['project_id'], unique=False)
    op.create_table('joysafeter_triggers',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('prompt_template', sa.Text(), nullable=False),
    sa.Column('environment_ref', sa.String(length=255), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('session_mode', sa.String(length=16), server_default='fresh', nullable=False),
    sa.Column('session_key', sa.Text(), nullable=True),
    sa.Column('pinned_session_id', sa.UUID(), nullable=True),
    sa.Column('reusable_session_id', sa.UUID(), nullable=True),
    sa.Column('webhook_auth_credential_id', sa.UUID(), nullable=True),
    sa.Column('webhook_auth_field', sa.String(length=255), nullable=True),
    sa.Column('filter', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('timeout_sec', sa.Integer(), server_default='7200', nullable=False),
    sa.Column('max_retries', sa.Integer(), server_default='2', nullable=False),
    sa.Column('cron_expr', sa.String(length=255), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('concurrency_policy', sa.String(length=16), server_default='allow', nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_fired_slot', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pending_slot_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('slot_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('auto_disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_reason', sa.Text(), nullable=True),
    sa.Column('locked_by', sa.Text(), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('project_id', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.String(length=255), nullable=True),
    sa.Column('org_id', sa.String(length=255), nullable=True),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_task_id', sa.UUID(), nullable=True),
    sa.Column('last_session_id', sa.UUID(), nullable=True),
    sa.Column('last_payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_triggers'))
    )
    op.create_index('idx_joysafeter_triggers_cron_due', 'joysafeter_triggers', ['next_run_at'], unique=False, postgresql_where=sa.text("enabled IS TRUE AND type = 'cron' AND deleted_at IS NULL"), sqlite_where=sa.text("enabled IS TRUE AND type = 'cron' AND deleted_at IS NULL"))
    op.create_index('idx_joysafeter_triggers_deleted', 'joysafeter_triggers', ['deleted_at'], unique=False)
    op.create_index('idx_joysafeter_triggers_last_attempt', 'joysafeter_triggers', ['last_attempt_at'], unique=False)
    op.create_index('idx_joysafeter_triggers_project', 'joysafeter_triggers', ['project_id'], unique=False)
    op.create_index('idx_joysafeter_triggers_project_created', 'joysafeter_triggers', ['project_id', 'created_at'], unique=False)
    op.create_index('idx_joysafeter_triggers_type_enabled', 'joysafeter_triggers', ['type', 'enabled'], unique=False)
    op.create_index('idx_joysafeter_triggers_updated', 'joysafeter_triggers', ['updated_at'], unique=False)
    op.create_index(op.f('ix_joysafeter_triggers_webhook_auth_credential_id'), 'joysafeter_triggers', ['webhook_auth_credential_id'], unique=False)
    op.create_index('uq_joysafeter_triggers_global_name', 'joysafeter_triggers', ['name'], unique=True, postgresql_where=sa.text('project_id IS NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NULL AND deleted_at IS NULL'))
    op.create_index('uq_joysafeter_triggers_project_name', 'joysafeter_triggers', ['project_id', 'name'], unique=True, postgresql_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'), sqlite_where=sa.text('project_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_table('joysafeter_users',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('password_reset_token', sa.String(length=255), nullable=True),
    sa.Column('password_reset_expires', sa.DateTime(timezone=True), nullable=True),
    sa.Column('email_verify_token', sa.String(length=255), nullable=True),
    sa.Column('email_verify_expires', sa.DateTime(timezone=True), nullable=True),
    sa.Column('image', sa.String(length=1024), nullable=True),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('is_super_user', sa.Boolean(), nullable=False),
    sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lock_reason', sa.String(length=255), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_ip', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_joysafeter_users'))
    )
    op.create_index(op.f('ix_joysafeter_users_email'), 'joysafeter_users', ['email'], unique=True)

    # Foreign keys are added after table creation so cyclic relationships can be
    # represented in a single explicit baseline migration.
    op.create_foreign_key('fk_joysafeter_agent_versions_agent_id_joysafeter_agents', 'joysafeter_agent_versions', 'joysafeter_agents', ['agent_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_agents_project_id_joysafeter_organizat_0323e88f26', 'joysafeter_agents', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_agents_model_credential_id_joysafeter_credentials', 'joysafeter_agents', 'joysafeter_credentials', ['model_credential_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_joysafeter_api_keys_created_by_joysafeter_users', 'joysafeter_api_keys', 'joysafeter_users', ['created_by'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_api_keys_org_id_joysafeter_organizations', 'joysafeter_api_keys', 'joysafeter_organizations', ['org_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_api_keys_project_id_joysafeter_organiz_c91dcf8ec0', 'joysafeter_api_keys', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_auth_sessions_active_organization_id_j_9debc1202a', 'joysafeter_auth_sessions', 'joysafeter_organizations', ['active_organization_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_auth_sessions_user_id_joysafeter_users', 'joysafeter_auth_sessions', 'joysafeter_users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_environments_project_id_joysafeter_org_d4176626fe', 'joysafeter_environments', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_files_project_id_joysafeter_organization_projects', 'joysafeter_files', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_files_session_id_joysafeter_sessions', 'joysafeter_files', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_memories_store_id_joysafeter_memory_stores', 'joysafeter_memories', 'joysafeter_memory_stores', ['store_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_memory_stores_project_id_joysafeter_or_7d59b8da80', 'joysafeter_memory_stores', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_memory_versions_store_id_joysafeter_memory_stores', 'joysafeter_memory_versions', 'joysafeter_memory_stores', ['store_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_oauth_account_user_id_joysafeter_users', 'joysafeter_oauth_account', 'joysafeter_users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_organization_members_organization_id_j_4b8586c925', 'joysafeter_organization_members', 'joysafeter_organizations', ['organization_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_organization_members_user_id_joysafeter_users', 'joysafeter_organization_members', 'joysafeter_users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_organization_projects_org_id_joysafete_b8f1c3feeb', 'joysafeter_organization_projects', 'joysafeter_organizations', ['org_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_project_members_project_id_joysafeter_2874b1b429', 'joysafeter_project_members', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_project_members_user_id_joysafeter_users', 'joysafeter_project_members', 'joysafeter_users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_sandbox_network_policies_sandbox_id_jo_4fc96cd56a', 'joysafeter_sandbox_network_policies', 'joysafeter_sandboxes', ['sandbox_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_sandbox_network_policies_session_id_jo_e6664db0a3', 'joysafeter_sandbox_network_policies', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_sandbox_network_policies_task_id_joysafeter_tasks', 'joysafeter_sandbox_network_policies', 'joysafeter_tasks', ['task_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_sandboxes_project_id_joysafeter_organi_f2ef079275', 'joysafeter_sandboxes', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_credentials_project_id', 'joysafeter_credentials', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_credential_groups_project_id', 'joysafeter_credential_groups', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_credentials_group_project', 'joysafeter_credentials', 'joysafeter_credential_groups', ['group_id', 'project_id'], ['id', 'project_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_session_credential_groups_session_id', 'joysafeter_session_credential_groups', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_session_credential_groups_group_id', 'joysafeter_session_credential_groups', 'joysafeter_credential_groups', ['credential_group_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_joysafeter_session_events_session_id_joysafeter_sessions', 'joysafeter_session_events', 'joysafeter_sessions', ['session_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_session_files_file_id_joysafeter_files', 'joysafeter_session_files', 'joysafeter_files', ['file_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_session_files_session_id_joysafeter_sessions', 'joysafeter_session_files', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_session_memory_stores_session_id_joysa_aa8c8fbc8a', 'joysafeter_session_memory_stores', 'joysafeter_sessions', ['session_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_session_memory_stores_store_id_joysafe_313eb9362d', 'joysafeter_session_memory_stores', 'joysafeter_memory_stores', ['store_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_session_repos_session_id_joysafeter_sessions', 'joysafeter_session_repos', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_session_storage_mounts_project_id_joys_8a2d4f22b9', 'joysafeter_session_storage_mounts', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_session_storage_mounts_session_id_joys_cddc15ba6e', 'joysafeter_session_storage_mounts', 'joysafeter_sessions', ['session_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_session_storage_mounts_volume_id_joysa_529a157a37', 'joysafeter_session_storage_mounts', 'joysafeter_storage_volumes', ['volume_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_joysafeter_sessions_agent_id_joysafeter_agents', 'joysafeter_sessions', 'joysafeter_agents', ['agent_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_sessions_project_id_joysafeter_organiz_ad0a96f3fd', 'joysafeter_sessions', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_skill_files_skill_id_joysafeter_skills', 'joysafeter_skill_files', 'joysafeter_skills', ['skill_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skill_security_scans_created_by_id_joy_645cce72d6', 'joysafeter_skill_security_scans', 'joysafeter_users', ['created_by_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skill_security_scans_owner_id_joysafeter_users', 'joysafeter_skill_security_scans', 'joysafeter_users', ['owner_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_security_scans_project_id_joysaf_9599cf2b71', 'joysafeter_skill_security_scans', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_security_scans_skill_id_joysafeter_skills', 'joysafeter_skill_security_scans', 'joysafeter_skills', ['skill_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_usage_log_skill_id_joysafeter_skills', 'joysafeter_skill_usage_log', 'joysafeter_skills', ['skill_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_usage_log_skill_version_id_joysa_1d025c6ee5', 'joysafeter_skill_usage_log', 'joysafeter_skill_versions', ['skill_version_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_version_files_version_id_joysafe_80d4fa3526', 'joysafeter_skill_version_files', 'joysafeter_skill_versions', ['version_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skill_versions_approved_by_id_joysafeter_users', 'joysafeter_skill_versions', 'joysafeter_users', ['approved_by_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_versions_published_by_id_joysafeter_users', 'joysafeter_skill_versions', 'joysafeter_users', ['published_by_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skill_versions_security_scan_id_joysaf_d854876dfc', 'joysafeter_skill_versions', 'joysafeter_skill_security_scans', ['security_scan_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skill_versions_skill_id_joysafeter_skills', 'joysafeter_skill_versions', 'joysafeter_skills', ['skill_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skills_created_by_id_joysafeter_users', 'joysafeter_skills', 'joysafeter_users', ['created_by_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skills_org_version_id_joysafeter_skill_versions', 'joysafeter_skills', 'joysafeter_skill_versions', ['org_version_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skills_owner_id_joysafeter_users', 'joysafeter_skills', 'joysafeter_users', ['owner_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_skills_project_id_joysafeter_organizat_e3294d7f80', 'joysafeter_skills', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_skills_public_version_id_joysafeter_sk_5f74e4dca4', 'joysafeter_skills', 'joysafeter_skill_versions', ['public_version_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_storage_mount_audit_volume_id_joysafet_27af0c6f83', 'joysafeter_storage_mount_audit', 'joysafeter_storage_volumes', ['volume_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_storage_organization_grants_org_id_joy_759c9d48db', 'joysafeter_storage_organization_grants', 'joysafeter_organizations', ['org_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_storage_organization_grants_volume_id_4831023562', 'joysafeter_storage_organization_grants', 'joysafeter_storage_volumes', ['volume_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_storage_project_grants_project_id_joys_5e1b7df3e2', 'joysafeter_storage_project_grants', 'joysafeter_organization_projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_storage_project_grants_volume_id_joysa_d11a27c3ea', 'joysafeter_storage_project_grants', 'joysafeter_storage_volumes', ['volume_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_joysafeter_tasks_agent_id_joysafeter_agents', 'joysafeter_tasks', 'joysafeter_agents', ['agent_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_tasks_chat_session_id_joysafeter_sessions', 'joysafeter_tasks', 'joysafeter_sessions', ['chat_session_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_tasks_project_id_joysafeter_organization_projects', 'joysafeter_tasks', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_tasks_trigger_id_joysafeter_triggers', 'joysafeter_tasks', 'joysafeter_triggers', ['trigger_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_triggers_agent_id_joysafeter_agents', 'joysafeter_triggers', 'joysafeter_agents', ['agent_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_triggers_last_session_id_joysafeter_sessions', 'joysafeter_triggers', 'joysafeter_sessions', ['last_session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_triggers_last_task_id_joysafeter_tasks', 'joysafeter_triggers', 'joysafeter_tasks', ['last_task_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_triggers_pinned_session_id_joysafeter_sessions', 'joysafeter_triggers', 'joysafeter_sessions', ['pinned_session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_triggers_project_id_joysafeter_organiz_afba10a3b6', 'joysafeter_triggers', 'joysafeter_organization_projects', ['project_id'], ['id'])
    op.create_foreign_key('fk_joysafeter_triggers_reusable_session_id_joysafeter_sessions', 'joysafeter_triggers', 'joysafeter_sessions', ['reusable_session_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_joysafeter_triggers_webhook_auth_credential_id', 'joysafeter_triggers', 'joysafeter_credentials', ['webhook_auth_credential_id'], ['id'], ondelete='RESTRICT')

    # Runtime membership mirror used by health checks/orchestrator. It is not an
    # ORM model but is still part of the deployment schema.

    op.create_table(
        "joysafeter_cluster_members",
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("instance_id", name=op.f("pk_joysafeter_cluster_members")),
    )
    op.create_index(
        "idx_joysafeter_cluster_members_role_expires_at",
        "joysafeter_cluster_members",
        ["role", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_joysafeter_cluster_members_role_expires_at",
        table_name="joysafeter_cluster_members",
    )
    op.drop_table("joysafeter_cluster_members")
    op.drop_constraint('fk_session_credential_groups_group_id', 'joysafeter_session_credential_groups', type_='foreignkey')
    op.drop_constraint('fk_session_credential_groups_session_id', 'joysafeter_session_credential_groups', type_='foreignkey')
    op.drop_constraint('fk_credentials_group_project', 'joysafeter_credentials', type_='foreignkey')
    op.drop_constraint('fk_credential_groups_project_id', 'joysafeter_credential_groups', type_='foreignkey')
    op.drop_constraint('fk_credentials_project_id', 'joysafeter_credentials', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_reusable_session_id_joysafeter_sessions', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_webhook_auth_credential_id', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_project_id_joysafeter_organiz_afba10a3b6', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_pinned_session_id_joysafeter_sessions', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_last_task_id_joysafeter_tasks', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_last_session_id_joysafeter_sessions', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_triggers_agent_id_joysafeter_agents', 'joysafeter_triggers', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_tasks_trigger_id_joysafeter_triggers', 'joysafeter_tasks', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_tasks_project_id_joysafeter_organization_projects', 'joysafeter_tasks', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_tasks_chat_session_id_joysafeter_sessions', 'joysafeter_tasks', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_tasks_agent_id_joysafeter_agents', 'joysafeter_tasks', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_storage_project_grants_volume_id_joysa_d11a27c3ea', 'joysafeter_storage_project_grants', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_storage_project_grants_project_id_joys_5e1b7df3e2', 'joysafeter_storage_project_grants', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_storage_organization_grants_volume_id_4831023562', 'joysafeter_storage_organization_grants', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_storage_organization_grants_org_id_joy_759c9d48db', 'joysafeter_storage_organization_grants', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_storage_mount_audit_volume_id_joysafet_27af0c6f83', 'joysafeter_storage_mount_audit', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skills_public_version_id_joysafeter_sk_5f74e4dca4', 'joysafeter_skills', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skills_project_id_joysafeter_organizat_e3294d7f80', 'joysafeter_skills', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skills_owner_id_joysafeter_users', 'joysafeter_skills', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skills_org_version_id_joysafeter_skill_versions', 'joysafeter_skills', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skills_created_by_id_joysafeter_users', 'joysafeter_skills', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_versions_skill_id_joysafeter_skills', 'joysafeter_skill_versions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_versions_security_scan_id_joysaf_d854876dfc', 'joysafeter_skill_versions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_versions_published_by_id_joysafeter_users', 'joysafeter_skill_versions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_versions_approved_by_id_joysafeter_users', 'joysafeter_skill_versions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_version_files_version_id_joysafe_80d4fa3526', 'joysafeter_skill_version_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_usage_log_skill_version_id_joysa_1d025c6ee5', 'joysafeter_skill_usage_log', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_usage_log_skill_id_joysafeter_skills', 'joysafeter_skill_usage_log', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_security_scans_skill_id_joysafeter_skills', 'joysafeter_skill_security_scans', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_security_scans_project_id_joysaf_9599cf2b71', 'joysafeter_skill_security_scans', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_security_scans_owner_id_joysafeter_users', 'joysafeter_skill_security_scans', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_security_scans_created_by_id_joy_645cce72d6', 'joysafeter_skill_security_scans', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_skill_files_skill_id_joysafeter_skills', 'joysafeter_skill_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sessions_project_id_joysafeter_organiz_ad0a96f3fd', 'joysafeter_sessions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sessions_agent_id_joysafeter_agents', 'joysafeter_sessions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_storage_mounts_volume_id_joysa_529a157a37', 'joysafeter_session_storage_mounts', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_storage_mounts_session_id_joys_cddc15ba6e', 'joysafeter_session_storage_mounts', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_storage_mounts_project_id_joys_8a2d4f22b9', 'joysafeter_session_storage_mounts', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_repos_session_id_joysafeter_sessions', 'joysafeter_session_repos', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_memory_stores_store_id_joysafe_313eb9362d', 'joysafeter_session_memory_stores', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_memory_stores_session_id_joysa_aa8c8fbc8a', 'joysafeter_session_memory_stores', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_files_session_id_joysafeter_sessions', 'joysafeter_session_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_files_file_id_joysafeter_files', 'joysafeter_session_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_session_events_session_id_joysafeter_sessions', 'joysafeter_session_events', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sandboxes_project_id_joysafeter_organi_f2ef079275', 'joysafeter_sandboxes', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sandbox_network_policies_task_id_joysafeter_tasks', 'joysafeter_sandbox_network_policies', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sandbox_network_policies_session_id_jo_e6664db0a3', 'joysafeter_sandbox_network_policies', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_sandbox_network_policies_sandbox_id_jo_4fc96cd56a', 'joysafeter_sandbox_network_policies', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_project_members_user_id_joysafeter_users', 'joysafeter_project_members', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_project_members_project_id_joysafeter_2874b1b429', 'joysafeter_project_members', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_organization_projects_org_id_joysafete_b8f1c3feeb', 'joysafeter_organization_projects', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_organization_members_user_id_joysafeter_users', 'joysafeter_organization_members', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_organization_members_organization_id_j_4b8586c925', 'joysafeter_organization_members', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_oauth_account_user_id_joysafeter_users', 'joysafeter_oauth_account', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_memory_versions_store_id_joysafeter_memory_stores', 'joysafeter_memory_versions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_memory_stores_project_id_joysafeter_or_7d59b8da80', 'joysafeter_memory_stores', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_memories_store_id_joysafeter_memory_stores', 'joysafeter_memories', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_files_session_id_joysafeter_sessions', 'joysafeter_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_files_project_id_joysafeter_organization_projects', 'joysafeter_files', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_environments_project_id_joysafeter_org_d4176626fe', 'joysafeter_environments', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_auth_sessions_user_id_joysafeter_users', 'joysafeter_auth_sessions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_auth_sessions_active_organization_id_j_9debc1202a', 'joysafeter_auth_sessions', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_api_keys_project_id_joysafeter_organiz_c91dcf8ec0', 'joysafeter_api_keys', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_api_keys_org_id_joysafeter_organizations', 'joysafeter_api_keys', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_api_keys_created_by_joysafeter_users', 'joysafeter_api_keys', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_agents_model_credential_id_joysafeter_credentials', 'joysafeter_agents', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_agents_project_id_joysafeter_organizat_0323e88f26', 'joysafeter_agents', type_='foreignkey')
    op.drop_constraint('fk_joysafeter_agent_versions_agent_id_joysafeter_agents', 'joysafeter_agent_versions', type_='foreignkey')
    op.drop_table('joysafeter_session_credential_groups')
    op.drop_table('joysafeter_credentials')
    op.drop_table('joysafeter_credential_groups')
    op.drop_table('joysafeter_users')
    op.drop_table('joysafeter_triggers')
    op.drop_table('joysafeter_tasks')
    op.drop_table('joysafeter_storage_volumes')
    op.drop_table('joysafeter_storage_project_grants')
    op.drop_table('joysafeter_storage_organization_grants')
    op.drop_table('joysafeter_storage_mount_audit')
    op.drop_table('joysafeter_skills')
    op.drop_table('joysafeter_skill_versions')
    op.drop_table('joysafeter_skill_version_files')
    op.drop_table('joysafeter_skill_usage_log')
    op.drop_table('joysafeter_skill_security_scans')
    op.drop_table('joysafeter_skill_files')
    op.drop_table('joysafeter_sessions')
    op.drop_table('joysafeter_session_storage_mounts')
    op.drop_table('joysafeter_session_repos')
    op.drop_table('joysafeter_session_memory_stores')
    op.drop_table('joysafeter_session_files')
    op.drop_table('joysafeter_session_events')
    op.drop_table('joysafeter_security_audit_logs')
    op.drop_table('joysafeter_sandboxes')
    op.drop_table('joysafeter_sandbox_network_policies')
    op.drop_table('joysafeter_project_members')
    op.drop_table('joysafeter_organizations')
    op.drop_table('joysafeter_organization_projects')
    op.drop_table('joysafeter_organization_members')
    op.drop_table('joysafeter_oauth_account')
    op.drop_table('joysafeter_memory_versions')
    op.drop_table('joysafeter_memory_stores')
    op.drop_table('joysafeter_memories')
    op.drop_table('joysafeter_files')
    op.drop_table('joysafeter_environments')
    op.drop_table('joysafeter_auth_sessions')
    op.drop_table('joysafeter_api_keys')
    op.drop_table('joysafeter_agents')
    op.drop_table('joysafeter_agent_versions')
    op.execute(sa.schema.DropSequence(sa.Sequence("joysafeter_task_owner_epoch_seq")))
