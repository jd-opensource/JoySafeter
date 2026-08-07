from __future__ import annotations

import uuid

import pytest

from app.joysafeter_domain.services.joysafeter_vault_service import VaultService
from app.joysafeter_shared.ids import VaultId

pytestmark = pytest.mark.no_db


class _Result:
    def scalar_one_or_none(self):
        return None


class _Db:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


@pytest.mark.asyncio
async def test_vault_reference_query_uses_single_canonical_prefixed_ref():
    """``session.vault_ids`` is canonically prefixed (the ``list[VaultId]`` request
    schema rejects bare uuids and create_session persists ``str(vault_id)``), so the
    reference lookup must query exactly the one canonical prefixed ref. Regression
    guards two failure modes introduced/masked by typing:
      * ``f"vault_{vault_id}"`` — ``str(VaultId)`` already carries the prefix, so this
        double-prefixes to ``vault_vault_<uuid>`` and matches nothing.
      * a lingering bare-uuid branch — vestigial dual-format tolerance for the old
        un-normalized write path; the typed boundary no longer produces bare refs."""
    vault_id = VaultId(uuid.uuid4())
    db = _Db()

    referenced = await VaultService(db).vault_is_referenced_by_sessions(  # type: ignore[arg-type]
        vault_id, project_id="proj-a"
    )
    assert referenced is False

    # The JSONB ``contains`` bind is the only list-valued param; project_id binds a
    # plain string. Assert exactly one contains, holding just the canonical prefixed ref.
    contains_args = [v for v in db.statement.compile().params.values() if isinstance(v, list)]
    assert contains_args == [[str(vault_id)]]
    assert [str(vault_id.uuid)] not in contains_args  # no bare-uuid branch
    assert [f"vault_{vault_id}"] not in contains_args  # no vault_vault_<uuid> double-prefix
