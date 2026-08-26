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


def test_federation_user_ids_remain_typed_across_application_boundaries() -> None:
    federation_directory = Path(__file__).resolve().parents[1] / "app" / "joysafeter_identity_federation"
    paths = (
        federation_directory / "domain/models.py",
        federation_directory / "domain/ports.py",
        federation_directory / "application/accounts.py",
        federation_directory / "infrastructure/account_gateway.py",
        federation_directory / "infrastructure/session_gateway.py",
    )

    for path in paths:
        assert "user_id: str" not in path.read_text(), path


def test_federation_tests_do_not_reintroduce_string_user_or_account_ids() -> None:
    tests_directory = Path(__file__).resolve().parent
    paths = (
        tests_directory / "test_identity_federation_account_gateway.py",
        tests_directory / "test_identity_federation_api.py",
        tests_directory / "test_identity_federation_complete_login.py",
        tests_directory / "test_identity_federation_session_gateway.py",
    )

    for path in paths:
        source = path.read_text()
        assert "user_id: str" not in source, path
        assert 'user_id="user-' not in source, path
        assert "id=str(uuid.uuid4())" not in source, path


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
        "call:urlparse",
        "callback-helper:_callback_url_fallback",
        "import:app.joysafeter_identity_federation.application.callback_policy",
        "import:app.joysafeter_shared.cache.redis",
        "import:urlparse",
        "protocol-branch:jd_sso",
        "symbol:CallbackUrlPolicy",
        "symbol:RedisClient",
    }


def test_oauth_api_architecture_analyzer_resolves_url_aliases_and_raw_callback_access() -> None:
    source = """
import urllib.parse as parser
from urllib import parse as url_tools
from urllib.parse import urljoin as combine

def _safe_destination(result):
    raw = result.callback_url
    return (
        parser.urlparse(raw),
        url_tools.urlsplit(raw),
        url_tools.unquote(raw),
        combine("https://app.example", raw),
    )
"""

    assert _oauth_api_architecture_violations(source) == {
        "call:unquote",
        "call:urljoin",
        "call:urlparse",
        "call:urlsplit",
        "import:urllib.parse",
        "import:urljoin",
        "raw-attribute:callback_url",
    }


def test_oauth_api_architecture_analyzer_resolves_top_level_urllib_alias() -> None:
    source = """
import urllib as tools

def inspect_destination(value):
    return (
        tools.parse.urlsplit(value),
        tools.parse.urlparse(value),
        tools.parse.urljoin("https://app.example", value),
        tools.parse.unquote(value),
    )
"""

    assert _oauth_api_architecture_violations(source) == {
        "call:unquote",
        "call:urljoin",
        "call:urlparse",
        "call:urlsplit",
    }


def test_oauth_api_architecture_analyzer_allows_urlencode_only() -> None:
    source = """
from urllib.parse import urlencode as encode_query

def redirect_error(code):
    return encode_query({"error_code": code})
"""

    assert _oauth_api_architecture_violations(source) == set()


def _oauth_api_architecture_violations(source: str) -> set[str]:
    tree = ast.parse(source)
    violations: set[str] = set()
    aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_import_root(alias.name, FORBIDDEN_OAUTH_IMPORT_ROOTS):
                    violations.add(f"import:{alias.name}")
                if alias.name == "urllib.parse":
                    bound_name = alias.asname or "urllib"
                    aliases[bound_name] = "urllib.parse" if alias.asname else "urllib"
                    violations.add("import:urllib.parse")
                elif alias.name == "urllib":
                    aliases[alias.asname or "urllib"] = "urllib"
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _matches_import_root(node.module, FORBIDDEN_OAUTH_IMPORT_ROOTS):
                violations.add(f"import:{node.module}")
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if alias.name in FORBIDDEN_OAUTH_SYMBOLS:
                    violations.add(f"symbol:{alias.name}")

                if node.module == "urllib" and alias.name == "parse":
                    aliases[bound_name] = "urllib.parse"
                    violations.add("import:urllib.parse")
                elif node.module == "urllib.parse":
                    aliases[bound_name] = f"urllib.parse.{alias.name}"
                    if alias.name != "urlencode":
                        violations.add(f"import:{alias.name}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_OAUTH_SYMBOLS:
            violations.add(f"symbol:{node.id}")
        elif isinstance(node, ast.Attribute) and node.attr == "callback_url":
            violations.add("raw-attribute:callback_url")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_forbidden_oauth_callback_helper(node.name):
                violations.add(f"callback-helper:{node.name}")
        elif isinstance(node, ast.Call):
            qualified_call = _qualified_ast_name(node.func, aliases)
            call_name = qualified_call.rsplit(".", 1)[-1]
            if call_name in FORBIDDEN_OAUTH_CALLS or _is_forbidden_oauth_callback_helper(call_name):
                violations.add(f"call:{call_name}")
            if qualified_call.startswith("urllib.parse.") and call_name != "urlencode":
                violations.add(f"call:{call_name}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"commit", "rollback"}:
                violations.add(f"call:{node.func.attr}")
        elif isinstance(node, ast.Constant) and node.value == "jd_sso":
            violations.add("protocol-branch:jd_sso")

    return violations


def _qualified_ast_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_ast_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


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
