"""Unit tests for the dependency-free documentation contract checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_documentation_contracts.py"
_SPEC = importlib.util.spec_from_file_location("documentation_contracts", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
checker = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = checker
_SPEC.loader.exec_module(checker)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_accepts_valid_relative_link_and_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "[target](guides/target.md#existing-heading)\n")
    write(tmp_path / "guides/target.md", "# Existing Heading\n")

    violations = checker.check_relative_markdown_links(
        tmp_path,
        [Path("README.md")],
    )

    assert violations == []


def test_reports_missing_path_and_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "[missing](missing.md)\n[bad](target.md#absent)\n")
    write(tmp_path / "target.md", "# Existing Heading\n")

    violations = checker.check_relative_markdown_links(
        tmp_path,
        [Path("README.md")],
    )

    assert [(item.code, item.path.as_posix()) for item in violations] == [
        ("DOC-LINK", "README.md"),
        ("DOC-LINK", "README.md"),
    ]
    assert "missing.md" in violations[0].message
    assert "#absent" in violations[1].message


def test_accepts_unicode_heading_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "[target](target.md#über-café)\n")
    write(tmp_path / "target.md", "# Über Café\n")

    violations = checker.check_relative_markdown_links(
        tmp_path,
        [Path("README.md")],
    )

    assert checker.slugify_markdown_heading("Über Café") == "über-café"
    assert violations == []


def test_run_checks_aggregates_selected_checks_in_stable_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        checker,
        "CHECKS",
        {
            "zeta": lambda _repo_root: [checker.Violation("DOC-Z", Path("z.md"), "z", 2)],
            "alpha": lambda _repo_root: [checker.Violation("DOC-A", Path("a.md"), "a", 3)],
        },
    )

    violations = checker.run_checks(tmp_path, frozenset({"zeta", "alpha"}))

    assert [(item.code, item.path.as_posix(), item.line) for item in violations] == [
        ("DOC-A", "a.md", 3),
        ("DOC-Z", "z.md", 2),
    ]
