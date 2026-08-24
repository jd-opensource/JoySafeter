from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_ROOT = BACKEND_ROOT / "app" / "joysafeter_domain" / "credentials"
CREDENTIAL_SCHEMA = BACKEND_ROOT / "app" / "joysafeter_domain" / "schemas" / "joysafeter_credential.py"
EXPECTED_MODULES = {
    "__init__.py",
    "bindings.py",
    "dependencies.py",
    "lifecycle.py",
    "material.py",
    "policies.py",
    "references.py",
    "resource.py",
    "types.py",
}
BANNED_IMPORT_PREFIXES = {
    "aiohttp",
    "fastapi",
    "http.client",
    "httpx",
    "pydantic",
    "redis",
    "requests",
    "sqlalchemy",
    "urllib.request",
}
BANNED_APP_LAYERS = {
    "app.joysafeter_api",
    "app.joysafeter_application",
    "app.joysafeter_infrastructure",
    "app.joysafeter_domain.routers",
}


def _module_name(path: Path, domain_root: Path) -> str:
    relative = path.relative_to(domain_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    suffix = ".".join(parts)
    return "app.joysafeter_domain.credentials" + (f".{suffix}" if suffix else "")


def _imports(path: Path, domain_root: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_name = _module_name(path, domain_root)
    package_name = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                resolved = resolve_name(relative_name, package_name)
            else:
                resolved = node.module or ""
            if resolved:
                imported.add(resolved)
                imported.update(f"{resolved}.{alias.name}" for alias in node.names if alias.name != "*")
    return imported


def _domain_import_violations(domain_root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(domain_root.rglob("*.py")):
        for imported in sorted(_imports(path, domain_root)):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in BANNED_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(domain_root)}: forbidden import {imported}")
            if any(imported == layer or imported.startswith(f"{layer}.") for layer in BANNED_APP_LAYERS):
                violations.append(f"{path.relative_to(domain_root)}: outward layer import {imported}")
            if imported.startswith("app.") and not imported.startswith("app.joysafeter_domain.credentials"):
                violations.append(f"{path.relative_to(domain_root)}: non-domain-core app import {imported}")
    return violations


def test_domain_core_has_the_exact_scoped_module_set() -> None:
    assert DOMAIN_ROOT.is_dir(), "Task 4 domain package must exist"
    assert {path.name for path in DOMAIN_ROOT.glob("*.py")} == EXPECTED_MODULES


def test_domain_core_import_graph_is_framework_free_and_inward_only() -> None:
    assert _domain_import_violations(DOMAIN_ROOT) == []


def test_architecture_guard_recurses_resolves_relative_imports_and_bans_http_clients(tmp_path: Path) -> None:
    domain_root = tmp_path / "app" / "joysafeter_domain" / "credentials"
    nested_root = domain_root / "nested"
    nested_root.mkdir(parents=True)
    (domain_root / "__init__.py").write_text("", encoding="utf-8")
    (domain_root / "url_value.py").write_text("from urllib.parse import urlsplit\n", encoding="utf-8")
    (nested_root / "__init__.py").write_text("", encoding="utf-8")
    (nested_root / "escape.py").write_text(
        "from ...schemas import joysafeter_credential\nimport urllib.request\nimport http.client\n",
        encoding="utf-8",
    )

    violations = _domain_import_violations(domain_root)

    assert any("app.joysafeter_domain.schemas" in violation for violation in violations)
    assert any("urllib.request" in violation for violation in violations)
    assert any("http.client" in violation for violation in violations)
    assert not any("urllib.parse" in violation for violation in violations)


@pytest.mark.parametrize(
    ("source", "forbidden_path"),
    [
        ("from urllib import request\n", "urllib.request"),
        ("from http import client\n", "http.client"),
        ("from ... import schemas\n", "app.joysafeter_domain.schemas"),
    ],
)
def test_architecture_guard_expands_importfrom_aliases(
    tmp_path: Path,
    source: str,
    forbidden_path: str,
) -> None:
    domain_root = tmp_path / "app" / "joysafeter_domain" / "credentials"
    nested_root = domain_root / "nested"
    nested_root.mkdir(parents=True)
    (domain_root / "__init__.py").write_text("", encoding="utf-8")
    (nested_root / "__init__.py").write_text("", encoding="utf-8")
    (nested_root / "escape.py").write_text(source, encoding="utf-8")

    violations = _domain_import_violations(domain_root)

    assert any(forbidden_path in violation for violation in violations)


def test_architecture_guard_allows_importfrom_urllib_parse_aliases(tmp_path: Path) -> None:
    domain_root = tmp_path / "app" / "joysafeter_domain" / "credentials"
    domain_root.mkdir(parents=True)
    (domain_root / "__init__.py").write_text("", encoding="utf-8")
    (domain_root / "url_value.py").write_text(
        "from urllib.parse import SplitResult, urlsplit, urlunsplit\n",
        encoding="utf-8",
    )

    assert _domain_import_violations(domain_root) == []


def test_domain_core_contains_no_framework_or_side_effect_concepts() -> None:
    banned_tokens = {
        "AsyncSession",
        "BaseModel",
        "Depends",
        "FastAPI",
        "HTTPException",
        "Redis",
        "Repository",
        "Session",
        "httpx",
    }
    violations: list[str] = []
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in sorted(banned_tokens):
            if token in source:
                violations.append(f"{path.name}: {token}")

    assert violations == []


def test_pydantic_credential_schema_imports_domain_kind_and_limits() -> None:
    source = CREDENTIAL_SCHEMA.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CREDENTIAL_SCHEMA))
    imported: dict[str, set[str]] = {}
    defined_classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)

    assert "CredentialKind" not in defined_classes
    assert imported["app.joysafeter_domain.credentials.types"] == {
        "CredentialAuthScheme",
        "CredentialKind",
    }
    assert imported["app.joysafeter_domain.credentials.material"] == {
        "CREDENTIAL_MATERIAL_MAX_FIELDS",
        "CREDENTIAL_MATERIAL_MAX_FIELD_NAME_LENGTH",
        "CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH",
    }
