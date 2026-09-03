from __future__ import annotations

import pytest

from app.joysafeter_api.api.v1.network_policies import (
    NetworkPolicyStatusResponse,
    _base_status_query,
)

pytestmark = pytest.mark.no_db


def test_base_status_query_selects_every_response_field() -> None:
    """The status query must SELECT every column that ``_row_to_response`` reads.

    ``_row_to_response`` maps each ``NetworkPolicyStatusResponse`` field to a
    ``row`` attribute of the same name. A field declared on the response but not
    selected by ``_base_status_query`` raises ``KeyError`` -> ``AttributeError``
    on the SQLAlchemy Row, surfacing as a 500 whenever a sandbox row is returned.
    """
    selected = set(_base_status_query().selected_columns.keys())
    required = set(NetworkPolicyStatusResponse.model_fields)

    missing = required - selected
    assert not missing, f"query missing columns read by _row_to_response: {sorted(missing)}"
