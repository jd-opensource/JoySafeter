from app.joysafeter_shared.common.error_catalog import (
    CATALOG,
    CatalogEntry,
    all_codes,
    entry_for,
    is_registered,
)


def test_catalog_is_wellformed_registry():
    assert isinstance(CATALOG, dict)
    for code, entry in CATALOG.items():
        assert isinstance(entry, CatalogEntry)
        assert entry.code == code, f"key {code!r} != entry.code {entry.code!r}"
        assert entry.default_message, f"{code} missing default_message"


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
