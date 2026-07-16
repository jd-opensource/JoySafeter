import inspect

from fastapi.params import Depends

from app.joysafeter_api.api.v1 import schedules, secrets, vaults
from app.joysafeter_shared.common.joysafeter_auth import (
    get_joysafeter_auth_context,
    require_joysafeter_write,
)


def _dependency_for(handler, parameter_name: str = "auth_ctx"):
    default = inspect.signature(handler).parameters[parameter_name].default
    assert isinstance(default, Depends)
    return default.dependency


def test_archived_project_read_routes_use_read_auth_context():
    assert _dependency_for(secrets.get_secret) is get_joysafeter_auth_context
    assert _dependency_for(vaults.get_vault) is get_joysafeter_auth_context
    assert _dependency_for(vaults.list_credentials) is get_joysafeter_auth_context
    assert _dependency_for(vaults.get_credential) is get_joysafeter_auth_context
    assert _dependency_for(schedules.list_schedules) is get_joysafeter_auth_context
    assert _dependency_for(schedules.get_schedule) is get_joysafeter_auth_context
    assert _dependency_for(schedules.list_schedule_runs) is get_joysafeter_auth_context


def test_project_resource_write_routes_still_require_write_context():
    assert _dependency_for(secrets.update_secret) is require_joysafeter_write
    assert _dependency_for(vaults.update_vault) is require_joysafeter_write
    assert _dependency_for(vaults.create_credential) is require_joysafeter_write
    assert _dependency_for(vaults.update_credential) is require_joysafeter_write
    assert _dependency_for(vaults.archive_credential) is require_joysafeter_write
    assert _dependency_for(vaults.delete_credential) is require_joysafeter_write
    assert _dependency_for(schedules.create_schedule) is require_joysafeter_write
    assert _dependency_for(schedules.update_schedule) is require_joysafeter_write
    assert _dependency_for(schedules.delete_schedule) is require_joysafeter_write
    assert _dependency_for(schedules.enable_schedule) is require_joysafeter_write
    assert _dependency_for(schedules.disable_schedule) is require_joysafeter_write
    assert _dependency_for(schedules.trigger_schedule) is require_joysafeter_write
