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

FORBIDDEN_OAUTH_IMPORT_ROOTS = {
    "app.joysafeter_domain.services.joysafeter_auth_service",
    "app.joysafeter_identity_federation.application.callback_policy",
    "app.joysafeter_identity_federation.infrastructure",
    "app.joysafeter_shared.cache.redis",
    "app.joysafeter_shared.oauth",
}
FORBIDDEN_OAUTH_SYMBOLS = {
    "AuthService",
    "CallbackUrlPolicy",
    "OAuthService",
    "RedisClient",
}
FORBIDDEN_OAUTH_CALLS = {
    "_redirect_to_jd_authorize",
    "_resolve_frontend_callback_url",
    "_validate_state",
    "get_oauth_config",
    "get_protocol_handler",
}
FORBIDDEN_OAUTH_CALLBACK_HELPERS = {
    "_redirect_to_jd_authorize",
    "_resolve_frontend_callback_url",
    "_validate_state",
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


def test_oauth_api_architecture_analyzer_detects_forbidden_ast_shapes() -> None:
    source = """
from urllib.parse import urlparse
from app.joysafeter_identity_federation.application.callback_policy import CallbackUrlPolicy
from app.joysafeter_shared.cache.redis import RedisClient

async def _callback_url_fallback(protocol, db):
    await db.commit()
    if protocol == "jd_sso":
        return get_protocol_handler(urlparse("https://example.com"))
"""

    assert _oauth_api_architecture_violations(source) == {
        "call:commit",
        "call:get_protocol_handler",
        "callback-helper:_callback_url_fallback",
        "import:app.joysafeter_identity_federation.application.callback_policy",
        "import:app.joysafeter_shared.cache.redis",
        "import:urlparse",
        "protocol-branch:jd_sso",
        "symbol:CallbackUrlPolicy",
        "symbol:RedisClient",
    }


def _oauth_api_architecture_violations(source: str) -> set[str]:
    violations: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_import_root(alias.name, FORBIDDEN_OAUTH_IMPORT_ROOTS):
                    violations.add(f"import:{alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _matches_import_root(node.module, FORBIDDEN_OAUTH_IMPORT_ROOTS):
                violations.add(f"import:{node.module}")
            for alias in node.names:
                if alias.name in FORBIDDEN_OAUTH_SYMBOLS:
                    violations.add(f"symbol:{alias.name}")
                if node.module == "urllib.parse" and alias.name in {"urlparse", "urlsplit"}:
                    violations.add(f"import:{alias.name}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_OAUTH_SYMBOLS:
            violations.add(f"symbol:{node.id}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_forbidden_oauth_callback_helper(node.name):
                violations.add(f"callback-helper:{node.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and (
                node.func.id in FORBIDDEN_OAUTH_CALLS or _is_forbidden_oauth_callback_helper(node.func.id)
            ):
                violations.add(f"call:{node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {"commit", "rollback"}:
                violations.add(f"call:{node.func.attr}")
        elif isinstance(node, ast.Constant) and node.value == "jd_sso":
            violations.add("protocol-branch:jd_sso")

    return violations


def _matches_import_root(module: str, roots: set[str]) -> bool:
    return any(module == root or module.startswith(f"{root}.") for root in roots)


def _is_forbidden_oauth_callback_helper(name: str) -> bool:
    if name in FORBIDDEN_OAUTH_CALLBACK_HELPERS:
        return True
    normalized = name.lower()
    return "callback" in normalized and any(
        marker in normalized for marker in ("fallback", "normalize", "policy", "resolve", "validate")
    )


def test_oauth_api_is_a_thin_federation_http_adapter() -> None:
    oauth_path = Path(__file__).resolve().parents[1] / "app" / "joysafeter_api" / "api" / "v1" / "oauth.py"

    assert _oauth_api_architecture_violations(oauth_path.read_text()) == set()
