import sys
from pathlib import Path

from app.joysafeter_shared.common.error_catalog import (
    CATALOG,
    CatalogEntry,
    all_codes,
    entry_for,
    is_registered,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_error_catalog import collect  # noqa: E402


def test_catalog_is_wellformed_registry():
    assert isinstance(CATALOG, dict)
    assert CATALOG, "catalog must be seeded (Task 1.2)"
    for code, entry in CATALOG.items():
        assert isinstance(entry, CatalogEntry)
        assert entry.code == code, f"key {code!r} != entry.code {entry.code!r}"
        assert entry.default_message, f"{code} missing default_message"


def test_conflict_codes_resolved_to_canonical_class():
    from app.joysafeter_shared.common.app_errors import (
        AccessDeniedError,
        AuthenticationError,
        ResourceConflictError,
    )

    assert CATALOG["PROJECT_ACCESS_DENIED"].error_class is AccessDeniedError
    assert CATALOG["SKILL_NAME_ALREADY_EXISTS"].error_class is ResourceConflictError
    assert CATALOG["USER_INVALID"].error_class is AuthenticationError
    assert CATALOG["USER_NOT_FOUND"].error_class is AuthenticationError


def test_catalog_accessors():
    # Absent-code behavior holds regardless of whether the catalog is seeded.
    assert is_registered("____DEFINITELY_NOT_A_CODE____") is False
    assert entry_for("____NOPE____") is None
    assert isinstance(all_codes(), frozenset)
    assert all_codes() == frozenset(CATALOG)

    # When the catalog is seeded (Task 1.2+), verify the present-code path too.
    if CATALOG:
        sample = next(iter(CATALOG))
        assert is_registered(sample) is True
        assert entry_for(sample) is CATALOG[sample]
        assert sample in all_codes()


def test_every_emitted_code_is_registered():
    emitted = set(collect())
    missing = sorted(emitted - all_codes())
    assert not missing, f"Codes raised in the backend but absent from CATALOG (add them to error_catalog.py): {missing}"
