import datetime as dt

import pytest
from typer.testing import CliRunner

from app.everos.core.persistence import MarkdownReader, MemoryRoot
from app.everos.core.persistence.lancedb import BaseLanceTable
from app.everos.core.persistence.lancedb.repository import LanceRepoBase
from app.everos.entrypoints.cli.commands import cascade
from app.everos.infra.persistence.markdown.writers import EpisodeWriter
from app.everos.memory.cascade.duplicate_entries import repair_duplicate_entries_file
from app.everos.memory.cascade.handlers.base import HandlerDeps
from app.everos.memory.cascade.handlers.episode import EpisodeHandler


def _entry(entry_id: str, *, content: str, timestamp: str = "2026-07-15T12:00:00+00:00") -> str:
    return "\n".join(
        [
            f"<!-- entry:{entry_id} -->",
            f"## {entry_id}",
            "",
            "**owner_id**: user-1",
            "**session_id**: session-1",
            f"**timestamp**: {timestamp}",
            "**parent_type**: memcell",
            "**parent_id**: mc-1",
            "**sender_ids**: [user-1]",
            "",
            "### Subject",
            "Duplicate test",
            "",
            "### Summary",
            content,
            "",
            "### Content",
            content,
            f"<!-- /entry:{entry_id} -->",
            "",
        ]
    )


@pytest.mark.asyncio
async def test_episode_writer_allocates_after_max_marker_id_when_frontmatter_count_is_stale(tmp_path):
    date = dt.date(2026, 7, 15)
    root = MemoryRoot(tmp_path)
    root.ensure()
    writer = EpisodeWriter(root)
    path = writer.path_for("user-1", date)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "entry_count: 1",
                "user_id: user-1",
                "date: '2026-07-15'",
                "---",
                _entry("ep_20260715_00000001", content="first"),
                _entry("ep_20260715_00000002", content="second"),
            ]
        ),
        encoding="utf-8",
    )

    new_id = await writer.append_entry(
        "user-1",
        inline={
            "owner_id": "user-1",
            "session_id": "session-1",
            "timestamp": "2026-07-15T12:03:00+00:00",
            "parent_type": "memcell",
            "parent_id": "mc-3",
            "sender_ids": ["user-1"],
        },
        sections={"Subject": "New", "Summary": "third", "Content": "third"},
        date=date,
    )

    parsed = await MarkdownReader.read(path)
    assert new_id.format() == "ep_20260715_00000003"
    assert [entry.id for entry in parsed.entries] == [
        "ep_20260715_00000001",
        "ep_20260715_00000002",
        "ep_20260715_00000003",
    ]
    assert parsed.frontmatter["entry_count"] == 3


class _Embedder:
    _model = "test-embedder"

    async def embed(self, text: str) -> list[float]:
        return [0.1] * 1024


class _Tokenizer:
    def tokenize(self, text: str) -> list[str]:
        return text.split()


class _EpisodeRepo:
    def __init__(self) -> None:
        self.upserted = []
        self.deleted = []

    async def find_where(self, where: str, *, limit: int):
        return []

    async def upsert(self, records):
        self.upserted.extend(records)

    async def delete(self, where: str):
        self.deleted.append(where)


@pytest.mark.asyncio
async def test_episode_cascade_keeps_last_duplicate_entry_before_upsert(tmp_path):
    md_path = "default_app/default_project/users/user-1/episodes/episode-2026-07-15.md"
    absolute = tmp_path / md_path
    absolute.parent.mkdir(parents=True)
    duplicate_id = "ep_20260715_00000001"
    absolute.write_text(
        "\n".join(
            [
                "---",
                "user_id: user-1",
                "date: '2026-07-15'",
                "entry_count: 2",
                "---",
                _entry(duplicate_id, content="old content"),
                _entry(duplicate_id, content="new content"),
            ]
        ),
        encoding="utf-8",
    )
    repo = _EpisodeRepo()

    class _Handler(EpisodeHandler):
        lance_repo = repo

    handler = _Handler(
        HandlerDeps(
            memory_root=MemoryRoot(tmp_path),
            embedder=_Embedder(),
            tokenizer=_Tokenizer(),
        )
    )

    outcome = await handler.handle_added_or_modified(md_path)

    assert outcome.upserted == 1
    assert len(repo.upserted) == 1
    assert repo.upserted[0].entry_id == duplicate_id
    assert repo.upserted[0].episode == "new content"


class _TinyRow(BaseLanceTable):
    TABLE_NAME = "tiny"

    id: str
    value: str


class _TinyRepo(LanceRepoBase[_TinyRow]):
    schema = _TinyRow


class _MergeBuilder:
    def __init__(self, table: "_FakeTable") -> None:
        self._table = table

    def when_matched_update_all(self):
        return self

    def when_not_matched_insert_all(self):
        return self

    async def execute(self, records):
        self._table.executed = list(records)


class _FakeTable:
    def __init__(self) -> None:
        self.executed = []

    def merge_insert(self, by: str):
        self.by = by
        return _MergeBuilder(self)


@pytest.mark.asyncio
async def test_lance_repo_upsert_deduplicates_duplicate_merge_keys():
    table = _FakeTable()
    repo = _TinyRepo(table)

    await repo.upsert(
        [
            _TinyRow(id="row-1", value="old"),
            _TinyRow(id="row-1", value="new"),
            _TinyRow(id="row-2", value="other"),
        ]
    )

    assert [(row.id, row.value) for row in table.executed] == [
        ("row-1", "new"),
        ("row-2", "other"),
    ]


def test_repair_duplicate_entries_file_dry_run_reports_without_mutating(tmp_path):
    path = tmp_path / "episode-2026-07-15.md"
    original = "\n".join(
        [
            "---",
            "entry_count: 2",
            "user_id: user-1",
            "---",
            _entry("ep_20260715_00000001", content="old content"),
            _entry("ep_20260715_00000001", content="new content"),
        ]
    )
    path.write_text(original, encoding="utf-8")

    report = repair_duplicate_entries_file(path, apply=False)

    assert report.changed is False
    assert report.duplicate_counts == {"ep_20260715_00000001": 2}
    assert report.original_count == 2
    assert report.unique_count == 1
    assert path.read_text(encoding="utf-8") == original


def test_repair_duplicate_entries_file_apply_keeps_last_duplicate_and_updates_entry_count(tmp_path):
    path = tmp_path / "episode-2026-07-15.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "entry_count: 2",
                "user_id: user-1",
                "---",
                _entry("ep_20260715_00000001", content="old content"),
                _entry("ep_20260715_00000001", content="new content"),
            ]
        ),
        encoding="utf-8",
    )

    report = repair_duplicate_entries_file(path, apply=True)
    parsed = MarkdownReader.parse(path.read_text(encoding="utf-8"))

    assert report.changed is True
    assert report.duplicate_counts == {"ep_20260715_00000001": 2}
    assert [entry.id for entry in parsed.entries] == ["ep_20260715_00000001"]
    assert parsed.entries[0].as_structured().sections["Content"] == "new content"
    assert parsed.frontmatter["entry_count"] == 1


def test_cascade_repair_duplicates_cli_dry_run_reports_duplicates_without_mutating(tmp_path):
    md_path = (
        tmp_path
        / "default_app"
        / "default_project"
        / "users"
        / "user-1"
        / "episodes"
        / "episode-2026-07-15.md"
    )
    md_path.parent.mkdir(parents=True)
    original = "\n".join(
        [
            "---",
            "entry_count: 2",
            "user_id: user-1",
            "---",
            _entry("ep_20260715_00000001", content="old content"),
            _entry("ep_20260715_00000001", content="new content"),
        ]
    )
    md_path.write_text(original, encoding="utf-8")

    result = CliRunner().invoke(
        cascade.app,
        ["--root", str(tmp_path), "repair-duplicates", "--kind", "episode"],
    )

    assert result.exit_code == 0
    assert "episode-2026-07-15.md" in result.output
    assert "ep_20260715_00000001 x2" in result.output
    assert "--apply" in result.output
    assert md_path.read_text(encoding="utf-8") == original
