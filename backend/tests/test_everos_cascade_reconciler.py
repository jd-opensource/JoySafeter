from types import SimpleNamespace

import pytest

from app.everos.memory.cascade import scanner
from app.everos.memory.cascade.reconciler import PriorState, reconcile
from app.everos.memory.cascade.types import ScanInput


class _Repo:
    def __init__(self, projection):
        self._projection = projection

    async def find_by_md_path(self, md_path: str):
        return self._projection


def test_reconcile_reenqueues_done_file_when_projection_is_missing():
    scan = [
        ScanInput(
            md_path="joysafeter/project/agents/agent-1/skills/skill_a/SKILL.md",
            kind="agent_skill",
            mtime=123.0,
        )
    ]
    state = {
        scan[0].md_path: PriorState(
            md_path=scan[0].md_path,
            kind="agent_skill",
            mtime=123.0,
            status="done",
            change_type="added",
        )
    }

    decisions = reconcile(scan, state, missing_projections={scan[0].md_path})

    assert len(decisions) == 1
    assert decisions[0].md_path == scan[0].md_path
    assert decisions[0].kind == "agent_skill"
    assert decisions[0].change_type == "modified"
    assert decisions[0].mtime == 123.0


def test_reconcile_skips_done_file_when_projection_exists():
    scan = [
        ScanInput(
            md_path="joysafeter/project/agents/agent-1/skills/skill_a/SKILL.md",
            kind="agent_skill",
            mtime=123.0,
        )
    ]
    state = {
        scan[0].md_path: PriorState(
            md_path=scan[0].md_path,
            kind="agent_skill",
            mtime=123.0,
            status="done",
            change_type="added",
        )
    }

    assert reconcile(scan, state) == []


def test_scanner_ignores_tmp_backup_tree(tmp_path, monkeypatch):
    normal = (
        tmp_path
        / "joysafeter/project/users/user-1/episodes/episode-2026-07-27.md"
    )
    backup = (
        tmp_path
        / ".tmp/before-cleanup/md/joysafeter/project/users/user-1/episodes/episode-2026-07-27.md"
    )
    normal.parent.mkdir(parents=True)
    backup.parent.mkdir(parents=True)
    normal.write_text("# normal\n", encoding="utf-8")
    backup.write_text("# backup\n", encoding="utf-8")
    monkeypatch.setattr(
        scanner,
        "KIND_REGISTRY",
        (
            SimpleNamespace(
                name="episode",
                path_glob=lambda: "**/episodes/*.md",
            ),
        ),
    )

    inputs = scanner._collect_scan_inputs(tmp_path)

    assert [item.md_path for item in inputs] == [
        "joysafeter/project/users/user-1/episodes/episode-2026-07-27.md"
    ]


@pytest.mark.asyncio
async def test_projection_audit_reenqueues_done_user_profile_when_digest_is_stale(
    tmp_path,
    monkeypatch,
):
    md_path = "joysafeter/test/users/user-1/user.md"
    absolute = tmp_path / md_path
    absolute.parent.mkdir(parents=True)
    absolute.write_text(
        "\n".join(
            [
                "---",
                "id: profile_user-1",
                "type: user_profile",
                "schema_version: 1",
                "user_id: user-1",
                "track: user",
                "summary: Fresh summary",
                "explicit_info: []",
                "implicit_traits: []",
                "profile_timestamp_ms: 123",
                "---",
                "Fresh summary",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scanner,
        "KIND_REGISTRY",
        (
            SimpleNamespace(
                name="user_profile",
                lance_repo=_Repo(SimpleNamespace(content_sha256="stale-digest")),
            ),
        ),
    )

    dirty = await scanner._find_stale_or_missing_done_projections(
        [
            ScanInput(
                md_path=md_path,
                kind="user_profile",
                mtime=123.0,
            )
        ],
        {
            md_path: PriorState(
                md_path=md_path,
                kind="user_profile",
                mtime=123.0,
                status="done",
                change_type="modified",
            )
        },
        tmp_path,
    )

    assert dirty == {md_path}


@pytest.mark.asyncio
async def test_projection_audit_keeps_done_user_profile_when_digest_matches(
    tmp_path,
    monkeypatch,
):
    md_path = "joysafeter/test/users/user-1/user.md"
    absolute = tmp_path / md_path
    absolute.parent.mkdir(parents=True)
    absolute.write_text(
        "\n".join(
            [
                "---",
                "id: profile_user-1",
                "type: user_profile",
                "schema_version: 1",
                "user_id: user-1",
                "track: user",
                "summary: Fresh summary",
                "explicit_info: []",
                "implicit_traits: []",
                "profile_timestamp_ms: 123",
                "---",
                "Fresh summary",
                "",
            ]
        ),
        encoding="utf-8",
    )
    expected_digest = await scanner._expected_projection_content_sha256(
        "user_profile",
        md_path,
        tmp_path,
    )
    monkeypatch.setattr(
        scanner,
        "KIND_REGISTRY",
        (
            SimpleNamespace(
                name="user_profile",
                lance_repo=_Repo(SimpleNamespace(content_sha256=expected_digest)),
            ),
        ),
    )

    dirty = await scanner._find_stale_or_missing_done_projections(
        [
            ScanInput(
                md_path=md_path,
                kind="user_profile",
                mtime=123.0,
            )
        ],
        {
            md_path: PriorState(
                md_path=md_path,
                kind="user_profile",
                mtime=123.0,
                status="done",
                change_type="modified",
            )
        },
        tmp_path,
    )

    assert dirty == set()


@pytest.mark.asyncio
async def test_projection_audit_reenqueues_done_atomic_fact_when_projection_is_missing(
    monkeypatch,
    tmp_path,
):
    md_path = "joysafeter/test/users/user-1/.atomic_facts/atomic_fact-2026-07-27.md"
    monkeypatch.setattr(
        scanner,
        "KIND_REGISTRY",
        (
            SimpleNamespace(
                name="atomic_fact",
                lance_repo=_Repo(None),
            ),
        ),
    )

    dirty = await scanner._find_stale_or_missing_done_projections(
        [
            ScanInput(
                md_path=md_path,
                kind="atomic_fact",
                mtime=123.0,
            )
        ],
        {
            md_path: PriorState(
                md_path=md_path,
                kind="atomic_fact",
                mtime=123.0,
                status="done",
                change_type="modified",
            )
        },
        tmp_path,
    )

    assert dirty == {md_path}
