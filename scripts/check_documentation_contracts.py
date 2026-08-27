"""Check deterministic documentation contracts without external dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

NORMATIVE_DOCUMENTS: tuple[Path, ...] = (
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("DEVELOPMENT.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/ARCHITECTURE_CN.md"),
    Path("backend/README.md"),
    Path("frontend/README.md"),
    Path("deploy/README.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/DOCUMENTATION_STATUS.md"),
)

_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.*?)(?:\s+#+\s*)?$")
_MARKDOWN_LINK_PATTERN = re.compile(
    r"\[[^\]]*\]\(\s*(?P<destination><[^>]+>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
_NON_ANCHOR_CHARACTERS = re.compile(r"[^\w\s-]", re.UNICODE)
_VIOLATION_DATACLASS = (
    dataclass(frozen=True, slots=True)
    if sys.version_info >= (3, 10)
    else dataclass(frozen=True)
)


@_VIOLATION_DATACLASS
class Violation:
    code: str
    path: Path
    message: str
    line: int | None = None


def slugify_markdown_heading(heading: str) -> str:
    """Return the GitHub-style fragment generated for a Markdown heading."""
    normalized = _NON_ANCHOR_CHARACTERS.sub("", heading.strip().lower())
    return re.sub(r"\s+", "-", normalized)


def _iter_non_fenced_lines(content: str) -> Iterable[tuple[int, str]]:
    """Yield ``(line_number, line)`` for lines outside fenced code blocks.

    Follows CommonMark fence semantics: a fence opened with N (>= 3) backticks
    or tildes is only closed by a line whose leading run is the SAME character,
    at least N long, and carries no trailing info string. A mismatched character
    (``~~~`` inside a backtick fence) or a shorter same-character run therefore
    does NOT close the fence — its lines stay code, so their headings never
    become anchors and their links are not scanned.
    """
    fence_char = ""
    fence_len = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if fence_char:
            if stripped[:1] == fence_char:
                run = len(stripped) - len(stripped.lstrip(fence_char))
                if run >= fence_len and stripped[run:].strip() == "":
                    fence_char = ""
                    fence_len = 0
            continue
        if stripped[:1] in ("`", "~"):
            char = stripped[0]
            run = len(stripped) - len(stripped.lstrip(char))
            if run >= 3:
                fence_char = char
                fence_len = run
                continue
        yield line_number, line


def _heading_anchors(content: str) -> set[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for _line_number, line in _iter_non_fenced_lines(content):
        match = _HEADING_PATTERN.match(line)
        if match is None:
            continue
        base_anchor = slugify_markdown_heading(match.group("heading"))
        occurrence = occurrences.get(base_anchor, 0)
        occurrences[base_anchor] = occurrence + 1
        anchors.add(base_anchor if occurrence == 0 else f"{base_anchor}-{occurrence}")
    return anchors


def _relative_path(repo_root: Path, path: Path) -> Path:
    try:
        return path.relative_to(repo_root)
    except ValueError:
        return path


def _iter_markdown_links(content: str) -> Iterable[tuple[int, str]]:
    for line_number, line in _iter_non_fenced_lines(content):
        for match in _MARKDOWN_LINK_PATTERN.finditer(line):
            destination = match.group("destination")
            yield (
                line_number,
                destination[1:-1] if destination.startswith("<") else destination,
            )


def _is_external_link(destination: str) -> bool:
    parsed = urlsplit(destination)
    return bool(parsed.scheme or parsed.netloc or parsed.path.startswith("/"))


def check_relative_markdown_links(
    repo_root: Path, documents: Sequence[Path]
) -> list[Violation]:
    """Report invalid relative Markdown paths and heading anchors."""
    resolved_root = repo_root.resolve()
    violations: list[Violation] = []

    for document in documents:
        source_path = document if document.is_absolute() else resolved_root / document
        relative_document = _relative_path(resolved_root, source_path)
        if not source_path.is_file():
            violations.append(
                Violation("DOC-LINK", relative_document, "Document does not exist.")
            )
            continue

        content = source_path.read_text(encoding="utf-8")
        for line_number, destination in _iter_markdown_links(content):
            if _is_external_link(destination):
                continue
            parsed = urlsplit(destination)
            target_path = (
                source_path
                if not parsed.path
                else source_path.parent / unquote(parsed.path)
            )
            target_path = target_path.resolve()
            if not target_path.is_file():
                violations.append(
                    Violation(
                        "DOC-LINK",
                        relative_document,
                        f"Relative link target does not exist: {destination}",
                        line_number,
                    )
                )
                continue
            if not parsed.fragment:
                continue

            anchor = unquote(parsed.fragment)
            target_anchors = _heading_anchors(target_path.read_text(encoding="utf-8"))
            if anchor not in target_anchors:
                violations.append(
                    Violation(
                        "DOC-LINK",
                        relative_document,
                        f"Heading anchor does not exist: #{anchor} in {destination}",
                        line_number,
                    )
                )

    return violations


def _check_normative_document_links(repo_root: Path) -> list[Violation]:
    return check_relative_markdown_links(repo_root, NORMATIVE_DOCUMENTS)


# Positive markers that must remain present so the normative docs keep describing
# the current unified-credential model.
REQUIRED_DOCUMENT_CONTENT: dict[Path, tuple[str, ...]] = {
    Path("docs/ARCHITECTURE.md"): (
        "JoySafeterCredential",
        "/credentials",
        "/credential-groups",
        "credential_ref",
        "joysafeter.agent_execution_snapshot.v2",
        "AgentVersionId",
        "agentver_",
        "ApiKeyId",
        "apikey_",
        "SessionResourceId",
        "session_memory_store",
    ),
    Path("docs/ARCHITECTURE_CN.md"): (
        "AgentVersionId",
        "agentver_",
        "ApiKeyId",
        "apikey_",
        "SessionResourceId",
    ),
    Path("docs/api/openapi.md"): (
        "agentver_<uuid>",
        "apikey_<uuid>",
        "session_memory_store",
    ),
    Path("docs/joysafeter-agent-environment-session-api.md"): (
        "model_credential_id",
        "environment_credential_ids",
        "cred_<uuid>",
    ),
    Path("docs/tutorials/01-model-provider-setup.md"): (
        "/api/v1/credentials",
        "kind=model",
        "model_credential_id",
    ),
    Path("docs/tutorials/04-agent-build-and-run.md"): (
        "model_credential_id",
        "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020",
    ),
}

FORBIDDEN_DOCUMENT_CONTENT: dict[Path, tuple[str, ...]] = {
    Path("docs/ARCHITECTURE.md"): (
        "SecretId",
        "VaultId",
        "secret_ref",
        "secret_refs",
        "vault_ids",
        "service_credential_id",
    ),
    Path("docs/ARCHITECTURE_CN.md"): (
        "SecretId",
        "VaultId",
        "secret_ref",
        "secret_refs",
        "vault_ids",
        "service_credential_id",
    ),
    Path("docs/api/openapi.md"): (
        "/secrets",
        "/vaults",
        "SecretId",
        "VaultId",
        "secret_ref",
        "secret_refs",
        "vault_ids",
        "service_credential_id",
    ),
    Path("docs/joysafeter-agent-environment-session-api.md"): (
        "secret_ref",
        "secret_refs",
        "vault_ids",
        "service_credential_id",
    ),
    Path("docs/tutorials/00-getting-started.md"): (
        "/managed/secrets",
        "/managed/vaults",
    ),
    Path("docs/tutorials/01-model-provider-setup.md"): (
        "/managed/secrets",
        "/api/v1/secrets",
        "secret_ref",
        "kind=llm",
        '"kind": "llm"',
    ),
    Path("docs/tutorials/04-agent-build-and-run.md"): ("secret_ref", "LLM Secret"),
    Path("docs/tutorials/06-environments.md"): ("/managed/secrets",),
    Path("docs/tutorials/README.md"): ("/managed/secrets", "/managed/vaults"),
    Path("docs/user-journey-quickstart.drawio"): (
        "/managed/secrets",
        "/managed/vaults",
    ),
}


def check_required_document_content(
    repo_root: Path,
    requirements: Mapping[Path, Sequence[str]] = REQUIRED_DOCUMENT_CONTENT,
) -> list[Violation]:
    """Report normative documents missing required content markers."""
    resolved_root = repo_root.resolve()
    violations: list[Violation] = []
    for document, markers in requirements.items():
        source_path = document if document.is_absolute() else resolved_root / document
        relative_document = _relative_path(resolved_root, source_path)
        if not source_path.is_file():
            violations.append(
                Violation("DOC-CONTENT", relative_document, "Document does not exist.")
            )
            continue
        content = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in content:
                violations.append(
                    Violation(
                        "DOC-CONTENT",
                        relative_document,
                        f"Required marker is missing: {marker!r}",
                    )
                )
    return violations


def _check_required_document_content(repo_root: Path) -> list[Violation]:
    return check_required_document_content(repo_root)


def check_forbidden_document_content(
    repo_root: Path,
    forbidden: Mapping[Path, Sequence[str]] = FORBIDDEN_DOCUMENT_CONTENT,
) -> list[Violation]:
    """Report obsolete public-contract markers in normative documents."""
    resolved_root = repo_root.resolve()
    violations: list[Violation] = []
    for document, markers in forbidden.items():
        source_path = document if document.is_absolute() else resolved_root / document
        relative_document = _relative_path(resolved_root, source_path)
        if not source_path.is_file():
            violations.append(
                Violation("DOC-CONTENT", relative_document, "Document does not exist.")
            )
            continue
        content = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker in content:
                violations.append(
                    Violation(
                        "DOC-CONTENT",
                        relative_document,
                        f"Forbidden obsolete marker is present: {marker!r}",
                    )
                )
    return violations


def _check_forbidden_document_content(repo_root: Path) -> list[Violation]:
    return check_forbidden_document_content(repo_root)


_BACKEND_COMMAND_DOCUMENTS: tuple[Path, ...] = (
    Path("CONTRIBUTING.md"),
    Path("backend/README.md"),
)
# Tools whose command matrix is owned solely by DEVELOPMENT.md. Derived docs must
# reference it, not duplicate it (single source of truth); bare and `uv run` forms
# both count as duplication. deploy/README.md is exempt (container-context alembic).
_BACKEND_COMMAND_TOKENS = re.compile(r"(?:^|[\s;&|(])(pytest|ruff|mypy|alembic)\b")


def _iter_fenced_lines(content: str) -> Iterable[tuple[int, str]]:
    """Yield ``(line_number, line)`` for lines INSIDE fenced code blocks.

    Mirrors the fence semantics of ``_iter_non_fenced_lines``; the opening and
    closing fence lines themselves are not yielded, so only command bodies match.
    """
    fence_char = ""
    fence_len = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if fence_char:
            if stripped[:1] == fence_char:
                run = len(stripped) - len(stripped.lstrip(fence_char))
                if run >= fence_len and stripped[run:].strip() == "":
                    fence_char = ""
                    fence_len = 0
                    continue
            yield line_number, line
            continue
        if stripped[:1] in ("`", "~"):
            char = stripped[0]
            run = len(stripped) - len(stripped.lstrip(char))
            if run >= 3:
                fence_char = char
                fence_len = run


def check_backend_command_single_source(
    repo_root: Path,
    documents: Sequence[Path] = _BACKEND_COMMAND_DOCUMENTS,
) -> list[Violation]:
    """Derived docs must reference DEVELOPMENT.md, not duplicate its backend command matrix."""
    resolved_root = repo_root.resolve()
    violations: list[Violation] = []
    for document in documents:
        source_path = resolved_root / document
        relative_document = _relative_path(resolved_root, source_path)
        if not source_path.is_file():
            violations.append(
                Violation("DOC-COMMAND", relative_document, "Document does not exist.")
            )
            continue
        content = source_path.read_text(encoding="utf-8")
        for line_number, line in _iter_fenced_lines(content):
            match = _BACKEND_COMMAND_TOKENS.search(line)
            if match is None:
                continue
            tool = match.group(1)
            violations.append(
                Violation(
                    "DOC-COMMAND",
                    relative_document,
                    (
                        f"Backend command {tool!r} is owned by DEVELOPMENT.md; "
                        "reference it instead of duplicating the command matrix."
                    ),
                    line_number,
                )
            )
    return violations


def _check_backend_command_single_source(repo_root: Path) -> list[Violation]:
    return check_backend_command_single_source(repo_root)


_ROUTER_SOURCE = Path("backend/app/joysafeter_api/api/v1/router.py")
_IDS_SOURCE = Path("backend/app/joysafeter_shared/ids.py")
_ROUTE_INVENTORY_DOCS: tuple[Path, ...] = (
    Path("docs/ARCHITECTURE.md"),
    Path("docs/ARCHITECTURE_CN.md"),
)
# Mounted API prefixes and typed-ID prefixes are enumerable from source; the
# architecture route table and typed-ID inventory must list every one, so a new
# router or ID cannot silently drift out of the docs.
_MOUNTED_ROUTE_PREFIX = re.compile(r'include_router\([^)]*prefix="(/[A-Za-z0-9/_-]+)"')
_TYPED_ID_PREFIX = re.compile(r'^\s*prefix\s*=\s*"([a-z][a-z0-9]*_)"', re.MULTILINE)


def _read_optional_source(repo_root: Path, relative: Path) -> str | None:
    path = repo_root.resolve() / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def check_route_inventory(repo_root: Path) -> list[Violation]:
    """Every ``include_router`` prefix must appear in the architecture route tables."""
    resolved_root = repo_root.resolve()
    router = _read_optional_source(resolved_root, _ROUTER_SOURCE)
    violations: list[Violation] = []
    if router is None:
        violations.append(Violation("DOC-ROUTE", _ROUTER_SOURCE, "Router source does not exist."))
        return violations
    prefixes = sorted(set(_MOUNTED_ROUTE_PREFIX.findall(router)))
    for document in _ROUTE_INVENTORY_DOCS:
        content = _read_optional_source(resolved_root, document)
        if content is None:
            violations.append(Violation("DOC-ROUTE", document, "Document does not exist."))
            continue
        for prefix in prefixes:
            if f"`{prefix}`" not in content:
                violations.append(
                    Violation(
                        "DOC-ROUTE",
                        document,
                        f"Mounted route prefix {prefix!r} is not documented in the route table.",
                    )
                )
    return violations


def _check_route_inventory(repo_root: Path) -> list[Violation]:
    return check_route_inventory(repo_root)


def check_typed_id_inventory(repo_root: Path) -> list[Violation]:
    """Every typed-ID prefix defined in ids.py must appear in the architecture typed-ID inventory."""
    resolved_root = repo_root.resolve()
    ids = _read_optional_source(resolved_root, _IDS_SOURCE)
    violations: list[Violation] = []
    if ids is None:
        violations.append(Violation("DOC-ID", _IDS_SOURCE, "IDs source does not exist."))
        return violations
    prefixes = sorted(set(_TYPED_ID_PREFIX.findall(ids)))
    for document in _ROUTE_INVENTORY_DOCS:
        content = _read_optional_source(resolved_root, document)
        if content is None:
            violations.append(Violation("DOC-ID", document, "Document does not exist."))
            continue
        for prefix in prefixes:
            # Anchor to a code span (backtick) so an unrelated prose substring
            # cannot satisfy the rule; matches both the EN table `pfx_` and the
            # CN prose `pfx_<uuid>` forms.
            if f"`{prefix}" not in content:
                violations.append(
                    Violation(
                        "DOC-ID",
                        document,
                        f"Typed-ID prefix {prefix!r} is not documented in the typed-ID inventory.",
                    )
                )
    return violations


def _check_typed_id_inventory(repo_root: Path) -> list[Violation]:
    return check_typed_id_inventory(repo_root)


CHECKS: dict[str, Callable[[Path], list[Violation]]] = {
    "commands": _check_backend_command_single_source,
    "routes": _check_route_inventory,
    "typed-ids": _check_typed_id_inventory,
    "forbidden-content": _check_forbidden_document_content,
    "links": _check_normative_document_links,
    "content": _check_required_document_content,
}


def run_checks(
    repo_root: Path,
    selected: frozenset[str] | None = None,
) -> list[Violation]:
    names = selected or frozenset(CHECKS)
    violations: list[Violation] = []
    for name in sorted(names):
        violations.extend(CHECKS[name](repo_root))
    return sorted(
        violations, key=lambda item: (item.path.as_posix(), item.line or 0, item.code)
    )


def _parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="append",
        choices=sorted(CHECKS),
        metavar="NAME",
        help=f"Run only the named check group. May be repeated. Available: {', '.join(sorted(CHECKS))}.",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    selected = frozenset(args.check) if args.check else None
    violations = run_checks(Path(__file__).resolve().parents[1], selected)
    for violation in violations:
        location = violation.path.as_posix()
        if violation.line is not None:
            location = f"{location}:{violation.line}"
        print(f"{location}: {violation.code}: {violation.message}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
