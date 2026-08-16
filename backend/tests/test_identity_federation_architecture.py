import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "redis",
    "httpx",
    "yaml",
    "app.joysafeter_shared.config.settings",
    "app.joysafeter_domain.services.joysafeter_auth_service",
}


def test_nested_domain_module_forbidden_import_is_detected(tmp_path: Path) -> None:
    nested_module = tmp_path / "nested" / "internal.py"
    nested_module.parent.mkdir()
    nested_module.write_text("import fastapi\n")

    assert _find_forbidden_domain_imports(tmp_path) == {"fastapi"}


def _find_forbidden_domain_imports(domain_directory: Path) -> set[str]:
    imported_modules: set[str] = set()

    for source_path in domain_directory.rglob("*.py"):
        for node in ast.walk(ast.parse(source_path.read_text())):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    return {
        imported_module
        for imported_module in imported_modules
        for forbidden_import in FORBIDDEN_DOMAIN_IMPORTS
        if imported_module == forbidden_import or imported_module.startswith(f"{forbidden_import}.")
    }


def test_domain_has_no_forbidden_import_roots() -> None:
    domain_directory = Path(__file__).resolve().parents[1] / "app" / "joysafeter_identity_federation" / "domain"

    assert not _find_forbidden_domain_imports(domain_directory)


def test_auth_service_dependency_is_limited_to_session_gateway() -> None:
    federation_directory = Path(__file__).resolve().parents[1] / "app" / "joysafeter_identity_federation"

    assert _find_auth_service_imports(federation_directory) == {Path("infrastructure/session_gateway.py")}


def _find_auth_service_imports(federation_directory: Path) -> set[Path]:
    auth_service_module = "app.joysafeter_domain.services.joysafeter_auth_service"
    import_paths: set[Path] = set()

    for source_path in federation_directory.rglob("*.py"):
        imported_modules: set[str] = set()
        for node in ast.walk(ast.parse(source_path.read_text())):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        if any(
            imported_module == auth_service_module or imported_module.startswith(f"{auth_service_module}.")
            for imported_module in imported_modules
        ):
            import_paths.add(source_path.relative_to(federation_directory))

    return import_paths


def test_oauth_api_is_a_thin_federation_http_adapter() -> None:
    oauth_path = Path(__file__).resolve().parents[1] / "app" / "joysafeter_api" / "api" / "v1" / "oauth.py"
    oauth_source = oauth_path.read_text()

    for forbidden in (
        "RedisClient",
        "OAuthService",
        "AuthService",
        "get_oauth_config",
        "get_protocol_handler",
        '== "jd_sso"',
        "_redirect_to_jd_authorize",
        "_validate_state",
        ".commit(",
        ".rollback(",
    ):
        assert forbidden not in oauth_source
