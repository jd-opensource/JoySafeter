"""base_tables

Revision ID: 000000000000
Revises:
Create Date: 2025-12-25 00:00:00.000000+00:00

初始迁移：创建所有核心数据库表
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===========================================
    # 1. 创建枚举类型
    # ===========================================
    op.execute("CREATE TYPE workspacestatus AS ENUM ('active', 'deprecated', 'archived')")
    op.execute("CREATE TYPE workspacetype AS ENUM ('personal', 'team')")
    op.execute("CREATE TYPE workspacememberrole AS ENUM ('owner', 'admin', 'member', 'viewer')")
    op.execute("CREATE TYPE workspaceinvitationstatus AS ENUM ('pending', 'accepted', 'rejected', 'cancelled')")
    op.execute("CREATE TYPE permissiontype AS ENUM ('admin', 'write', 'read')")

    # ===========================================
    # 2. 创建核心用户表 (无外键依赖)
    # ===========================================

    # user 表
    op.create_table(
        "user",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, default=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("password_reset_token", sa.String(255), nullable=True),
        sa.Column("password_reset_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verify_token", sa.String(255), nullable=True),
        sa.Column("email_verify_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image", sa.String(1024), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("is_super_user", sa.Boolean(), nullable=False, default=False),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_reason", sa.String(255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    # organization 表
    op.create_table(
        "organization",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("logo", sa.String(500), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("org_usage_limit", sa.Numeric(), nullable=True),
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False, default=0),
        sa.Column("departed_member_usage", sa.Numeric(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ===========================================
    # 3. 创建依赖用户表的表
    # ===========================================

    # session 表
    op.create_table(
        "session",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token", sa.String(255), nullable=False, unique=True),
        sa.Column("ip_address", sa.String(255), nullable=True),
        sa.Column("user_agent", sa.String(1024), nullable=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "active_organization_id",
            sa.String(255),
            sa.ForeignKey("organization.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("session_user_id_idx", "session", ["user_id"])
    op.create_index("session_token_idx", "session", ["token"], unique=True)

    # member 表
    op.create_table(
        "member",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id", sa.String(255), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("member_user_id_idx", "member", ["user_id"])
    op.create_index("member_organization_id_idx", "member", ["organization_id"])

    # workspaces 表
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("active", "deprecated", "archived", name="workspacestatus", create_type=False),
            nullable=False,
            default="active",
        ),
        sa.Column(
            "type",
            postgresql.ENUM("personal", "team", name="workspacetype", create_type=False),
            nullable=False,
            default="personal",
        ),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("owner_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("allow_personal_api_keys", sa.Boolean(), nullable=False, default=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # workspace_members 表
    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("owner", "admin", "member", "viewer", name="workspacememberrole", create_type=False),
            nullable=False,
            default="member",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # workspace_folder 表
    op.create_table(
        "workspace_folder",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_folder.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("color", sa.String(32), nullable=True, default="#6B7280"),
        sa.Column("is_expanded", sa.Boolean(), nullable=False, default=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, default=0),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("workspace_folder_user_idx", "workspace_folder", ["user_id"])
    op.create_index("workspace_folder_workspace_parent_idx", "workspace_folder", ["workspace_id", "parent_id"])
    op.create_index("workspace_folder_parent_sort_idx", "workspace_folder", ["parent_id", "sort_order"])
    op.create_index("workspace_folder_deleted_at_idx", "workspace_folder", ["deleted_at"])

    # ===========================================
    # 4. 创建 graphs 相关表
    # ===========================================

    # graphs 表
    op.create_table(
        "graphs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_folder.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("color", sa.String(2000), nullable=True),
        sa.Column("is_deployed", sa.Boolean(), nullable=False, default=False),
        sa.Column("variables", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("graphs_user_id_idx", "graphs", ["user_id"])
    op.create_index("graphs_workspace_id_idx", "graphs", ["workspace_id"])
    op.create_index("graphs_folder_id_idx", "graphs", ["folder_id"])
    op.create_index("graphs_parent_id_idx", "graphs", ["parent_id"])

    # graph_nodes 表
    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tools", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("memory", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("position_x", sa.Numeric(), nullable=False),
        sa.Column("position_y", sa.Numeric(), nullable=False),
        sa.Column("position_absolute_x", sa.Numeric(), nullable=True),
        sa.Column("position_absolute_y", sa.Numeric(), nullable=True),
        sa.Column("width", sa.Numeric(), nullable=False, default=0),
        sa.Column("height", sa.Numeric(), nullable=False, default=0),
        sa.Column("data", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("graph_nodes_graph_id_idx", "graph_nodes", ["graph_id"])
    op.create_index("graph_nodes_type_idx", "graph_nodes", ["type"])

    # graph_edges 表
    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "source_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("graph_edges_graph_id_idx", "graph_edges", ["graph_id"])
    op.create_index("graph_edges_source_node_id_idx", "graph_edges", ["source_node_id"])
    op.create_index("graph_edges_target_node_id_idx", "graph_edges", ["target_node_id"])
    op.create_index("graph_edges_graph_source_idx", "graph_edges", ["graph_id", "source_node_id"])
    op.create_index("graph_edges_graph_target_idx", "graph_edges", ["graph_id", "target_node_id"])

    # graph_deployment_version 表
    op.create_table(
        "graph_deployment_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("graph_id", "version", name="graph_deployment_version_graph_version_unique"),
    )
    op.create_index("graph_deployment_version_graph_active_idx", "graph_deployment_version", ["graph_id", "is_active"])
    op.create_index("graph_deployment_version_created_at_idx", "graph_deployment_version", ["created_at"])

    # ===========================================
    # 5. 创建对话相关表
    # ===========================================

    # conversations 表
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", sa.String(100), nullable=False, unique=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("meta_data", postgresql.JSON(), nullable=True, default=dict),
        sa.Column("is_active", sa.Integer(), nullable=False, default=1),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_conversations_thread_id", "conversations", ["thread_id"], unique=True)
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # messages 表
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "thread_id", sa.String(100), sa.ForeignKey("conversations.thread_id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta_data", postgresql.JSON(), nullable=True, default=dict),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])

    # chat 表
    op.create_table(
        "chat",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identifier", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("customizations", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("auth_type", sa.String(50), nullable=False, default="public"),
        sa.Column("password", sa.String(255), nullable=True),
        sa.Column("allowed_emails", postgresql.JSONB(), nullable=False, default=list),
        sa.Column("output_configs", postgresql.JSONB(), nullable=False, default=list),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("identifier", name="identifier_idx"),
    )

    # copilot_chats 表
    op.create_table(
        "copilot_chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("messages", postgresql.JSONB(), nullable=False, default=list),
        sa.Column("model", sa.String(100), nullable=False, default="claude-3-7-sonnet-latest"),
        sa.Column("conversation_id", sa.String(255), nullable=True),
        sa.Column("preview_yaml", sa.Text(), nullable=True),
        sa.Column("plan_artifact", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("copilot_chats_user_id_idx", "copilot_chats", ["user_id"])
    op.create_index("copilot_chats_created_at_idx", "copilot_chats", ["created_at"])
    op.create_index("copilot_chats_updated_at_idx", "copilot_chats", ["updated_at"])

    # ===========================================
    # 6. 创建权限和邀请相关表
    # ===========================================

    # workspace_invitation 表
    op.create_table(
        "workspace_invitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("inviter_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, default="member"),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "accepted", "rejected", "cancelled", name="workspaceinvitationstatus", create_type=False
            ),
            nullable=False,
            default="pending",
        ),
        sa.Column("token", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "permissions",
            postgresql.ENUM("admin", "write", "read", name="permissiontype", create_type=False),
            nullable=False,
            default="admin",
        ),
        sa.Column("org_invitation_id", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("workspace_invitation_email_status_idx", "workspace_invitation", ["email", "status"])
    op.create_index("workspace_invitation_expires_at_idx", "workspace_invitation", ["expires_at"])
    op.create_index("workspace_invitation_workspace_id_idx", "workspace_invitation", ["workspace_id"])

    # permissions 表
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column(
            "permission_type",
            postgresql.ENUM("admin", "write", "read", name="permissiontype", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", name="permissions_unique_constraint"),
    )
    op.create_index("permissions_user_id_idx", "permissions", ["user_id"])
    op.create_index("permissions_entity_idx", "permissions", ["entity_type", "entity_id"])
    op.create_index("permissions_user_entity_type_idx", "permissions", ["user_id", "entity_type"])
    op.create_index(
        "permissions_user_entity_permission_idx", "permissions", ["user_id", "entity_type", "permission_type"]
    )
    op.create_index("permissions_user_entity_idx", "permissions", ["user_id", "entity_type", "entity_id"])

    # ===========================================
    # 7. 创建设置相关表
    # ===========================================

    # environment 表
    op.create_table(
        "environment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("variables", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # workspace_environment 表
    op.create_table(
        "workspace_environment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variables", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("workspace_id", name="workspace_environment_workspace_unique"),
    )

    # settings 表
    op.create_table(
        "settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("theme", sa.String(50), nullable=False, default="system"),
        sa.Column("auto_connect", sa.Boolean(), nullable=False, default=True),
        sa.Column("auto_pan", sa.Boolean(), nullable=False, default=True),
        sa.Column("console_expanded_by_default", sa.Boolean(), nullable=False, default=True),
        sa.Column("telemetry_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("email_preferences", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("billing_usage_notifications_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("show_floating_controls", sa.Boolean(), nullable=False, default=True),
        sa.Column("show_training_controls", sa.Boolean(), nullable=False, default=False),
        sa.Column("super_user_mode_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("error_notifications_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("copilot_enabled_models", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("settings_user_id_idx", "settings", ["user_id"])

    # ===========================================
    # 8. 创建文件存储相关表
    # ===========================================

    # workspace_file 表
    op.create_table(
        "workspace_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key", sa.String(512), nullable=False, unique=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("uploaded_by", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("workspace_file_workspace_id_idx", "workspace_file", ["workspace_id"])
    op.create_index("workspace_file_key_idx", "workspace_file", ["key"])

    # workspace_files 表
    op.create_table(
        "workspace_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(512), nullable=False, unique=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("context", sa.String(50), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("workspace_files_key_idx", "workspace_files", ["key"])
    op.create_index("workspace_files_user_id_idx", "workspace_files", ["user_id"])
    op.create_index("workspace_files_workspace_id_idx", "workspace_files", ["workspace_id"])
    op.create_index("workspace_files_context_idx", "workspace_files", ["context"])

    # ===========================================
    # 9. 创建 API Key 和工具相关表
    # ===========================================

    # api_key 表
    op.create_table(
        "api_key",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("type", sa.String(50), nullable=False, default="personal"),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(type = 'workspace' AND workspace_id IS NOT NULL) OR (type = 'personal' AND workspace_id IS NULL)",
            name="workspace_type_check",
        ),
    )
    op.create_index("api_key_user_id_idx", "api_key", ["user_id"])
    op.create_index("api_key_workspace_id_idx", "api_key", ["workspace_id"])
    op.create_index("api_key_key_idx", "api_key", ["key"])

    # custom_tools 表
    op.create_table(
        "custom_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("schema", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("runtime", sa.String(50), nullable=False, default="python"),
        sa.Column("enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="custom_tools_owner_name_unique"),
    )
    op.create_index("custom_tools_owner_idx", "custom_tools", ["owner_id"])

    # mcp_servers 表
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(255), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transport", sa.String(50), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("headers", postgresql.JSONB(), nullable=False, default=dict),
        sa.Column("timeout", sa.Integer(), nullable=True, default=30000),
        sa.Column("retries", sa.Integer(), nullable=True, default=3),
        sa.Column("enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("last_connected", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_status", sa.String(50), nullable=True, default="disconnected"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tool_count", sa.Integer(), nullable=True, default=0),
        sa.Column("last_tools_refresh", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_requests", sa.Integer(), nullable=True, default=0),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("mcp_servers_user_id_idx", "mcp_servers", ["user_id"])
    op.create_index("mcp_servers_user_enabled_idx", "mcp_servers", ["user_id", "enabled"])
    op.create_index("mcp_servers_user_name_unique_idx", "mcp_servers", ["user_id", "name"], unique=True)

    # ===========================================
    # 10. 创建模型相关表
    # ===========================================

    # model_provider 表
    op.create_table(
        "model_provider",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("icon", sa.String(500), nullable=True),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("supported_model_types", postgresql.JSON(), nullable=False, default=list),
        sa.Column("credential_schema", postgresql.JSON(), nullable=False, default=dict),
        sa.Column("config_schema", postgresql.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("model_provider_name_idx", "model_provider", ["name"])
    op.create_index("model_provider_enabled_idx", "model_provider", ["is_enabled"])

    # model_credential 表
    op.create_table(
        "model_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_provider.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credentials", sa.String(4096), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False, default=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(workspace_id IS NULL) OR (workspace_id IS NOT NULL)", name="model_credential_scope_check"),
    )
    op.create_index("model_credential_user_id_idx", "model_credential", ["user_id"])
    op.create_index("model_credential_workspace_id_idx", "model_credential", ["workspace_id"])
    op.create_index("model_credential_provider_id_idx", "model_credential", ["provider_id"])
    op.create_index("model_credential_user_provider_idx", "model_credential", ["user_id", "provider_id"])

    # model_instance 表
    op.create_table(
        "model_instance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_provider.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_parameters", postgresql.JSON(), nullable=False, default=dict),
        sa.Column("is_default", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "user_id", "workspace_id", "provider_id", "model_name", name="uq_model_instance_user_provider_model"
        ),
    )
    op.create_index("model_instance_user_id_idx", "model_instance", ["user_id"])
    op.create_index("model_instance_workspace_id_idx", "model_instance", ["workspace_id"])
    op.create_index("model_instance_provider_id_idx", "model_instance", ["provider_id"])
    op.create_index(
        "model_instance_user_provider_model_idx", "model_instance", ["user_id", "provider_id", "model_name"]
    )

    # ===========================================
    # 11. 创建 Skill 相关表
    # ===========================================

    # skills 表
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, default=list),
        sa.Column("source_type", sa.String(50), nullable=False, default="local"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("root_path", sa.String(512), nullable=True),
        sa.Column("owner_id", sa.String(255), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=False),
        sa.Column("license", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="skills_owner_name_unique"),
    )
    op.create_index("skills_owner_idx", "skills", ["owner_id"])
    op.create_index("skills_created_by_idx", "skills", ["created_by_id"])
    op.create_index("skills_public_idx", "skills", ["is_public"])
    op.create_index("skills_tags_idx", "skills", ["tags"], postgresql_using="gin")

    # skill_files 表
    op.create_table(
        "skill_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("storage_type", sa.String(20), nullable=False, default="database"),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("skill_files_skill_idx", "skill_files", ["skill_id"])
    op.create_index("skill_files_path_idx", "skill_files", ["skill_id", "path"])

    # ===========================================
    # 12. 创建安全审计和记忆相关表
    # ===========================================

    # memories 表
    op.create_table(
        "memories",
        sa.Column("memory_id", sa.String(), primary_key=True),
        sa.Column("memory", postgresql.JSON(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("input", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("team_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("topics", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_updated_at", "memories", ["updated_at"])
    op.create_index("ix_memories_created_at", "memories", ["created_at"])

    # security_audit_log 表
    op.create_table(
        "security_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("event_status", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(255), nullable=False),
        sa.Column("user_agent", sa.String(1024), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("country", sa.String(10), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_security_audit_log_user_id", "security_audit_log", ["user_id"])
    op.create_index("ix_security_audit_log_event_type", "security_audit_log", ["event_type"])
    op.create_index("ix_security_audit_log_event_status", "security_audit_log", ["event_status"])
    op.create_index("audit_log_user_id_idx", "security_audit_log", ["user_id"])
    op.create_index("audit_log_user_event_idx", "security_audit_log", ["user_id", "event_type"])
    op.create_index("audit_log_event_type_idx", "security_audit_log", ["event_type"])
    op.create_index("audit_log_event_status_idx", "security_audit_log", ["event_status"])
    op.create_index("audit_log_created_at_idx", "security_audit_log", ["created_at"])


def downgrade() -> None:
    # 按依赖关系反向删除表

    # 12. 安全审计和记忆相关表
    op.drop_index("audit_log_created_at_idx", table_name="security_audit_log")
    op.drop_index("audit_log_event_status_idx", table_name="security_audit_log")
    op.drop_index("audit_log_event_type_idx", table_name="security_audit_log")
    op.drop_index("audit_log_user_event_idx", table_name="security_audit_log")
    op.drop_index("audit_log_user_id_idx", table_name="security_audit_log")
    op.drop_index("ix_security_audit_log_event_status", table_name="security_audit_log")
    op.drop_index("ix_security_audit_log_event_type", table_name="security_audit_log")
    op.drop_index("ix_security_audit_log_user_id", table_name="security_audit_log")
    op.drop_table("security_audit_log")

    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_memories_updated_at", table_name="memories")
    op.drop_index("ix_memories_user_id", table_name="memories")
    op.drop_table("memories")

    # 11. Skill 相关表
    op.drop_index("skill_files_path_idx", table_name="skill_files")
    op.drop_index("skill_files_skill_idx", table_name="skill_files")
    op.drop_table("skill_files")

    op.drop_index("skills_tags_idx", table_name="skills")
    op.drop_index("skills_public_idx", table_name="skills")
    op.drop_index("skills_created_by_idx", table_name="skills")
    op.drop_index("skills_owner_idx", table_name="skills")
    op.drop_table("skills")

    # 10. 模型相关表
    op.drop_index("model_instance_user_provider_model_idx", table_name="model_instance")
    op.drop_index("model_instance_provider_id_idx", table_name="model_instance")
    op.drop_index("model_instance_workspace_id_idx", table_name="model_instance")
    op.drop_index("model_instance_user_id_idx", table_name="model_instance")
    op.drop_table("model_instance")

    op.drop_index("model_credential_user_provider_idx", table_name="model_credential")
    op.drop_index("model_credential_provider_id_idx", table_name="model_credential")
    op.drop_index("model_credential_workspace_id_idx", table_name="model_credential")
    op.drop_index("model_credential_user_id_idx", table_name="model_credential")
    op.drop_table("model_credential")

    op.drop_index("model_provider_enabled_idx", table_name="model_provider")
    op.drop_index("model_provider_name_idx", table_name="model_provider")
    op.drop_table("model_provider")

    # 9. API Key 和工具相关表
    op.drop_index("mcp_servers_user_name_unique_idx", table_name="mcp_servers")
    op.drop_index("mcp_servers_user_enabled_idx", table_name="mcp_servers")
    op.drop_index("mcp_servers_user_id_idx", table_name="mcp_servers")
    op.drop_table("mcp_servers")

    op.drop_index("custom_tools_owner_idx", table_name="custom_tools")
    op.drop_table("custom_tools")

    op.drop_index("api_key_key_idx", table_name="api_key")
    op.drop_index("api_key_workspace_id_idx", table_name="api_key")
    op.drop_index("api_key_user_id_idx", table_name="api_key")
    op.drop_table("api_key")

    # 8. 文件存储相关表
    op.drop_index("workspace_files_context_idx", table_name="workspace_files")
    op.drop_index("workspace_files_workspace_id_idx", table_name="workspace_files")
    op.drop_index("workspace_files_user_id_idx", table_name="workspace_files")
    op.drop_index("workspace_files_key_idx", table_name="workspace_files")
    op.drop_table("workspace_files")

    op.drop_index("workspace_file_key_idx", table_name="workspace_file")
    op.drop_index("workspace_file_workspace_id_idx", table_name="workspace_file")
    op.drop_table("workspace_file")

    # 7. 设置相关表
    op.drop_index("settings_user_id_idx", table_name="settings")
    op.drop_table("settings")
    op.drop_table("workspace_environment")
    op.drop_table("environment")

    # 6. 权限和邀请相关表
    op.drop_index("permissions_user_entity_idx", table_name="permissions")
    op.drop_index("permissions_user_entity_permission_idx", table_name="permissions")
    op.drop_index("permissions_user_entity_type_idx", table_name="permissions")
    op.drop_index("permissions_entity_idx", table_name="permissions")
    op.drop_index("permissions_user_id_idx", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("workspace_invitation_workspace_id_idx", table_name="workspace_invitation")
    op.drop_index("workspace_invitation_expires_at_idx", table_name="workspace_invitation")
    op.drop_index("workspace_invitation_email_status_idx", table_name="workspace_invitation")
    op.drop_table("workspace_invitation")

    # 5. 对话相关表
    op.drop_index("copilot_chats_updated_at_idx", table_name="copilot_chats")
    op.drop_index("copilot_chats_created_at_idx", table_name="copilot_chats")
    op.drop_index("copilot_chats_user_id_idx", table_name="copilot_chats")
    op.drop_table("copilot_chats")
    op.drop_table("chat")

    op.drop_index("ix_messages_thread_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_thread_id", table_name="conversations")
    op.drop_table("conversations")

    # 4. graphs 相关表
    op.drop_index("graph_deployment_version_created_at_idx", table_name="graph_deployment_version")
    op.drop_index("graph_deployment_version_graph_active_idx", table_name="graph_deployment_version")
    op.drop_table("graph_deployment_version")

    op.drop_index("graph_edges_graph_target_idx", table_name="graph_edges")
    op.drop_index("graph_edges_graph_source_idx", table_name="graph_edges")
    op.drop_index("graph_edges_target_node_id_idx", table_name="graph_edges")
    op.drop_index("graph_edges_source_node_id_idx", table_name="graph_edges")
    op.drop_index("graph_edges_graph_id_idx", table_name="graph_edges")
    op.drop_table("graph_edges")

    op.drop_index("graph_nodes_type_idx", table_name="graph_nodes")
    op.drop_index("graph_nodes_graph_id_idx", table_name="graph_nodes")
    op.drop_table("graph_nodes")

    op.drop_index("graphs_parent_id_idx", table_name="graphs")
    op.drop_index("graphs_folder_id_idx", table_name="graphs")
    op.drop_index("graphs_workspace_id_idx", table_name="graphs")
    op.drop_index("graphs_user_id_idx", table_name="graphs")
    op.drop_table("graphs")

    # 3. 依赖用户表的表
    op.drop_index("workspace_folder_deleted_at_idx", table_name="workspace_folder")
    op.drop_index("workspace_folder_parent_sort_idx", table_name="workspace_folder")
    op.drop_index("workspace_folder_workspace_parent_idx", table_name="workspace_folder")
    op.drop_index("workspace_folder_user_idx", table_name="workspace_folder")
    op.drop_table("workspace_folder")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")

    op.drop_index("member_organization_id_idx", table_name="member")
    op.drop_index("member_user_id_idx", table_name="member")
    op.drop_table("member")

    op.drop_index("session_token_idx", table_name="session")
    op.drop_index("session_user_id_idx", table_name="session")
    op.drop_table("session")

    # 2. 核心用户表
    op.drop_table("organization")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")

    # 1. 删除枚举类型
    op.execute("DROP TYPE IF EXISTS permissiontype")
    op.execute("DROP TYPE IF EXISTS workspaceinvitationstatus")
    op.execute("DROP TYPE IF EXISTS workspacememberrole")
    op.execute("DROP TYPE IF EXISTS workspacetype")
    op.execute("DROP TYPE IF EXISTS workspacestatus")
