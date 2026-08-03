from __future__ import annotations

import pytest

from app.joysafeter_shared.everos_scope import (
    compose_everos_project_id,
    compose_everos_user_id,
    extract_joysafeter_project_id,
)

pytestmark = pytest.mark.no_db


def test_compose_everos_project_id_uses_slug_and_stable_project_id():
    assert (
        compose_everos_project_id(
            project_slug="test",
            project_id="55c665e3-5fe7-4e26-a11b-e6bf095d1a07",
        )
        == "test__55c665e3-5fe7-4e26-a11b-e6bf095d1a07"
    )


def test_compose_everos_project_id_sanitizes_slug_without_changing_project_id():
    assert (
        compose_everos_project_id(
            project_slug="../My Project/测试",
            project_id="e032a643-5415-4390-be97-4ac225e500f2",
        )
        == "My_Project__e032a643-5415-4390-be97-4ac225e500f2"
    )


def test_compose_everos_project_id_truncates_slug_before_project_id():
    value = compose_everos_project_id(
        project_slug="a" * 200,
        project_id="e032a643-5415-4390-be97-4ac225e500f2",
    )

    assert len(value) == 128
    assert value.endswith("__e032a643-5415-4390-be97-4ac225e500f2")


def test_extract_joysafeter_project_id_returns_suffix_from_composite_scope():
    assert (
        extract_joysafeter_project_id(
            "test__55c665e3-5fe7-4e26-a11b-e6bf095d1a07"
        )
        == "55c665e3-5fe7-4e26-a11b-e6bf095d1a07"
    )


def test_extract_joysafeter_project_id_keeps_legacy_uuid_scope():
    assert (
        extract_joysafeter_project_id("e032a643-5415-4390-be97-4ac225e500f2")
        == "e032a643-5415-4390-be97-4ac225e500f2"
    )


def test_compose_everos_user_id_uses_path_safe_joysafeter_user_name():
    assert (
        compose_everos_user_id(
            user_name="huajie Sun",
            user_id="e7197065-b019-4f81-80a6-e66515074cba",
        )
        == "huajie_Sun"
    )


def test_compose_everos_user_id_falls_back_to_stable_user_id_when_name_missing():
    assert (
        compose_everos_user_id(
            user_name="",
            user_id="e7197065-b019-4f81-80a6-e66515074cba",
        )
        == "e7197065-b019-4f81-80a6-e66515074cba"
    )
