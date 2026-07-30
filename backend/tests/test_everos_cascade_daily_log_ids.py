from pathlib import Path
from types import SimpleNamespace

import pytest

from app.everos.core.persistence import MarkdownReader
from app.everos.memory.cascade.handlers import HandlerDeps
from app.everos.memory.cascade.handlers._daily_log_base import (
    BaseDailyLogHandler,
    ParsedEntry,
)
from app.everos.memory.cascade.handlers.atomic_fact import AtomicFactHandler


class _Tokenizer:
    def tokenize(self, text: str) -> list[str]:
        return text.split()


class _Embedder:
    _model = "test-embedding"

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 1024


def _handler() -> AtomicFactHandler:
    return AtomicFactHandler(
        HandlerDeps(
            memory_root=SimpleNamespace(root=Path(".")),
            embedder=_Embedder(),
            tokenizer=_Tokenizer(),
        )
    )


def _parsed_entry(entry_id: str) -> ParsedEntry:
    parsed = MarkdownReader.parse(
        "\n".join(
            [
                f"<!-- entry:{entry_id} -->",
                f"## {entry_id}",
                "",
                "**owner_id**: huajie_Sun",
                "**timestamp**: 2026-07-28T02:01:46+00:00",
                "**parent_type**: episode",
                "**parent_id**: ep_20260728_00000001",
                "",
                "### Fact",
                "The user investigated EverOS memory extraction.",
                f"<!-- /entry:{entry_id} -->",
            ]
        )
    )
    structured = parsed.entries[0].as_structured()
    return ParsedEntry(
        entry_id=entry_id,
        structured=structured,
        content_sha256="digest",
    )


@pytest.mark.asyncio
async def test_daily_log_row_id_uses_md_path_and_entry_id():
    entry = _parsed_entry("af_20260728_00000001")
    handler = _handler()

    default_row = await handler._build_row(  # noqa: SLF001
        owner_id="huajie_Sun",
        owner_type="user",
        app_id="joysafeter",
        project_id="default__project",
        md_path="joysafeter/default__project/users/huajie_Sun/.atomic_facts/atomic_fact-2026-07-28.md",
        entry=entry,
    )
    test_row = await handler._build_row(  # noqa: SLF001
        owner_id="huajie_Sun",
        owner_type="user",
        app_id="joysafeter",
        project_id="test__project",
        md_path="joysafeter/test__project/users/huajie_Sun/.atomic_facts/atomic_fact-2026-07-28.md",
        entry=entry,
    )

    assert default_row.id == (
        "joysafeter/default__project/users/huajie_Sun/.atomic_facts/"
        "atomic_fact-2026-07-28.md#af_20260728_00000001"
    )
    assert test_row.id == (
        "joysafeter/test__project/users/huajie_Sun/.atomic_facts/"
        "atomic_fact-2026-07-28.md#af_20260728_00000001"
    )
    assert default_row.id != test_row.id


def test_daily_log_diff_rebuilds_rows_with_legacy_owner_entry_id():
    entry = _parsed_entry("af_20260728_00000001")
    legacy_row = SimpleNamespace(
        id="huajie_Sun_af_20260728_00000001",
        entry_id="af_20260728_00000001",
        content_sha256="digest",
        vector_status="ready",
    )

    to_build, skipped = BaseDailyLogHandler._diff_entries(
        [entry],
        [legacy_row],
        "joysafeter/default__project/users/huajie_Sun/.atomic_facts/atomic_fact-2026-07-28.md",
    )

    assert to_build == [entry]
    assert skipped == 0
