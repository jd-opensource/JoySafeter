from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
APP_ERRORS = APP_ROOT / "joysafeter_shared" / "common" / "app_errors.py"

# Semantic classes whose constructor takes `code=` and carries a default source.
SEMANTIC_CLASSES = {
    "NotFoundError",
    "InvalidRequestError",
    "AuthenticationError",
    "AccessDeniedError",
    "ResourceConflictError",
    "RateLimitExceededError",
    "InternalServiceError",
    "ServiceUnavailableError",
    "ClientClosedError",
    "RequestValidationAppError",
    "ModelConfigError",
    "AppError",
}


def _string_value(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


# Codes raised with >1 semantic class across sites (see --conflicts). The chosen
# class is the canonical one for the catalog; per-site raises are unchanged.
CONFLICT_RESOLUTIONS: dict[str, str] = {
    "PROJECT_ACCESS_DENIED": "AccessDeniedError",  # 403 access-denied, not an auth failure
    "SKILL_NAME_ALREADY_EXISTS": "ResourceConflictError",  # 409 name collision
    "USER_INVALID": "AuthenticationError",  # 401 login context
    "USER_NOT_FOUND": "AuthenticationError",  # 401 in auth flows (avoid user enumeration)
}


def scan_call_site_codes(root: Path) -> dict[str, tuple[set[str], str]]:
    """code -> (set of error_class names seen, first default_message)."""
    found: dict[str, tuple[set[str], str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            cls = call.func.id
            if cls not in SEMANTIC_CLASSES:
                continue
            code = None
            for kw in call.keywords:
                if kw.arg == "code":
                    code = _string_value(kw.value)
            if code is None:
                continue
            msg = ""
            if call.args:
                msg = _string_value(call.args[0]) or ""
            for kw in call.keywords:
                if kw.arg == "message":
                    msg = _string_value(kw.value) or msg
            classes, existing_msg = found.get(code, (set(), ""))
            classes.add(cls)
            found[code] = (classes, existing_msg or msg)
    return found


def scan_class_default_codes(app_errors: Path) -> dict[str, tuple[str, str]]:
    """code -> (error_class, default_message) from each subclass __init__ default `code=`."""
    tree = ast.parse(app_errors.read_text(encoding="utf-8"))
    found: dict[str, tuple[str, str]] = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        init = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        if init is None:
            continue
        args = init.args
        defaults_by_name: dict[str, ast.AST] = {}
        pos = args.args[1:]  # skip self
        if args.defaults:
            for name, default in zip([a.arg for a in pos][-len(args.defaults) :], args.defaults):
                defaults_by_name[name] = default
        for name, default in zip([a.arg for a in args.kwonlyargs], args.kw_defaults):
            if default is not None:
                defaults_by_name[name] = default
        code = _string_value(defaults_by_name["code"]) if "code" in defaults_by_name else None
        msg = _string_value(defaults_by_name["message"]) if "message" in defaults_by_name else ""
        if code:
            found.setdefault(code, (cls.name, msg or ""))
    return found


def collect() -> dict[str, tuple[str, str]]:
    """code -> (error_class, default_message). First class wins per code (see --conflicts)."""
    merged: dict[str, tuple[str, str]] = dict(scan_class_default_codes(APP_ERRORS))
    for code, (classes, msg) in scan_call_site_codes(APP_ROOT).items():
        if code in merged:
            continue
        chosen = CONFLICT_RESOLUTIONS.get(code) or sorted(classes)[0]
        merged[code] = (chosen, msg or code.replace("_", " ").capitalize())
    return dict(sorted(merged.items()))


def conflicts() -> dict[str, set[str]]:
    """code -> set of >1 error_class names, for the codes raised with divergent classes."""
    class_defaults = scan_class_default_codes(APP_ERRORS)
    out: dict[str, set[str]] = {}
    for code, (classes, _msg) in scan_call_site_codes(APP_ROOT).items():
        if code in class_defaults:
            continue
        if len(classes) > 1:
            out[code] = classes
    return out


def render_catalog(entries: dict[str, tuple[str, str]]) -> str:
    lines = [
        f'    "{code}": CatalogEntry(code="{code}", error_class={cls}, default_message={msg!r}),'
        for code, (cls, msg) in entries.items()
    ]
    return "CATALOG: dict[str, CatalogEntry] = {\n" + "\n".join(lines) + "\n}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="exit 1 if emitted codes not in catalog")
    ap.add_argument("--emit", action="store_true", help="print the CATALOG literal for pasting")
    ap.add_argument("--conflicts", action="store_true", help="list codes raised with >1 class")
    args = ap.parse_args()
    entries = collect()
    if args.conflicts:
        conf = conflicts()
        if not conf:
            print("No multi-class code conflicts.")
        for code, classes in sorted(conf.items()):
            print(f"{code}: {sorted(classes)}")
        return 0
    if args.emit:
        print(render_catalog(entries))
        return 0
    if args.audit:
        from app.joysafeter_shared.common.error_catalog import all_codes  # noqa: PLC0415

        missing = sorted(set(entries) - all_codes())
        if missing:
            print("Emitted codes missing from CATALOG:", *missing, sep="\n  ")
            return 1
        print(f"OK: all {len(entries)} emitted codes are registered.")
        return 0
    print(f"{len(entries)} emitted codes discovered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
