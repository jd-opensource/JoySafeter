import inspect

from fastapi.params import Depends

from app.joysafeter_api.api.v1 import (
    agents,
    auth,
    environments,
    files,
    memory_stores,
    quickstart,
    sandboxes,
    schedules,
    secrets,
    sessions,
    skills,
    skills_ai_authoring,
    tasks,
    vaults,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    get_joysafeter_auth_context,
    require_joysafeter_admin,
    require_joysafeter_user_admin,
    require_joysafeter_user_context,
    require_joysafeter_user_write,
    require_joysafeter_write,
)


def _dependency_for(handler, parameter_name: str = "auth_ctx"):
    default = inspect.signature(handler).parameters[parameter_name].default
    assert isinstance(default, Depends)
    return default.dependency


def _dependencies_for(handler):
    dependencies = []
    for parameter in inspect.signature(handler).parameters.values():
        default = parameter.default
        if isinstance(default, Depends):
            dependencies.append(default.dependency)
    return dependencies


def _write_routes(router):
    mutating_methods = {"POST", "PUT", "PATCH", "DELETE"}
    return [
        route
        for route in router.routes
        if getattr(route, "methods", set()) & mutating_methods
    ]


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


def test_all_project_resource_write_routes_require_project_write_context():
    project_resource_modules = [
        agents,
        environments,
        files,
        memory_stores,
        quickstart,
        sandboxes,
        schedules,
        secrets,
        sessions,
        skills,
        skills_ai_authoring,
        tasks,
        vaults,
    ]

    offenders = []
    for module in project_resource_modules:
        for route in _write_routes(module.router):
            dependencies = _dependencies_for(route.endpoint)
            if require_joysafeter_write not in dependencies:
                methods = ",".join(sorted(route.methods or []))
                offenders.append(f"{module.__name__}.{route.endpoint.__name__} [{methods}] {route.path}")
            if require_joysafeter_admin in dependencies:
                offenders.append(f"{module.__name__}.{route.endpoint.__name__} uses admin for project resource write")

    assert offenders == []


def test_auth_management_context_routes_require_user_principal():
    allowed = {
        require_joysafeter_user_context,
        require_joysafeter_user_write,
        require_joysafeter_user_admin,
    }

    offenders = []
    for route in auth.router.routes:
        handler = route.endpoint
        parameters = inspect.signature(handler).parameters
        if "auth_ctx" not in parameters:
            continue
        dependency = _dependency_for(handler)
        if dependency not in allowed:
            offenders.append(f"{handler.__name__} uses {getattr(dependency, '__name__', dependency)!r}")

    assert offenders == []


def test_auth_management_route_dependency_contract():
    assert _dependency_for(auth.get_me) is require_joysafeter_user_context
    assert _dependency_for(auth.switch_context) is require_joysafeter_user_context
    assert _dependency_for(auth.list_projects) is require_joysafeter_user_context
    assert _dependency_for(auth.get_project) is require_joysafeter_user_context
    assert _dependency_for(auth.list_api_keys) is require_joysafeter_user_context
    assert _dependency_for(auth.create_organization) is require_joysafeter_user_context
    assert _dependency_for(auth.list_members) is require_joysafeter_user_context

    assert _dependency_for(auth.create_api_key) is require_joysafeter_user_write
    assert _dependency_for(auth.revoke_api_key) is require_joysafeter_user_write

    assert _dependency_for(auth.create_project) is require_joysafeter_user_admin
    assert _dependency_for(auth.update_project) is require_joysafeter_user_admin
    assert _dependency_for(auth.archive_project) is require_joysafeter_user_admin
    assert _dependency_for(auth.set_default_project) is require_joysafeter_user_admin
    assert _dependency_for(auth.restore_project) is require_joysafeter_user_admin
    assert _dependency_for(auth.search_users) is require_joysafeter_user_admin
    assert _dependency_for(auth.invite_member) is require_joysafeter_user_admin
    assert _dependency_for(auth.remove_member) is require_joysafeter_user_admin
    assert _dependency_for(auth.update_member_role) is require_joysafeter_user_admin
