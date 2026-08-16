import ast
from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml

from app.joysafeter_shared.config.settings import Settings

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve()

LEGACY_PATHS = (
    Path("backend/app/joysafeter_shared/oauth"),
    Path("backend/config/oauth_providers.yaml"),
    Path("backend/config/oauth_providers.example.yaml"),
    Path("backend/config/README_OAUTH_LOCAL.md"),
    Path("backend/tests/test_oauth_async_boundary_contract.py"),
)

LEGACY_TEXT_TOKENS = (
    "app.joysafeter_shared.oauth",
    "joysafeter_shared/oauth",
    "OAuthService",
    "[OAuthService]",
    "_oauth_service_error_payload",
    "get_oauth_config",
    "reload_oauth_config",
    "OAuthConfigLoader",
    "get_protocol_handler",
    "oauth_config_path",
    "OAUTH_CONFIG_PATH",
    "SSO_DEFAULT_PROVIDER",
    "JD_TOKEN_URL",
    "JOYSAFETER_ENABLED",
    "oauth_providers.yaml",
    "oauth_providers.example.yaml",
    "README_OAUTH_LOCAL.md",
)

LEGACY_PYTHON_SYMBOLS = {
    "OAuthService",
    "_oauth_service_error_payload",
    "get_oauth_config",
    "reload_oauth_config",
    "OAuthConfigLoader",
    "get_protocol_handler",
}

ACTIVE_TEXT_ROOTS = (
    Path("backend/app"),
    Path("backend/config"),
    Path("frontend/app"),
    Path("frontend/components"),
    Path("frontend/lib"),
    Path("deploy"),
    Path("docs"),
)

ACTIVE_TEXT_FILES = (
    Path("backend/env.example"),
    Path("frontend/env.example"),
    Path("frontend/README.md"),
    Path("README.md"),
    Path("README_CN.md"),
    Path("INSTALL.md"),
    Path("INSTALL_CN.md"),
    Path("DEVELOPMENT.md"),
    Path("CHANGELOG.md"),
)

TEXT_SUFFIXES = {".cjs", ".env", ".example", ".js", ".json", ".jsx", ".md", ".mjs", ".py", ".ts", ".tsx", ".yaml", ".yml"}


def _iter_active_text_files() -> Iterable[Path]:
    for relative_root in ACTIVE_TEXT_ROOTS:
        root = REPO_ROOT / relative_root
        for path in root.rglob("*"):
            relative_path = path.relative_to(REPO_ROOT)
            if relative_path.parts[:2] in {("docs", "plans"), ("docs", "superpowers")}:
                continue
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                yield path

    for relative_path in ACTIVE_TEXT_FILES:
        path = REPO_ROOT / relative_path
        if path.is_file():
            yield path


def _search_active_text(token: str) -> list[str]:
    matches: list[str] = []
    for path in _iter_active_text_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if token in line:
                matches.append(f"{path.relative_to(REPO_ROOT)}:{line_number}:{line.strip()}")
    return matches


def _iter_python_sources() -> Iterable[Path]:
    for relative_root in (Path("backend/app"), Path("backend/tests")):
        for path in (REPO_ROOT / relative_root).rglob("*.py"):
            if path.resolve() != THIS_FILE:
                yield path


def _legacy_python_references() -> list[str]:
    violations: list[str] = []
    for path in _iter_python_sources():
        relative_path = path.relative_to(REPO_ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.joysafeter_shared.oauth" or alias.name.startswith(
                        "app.joysafeter_shared.oauth."
                    ):
                        violations.append(f"{relative_path}:{node.lineno}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "app.joysafeter_shared.oauth" or module.startswith("app.joysafeter_shared.oauth."):
                    violations.append(f"{relative_path}:{node.lineno}:import-from:{module}")
                for alias in node.names:
                    if alias.name in LEGACY_PYTHON_SYMBOLS:
                        violations.append(f"{relative_path}:{node.lineno}:import-symbol:{alias.name}")
            elif isinstance(node, ast.Name) and node.id in LEGACY_PYTHON_SYMBOLS:
                violations.append(f"{relative_path}:{node.lineno}:name:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in LEGACY_PYTHON_SYMBOLS:
                violations.append(f"{relative_path}:{node.lineno}:attribute:{node.attr}")
    return sorted(set(violations))


def _dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value
    return values


def test_legacy_federation_runtime_and_config_files_are_removed() -> None:
    existing = [str(path) for path in LEGACY_PATHS if (REPO_ROOT / path).exists()]

    assert existing == []
    assert (REPO_ROOT / "backend/config/README_IDENTITY_FEDERATION_LOCAL.md").is_file()
    assert (REPO_ROOT / "backend/tests/test_identity_federation_async_boundary_contract.py").is_file()


@pytest.mark.parametrize("token", LEGACY_TEXT_TOKENS)
def test_legacy_tokens_are_absent_from_active_runtime_deploy_and_config_docs(token: str) -> None:
    assert _search_active_text(token) == []


def test_python_imports_and_symbol_references_do_not_reach_legacy_oauth_runtime() -> None:
    assert _legacy_python_references() == []


def test_settings_model_exposes_only_identity_federation_configuration() -> None:
    assert "oauth_config_path" not in Settings.model_fields
    assert {
        "identity_federation_providers",
        "identity_federation_config_path",
        "identity_federation_login_mode",
    }.issubset(Settings.model_fields)


def test_provider_catalog_has_no_per_provider_compatibility_activation_keys() -> None:
    catalog_path = REPO_ROOT / "backend/config/identity_federation_providers.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    providers = catalog["providers"]

    assert isinstance(providers, dict)
    assert {
        key
        for provider in providers.values()
        for key in provider
        if key in {"enabled", "auto", "default_provider"}
    } == set()


def test_env_examples_publish_only_canonical_federation_activation() -> None:
    backend_values = _dotenv_values(REPO_ROOT / "backend/env.example")
    deploy_values = _dotenv_values(REPO_ROOT / "deploy/.env.example")

    assert backend_values["IDENTITY_FEDERATION_PROVIDERS"] == ""
    assert backend_values["IDENTITY_FEDERATION_CONFIG_PATH"] == ""
    assert backend_values["IDENTITY_FEDERATION_LOGIN_MODE"] == "chooser"
    assert deploy_values["IDENTITY_FEDERATION_PROVIDERS"] == "jd"
    assert deploy_values["IDENTITY_FEDERATION_CONFIG_PATH"] == ""
    assert deploy_values["IDENTITY_FEDERATION_LOGIN_MODE"] == "redirect"


def test_compose_explicitly_passes_canonical_federation_environment() -> None:
    compose_path = REPO_ROOT / "deploy/docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    common_environment = compose["x-backend-common-env"]

    assert common_environment["IDENTITY_FEDERATION_PROVIDERS"] == "${IDENTITY_FEDERATION_PROVIDERS:-}"
    assert common_environment["IDENTITY_FEDERATION_CONFIG_PATH"] == "${IDENTITY_FEDERATION_CONFIG_PATH:-}"
    assert common_environment["IDENTITY_FEDERATION_LOGIN_MODE"] == "${IDENTITY_FEDERATION_LOGIN_MODE:-chooser}"
