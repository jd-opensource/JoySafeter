import ast
from pathlib import Path

FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "redis",
    "httpx",
    "yaml",
    "app.joysafeter_shared.config.settings",
    "app.joysafeter_domain.services.joysafeter_auth_service",
}


def test_domain_has_no_forbidden_import_roots() -> None:
    domain_directory = (
        Path(__file__).resolve().parents[1] / "app" / "joysafeter_identity_federation" / "domain"
    )
    imported_modules: set[str] = set()

    for source_path in domain_directory.glob("*.py"):
        for node in ast.walk(ast.parse(source_path.read_text())):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not {
        imported_module
        for imported_module in imported_modules
        for forbidden_import in FORBIDDEN_DOMAIN_IMPORTS
        if imported_module == forbidden_import or imported_module.startswith(f"{forbidden_import}.")
    }
