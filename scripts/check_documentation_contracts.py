"""Check deterministic documentation contracts without external dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence
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
_VIOLATION_DATACLASS = dataclass(frozen=True, slots=True) if sys.version_info >= (3, 10) else dataclass(frozen=True)


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


def _heading_anchors(content: str) -> set[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for line in content.splitlines():
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
    in_fenced_code_block = False
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fenced_code_block = not in_fenced_code_block
            continue
        if in_fenced_code_block:
            continue
        for match in _MARKDOWN_LINK_PATTERN.finditer(line):
            destination = match.group("destination")
            yield line_number, destination[1:-1] if destination.startswith("<") else destination


def _is_external_link(destination: str) -> bool:
    parsed = urlsplit(destination)
    return bool(parsed.scheme or parsed.netloc or parsed.path.startswith("/"))


def check_relative_markdown_links(repo_root: Path, documents: Sequence[Path]) -> list[Violation]:
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
            target_path = source_path if not parsed.path else source_path.parent / unquote(parsed.path)
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


CHECKS: dict[str, Callable[[Path], list[Violation]]] = {
    "links": _check_normative_document_links,
}


def run_checks(
    repo_root: Path,
    selected: frozenset[str] | None = None,
) -> list[Violation]:
    names = selected or frozenset(CHECKS)
    violations: list[Violation] = []
    for name in sorted(names):
        violations.extend(CHECKS[name](repo_root))
    return sorted(violations, key=lambda item: (item.path.as_posix(), item.line or 0, item.code))


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
