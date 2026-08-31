from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, Table

import app.joysafeter_domain.models  # noqa: F401 — register ORM metadata
from app.joysafeter_domain.credentials.dependencies import CREDENTIAL_REFERENCE_SURFACES
from app.joysafeter_shared.database import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
EXCEPTIONS_PATH = BACKEND_ROOT / "contracts" / "credential_reference_surface_exceptions.json"
REFERENCE_CONTRACT_PATH = BACKEND_ROOT / "contracts" / "credential_reference_contract.json"
CREDENTIAL_TABLES = {
    "joysafeter_credentials",
    "joysafeter_credential_groups",
    "joysafeter_session_credential_groups",
}
REFERENCE_COLUMN_NAMES = {
    "model_credential_id",
    "webhook_auth_credential_id",
    "credential_group_id",
    "group_id",
}
SENSITIVE_CALL_NAMES = {"decrypt", "reveal", "reveal_values"}
RAW_KEY_EXCLUDED_FILES: set[str] = set()
RAW_KEY_EXCLUDED_SCOPES: set[tuple[str, str]] = set()
CODEC_INTERNAL_RAW_KEY_PREFIX = "raw_key:backend/app/joysafeter_domain/credentials/references.py:"


@dataclass(frozen=True, slots=True)
class CensusFinding:
    surface: str
    category: str


REGISTERED_CLASSIFICATIONS = {
    "typed_id:sqlalchemy:joysafeter_agents.model_credential_id": {"live_agent_model_binding"},
    "typed_id:sqlalchemy:joysafeter_triggers.webhook_auth_credential_id": {"trigger_webhook_auth_binding"},
    "typed_id:sqlalchemy:joysafeter_session_credential_groups.credential_group_id": {
        "session_credential_group_association"
    },
    "typed_id:alembic:20260814_000001_unify_credentials:joysafeter_agents.model_credential_id->joysafeter_credentials.id": {
        "live_agent_model_binding"
    },
    "typed_id:alembic:20260814_000001_unify_credentials:joysafeter_triggers.webhook_auth_credential_id->joysafeter_credentials.id": {
        "trigger_webhook_auth_binding"
    },
    "typed_id:alembic:20260814_000001_unify_credentials:joysafeter_session_credential_groups.credential_group_id->joysafeter_credential_groups.id": {
        "session_credential_group_association"
    },
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:58260fff0370": {
        "trigger_webhook_auth_binding"
    },
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:3367698b1fc3": {
        "trigger_webhook_auth_binding"
    },
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:62ee839db546": {
        "trigger_webhook_auth_binding"
    },
    "raw_key:backend/app/joysafeter_domain/triggers/providers/webhook.py:<module>.WebhookTriggerProvider.build_config:webhook_auth_credential_id:9c088451c7c5": {
        "trigger_webhook_auth_binding"
    },
}


def _codec_path_classifications() -> dict[str, set[str]]:
    contract = json.loads(REFERENCE_CONTRACT_PATH.read_text())
    classifications = {}
    for entry in contract["reference_paths"]:
        fixture = entry["scanner_fixture"]
        surface = entry["surface"]
        for schema in entry["schemas"]:
            identity = f"codec_path:{schema}:{entry['document']}:{entry['path']}:{surface}:{fixture}"
            classifications[identity] = {surface}
    return classifications


REGISTERED_CLASSIFICATIONS.update(_codec_path_classifications())
AGGREGATE_INTERNAL_CLASSIFICATIONS = {
    "typed_id:sqlalchemy:joysafeter_credentials.group_id",
    "typed_id:alembic:20260814_000001_unify_credentials:joysafeter_credentials.group_id->joysafeter_credential_groups.id",
    "typed_id:alembic:20260814_000001_unify_credentials:joysafeter_credentials.project_id->joysafeter_credential_groups.project_id",
}
EXPECTED_PRODUCTION_RAW_KEY_SURFACES = {
    "raw_key:backend/app/joysafeter_api/api/v1/credentials.py:<module>.get_credential:/{credential_id}:cb1cb666ca53",
    "raw_key:backend/app/joysafeter_domain/services/credential_binding_errors.py:<module>.raise_public_credential_error:credential_id:9c4f2e9cd651",
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:58260fff0370",
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:3367698b1fc3",
    "raw_key:backend/app/joysafeter_domain/services/joysafeter_trigger_config_policy.py:<module>.TriggerConfigPolicy.plan_update:webhook_auth_credential_id:62ee839db546",
    "raw_key:backend/app/joysafeter_domain/triggers/providers/webhook.py:<module>.WebhookTriggerProvider.build_config:webhook_auth_credential_id:9c088451c7c5",
}


def _column_is_credential_reference(column) -> bool:
    foreign_keys = {foreign_key.target_fullname for foreign_key in column.foreign_keys}
    return foreign_keys.intersection(
        {
            "joysafeter_credentials.id",
            "joysafeter_credential_groups.id",
        }
    ) or (
        column.name in REFERENCE_COLUMN_NAMES
        and (
            foreign_keys.intersection(
                {
                    "joysafeter_credentials.id",
                    "joysafeter_credential_groups.id",
                }
            )
            or type(column.type).__name__ == "EntityIdType"
        )
    )


def discover_sqlalchemy_typed_ids(metadata: MetaData) -> set[CensusFinding]:
    findings = set()
    for table in metadata.tables.values():
        for column in table.columns:
            if _column_is_credential_reference(column):
                findings.add(
                    CensusFinding(
                        f"typed_id:sqlalchemy:{table.name}.{column.name}",
                        "typed_id",
                    )
                )
    return findings


def _literal_text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_texts(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return ()
    values = tuple(_literal_text(element) for element in node.elts)
    return tuple(value for value in values if value is not None)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


@dataclass(frozen=True, slots=True)
class PythonCallsite:
    scope: str
    node: ast.AST


class _PythonCallsiteVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope = ["<module>"]
        self.callsites: list[PythonCallsite] = []

    def _visit_scope(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        self.callsites.append(PythonCallsite(".".join(self.scope), node))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.callsites.append(PythonCallsite(".".join(self.scope), node))

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.callsites.append(PythonCallsite(".".join(self.scope), node))
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        self.callsites.append(PythonCallsite(".".join(self.scope), node))
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        self.callsites.append(PythonCallsite(".".join(self.scope), node))
        self.generic_visit(node)


def _python_callsites(source: str) -> tuple[PythonCallsite, ...]:
    visitor = _PythonCallsiteVisitor()
    visitor.visit(ast.parse(source))
    return tuple(visitor.callsites)


def _span(node: ast.AST) -> str:
    return f"L{node.lineno}C{node.col_offset}-L{node.end_lineno}C{node.end_col_offset}"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(" ".join(value.split()).encode()).hexdigest()[:12]


def discover_alembic_typed_ids(versions_dir: Path) -> set[CensusFinding]:
    findings: set[CensusFinding] = set()
    for path in versions_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        revision = (
            next(
                (
                    _literal_text(node.value)
                    for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets)
                ),
                None,
            )
            or path.stem
        )

        def add(table_name: str, column_name: str, target: str) -> None:
            findings.add(
                CensusFinding(
                    f"typed_id:alembic:{revision}:{table_name}.{column_name}->{target}",
                    "typed_id",
                )
            )

        def inspect_column(table_name: str, column_call: ast.Call) -> None:
            if not column_call.args:
                return
            column_name = _literal_text(column_call.args[0])
            if column_name is None:
                return
            for argument in column_call.args[1:]:
                if not isinstance(argument, ast.Call):
                    continue
                argument_name = _call_name(argument.func)
                if argument_name and argument_name.endswith("ForeignKey") and argument.args:
                    target = _literal_text(argument.args[0])
                    if target and target.split(".", 1)[0] in CREDENTIAL_TABLES:
                        add(table_name, column_name, target)
                if argument_name and argument_name.endswith("EntityIdType") and argument.args:
                    id_type = _call_name(argument.args[0])
                    if id_type in {"CredentialId", "CredentialGroupId"}:
                        add(table_name, column_name, id_type)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "create_table" and node.args:
                table_name = _literal_text(node.args[0])
                for argument in node.args[1:]:
                    if not isinstance(argument, ast.Call) or not isinstance(argument.func, ast.Attribute):
                        continue
                    if argument.func.attr == "Column" and table_name:
                        inspect_column(table_name, argument)
                    if argument.func.attr == "ForeignKeyConstraint" and table_name and len(argument.args) >= 2:
                        local_columns = _literal_texts(argument.args[0])
                        remote_columns = _literal_texts(argument.args[1])
                        for local_column, remote_column in zip(local_columns, remote_columns, strict=True):
                            if remote_column.split(".", 1)[0] in CREDENTIAL_TABLES:
                                add(table_name, local_column, remote_column)
            if node.func.attr == "add_column" and len(node.args) >= 2:
                table_name = _literal_text(node.args[0])
                column_call = node.args[1]
                if (
                    table_name
                    and isinstance(column_call, ast.Call)
                    and isinstance(column_call.func, ast.Attribute)
                    and column_call.func.attr == "Column"
                    and column_call.args
                ):
                    inspect_column(table_name, column_call)
            if node.func.attr == "create_foreign_key" and len(node.args) >= 5:
                table_name = _literal_text(node.args[1])
                target_table = _literal_text(node.args[2])
                local_columns = _literal_texts(node.args[3])
                remote_columns = _literal_texts(node.args[4])
                if table_name and target_table in CREDENTIAL_TABLES:
                    for local_column, remote_column in zip(local_columns, remote_columns, strict=True):
                        add(table_name, local_column, f"{target_table}.{remote_column}")
    return findings


def discover_codec_keys(contract_path: Path) -> set[CensusFinding]:
    contract = json.loads(contract_path.read_text())
    findings = set()
    for entry in contract["reference_paths"]:
        fixture = entry["scanner_fixture"]
        surface = entry["surface"]
        findings.update(
            CensusFinding(
                f"codec_path:{schema}:{entry['document']}:{entry['path']}:{surface}:{fixture}",
                "codec_key",
            )
            for schema in entry["schemas"]
        )
    return findings


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def discover_python_raw_sql(paths: Iterable[Path]) -> set[CensusFinding]:
    findings = set()
    for path in paths:
        relative_path = _display_path(path)
        for callsite in _python_callsites(path.read_text()):
            literal = _literal_text(callsite.node)
            if literal is None:
                continue
            normalized = " ".join(literal.lower().split())
            if not re.search(r"\b(select|insert|update|delete|from|join)\b", normalized):
                continue
            for table in CREDENTIAL_TABLES:
                if table in normalized:
                    findings.add(
                        CensusFinding(
                            f"raw_sql:python:{relative_path}:{callsite.scope}:{table}:{_fingerprint(normalized)}",
                            "raw_sql",
                        )
                    )
    return findings


@dataclass(frozen=True, slots=True)
class RustStringLiteral:
    start: int
    end: int
    kind: str
    value: str
    terminated: bool


@dataclass(frozen=True, slots=True)
class RustFunction:
    name: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class RustAttribute:
    start: int
    end: int
    name: str | None


@dataclass(frozen=True, slots=True)
class RustModuleDeclaration:
    name: str
    namespace: tuple[str, ...]
    start: int
    attributes: tuple[RustAttribute, ...]


@dataclass(frozen=True, slots=True)
class RustCompileInputEdge:
    start: int
    target: Path


@dataclass(frozen=True, slots=True)
class RustProductionSource:
    path: Path
    source: str
    code: str
    literals: tuple[RustStringLiteral, ...]
    functions: tuple[RustFunction, ...]


def _blank_rust_range(mask: list[str], source: str, start: int, end: int) -> None:
    for index in range(start, end):
        if source[index] != "\n":
            mask[index] = " "


def _rust_code_and_literals(source: str) -> tuple[str, tuple[RustStringLiteral, ...]]:
    mask = list(source)
    literals = []
    cursor = 0
    while cursor < len(source):
        if source.startswith("//", cursor):
            end = source.find("\n", cursor + 2)
            end = len(source) if end < 0 else end
            _blank_rust_range(mask, source, cursor, end)
            cursor = end
            continue
        if source.startswith("/*", cursor):
            depth = 1
            end = cursor + 2
            while end < len(source) and depth:
                if source.startswith("/*", end):
                    depth += 1
                    end += 2
                elif source.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            _blank_rust_range(mask, source, cursor, end)
            cursor = end
            continue

        raw_match = re.match(r"(?P<prefix>(?:b|c)?r)(?P<hashes>#{0,255})\"", source[cursor:])
        if raw_match:
            prefix = raw_match.group("prefix")
            hashes = raw_match.group("hashes")
            value_start = cursor + raw_match.end()
            terminator = f'"{hashes}'
            terminator_start = source.find(terminator, value_start)
            terminated = terminator_start >= 0
            end = len(source) if not terminated else terminator_start + len(terminator)
            value_end = len(source) if not terminated else terminator_start
            kind = {"r": "raw", "br": "raw_byte", "cr": "raw_c"}[prefix]
            literals.append(RustStringLiteral(cursor, end, kind, source[value_start:value_end], terminated))
            _blank_rust_range(mask, source, cursor, end)
            cursor = end
            continue

        string_prefix = 2 if source.startswith(('b"', 'c"'), cursor) else 1 if source[cursor] == '"' else 0
        if string_prefix:
            kind = {1: "ordinary", 2: "byte" if source[cursor] == "b" else "c"}[string_prefix]
            value_start = cursor + string_prefix
            end = value_start
            escaped = False
            terminated = False
            while end < len(source):
                char = source[end]
                if char == '"' and not escaped:
                    end += 1
                    terminated = True
                    break
                if char == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
                end += 1
            value_end = end - 1 if terminated else end
            literals.append(RustStringLiteral(cursor, end, kind, source[value_start:value_end], terminated))
            _blank_rust_range(mask, source, cursor, end)
            cursor = end
            continue

        if source[cursor] == "'":
            end = cursor + 1
            escaped = False
            while end < len(source) and end - cursor <= 8:
                char = source[end]
                if char == "'" and not escaped:
                    end += 1
                    _blank_rust_range(mask, source, cursor, end)
                    cursor = end
                    break
                if char == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
                end += 1
            else:
                cursor += 1
            continue
        cursor += 1
    return "".join(mask), tuple(literals)


def _matching_rust_delimiter(source: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for cursor in range(start, len(source)):
        if source[cursor] == opening:
            depth += 1
        elif source[cursor] == closing:
            depth -= 1
            if depth == 0:
                return cursor + 1
    return len(source)


def _matching_rust_group(source: str, start: int) -> int | None:
    pairs = {"(": ")", "[": "]", "{": "}"}
    opening = source[start] if start < len(source) else ""
    if opening not in pairs:
        return None
    stack = [opening]
    for cursor in range(start + 1, len(source)):
        char = source[cursor]
        if char in pairs:
            stack.append(char)
            continue
        if char not in pairs.values():
            continue
        if pairs[stack[-1]] != char:
            return None
        stack.pop()
        if not stack:
            return cursor + 1
    return None


def _rust_skip_whitespace(code: str, cursor: int, end: int | None = None) -> int:
    boundary = len(code) if end is None else end
    while cursor < boundary and code[cursor].isspace():
        cursor += 1
    return cursor


def _rust_identifier(code: str, cursor: int, end: int | None = None) -> tuple[str, int] | None:
    boundary = len(code) if end is None else end
    if cursor >= boundary or not (code[cursor].isalpha() or code[cursor] == "_"):
        return None
    identifier_end = cursor + 1
    while identifier_end < boundary and (code[identifier_end].isalnum() or code[identifier_end] == "_"):
        identifier_end += 1
    return code[cursor:identifier_end], identifier_end


class _RustCfgParser:
    def __init__(self, expression: str) -> None:
        self.tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_-]*|[(),=]", expression)
        self.cursor = 0

    def parse(self) -> bool | None:
        if self.cursor >= len(self.tokens):
            return None
        name = self.tokens[self.cursor]
        self.cursor += 1
        if self.cursor < len(self.tokens) and self.tokens[self.cursor] == "=":
            self.cursor += 1
            if self.cursor < len(self.tokens) and self.tokens[self.cursor] not in {",", ")"}:
                self.cursor += 1
            return None
        if self.cursor >= len(self.tokens) or self.tokens[self.cursor] != "(":
            return False if name == "test" else None
        self.cursor += 1
        values = []
        while self.cursor < len(self.tokens) and self.tokens[self.cursor] != ")":
            values.append(self.parse())
            if self.cursor < len(self.tokens) and self.tokens[self.cursor] == ",":
                self.cursor += 1
        if self.cursor < len(self.tokens) and self.tokens[self.cursor] == ")":
            self.cursor += 1
        if name == "not" and len(values) == 1:
            return None if values[0] is None else not values[0]
        if name == "all":
            if any(value is False for value in values):
                return False
            return True if values and all(value is True for value in values) else None
        if name == "any":
            if any(value is True for value in values):
                return True
            return False if values and all(value is False for value in values) else None
        return None


def _rust_item_end(code: str, start: int) -> int:
    parentheses = 0
    brackets = 0
    cursor = start
    while cursor < len(code):
        char = code[cursor]
        if char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        elif char == "{" and parentheses == 0 and brackets == 0:
            return _matching_rust_delimiter(code, cursor, "{", "}")
        elif char == ";" and parentheses == 0 and brackets == 0:
            return cursor + 1
        cursor += 1
    return len(code)


def _rust_cfg_exclusions(code: str) -> tuple[tuple[tuple[int, int], ...], tuple[str, ...]]:
    ranges = []
    external_modules = []
    marker = re.compile(r"#\s*\[\s*cfg\s*\(")
    for match in marker.finditer(code):
        expression_start = code.find("(", match.start())
        expression_end = _matching_rust_delimiter(code, expression_start, "(", ")")
        if _RustCfgParser(code[expression_start + 1 : expression_end - 1]).parse() is not False:
            continue
        attribute_end = code.find("]", expression_end)
        if attribute_end < 0:
            attribute_end = expression_end
        item_start = attribute_end + 1
        while item_start < len(code) and code[item_start].isspace():
            item_start += 1
        item_end = _rust_item_end(code, item_start)
        ranges.append((match.start(), item_end))
        declaration = code[item_start:item_end]
        module_match = re.fullmatch(r"(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", declaration.strip())
        if module_match:
            external_modules.append(module_match.group(1))
    return tuple(ranges), tuple(external_modules)


def _rust_external_module_candidates(
    path: Path,
    module_name: str,
    *,
    crate_root: bool,
    namespace: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    base = path.parent if crate_root or path.name == "mod.rs" else path.parent / path.stem
    base = base.joinpath(*namespace)
    return base / f"{module_name}.rs", base / module_name / "mod.rs"


def _rust_module_declarations(
    code: str,
    *,
    start: int = 0,
    end: int | None = None,
    namespace: tuple[str, ...] = (),
    issues: list[tuple[int, str]] | None = None,
) -> tuple[RustModuleDeclaration, ...]:
    declarations = []
    issue_list = [] if issues is None else issues
    boundary = len(code) if end is None else end
    cursor = start
    while cursor < boundary:
        cursor = _rust_skip_whitespace(code, cursor, boundary)
        attributes = []
        while cursor < boundary and code[cursor] == "#":
            attribute_start = cursor
            attribute_cursor = _rust_skip_whitespace(code, cursor + 1, boundary)
            inner_attribute = attribute_cursor < boundary and code[attribute_cursor] == "!"
            if inner_attribute:
                attribute_cursor = _rust_skip_whitespace(code, attribute_cursor + 1, boundary)
            if attribute_cursor >= boundary or code[attribute_cursor] != "[":
                issue_list.append((attribute_start, "ambiguous module syntax"))
                break
            attribute_end = _matching_rust_group(code, attribute_cursor)
            if attribute_end is None or attribute_end > boundary:
                issue_list.append((attribute_start, "ambiguous module syntax"))
                return tuple(declarations)
            name_cursor = _rust_skip_whitespace(code, attribute_cursor + 1, attribute_end - 1)
            name_match = _rust_identifier(code, name_cursor, attribute_end - 1)
            if not inner_attribute:
                attributes.append(
                    RustAttribute(
                        attribute_start,
                        attribute_end,
                        name_match[0] if name_match else None,
                    )
                )
            cursor = _rust_skip_whitespace(code, attribute_end, boundary)
            if inner_attribute:
                attributes.clear()

        item_start = cursor
        token_match = _rust_identifier(code, cursor, boundary)
        if token_match is None:
            cursor += 1
            continue
        token, cursor = token_match
        if token == "pub":
            cursor = _rust_skip_whitespace(code, cursor, boundary)
            if cursor < boundary and code[cursor] == "(":
                visibility_end = _matching_rust_group(code, cursor)
                if visibility_end is None or visibility_end > boundary:
                    issue_list.append((item_start, "ambiguous module syntax"))
                    return tuple(declarations)
                cursor = _rust_skip_whitespace(code, visibility_end, boundary)
            token_match = _rust_identifier(code, cursor, boundary)
            if token_match is None:
                cursor = _rust_item_end(code, item_start)
                continue
            token, cursor = token_match
        if token != "mod":
            cursor = _rust_item_end(code, item_start)
            continue

        cursor = _rust_skip_whitespace(code, cursor, boundary)
        name_match = _rust_identifier(code, cursor, boundary)
        if name_match is None:
            issue_list.append((item_start, "ambiguous module syntax"))
            cursor = _rust_item_end(code, item_start)
            continue
        module_name, cursor = name_match
        cursor = _rust_skip_whitespace(code, cursor, boundary)
        if cursor < boundary and code[cursor] == ";":
            declarations.append(RustModuleDeclaration(module_name, namespace, item_start, tuple(attributes)))
            cursor += 1
            continue
        if cursor >= boundary or code[cursor] != "{":
            issue_list.append((item_start, "ambiguous module syntax"))
            cursor = _rust_item_end(code, item_start)
            continue
        body_end = _matching_rust_group(code, cursor)
        if body_end is None or body_end > boundary:
            issue_list.append((item_start, "ambiguous module syntax"))
            return tuple(declarations)
        declarations.extend(
            _rust_module_declarations(
                code,
                start=cursor + 1,
                end=body_end - 1,
                namespace=(*namespace, module_name),
                issues=issue_list,
            )
        )
        cursor = body_end
    return tuple(declarations)


def _rust_attribute_has_path_assignment(code: str, attribute: RustAttribute) -> bool:
    cursor = attribute.start
    while cursor < attribute.end:
        identifier_match = _rust_identifier(code, cursor, attribute.end)
        if identifier_match is None:
            cursor += 1
            continue
        identifier, cursor = identifier_match
        cursor = _rust_skip_whitespace(code, cursor, attribute.end)
        if identifier == "path" and cursor < attribute.end and code[cursor] == "=":
            return True
    return False


def _rust_compile_input_literal_value(source: str, literal: RustStringLiteral) -> str | None:
    literal_source = source[literal.start : literal.end]
    if not literal.terminated:
        return None
    if literal.kind == "raw":
        return literal.value
    if literal.kind != "ordinary" or not literal_source.startswith('"') or not literal_source.endswith('"'):
        return None

    decoded = []
    cursor = 0
    simple_escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        "0": "\0",
        "'": "'",
        '"': '"',
    }
    while cursor < len(literal.value):
        char = literal.value[cursor]
        if char != "\\":
            decoded.append(char)
            cursor += 1
            continue
        cursor += 1
        if cursor >= len(literal.value):
            return None
        escape = literal.value[cursor]
        if escape in simple_escapes:
            decoded.append(simple_escapes[escape])
            cursor += 1
            continue
        if escape == "x":
            digits = literal.value[cursor + 1 : cursor + 3]
            if len(digits) != 2 or re.fullmatch(r"[0-9A-Fa-f]{2}", digits) is None:
                return None
            value = int(digits, 16)
            if value > 0x7F:
                return None
            decoded.append(chr(value))
            cursor += 3
            continue
        if escape == "u":
            unicode_match = re.match(r"\{(?P<digits>[0-9A-Fa-f]{1,6})\}", literal.value[cursor + 1 :])
            if unicode_match is None:
                return None
            value = int(unicode_match.group("digits"), 16)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                return None
            decoded.append(chr(value))
            cursor += 1 + unicode_match.end()
            continue
        return None
    return "".join(decoded)


def _rust_static_path_attribute(
    source: str,
    code: str,
    literals: tuple[RustStringLiteral, ...],
    attribute: RustAttribute,
) -> str | None:
    name_start = code.find(attribute.name or "", attribute.start, attribute.end)
    if name_start < 0:
        return None
    cursor = _rust_skip_whitespace(code, name_start + len(attribute.name or ""), attribute.end)
    if cursor >= attribute.end or code[cursor] != "=":
        return None
    candidates = tuple(literal for literal in literals if cursor < literal.start and literal.end < attribute.end)
    if len(candidates) != 1:
        return None
    literal = candidates[0]
    if code[cursor + 1 : literal.start].strip() or code[literal.end : attribute.end - 1].strip():
        return None
    return _rust_compile_input_literal_value(source, literal)


def _rust_compile_input_error(path: Path, source: str, position: int, reason: str) -> RuntimeError:
    return RuntimeError(
        f"unresolved Rust compile-input edge: {reason} at {_display_path(path)}:{_rust_position(source, position)}"
    )


def _rust_module_edges(
    path: Path,
    source: str,
    code: str,
    literals: tuple[RustStringLiteral, ...],
    *,
    crate_root: bool,
    fail_closed: bool,
) -> tuple[RustCompileInputEdge, ...]:
    edges = []
    issues: list[tuple[int, str]] = []
    declarations = _rust_module_declarations(code, issues=issues)
    if fail_closed and issues:
        position, reason = issues[0]
        raise _rust_compile_input_error(path, source, position, reason)
    for declaration in declarations:
        cfg_attr_paths = tuple(
            attribute
            for attribute in declaration.attributes
            if attribute.name == "cfg_attr" and _rust_attribute_has_path_assignment(code, attribute)
        )
        if cfg_attr_paths:
            if fail_closed:
                raise _rust_compile_input_error(path, source, cfg_attr_paths[0].start, "cfg_attr path")
            continue
        path_attributes = tuple(attribute for attribute in declaration.attributes if attribute.name == "path")
        if path_attributes:
            path_values = tuple(
                _rust_static_path_attribute(source, code, literals, attribute) for attribute in path_attributes
            )
            if len(path_values) != 1 or path_values[0] is None:
                if fail_closed:
                    raise _rust_compile_input_error(
                        path,
                        source,
                        path_attributes[0].start,
                        "path attribute target",
                    )
                continue
            target = path.parent.joinpath(*declaration.namespace, path_values[0]).resolve()
            edges.append(RustCompileInputEdge(declaration.start, target))
            continue
        edges.extend(
            RustCompileInputEdge(declaration.start, candidate)
            for candidate in _rust_external_module_candidates(
                path,
                declaration.name,
                crate_root=crate_root,
                namespace=declaration.namespace,
            )
        )
    return tuple(edges)


def _rust_include_edges(
    path: Path,
    source: str,
    code: str,
    literals: tuple[RustStringLiteral, ...],
    *,
    fail_closed: bool,
) -> tuple[RustCompileInputEdge, ...]:
    edges = []
    cursor = 0
    while cursor < len(code):
        identifier_match = _rust_identifier(code, cursor)
        if identifier_match is None:
            cursor += 1
            continue
        identifier, identifier_end = identifier_match
        cursor = identifier_end
        if identifier != "include":
            continue
        bang = _rust_skip_whitespace(code, identifier_end)
        if bang >= len(code) or code[bang] != "!":
            continue
        opening = _rust_skip_whitespace(code, bang + 1)
        if opening >= len(code) or code[opening] not in "([{":
            if fail_closed:
                raise _rust_compile_input_error(path, source, identifier_end, "include! target")
            continue
        closing = _matching_rust_group(code, opening)
        if closing is None:
            if fail_closed:
                raise _rust_compile_input_error(path, source, opening, "include! target")
            continue
        candidates = tuple(literal for literal in literals if opening < literal.start and literal.end < closing)
        body_without_literal = code[opening + 1 : closing - 1].strip()
        if len(candidates) != 1 or body_without_literal not in {"", ","}:
            if fail_closed:
                raise _rust_compile_input_error(path, source, opening, "include! target")
            cursor = closing
            continue
        literal = candidates[0]
        literal_value = _rust_compile_input_literal_value(source, literal)
        if literal_value is None:
            if fail_closed:
                raise _rust_compile_input_error(path, source, literal.start, "include! target")
            cursor = closing
            continue
        edges.append(RustCompileInputEdge(cursor - len(identifier), (path.parent / literal_value).resolve()))
        cursor = closing
    return tuple(edges)


def _rust_compile_input_edges(
    path: Path,
    source: str,
    code: str,
    literals: tuple[RustStringLiteral, ...],
    *,
    crate_root: bool,
    fail_closed: bool,
) -> tuple[RustCompileInputEdge, ...]:
    return (
        *_rust_module_edges(
            path,
            source,
            code,
            literals,
            crate_root=crate_root,
            fail_closed=fail_closed,
        ),
        *_rust_include_edges(path, source, code, literals, fail_closed=fail_closed),
    )


def _rust_crate_roots(paths: tuple[Path, ...]) -> frozenset[Path]:
    roots = {
        path
        for path in paths
        if path.name in {"lib.rs", "main.rs"} or (path.parent.name == "bin" and path.suffix == ".rs")
    }
    return frozenset(roots or paths)


def _rust_functions(code: str) -> tuple[RustFunction, ...]:
    functions = []
    for match in re.finditer(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>{}]*>)?\s*\(", code):
        opening = code.find("{", match.end())
        semicolon = code.find(";", match.end())
        if opening < 0 or (semicolon >= 0 and semicolon < opening):
            continue
        functions.append(
            RustFunction(
                match.group(1),
                match.start(),
                _matching_rust_delimiter(code, opening, "{", "}"),
            )
        )
    return tuple(functions)


def _rust_production_sources(paths: Iterable[Path]) -> tuple[RustProductionSource, ...]:
    path_list = tuple(path.resolve() for path in paths)
    path_set = set(path_list)
    crate_roots = _rust_crate_roots(path_list)
    parsed = {}
    test_only_targets = set()
    for path in path_list:
        source = path.read_text()
        code, literals = _rust_code_and_literals(source)
        ranges, _ = _rust_cfg_exclusions(code)
        mask = list(code)
        for start, end in ranges:
            _blank_rust_range(mask, code, start, end)
        production_code = "".join(mask)
        production_literals = tuple(
            literal for literal in literals if not any(start <= literal.start < end for start, end in ranges)
        )
        parsed[path] = (source, code, literals, ranges, production_code, production_literals)

        test_only_targets.update(
            edge.target
            for edge in _rust_compile_input_edges(
                path,
                source,
                code,
                literals,
                crate_root=path in crate_roots,
                fail_closed=False,
            )
            if edge.target in path_set and any(start <= edge.start < end for start, end in ranges)
        )

    module_edges = {}
    possible_targets = set()
    for path, (source, _, _, _, production_code, production_literals) in parsed.items():
        edges = _rust_compile_input_edges(
            path,
            source,
            production_code,
            production_literals,
            crate_root=path in crate_roots,
            fail_closed=True,
        )
        targets = {edge.target for edge in edges if edge.target in path_set}
        module_edges[path] = targets
        possible_targets.update(targets)

    reachable = set()
    pending = list(crate_roots)
    while pending:
        path = pending.pop()
        if path in reachable:
            continue
        reachable.add(path)
        pending.extend(module_edges.get(path, ()))

    production_sources = []
    for path in path_list:
        if path not in reachable and path in test_only_targets and path not in possible_targets:
            continue
        source, _, _, _, production_code, production_literals = parsed[path]
        production_sources.append(
            RustProductionSource(
                path,
                source,
                production_code,
                production_literals,
                _rust_functions(production_code),
            )
        )
    return tuple(production_sources)


def _rust_scope(functions: tuple[RustFunction, ...], position: int) -> str:
    enclosing = [function for function in functions if function.start <= position < function.end]
    return min(enclosing, key=lambda function: function.end - function.start).name if enclosing else "<module>"


def _rust_position(source: str, position: int) -> str:
    line = source.count("\n", 0, position) + 1
    line_start = source.rfind("\n", 0, position) + 1
    return f"L{line}C{position - line_start}"


def _rust_line_text(source: str, position: int) -> str:
    line_start = source.rfind("\n", 0, position) + 1
    line_end = source.find("\n", position)
    return source[line_start:] if line_end < 0 else source[line_start:line_end]


def discover_rust_raw_sql(paths: Iterable[Path]) -> set[CensusFinding]:
    findings = set()
    for production in _rust_production_sources(paths):
        relative_path = _display_path(production.path)
        for literal in production.literals:
            normalized = " ".join(literal.value.lower().split())
            if not re.search(r"\b(select|insert|update|delete|from|join)\b", normalized):
                continue
            for table in CREDENTIAL_TABLES:
                if table in normalized:
                    findings.add(
                        CensusFinding(
                            "raw_sql:rust:"
                            f"{relative_path}:{_rust_scope(production.functions, literal.start)}:"
                            f"{table}:{_fingerprint(normalized)}",
                            "raw_sql",
                        )
                    )
    return findings


def discover_python_sensitive_calls(paths: Iterable[Path]) -> set[CensusFinding]:
    findings = set()
    for path in paths:
        relative_path = _display_path(path)
        for callsite in _python_callsites(path.read_text()):
            node = callsite.node
            if not isinstance(node, ast.Call):
                continue
            call_name = None
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            if call_name in SENSITIVE_CALL_NAMES:
                findings.add(
                    CensusFinding(
                        "material_call:python:"
                        f"{relative_path}:{callsite.scope}:{call_name}:"
                        f"{_fingerprint(ast.dump(node, include_attributes=False))}",
                        "material_call",
                    )
                )
    return findings


def discover_rust_sensitive_calls(paths: Iterable[Path]) -> set[CensusFinding]:
    findings = set()
    calls = re.compile(rf"\.({'|'.join(sorted(SENSITIVE_CALL_NAMES))})\s*\(")
    for production in _rust_production_sources(paths):
        relative_path = _display_path(production.path)
        for match in calls.finditer(production.code):
            call_name = match.group(1)
            findings.add(
                CensusFinding(
                    "material_call:rust:"
                    f"{relative_path}:{_rust_scope(production.functions, match.start())}:"
                    f"{call_name}:{_fingerprint(_rust_line_text(production.source, match.start()))}",
                    "material_call",
                )
            )
    return findings


def _python_string_bindings(source: str) -> dict[str, set[str]]:
    tree = ast.parse(source)
    bindings: dict[str, set[str]] = {}

    def values(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name):
            return set(bindings.get(node.id, ()))
        return set()

    for _ in range(4):
        changed = False
        for node in ast.walk(tree):
            target = None
            value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                target, value = node.target.id, node.value
            if target is None or value is None:
                continue
            resolved = values(value)
            if resolved and not resolved <= bindings.get(target, set()):
                bindings.setdefault(target, set()).update(resolved)
                changed = True
        if not changed:
            break
    return bindings


def _python_resolved_strings(node: ast.AST, bindings: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(bindings.get(node.id, ()))
    return set()


def _registered_reference_keys() -> set[str]:
    contract = json.loads(REFERENCE_CONTRACT_PATH.read_text())
    return {
        *contract["canonical_reference_keys"],
        *contract["legacy_decoder_keys"],
        *(alias for aliases in contract["legacy_aliases"].values() for alias in aliases),
    }


def _looks_like_reference_key(key: str) -> bool:
    return key in _registered_reference_keys() or bool(
        re.search(r"(?:credential|secret).*(?:id|ref)|(?:id|ref).*(?:credential|secret)", key)
    )


def discover_python_registered_key_reads(
    source: str,
    registered_keys: set[str],
) -> tuple[tuple[PythonCallsite, str], ...]:
    bindings = _python_string_bindings(source)
    reads: list[tuple[PythonCallsite, str]] = []
    for callsite in _python_callsites(source):
        node = callsite.node
        keys: set[str] = set()
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            keys.update(_python_resolved_strings(node.slice, bindings))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            if node.func.attr in {"get", "pop", "setdefault", "__contains__"}:
                keys.update(_python_resolved_strings(node.args[0], bindings))
        elif isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                if isinstance(operator, (ast.In, ast.NotIn)):
                    if not (isinstance(comparator, ast.Attribute) and comparator.attr == "model_fields_set"):
                        keys.update(_python_resolved_strings(node.left, bindings))
                    keys.update(_python_resolved_strings(comparator, bindings))
        elif isinstance(node, ast.MatchMapping):
            for key_node in node.keys:
                if key_node is not None:
                    keys.update(_python_resolved_strings(key_node, bindings))
        reads.extend((callsite, key) for key in keys if key in registered_keys)
    return tuple(reads)


def discover_raw_key_paths(source: str, *, origin: str) -> set[CensusFinding]:
    findings = set()
    candidate_keys = _registered_reference_keys()
    candidate_keys.update(
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _looks_like_reference_key(node.value)
    )
    for callsite, key in discover_python_registered_key_reads(source, candidate_keys):
        node = callsite.node
        if _looks_like_reference_key(key):
            findings.add(
                CensusFinding(
                    f"raw_key:{origin}:{callsite.scope}:{key}:{_fingerprint(ast.dump(node, include_attributes=False))}",
                    "raw_key",
                )
            )
    return findings


def _lexical_string_bindings(source: str, *, rust: bool) -> dict[str, str]:
    if rust:
        pattern = re.compile(r'\b(?:const|static|let)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)[^=;]*=\s*"(?P<value>[^"\\]*)"')
    else:
        pattern = re.compile(
            r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*['\"](?P<value>[^'\"\\]*)['\"]"
        )
    return {match.group("name"): match.group("value") for match in pattern.finditer(source)}


def _lexical_key(argument: str, bindings: dict[str, str], registered_keys: set[str]) -> str | None:
    stripped = argument.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        value = stripped[1:-1]
    else:
        value = bindings.get(stripped)
    return value if value in registered_keys else None


def discover_rust_registered_key_reads(source: str, registered_keys: set[str]) -> tuple[tuple[int, str], ...]:
    bindings = _lexical_string_bindings(source, rust=True)
    reads: set[tuple[int, str]] = set()
    access_patterns = (
        re.compile(r"\.\s*(?:get|remove|contains_key|entry)\s*\(\s*(?P<arg>[^,)]+)"),
        re.compile(r"\[\s*(?P<arg>[^\]]+)\s*\]"),
    )
    for pattern in access_patterns:
        for match in pattern.finditer(source):
            key = _lexical_key(match.group("arg"), bindings, registered_keys)
            if key is not None:
                reads.add((match.start(), key))
    match_arm = re.compile(r'\bmatch\b[\s\S]{0,300}?"(?P<key>[^"\\]+)"\s*=>')
    for match in match_arm.finditer(source):
        if match.group("key") in registered_keys:
            reads.add((match.start(), match.group("key")))
    return tuple(sorted(reads))


def discover_frontend_registered_key_reads(
    source: str,
    registered_keys: set[str],
) -> tuple[tuple[int, str], ...]:
    bindings = _lexical_string_bindings(source, rust=False)
    tainted = {"raw", "response", "payload", "document"}
    typed_unknown = re.compile(
        r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(?:unknown|any|Record\s*<\s*string\s*,\s*unknown\s*>)"
    )
    tainted.update(match.group("name") for match in typed_unknown.finditer(source))
    alias = re.compile(
        r"\b(?:const|let|var)\s+(?P<target>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?P<source>[A-Za-z_$][A-Za-z0-9_$]*)\b"
    )
    for _ in range(4):
        before = len(tainted)
        for match in alias.finditer(source):
            if match.group("source") in tainted:
                tainted.add(match.group("target"))
        if len(tainted) == before:
            break

    reads: set[tuple[int, str]] = set()
    for name in tainted:
        escaped = re.escape(name)
        dot = re.compile(rf"\b{escaped}\s*(?:\?\.)?\.\s*(?P<key>[A-Za-z_$][A-Za-z0-9_$]*)")
        bracket = re.compile(rf"\b{escaped}\s*(?:\?\.)?\[\s*(?P<arg>[^\]]+)\s*\]")
        membership = re.compile(rf"(?P<arg>['\"][^'\"]+['\"]|[A-Za-z_$][A-Za-z0-9_$]*)\s+in\s+{escaped}\b")
        destructuring = re.compile(rf"\{{(?P<body>[^}}]+)\}}\s*=\s*{escaped}\b")
        for match in dot.finditer(source):
            if match.group("key") in registered_keys:
                reads.add((match.start(), match.group("key")))
        for pattern in (bracket, membership):
            for match in pattern.finditer(source):
                key = _lexical_key(match.group("arg"), bindings, registered_keys)
                if key is not None:
                    reads.add((match.start(), key))
        for match in destructuring.finditer(source):
            for key in registered_keys:
                if re.search(rf"(?:^|,)\s*{re.escape(key)}\s*(?::|,|$)", match.group("body")):
                    reads.add((match.start(), key))
    return tuple(sorted(reads))


def _load_reviewed_exceptions(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    entries = json.loads(path.read_text())
    assert isinstance(entries, list)
    result = {}
    for entry in entries:
        assert set(entry) == {"surface", "owner", "reason", "removal_condition"}
        assert all(isinstance(entry[field], str) and entry[field].strip() for field in entry)
        assert entry["surface"] not in result
        result[entry["surface"]] = entry
    return result


def assert_reverse_census_closed(
    findings: Iterable[CensusFinding],
    *,
    registered_surface_ids: set[str],
    reviewed_exceptions: dict[str, dict[str, str]],
    aggregate_internal_surfaces: set[str] | None = None,
) -> None:
    aggregate_internal_surfaces = AGGREGATE_INTERNAL_CLASSIFICATIONS | (aggregate_internal_surfaces or set())
    unclassified = []
    ambiguous = []
    for finding in findings:
        registered = REGISTERED_CLASSIFICATIONS.get(finding.surface)
        classifications = sum(
            (
                finding.surface in aggregate_internal_surfaces,
                registered is not None and registered <= registered_surface_ids,
                finding.surface in reviewed_exceptions,
            )
        )
        if classifications == 0:
            unclassified.append(finding.surface)
        elif classifications > 1:
            ambiguous.append(finding.surface)
    if unclassified:
        raise AssertionError(f"unclassified credential reference surfaces: {sorted(unclassified)}")
    if ambiguous:
        raise AssertionError(f"ambiguously classified credential reference surfaces: {sorted(ambiguous)}")


def _production_findings() -> set[CensusFinding]:
    python_paths = tuple((BACKEND_ROOT / "app").rglob("*.py")) + tuple((BACKEND_ROOT / "scripts").rglob("*.py"))
    rust_paths = tuple((BACKEND_ROOT / "app" / "joysafeter_orchestrator_rs" / "src").rglob("*.rs"))
    raw_key_findings = set()
    for path in python_paths:
        origin = _display_path(path)
        raw_key_findings.update(discover_raw_key_paths(path.read_text(), origin=origin))
    return set().union(
        discover_sqlalchemy_typed_ids(Base.metadata),
        discover_alembic_typed_ids(BACKEND_ROOT / "alembic" / "versions"),
        discover_codec_keys(BACKEND_ROOT / "contracts" / "credential_reference_contract.json"),
        discover_python_raw_sql(python_paths),
        discover_rust_raw_sql(rust_paths),
        discover_python_sensitive_calls(python_paths),
        discover_rust_sensitive_calls(rust_paths),
        raw_key_findings,
    )


@pytest.mark.no_db
def test_reverse_census_independently_closes_every_production_finding() -> None:
    registered_surface_ids = {str(descriptor.surface_id) for descriptor in CREDENTIAL_REFERENCE_SURFACES}
    findings = _production_findings()

    assert {finding.category for finding in findings} >= {
        "typed_id",
        "codec_key",
        "raw_sql",
        "material_call",
        "raw_key",
    }
    raw_key_surfaces = {finding.surface for finding in findings if finding.category == "raw_key"}
    codec_internal_surfaces = {
        surface for surface in raw_key_surfaces if surface.startswith(CODEC_INTERNAL_RAW_KEY_PREFIX)
    }
    assert codec_internal_surfaces
    assert raw_key_surfaces - codec_internal_surfaces == EXPECTED_PRODUCTION_RAW_KEY_SURFACES
    assert_reverse_census_closed(
        findings,
        registered_surface_ids=registered_surface_ids,
        reviewed_exceptions=_load_reviewed_exceptions(EXCEPTIONS_PATH),
        aggregate_internal_surfaces=codec_internal_surfaces,
    )


@pytest.mark.no_db
def test_codec_census_is_schema_path_owner_and_fixture_qualified() -> None:
    contract_path = BACKEND_ROOT / "contracts" / "credential_reference_contract.json"
    contract = json.loads(contract_path.read_text())
    findings = discover_codec_keys(contract_path)
    expected_count = sum(len(entry["schemas"]) for entry in contract["reference_paths"])

    assert len(findings) == expected_count
    assert all(finding.surface.startswith("codec_path:") for finding in findings)
    assert all(
        all(part in finding.surface for part in (entry["document"], entry["path"], entry["scanner_fixture"]))
        for entry in contract["reference_paths"]
        for finding in findings
        if finding.surface.endswith(f":{entry['scanner_fixture']}")
    )


@pytest.mark.no_db
def test_delegating_registry_and_repository_machinery_has_no_raw_key_reads() -> None:
    raw_keys = {finding.surface for finding in _production_findings() if finding.category == "raw_key"}

    assert not any("dependency_scanners.py" in surface for surface in raw_keys)
    assert not any(
        "sqlalchemy_repository.py:_config_references_credential" in surface
        or "sqlalchemy_repository.py:_snapshot_references_credential" in surface
        for surface in raw_keys
    )


@pytest.mark.no_db
def test_registered_json_reference_reads_are_codec_owned_across_python_rust_and_frontend() -> None:
    contract = json.loads(REFERENCE_CONTRACT_PATH.read_text())
    registered_keys = set(contract["canonical_reference_keys"])
    registered_keys.update(contract["legacy_decoder_keys"])
    registered_keys.update(alias for aliases in contract["legacy_aliases"].values() for alias in aliases)
    registered_keys.update(
        segment.removesuffix("[*]")
        for entry in contract["reference_paths"]
        for segment in entry["path"].removeprefix("$.").split(".")
        if "credential" in segment or "secret" in segment
    )

    python_codec = "backend/app/joysafeter_domain/credentials/references.py"
    rust_codec = "backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/reference.rs"
    frontend_codec = "frontend/lib/managed/environment-response-parsers.ts"
    findings: list[str] = []

    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        origin = _display_path(path)
        if origin == python_codec:
            continue
        for callsite, key in discover_python_registered_key_reads(path.read_text(), registered_keys):
            findings.append(f"python:{origin}:{callsite.scope}:{_span(callsite.node)}:{key}")

    rust_root = BACKEND_ROOT / "app" / "joysafeter_orchestrator_rs" / "src"
    for production in _rust_production_sources(tuple(rust_root.rglob("*.rs"))):
        origin = _display_path(production.path)
        if origin == rust_codec:
            continue
        for position, key in discover_rust_registered_key_reads(production.code, registered_keys):
            findings.append(
                f"rust:{origin}:{_rust_scope(production.functions, position)}:"
                f"{_rust_position(production.source, position)}:{key}"
            )

    frontend_root = REPO_ROOT / "frontend"
    for path in (*frontend_root.rglob("*.ts"), *frontend_root.rglob("*.tsx")):
        origin = _display_path(path)
        if origin == frontend_codec or ".test." in path.name or "node_modules" in path.parts:
            continue
        for position, key in discover_frontend_registered_key_reads(path.read_text(), registered_keys):
            findings.append(f"frontend:{origin}:{position}:{key}")

    assert findings == [], "registered reference JSON reads outside Codec: " + repr(sorted(findings))


@pytest.mark.no_db
def test_reviewed_exception_contract_has_no_stale_or_malformed_entries() -> None:
    findings = {finding.surface for finding in _production_findings()}
    exceptions = _load_reviewed_exceptions(EXCEPTIONS_PATH)

    assert exceptions
    assert set(exceptions) <= findings


@pytest.mark.no_db
def test_deliberate_unregistered_typed_credential_id_fails_closed() -> None:
    metadata = MetaData()
    Table("joysafeter_credentials", metadata, Column("id", primary_key=True))
    Table(
        "rogue_consumer",
        metadata,
        Column("rogue_credential_id", ForeignKey("joysafeter_credentials.id")),
    )
    findings = discover_sqlalchemy_typed_ids(metadata)

    assert findings
    with pytest.raises(AssertionError, match="rogue_consumer.rogue_credential_id"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions={},
        )


@pytest.mark.no_db
def test_alembic_census_discovers_fk_constraints_and_typed_ids_with_arbitrary_names(tmp_path) -> None:
    migration = tmp_path / "20260817_000001_rogue_refs.py"
    migration.write_text(
        'revision = "20260817_000001"\n'
        "def upgrade():\n"
        '    op.create_table("inline_consumer",\n'
        '        sa.Column("api_credential", sa.UUID(), sa.ForeignKey("joysafeter_credentials.id")))\n'
        '    op.create_table("constraint_consumer",\n'
        '        sa.Column("group_link", sa.UUID()),\n'
        '        sa.ForeignKeyConstraint(["group_link"], ["joysafeter_credential_groups.id"]))\n'
        '    op.add_column("typed_consumer",\n'
        '        sa.Column("arbitrary_name", EntityIdType(CredentialId)))\n'
        '    op.add_column("separate_consumer", sa.Column("later_link", sa.UUID()))\n'
        '    op.create_foreign_key("fk_later", "separate_consumer", "joysafeter_credentials",\n'
        '        ["later_link"], ["id"])\n'
    )

    findings = discover_alembic_typed_ids(tmp_path)

    assert {finding.surface for finding in findings} == {
        "typed_id:alembic:20260817_000001:inline_consumer.api_credential->joysafeter_credentials.id",
        "typed_id:alembic:20260817_000001:constraint_consumer.group_link->joysafeter_credential_groups.id",
        "typed_id:alembic:20260817_000001:typed_consumer.arbitrary_name->CredentialId",
        "typed_id:alembic:20260817_000001:separate_consumer.later_link->joysafeter_credentials.id",
    }


@pytest.mark.no_db
def test_deliberate_unregistered_raw_key_path_fails_closed() -> None:
    findings = discover_raw_key_paths(
        'payload.get("rogue_credential_ref")',
        origin="fixture.py",
    )

    assert findings
    with pytest.raises(AssertionError, match="rogue_credential_ref"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions={},
        )


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        'payload.pop("credential_ref")',
        'payload.setdefault("credential_ref", None)',
        '"credential_ref" in payload',
        'KEY = "credential_ref"\npayload.get(KEY)',
        'match payload:\n    case {"credential_ref": value}:\n        pass',
    ],
)
def test_python_registered_key_bypass_forms_are_detected(source: str) -> None:
    findings = discover_raw_key_paths(source, origin="fixture.py")

    assert findings
    assert all("credential_ref" in finding.surface for finding in findings)


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        'fn read(payload: &serde_json::Value) { let _ = payload["credential_ref"].clone(); }',
        'fn read(config: &mut Map<String, Value>) { config.remove("credential_ref"); }',
        'fn read(config: &Map<String, Value>) { config.contains_key("credential_ref"); }',
        'const KEY: &str = "credential_ref"; fn read(payload: &Value) { let _ = payload[KEY].clone(); }',
    ],
)
def test_rust_registered_key_bypass_forms_are_detected(source: str) -> None:
    findings = discover_rust_registered_key_reads(source, {"credential_ref"})

    assert findings
    assert {key for _position, key in findings} == {"credential_ref"}


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        'const KEY = "credential_ref"; const value = payload[KEY];',
        "const renamed = payload; const value = renamed.credential_ref;",
        "const { credential_ref: value } = payload;",
        'if ("credential_ref" in payload) consume(payload);',
    ],
)
def test_frontend_registered_key_bypass_forms_are_detected(source: str) -> None:
    findings = discover_frontend_registered_key_reads(source, {"credential_ref"})

    assert findings
    assert {key for _position, key in findings} == {"credential_ref"}


@pytest.mark.no_db
def test_raw_key_census_has_no_implicit_broad_exclusions() -> None:
    assert RAW_KEY_EXCLUDED_FILES == set()
    assert RAW_KEY_EXCLUDED_SCOPES == set()


@pytest.mark.no_db
def test_python_census_surface_ids_ignore_line_shifts(tmp_path) -> None:
    fixture = tmp_path / "stable.py"
    source = """
def load(payload, material):
    query = "SELECT id FROM joysafeter_credentials"
    credential_id = payload["credential_id"]
    return query, credential_id, material.reveal()
"""
    fixture.write_text(source)
    before = set().union(
        discover_python_raw_sql((fixture,)),
        discover_python_sensitive_calls((fixture,)),
        discover_raw_key_paths(source, origin="fixture.py"),
    )

    shifted = "\n\n" + source
    fixture.write_text(shifted)
    after = set().union(
        discover_python_raw_sql((fixture,)),
        discover_python_sensitive_calls((fixture,)),
        discover_raw_key_paths(shifted, origin="fixture.py"),
    )

    assert after == before


@pytest.mark.no_db
def test_rust_census_surface_ids_ignore_line_shifts(tmp_path) -> None:
    fixture = tmp_path / "stable.rs"
    source = """
fn load(material: Material) {
    let query = "SELECT id FROM joysafeter_credentials";
    material.reveal();
}
"""
    fixture.write_text(source)
    before = discover_rust_raw_sql((fixture,)) | discover_rust_sensitive_calls((fixture,))

    fixture.write_text("\n\n" + source)
    after = discover_rust_raw_sql((fixture,)) | discover_rust_sensitive_calls((fixture,))

    assert after == before


@pytest.mark.no_db
def test_rust_sensitive_surface_ids_distinguish_calls_in_one_scope(tmp_path) -> None:
    fixture = tmp_path / "same_scope.rs"
    fixture.write_text(
        "fn load(primary: Material, fallback: Material) {\n    primary.reveal();\n    fallback.reveal();\n}\n"
    )

    assert len(discover_rust_sensitive_calls((fixture,))) == 2


@pytest.mark.no_db
def test_deliberate_unregistered_sql_query_fails_closed(tmp_path) -> None:
    fixture = tmp_path / "rogue.py"
    fixture.write_text('QUERY = "SELECT id FROM joysafeter_credentials"')
    findings = discover_python_raw_sql((fixture,))
    normalized = {
        CensusFinding(
            finding.surface.replace(tmp_path.as_posix(), "fixture"),
            finding.category,
        )
        for finding in findings
    }

    assert normalized
    with pytest.raises(AssertionError, match="joysafeter_credentials"):
        assert_reverse_census_closed(
            normalized,
            registered_surface_ids=set(),
            reviewed_exceptions={},
        )


@pytest.mark.no_db
def test_deliberate_unregistered_reveal_callsite_fails_closed(tmp_path) -> None:
    fixture = tmp_path / "rogue.py"
    fixture.write_text("material.reveal()")
    findings = discover_python_sensitive_calls((fixture,))
    normalized = {
        CensusFinding(
            finding.surface.replace(tmp_path.as_posix(), "fixture"),
            finding.category,
        )
        for finding in findings
    }

    assert normalized
    with pytest.raises(AssertionError, match="reveal"):
        assert_reverse_census_closed(
            normalized,
            registered_surface_ids=set(),
            reviewed_exceptions={},
        )


def _reviewed_exception(surface: str) -> dict[str, dict[str, str]]:
    return {
        surface: {
            "surface": surface,
            "owner": "fixture-owner",
            "reason": "first callsite is deliberately reviewed",
            "removal_condition": "remove fixture classification",
        }
    }


@pytest.mark.no_db
def test_rust_escaped_include_literal_preserves_production_edge(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\ninclude!("shar\\u{65}d.rs");\n')
    shared.write_text('fn escaped_include_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "escaped_include_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_escaped_path_literal_preserves_production_edge(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\n#[path = "shar\\u{65}d.rs"]\nmod production_shared;\n')
    shared.write_text('fn escaped_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "escaped_path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("literal_source", "expected"),
    [
        ('"line\\ncarriage\\rtab\\tzero\\0.rs"', "line\ncarriage\rtab\tzero\0.rs"),
        ('"quote\\"apostrophe\\\'slash\\\\.rs"', "quote\"apostrophe'slash\\.rs"),
        ('"hex\\x2eunicode\\u{2e}.rs"', "hex.unicode..rs"),
        ('r#"raw\\u{65}\\"\\\\.rs"#', r"raw\u{65}\"\\.rs"),
    ],
)
def test_rust_compile_input_literal_decodes_supported_spelling(literal_source: str, expected: str) -> None:
    _, literals = _rust_code_and_literals(literal_source)

    assert len(literals) == 1
    assert _rust_compile_input_literal_value(literal_source, literals[0]) == expected


@pytest.mark.no_db
@pytest.mark.parametrize(
    "literal_source",
    [
        r'"unsupported\q.rs"',
        r'"short_hex\x2.rs"',
        r'"invalid_hex\xgg.rs"',
        r'"missing_unicode_braces\u65.rs"',
        r'"empty_unicode\u{}.rs"',
        r'"out_of_range_unicode\u{110000}.rs"',
        r'"surrogate_unicode\u{d800}.rs"',
        '"continued\\\n  path.rs"',
        '"unterminated.rs',
    ],
)
def test_rust_compile_input_literal_rejects_unresolved_spelling(literal_source: str) -> None:
    _, literals = _rust_code_and_literals(literal_source)

    assert len(literals) == 1
    assert _rust_compile_input_literal_value(literal_source, literals[0]) is None


@pytest.mark.no_db
@pytest.mark.parametrize(
    "edge",
    [
        'include!("shared\\q.rs");',
        '#[path = "shared\\q.rs"]\nmod production_shared;',
        'include!("shared\\\n  .rs");',
        '#[path = "shared\\\n  .rs"]\nmod production_shared;',
    ],
)
def test_rust_unresolved_compile_input_literal_fails_closed(tmp_path, edge: str) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text(f"#[cfg(test)]\nmod shared;\n\n{edge}\n")
    shared.write_text('fn unresolved_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    with pytest.raises(RuntimeError, match="unresolved Rust compile-input edge"):
        discover_rust_raw_sql((lib, shared))


@pytest.mark.no_db
@pytest.mark.parametrize(
    "edge",
    [
        'include!(r#"shared.rs"#);',
        '#[path = r#"shared.rs"#]\nmod production_shared;',
    ],
)
def test_rust_raw_compile_input_literal_uses_content_directly(tmp_path, edge: str) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text(f"#[cfg(test)]\nmod shared;\n\n{edge}\n")
    shared.write_text('fn raw_literal_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "raw_literal_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_fake_compile_input_syntax_in_literals_and_comments_is_ignored(tmp_path) -> None:
    fixture = tmp_path / "lib.rs"
    fixture.write_text(
        'const ORDINARY: &str = "include!(\\"missing.rs\\")";\n'
        'const RAW: &str = r#"#[path = "missing.rs"] mod missing;"#;\n'
        'const BYTES: &[u8] = b"include!(\\"missing.rs\\")";\n'
        '// include!("missing.rs");\n'
        '/* #[path = "missing.rs"] mod missing; */\n'
        'fn real_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n'
    )

    findings = discover_rust_raw_sql((fixture,))

    assert len(findings) == 1
    assert "real_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
@pytest.mark.parametrize(
    "edge",
    [
        'include!(b"shared.rs");',
        '#[path = b"shared.rs"]\nmod production_shared;',
    ],
)
def test_rust_byte_compile_input_literal_fails_closed(tmp_path, edge: str) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text(f"#[cfg(test)]\nmod shared;\n\n{edge}\n")
    shared.write_text('fn byte_literal_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    with pytest.raises(RuntimeError, match="unresolved Rust compile-input edge"):
        discover_rust_raw_sql((lib, shared))


@pytest.mark.no_db
def test_second_sql_callsite_in_same_file_is_not_covered_by_first_exception(tmp_path) -> None:
    fixture = tmp_path / "same_file_sql.py"
    fixture.write_text(
        'def reviewed():\n    return "SELECT id FROM joysafeter_credentials"\n\n'
        'def unregistered():\n    return "SELECT data FROM joysafeter_credentials"\n'
    )
    findings = discover_python_raw_sql((fixture,))

    assert len(findings) == 2
    reviewed = min(findings, key=lambda finding: finding.surface)
    with pytest.raises(AssertionError, match="unclassified credential reference surfaces"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions=_reviewed_exception(reviewed.surface),
        )


@pytest.mark.no_db
def test_second_reveal_callsite_in_same_file_is_not_covered_by_first_exception(tmp_path) -> None:
    fixture = tmp_path / "same_file_reveal.py"
    fixture.write_text(
        "def reviewed(material):\n    return material.reveal()\n\n"
        "def unregistered(material):\n    return material.reveal()\n"
    )
    findings = discover_python_sensitive_calls((fixture,))

    assert len(findings) == 2
    reviewed = min(findings, key=lambda finding: finding.surface)
    with pytest.raises(AssertionError, match="unclassified credential reference surfaces"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions=_reviewed_exception(reviewed.surface),
        )


@pytest.mark.no_db
def test_second_raw_key_callsite_in_same_file_is_not_covered_by_first_classification() -> None:
    findings = discover_raw_key_paths(
        'def reviewed(payload):\n    return payload.get("credential_ref")\n\n'
        'def unregistered(payload):\n    return payload.get("credential_ref")\n',
        origin="same_file_key.py",
    )

    assert len(findings) == 2
    reviewed = min(findings, key=lambda finding: finding.surface)
    with pytest.raises(AssertionError, match="unclassified credential reference surfaces"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions=_reviewed_exception(reviewed.surface),
        )


@pytest.mark.no_db
def test_rust_external_test_module_is_not_a_production_input(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    tests = crate / "tests.rs"
    lib.write_text("#[cfg(test)]\nmod tests;\n")
    tests.write_text(
        'fn test_only(material: Material) { let _ = "SELECT id FROM joysafeter_credentials"; material.reveal(); }\n'
    )

    assert discover_rust_raw_sql((lib, tests)) == set()
    assert discover_rust_sensitive_calls((lib, tests)) == set()


@pytest.mark.no_db
def test_rust_external_module_with_test_and_production_edges_remains_reachable(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text("#[cfg(test)]\nmod shared;\n\n#[cfg(not(test))]\nmod shared;\n")
    shared.write_text('fn production_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "production_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_external_module_with_unknown_cfg_is_retained_fail_closed(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(feature = "possible-production")]\nmod shared;\n')
    shared.write_text('fn possible_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "possible_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_brace_include_with_test_only_edge_remains_reachable(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\ninclude! { "./shared.rs" }\n')
    shared.write_text('fn brace_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "brace_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_square_include_is_a_production_input(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    generated = crate / "generated.rs"
    lib.write_text('#[cfg(test)]\nmod generated;\n\ninclude! [ "./generated.rs", ]\n')
    generated.write_text('fn square_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, generated))

    assert len(findings) == 1
    assert "square_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_path_attribute_with_test_only_edge_remains_reachable(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\n#[path = "./shared.rs"]\nmod production_shared;\n')
    shared.write_text('fn path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, shared))

    assert len(findings) == 1
    assert "path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_root_path_attribute_is_a_production_input(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    target = crate / "root_target.rs"
    lib.write_text(
        "#[cfg(test)]\nmod root_target;\n\n"
        '#[allow(dead_code)]\n#[cfg(feature = "possible-production")]\n'
        '#[path = "./root_target.rs"]\nmod root_alias;\n'
    )
    target.write_text('fn root_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, target))

    assert len(findings) == 1
    assert "root_path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_inline_module_path_attribute_uses_inline_namespace(tmp_path) -> None:
    crate = tmp_path / "src"
    target_dir = crate / "outer"
    target_dir.mkdir(parents=True)
    lib = crate / "lib.rs"
    target = target_dir / "inline_target.rs"
    lib.write_text('mod outer { #[cfg(test)] mod inline_target; #[path = "inline_target.rs"] mod inline_alias; }\n')
    target.write_text('fn inline_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, target))

    assert len(findings) == 1
    assert "inline_path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_nested_module_path_attribute_uses_nested_namespace(tmp_path) -> None:
    crate = tmp_path / "src"
    target_dir = crate / "outer" / "nested"
    target_dir.mkdir(parents=True)
    lib = crate / "lib.rs"
    target = target_dir / "nested_target.rs"
    lib.write_text(
        "mod outer { mod nested { #[cfg(test)] mod nested_target; "
        '#[cfg(not(test))] #[path = "nested_target.rs"] mod nested_alias; } }\n'
    )
    target.write_text('fn nested_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, target))

    assert len(findings) == 1
    assert "nested_path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_test_only_path_attribute_excludes_but_production_dual_edge_retains(tmp_path) -> None:
    test_only_crate = tmp_path / "test-only" / "src"
    test_only_crate.mkdir(parents=True)
    test_only_lib = test_only_crate / "lib.rs"
    test_only_shared = test_only_crate / "shared.rs"
    test_only_lib.write_text('#[cfg(test)]\n#[path = "./shared.rs"]\nmod test_shared;\n')
    test_only_shared.write_text('fn test_only_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    assert discover_rust_raw_sql((test_only_lib, test_only_shared)) == set()

    dual_crate = tmp_path / "dual" / "src"
    dual_crate.mkdir(parents=True)
    dual_lib = dual_crate / "lib.rs"
    dual_shared = dual_crate / "shared.rs"
    dual_lib.write_text(
        '#[cfg(test)]\n#[path = "./shared.rs"]\nmod test_shared;\n\n#[path = "./shared.rs"]\nmod production_shared;\n'
    )
    dual_shared.write_text('fn dual_path_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((dual_lib, dual_shared))

    assert len(findings) == 1
    assert "dual_path_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_cfg_attr_path_target_fails_closed(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text(
        "#[cfg(test)]\nmod shared;\n\n"
        '#[cfg_attr(feature = "possible-production", path = "./shared.rs")]\nmod production_shared;\n'
    )
    shared.write_text('fn cfg_attr_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    with pytest.raises(RuntimeError, match="unresolved Rust compile-input edge: cfg_attr path"):
        discover_rust_raw_sql((lib, shared))


@pytest.mark.no_db
def test_rust_dynamic_include_target_fails_closed(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\ninclude!(concat!("./", "shared.rs"));\n')
    shared.write_text('fn dynamic_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    with pytest.raises(RuntimeError, match="unresolved Rust compile-input edge: include! target"):
        discover_rust_raw_sql((lib, shared))


@pytest.mark.no_db
def test_rust_ambiguous_module_attribute_syntax_fails_closed(tmp_path) -> None:
    crate = tmp_path / "src"
    crate.mkdir()
    lib = crate / "lib.rs"
    shared = crate / "shared.rs"
    lib.write_text('#[cfg(test)]\nmod shared;\n\n#[path = "./shared.rs"\nmod production_shared;\n')
    shared.write_text('fn ambiguous_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    with pytest.raises(RuntimeError, match="unresolved Rust compile-input edge: ambiguous module syntax"):
        discover_rust_raw_sql((lib, shared))


@pytest.mark.no_db
def test_rust_include_identifier_without_macro_invocation_is_not_an_edge(tmp_path) -> None:
    fixture = tmp_path / "lib.rs"
    fixture.write_text('fn include() {}\nfn production_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((fixture,))

    assert len(findings) == 1
    assert "production_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_real_rust_tree_retains_include_input_and_excludes_test_only_module() -> None:
    source_root = BACKEND_ROOT / "app" / "joysafeter_orchestrator_rs" / "src"
    production_paths = {source.path for source in _rust_production_sources(tuple(source_root.rglob("*.rs")))}

    assert (source_root / "grpc" / "joysafeter.rs") in production_paths
    assert (source_root / "db" / "queries" / "tests.rs") not in production_paths
    assert (source_root / "kernel" / "sandbox_resolver_tests.rs") not in production_paths


@pytest.mark.no_db
def test_rust_inline_module_external_child_uses_inline_namespace(tmp_path) -> None:
    crate = tmp_path / "src"
    child_dir = crate / "outer"
    child_dir.mkdir(parents=True)
    lib = crate / "lib.rs"
    child = child_dir / "child.rs"
    lib.write_text("mod outer { mod child; }\n")
    child.write_text('fn inline_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, child))

    assert len(findings) == 1
    assert "inline_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_nested_inline_namespace_preserves_unknown_cfg_external_edge(tmp_path) -> None:
    crate = tmp_path / "src"
    child_dir = crate / "outer" / "nested"
    child_dir.mkdir(parents=True)
    lib = crate / "lib.rs"
    child = child_dir / "child.rs"
    lib.write_text('mod outer { #[cfg(feature = "possible-production")] mod nested { mod child; } }\n')
    child.write_text('fn nested_lookup() { let _ = "SELECT id FROM joysafeter_credentials"; }\n')

    findings = discover_rust_raw_sql((lib, child))

    assert len(findings) == 1
    assert "nested_lookup" in next(iter(findings)).surface


@pytest.mark.no_db
def test_rust_item_level_test_cfg_is_excluded(tmp_path) -> None:
    fixture = tmp_path / "lib.rs"
    fixture.write_text(
        '#[cfg(test)]\nfn test_only(material: Material) { let _ = "SELECT id FROM joysafeter_credentials"; '
        "material.reveal(); }\n"
    )

    assert discover_rust_raw_sql((fixture,)) == set()
    assert discover_rust_sensitive_calls((fixture,)) == set()


@pytest.mark.no_db
def test_rust_nested_test_cfg_is_excluded(tmp_path) -> None:
    fixture = tmp_path / "lib.rs"
    fixture.write_text(
        '#[cfg(all(any(test, feature = "fixture"), not(not(test))))]\n'
        'mod test_only { fn query() { let _ = "SELECT id FROM joysafeter_credentials"; } }\n'
    )

    assert discover_rust_raw_sql((fixture,)) == set()


@pytest.mark.no_db
def test_rust_cfg_inventory_ignores_braces_in_strings_and_comments(tmp_path) -> None:
    fixture = tmp_path / "lib.rs"
    fixture.write_text(
        "#[cfg(test)]\nmod tests {\n"
        '  fn test_only() { let _ = "} SELECT id FROM joysafeter_credentials"; /* } */ }\n'
        "}\n"
        'fn production() { let _ = "SELECT id FROM joysafeter_credential_groups"; }\n'
    )

    findings = discover_rust_raw_sql((fixture,))

    assert len(findings) == 1
    assert "production" in next(iter(findings)).surface
    assert "joysafeter_credential_groups" in next(iter(findings)).surface


@pytest.mark.no_db
def test_second_rust_sql_callsite_in_same_file_is_not_covered_by_first_exception(tmp_path) -> None:
    fixture = tmp_path / "same_file_sql.rs"
    fixture.write_text(
        'fn reviewed() { let _ = "SELECT id FROM joysafeter_credentials"; }\n'
        'fn unregistered() { let _ = "SELECT data FROM joysafeter_credentials"; }\n'
    )
    findings = discover_rust_raw_sql((fixture,))

    assert len(findings) == 2
    reviewed = min(findings, key=lambda finding: finding.surface)
    with pytest.raises(AssertionError, match="unclassified credential reference surfaces"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions=_reviewed_exception(reviewed.surface),
        )


@pytest.mark.no_db
def test_second_rust_reveal_callsite_in_same_file_is_not_covered_by_first_exception(tmp_path) -> None:
    fixture = tmp_path / "same_file_reveal.rs"
    fixture.write_text(
        "fn reviewed(material: Material) { material.reveal(); }\n"
        "fn unregistered(material: Material) { material.reveal(); }\n"
    )
    findings = discover_rust_sensitive_calls((fixture,))

    assert len(findings) == 2
    reviewed = min(findings, key=lambda finding: finding.surface)
    with pytest.raises(AssertionError, match="unclassified credential reference surfaces"):
        assert_reverse_census_closed(
            findings,
            registered_surface_ids=set(),
            reviewed_exceptions=_reviewed_exception(reviewed.surface),
        )
