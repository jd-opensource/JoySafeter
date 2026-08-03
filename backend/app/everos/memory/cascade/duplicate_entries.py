"""Detect and repair duplicate daily-log markdown entry markers."""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path

from app.everos.core.persistence import MarkdownReader
from app.everos.core.persistence.markdown.frontmatter import dump_frontmatter

from .registry import KIND_REGISTRY

_REPAIRABLE_DAILY_KINDS = {"episode", "atomic_fact", "foresight", "agent_case"}


@dataclasses.dataclass(frozen=True)
class DuplicateEntryReport:
    path: Path
    duplicate_counts: dict[str, int]
    original_count: int
    unique_count: int
    changed: bool

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicate_counts)


def repair_duplicate_entries_file(path: Path, *, apply: bool = False) -> DuplicateEntryReport:
    """Report or repair duplicate entry ids in one markdown file.

    Repair is last-wins: if the same marker id appears multiple times, the
    latest block in the file is retained and earlier blocks are removed.
    """
    raw = path.read_text(encoding="utf-8")
    parsed = MarkdownReader.parse(raw)
    counts = Counter(entry.id for entry in parsed.entries)
    duplicates = {entry_id: count for entry_id, count in counts.items() if count > 1}
    unique_count = len(counts)
    if not duplicates:
        return DuplicateEntryReport(
            path=path,
            duplicate_counts={},
            original_count=len(parsed.entries),
            unique_count=unique_count,
            changed=False,
        )

    if apply:
        body = _body_without_earlier_duplicates(parsed.body, duplicates)
        frontmatter = dict(parsed.frontmatter)
        frontmatter["entry_count"] = unique_count
        path.write_text(dump_frontmatter(frontmatter) + body, encoding="utf-8")

    return DuplicateEntryReport(
        path=path,
        duplicate_counts=duplicates,
        original_count=len(parsed.entries),
        unique_count=unique_count,
        changed=apply,
    )


def scan_duplicate_entry_files(
    root: Path,
    *,
    apply: bool = False,
    kind: str = "all",
) -> list[DuplicateEntryReport]:
    """Scan repairable daily-log files under ``root`` and report duplicates."""
    reports: list[DuplicateEntryReport] = []
    for path in _iter_repairable_paths(root, kind=kind):
        report = repair_duplicate_entries_file(path, apply=apply)
        if report.has_duplicates:
            reports.append(report)
    return reports


def _body_without_earlier_duplicates(body: str, duplicates: dict[str, int]) -> str:
    parsed = MarkdownReader.parse(body)
    remaining = Counter(duplicates)
    chunks: list[str] = []
    cursor = 0
    for entry in parsed.entries:
        chunks.append(body[cursor : entry.start])
        if remaining.get(entry.id, 0) > 1:
            remaining[entry.id] -= 1
        else:
            chunks.append(body[entry.start : entry.end])
        cursor = entry.end
    chunks.append(body[cursor:])
    return "".join(chunks)


def _iter_repairable_paths(root: Path, *, kind: str) -> list[Path]:
    selected = []
    for spec in KIND_REGISTRY:
        if spec.name not in _REPAIRABLE_DAILY_KINDS:
            continue
        if kind != "all" and spec.name != kind:
            continue
        selected.extend(path for path in root.glob(spec.path_glob()) if path.is_file())
    if kind != "all" and not selected and kind not in _REPAIRABLE_DAILY_KINDS:
        valid = ", ".join(["all", *_REPAIRABLE_DAILY_KINDS])
        raise ValueError(f"unsupported duplicate-entry repair kind {kind!r}; use {valid}")
    return sorted(selected)
