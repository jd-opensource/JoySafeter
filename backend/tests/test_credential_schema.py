"""Pure-metadata schema tests for the unified credential models.

These tests import ONLY the model module and assert on SQLAlchemy metadata
(columns / constraints / indexes). No ``db_session``, no app import, no async —
so they survive the intermediate broken tree while downstream services still
reference the deleted secret/vault models.
"""

from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
    JoySafeterSessionCredentialGroup,
)


def test_credentials_table_shape() -> None:
    table = JoySafeterCredential.__table__
    assert table.name == "joysafeter_credentials"

    cols = {c.name for c in table.columns}
    expected = {
        "id",
        "project_id",
        "kind",
        "name",
        "data",
        "provider",
        "protocol",
        "is_default",
        "mcp_server_url",
        "normalized_mcp_server_url",
        "credential_type",
        "oauth_config",
        "group_id",
        "archived_at",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert expected <= cols

    # project_id must be NOT NULL (global credentials are API-unreachable).
    assert table.columns["project_id"].nullable is False


def test_credentials_kind_identity_check_exists() -> None:
    from sqlalchemy import CheckConstraint

    checks = [c for c in JoySafeterCredential.__table__.constraints if isinstance(c, CheckConstraint)]
    names = {c.name for c in checks}
    # The declared name is "kind_identity"; the project-wide naming convention
    # expands it to ck_<table>_kind_identity.
    assert any(n == "kind_identity" or n.endswith("kind_identity") for n in names)

    kind_identity = next(c for c in checks if c.name and c.name.endswith("kind_identity"))
    sql = str(kind_identity.sqltext)
    assert "normalized_mcp_server_url IS NOT NULL" in sql
    assert "credential_type IS NOT NULL" in sql
    assert sql.count("credential_type IS NULL") == 2
    assert sql.count("oauth_config IS NULL") == 2


def test_credentials_partial_unique_indexes_exist() -> None:
    index_names = {ix.name for ix in JoySafeterCredential.__table__.indexes}
    assert "uq_credentials_project_kind_name" in index_names
    assert "uq_credentials_default_protocol" in index_names
    assert "uq_credentials_group_url" in index_names


def test_credential_groups_table_shape() -> None:
    table = JoySafeterCredentialGroup.__table__
    assert table.name == "joysafeter_credential_groups"

    cols = {c.name for c in table.columns}
    expected = {
        "id",
        "project_id",
        "name",
        "description",
        "metadata",
        "archived_at",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert expected <= cols
    assert table.columns["project_id"].nullable is False

    from sqlalchemy import UniqueConstraint

    uniques = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_credential_groups_id_project" in uniques


def test_session_credential_groups_table_shape() -> None:
    table = JoySafeterSessionCredentialGroup.__table__
    assert table.name == "joysafeter_session_credential_groups"

    cols = {c.name for c in table.columns}
    assert {"session_id", "credential_group_id"} <= cols

    pk_cols = {c.name for c in table.primary_key.columns}
    assert pk_cols == {"session_id", "credential_group_id"}
