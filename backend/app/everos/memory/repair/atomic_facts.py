"""Repair stale AtomicFact text in EverOS markdown files."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import anyio

from app.everos.component.llm import get_project_llm_client
from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import (
    MarkdownReader,
    MarkdownWriter,
    MemoryRoot,
    dump_frontmatter,
    render_structured_entry,
)
from app.everos.core.persistence.lancedb.repository import _q
from app.everos.infra.persistence.lancedb import atomic_fact_repo
from app.everos.memory.language_policy import ensure_chinese_memory_llm
from app.everos.memory.strategies.extract_atomic_facts import (
    _ensure_chinese_fact_text,
    _fact_is_valid,
)

logger = get_logger(__name__)


async def repair_atomic_facts(
    *,
    app_id: str,
    project_id: str,
    owner_id: str | None = None,
    entry_ids: Sequence[str] | None = None,
    limit: int = 1000,
) -> dict[str, int]:
    """Rewrite active non-Chinese AtomicFact entries in markdown."""
    rows = await _load_atomic_fact_rows(
        app_id=app_id,
        project_id=project_id,
        owner_id=owner_id,
        entry_ids=entry_ids,
        limit=limit,
    )
    if not rows:
        return {
            "scanned": 0,
            "changed_entries": 0,
            "changed_files": 0,
            "failed_entries": 0,
            "skipped_entries": 0,
        }

    repairs_by_path: dict[str, dict[str, str]] = defaultdict(dict)
    llm_by_project: dict[str, Any] = {}
    failed_entries = 0
    skipped_entries = 0
    for row in rows:
        current_fact = str(getattr(row, "fact", "") or "").strip()
        if _fact_is_valid(current_fact):
            skipped_entries += 1
            continue
        try:
            llm_client = await _llm_for_project(str(row.project_id), llm_by_project)
            rewritten = await _ensure_chinese_fact_text(
                current_fact,
                llm_client,
                source_episode=current_fact,
            )
        except Exception as exc:
            failed_entries += 1
            logger.warning(
                "atomic_fact_repair_entry_failed",
                entry_id=getattr(row, "entry_id", None),
                md_path=getattr(row, "md_path", None),
                error=str(exc),
            )
            continue
        if rewritten and rewritten != current_fact:
            repairs_by_path[row.md_path][row.entry_id] = rewritten
        else:
            failed_entries += 1

    if not repairs_by_path:
        return {
            "scanned": len(rows),
            "changed_entries": 0,
            "changed_files": 0,
            "failed_entries": failed_entries,
            "skipped_entries": skipped_entries,
        }

    root = MemoryRoot.default()
    writer = MarkdownWriter(root)
    changed_files = 0
    changed_entries = 0
    for md_path, repairs in repairs_by_path.items():
        path = root.root / md_path
        async with writer.lock_for(path):
            raw = await anyio.Path(path).read_text(encoding="utf-8")
            repaired, changed = repair_atomic_fact_markdown_text(raw, repairs=repairs)
            if not changed:
                continue
            await writer.write(Path(path), repaired)
            changed_files += 1
            changed_entries += len(repairs)

    logger.info(
        "atomic_fact_repair_completed",
        app_id=app_id,
        project_id=project_id,
        owner_id=owner_id,
        scanned=len(rows),
        changed_entries=changed_entries,
        changed_files=changed_files,
        failed_entries=failed_entries,
        skipped_entries=skipped_entries,
    )
    return {
        "scanned": len(rows),
        "changed_entries": changed_entries,
        "changed_files": changed_files,
        "failed_entries": failed_entries,
        "skipped_entries": skipped_entries,
    }


def repair_atomic_fact_markdown_text(
    text: str,
    *,
    repairs: Mapping[str, str],
) -> tuple[str, bool]:
    """Return markdown text with selected Fact sections repaired."""
    parsed = MarkdownReader.parse(text)
    replacements: list[tuple[int, int, str]] = []
    for entry in parsed.entries:
        repaired_fact = repairs.get(entry.id)
        if repaired_fact is None:
            continue
        structured = entry.as_structured()
        sections = dict(structured.sections)
        if sections.get("Fact") == repaired_fact:
            continue
        sections["Fact"] = repaired_fact
        entry_body = render_structured_entry(
            header=structured.header or entry.id,
            inline=structured.inline,
            sections=sections,
        )
        replacement = (
            f"<!-- entry:{entry.id} -->\n"
            f"{entry_body}\n"
            f"<!-- /entry:{entry.id} -->"
        )
        replacements.append((entry.start, entry.end, replacement))

    if not replacements:
        return text, False

    body = parsed.body
    for start, end, replacement in sorted(replacements, reverse=True):
        body = body[:start] + replacement + body[end:]
    if body and not body.endswith("\n"):
        body += "\n"
    return dump_frontmatter(parsed.frontmatter) + body, True


async def _load_atomic_fact_rows(
    *,
    app_id: str,
    project_id: str,
    owner_id: str | None,
    entry_ids: Sequence[str] | None,
    limit: int,
) -> list[Any]:
    clauses = [
        f"app_id = '{_q(app_id)}'",
        f"project_id = '{_q(project_id)}'",
        "deprecated_by IS NULL",
    ]
    if owner_id:
        clauses.append(f"owner_id = '{_q(owner_id)}'")
    if entry_ids:
        quoted = ", ".join(f"'{_q(entry_id)}'" for entry_id in entry_ids)
        clauses.append(f"entry_id IN ({quoted})")
    return await atomic_fact_repo.find_where(" AND ".join(clauses), limit=limit)


async def _llm_for_project(project_id: str, cache: dict[str, Any]) -> Any:
    if project_id not in cache:
        cache[project_id] = ensure_chinese_memory_llm(
            await get_project_llm_client(
                project_id,
                default_timeout_seconds=180.0,
            )
        )
    return cache[project_id]


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", default="joysafeter")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--owner-id")
    parser.add_argument("--entry-id", action="append", dest="entry_ids")
    args = parser.parse_args()
    result = await repair_atomic_facts(
        app_id=args.app_id,
        project_id=args.project_id,
        owner_id=args.owner_id,
        entry_ids=args.entry_ids,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
