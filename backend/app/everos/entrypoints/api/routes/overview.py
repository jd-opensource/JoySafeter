"""GET /api/v1/memory/overview — dashboard-friendly memory listing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException, Query

from app.everos.core.persistence import MemoryRoot, app_dir_name, project_dir_name
from app.everos.infra.persistence.lancedb import (
    agent_case_repo,
    agent_skill_repo,
    atomic_fact_repo,
    episode_repo,
    user_profile_repo,
)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _q(value: str) -> str:
    return value.replace("'", "''")


def _space_where(app_id: str, project_id: str) -> str:
    return f"app_id = '{_q(app_id)}' AND project_id = '{_q(project_id)}'"


def _active_where(app_id: str, project_id: str) -> str:
    return f"{_space_where(app_id, project_id)} AND deprecated_by IS NULL"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _iso_from_ms(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _short(value: str | None, fallback: str = "Untitled") -> str:
    text = (value or "").strip()
    return text if text else fallback


def _dedupe_profiles(profiles: list[Any]) -> list[Any]:
    by_owner: dict[str, Any] = {}
    for profile in profiles:
        owner_id = str(profile.owner_id)
        prior = by_owner.get(owner_id)
        if prior is None:
            by_owner[owner_id] = profile
            continue
        prior_updated = getattr(prior, "updated_at", None)
        current_updated = getattr(profile, "updated_at", None)
        if str(current_updated or "") >= str(prior_updated or ""):
            by_owner[owner_id] = profile
    return list(by_owner.values())


def _active_rows(rows: list[Any]) -> list[Any]:
    return [row for row in rows if getattr(row, "deprecated_by", None) in (None, "")]


def _quoted_in(values: list[str]) -> str:
    return ", ".join(f"'{_q(value)}'" for value in values)


async def _facts_for_overview_episodes(
    *,
    active_where: str,
    episodes: list[Any],
    broad_facts: list[Any],
) -> list[Any]:
    """Return active facts, including facts attached to visible episodes.

    A broad LanceDB ``find_where`` can return an arbitrary limited slice
    before app-side sorting. Backfill by visible episode ``entry_id`` so
    expanded episode rows can always show their related facts.
    """
    by_id = {row.id: row for row in broad_facts}
    parent_ids = sorted(
        {
            str(getattr(episode, "entry_id", ""))
            for episode in episodes
            if getattr(episode, "entry_id", None)
        }
    )
    if not parent_ids:
        return list(by_id.values())

    scoped_where = (
        f"{active_where} "
        "AND parent_type = 'episode' "
        f"AND parent_id IN ({_quoted_in(parent_ids)})"
    )
    for row in _active_rows(await atomic_fact_repo.find_where(scoped_where, limit=10_000)):
        by_id[row.id] = row
    return list(by_id.values())


def _resolve_project_md_path(app_id: str, project_id: str, md_path: str) -> Path:
    rel_path = Path(md_path)
    if rel_path.is_absolute() or ".." in rel_path.parts or rel_path.suffix != ".md":
        raise HTTPException(status_code=400, detail="Invalid markdown path")

    memory_root = MemoryRoot.default()
    project_root = (
        memory_root.root / app_dir_name(app_id) / project_dir_name(project_id)
    ).resolve()
    file_path = (memory_root.root / rel_path).resolve()

    if not file_path.is_relative_to(project_root):
        raise HTTPException(status_code=404, detail="Markdown document not found")

    return file_path


@router.get("/overview")
async def get_memory_overview(
    app_id: str = Query("joysafeter", min_length=1),
    project_id: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """Return a compact overview of user and agent memories in one project."""
    where = _space_where(app_id, project_id)
    active_where = _active_where(app_id, project_id)

    profiles = _dedupe_profiles(await user_profile_repo.find_where(where, limit=limit))
    episodes = _active_rows(await episode_repo.find_where(active_where, limit=limit))
    broad_facts = _active_rows(
        await atomic_fact_repo.find_where(active_where, limit=limit)
    )
    facts = await _facts_for_overview_episodes(
        active_where=active_where,
        episodes=episodes,
        broad_facts=broad_facts,
    )
    cases = await agent_case_repo.find_where(where, limit=limit)
    skills = await agent_skill_repo.find_where(where, limit=limit)

    episodes_sorted = sorted(episodes, key=lambda r: r.timestamp, reverse=True)
    facts_sorted = sorted(facts, key=lambda r: r.timestamp, reverse=True)
    cases_sorted = sorted(cases, key=lambda r: r.timestamp, reverse=True)
    skills_sorted = sorted(skills, key=lambda r: r.name.lower())

    profile_items = [
        {
            "id": p.id,
            "owner_id": p.owner_id,
            "summary": p.summary,
            "explicit_info_json": p.explicit_info_json,
            "implicit_traits_json": p.implicit_traits_json,
            "timestamp_ms": p.profile_timestamp_ms,
            "updated_at": _iso(getattr(p, "updated_at", None)),
            "md_path": p.md_path,
        }
        for p in profiles
    ]
    episode_items = [
        {
            "id": e.id,
            "entry_id": e.entry_id,
            "owner_id": e.owner_id,
            "session_id": e.session_id,
            "parent_type": getattr(e, "parent_type", "memcell"),
            "parent_id": getattr(e, "parent_id", None),
            "source_entry_ids": list(getattr(e, "source_entry_ids", []) or []),
            "source_session_ids": list(getattr(e, "source_session_ids", []) or []),
            "source_agent_ids": list(getattr(e, "source_agent_ids", []) or []),
            "timestamp": _iso(e.timestamp),
            "subject": _short(e.subject, "Episode"),
            "summary": _short(e.summary, e.episode[:160]),
            "episode": e.episode,
            "md_path": e.md_path,
        }
        for e in episodes_sorted
    ]
    atomic_fact_items = [
        {
            "id": f.id,
            "entry_id": f.entry_id,
            "owner_id": f.owner_id,
            "session_id": f.session_id,
            "timestamp": _iso(f.timestamp),
            "parent_type": f.parent_type,
            "parent_id": f.parent_id,
            "sender_ids": f.sender_ids,
            "fact": f.fact,
            "md_path": f.md_path,
            "deprecated_by": f.deprecated_by,
        }
        for f in facts_sorted
    ]
    case_items = [
        {
            "id": c.id,
            "entry_id": c.entry_id,
            "owner_id": c.owner_id,
            "session_id": c.session_id,
            "timestamp": _iso(c.timestamp),
            "task_intent": c.task_intent,
            "approach": c.approach,
            "key_insight": c.key_insight,
            "quality_score": c.quality_score,
            "md_path": c.md_path,
        }
        for c in cases_sorted
    ]
    skill_items = [
        {
            "id": s.id,
            "owner_id": s.owner_id,
            "name": s.name,
            "description": s.description,
            "content": s.content,
            "confidence": s.confidence,
            "maturity_score": s.maturity_score,
            "source_case_ids": s.source_case_ids,
            "cluster_id": s.cluster_id,
            "updated_at": _iso(getattr(s, "updated_at", None)),
            "md_path": s.md_path,
        }
        for s in skills_sorted
    ]

    recent_activity = [
        *[
            {
                "id": p["id"],
                "kind": "profile",
                "action": "Update",
                "owner_id": p["owner_id"],
                "timestamp": p["updated_at"] or _iso_from_ms(p["timestamp_ms"]),
                "summary": p["summary"],
                "md_path": p["md_path"],
            }
            for p in profile_items[:20]
        ],
        *[
            {
                "id": e["id"],
                "entry_id": e["entry_id"],
                "kind": "episode",
                "action": "Create",
                "owner_id": e["owner_id"],
                "session_id": e["session_id"],
                "source_entry_ids": e["source_entry_ids"],
                "source_session_ids": e["source_session_ids"],
                "source_agent_ids": e["source_agent_ids"],
                "timestamp": e["timestamp"],
                "subject": e["subject"],
                "summary": e["summary"],
                "md_path": e["md_path"],
            }
            for e in episode_items[:20]
        ],
        *[
            {
                "id": c["id"],
                "entry_id": c["entry_id"],
                "kind": "agent_case",
                "action": "Create",
                "owner_id": c["owner_id"],
                "timestamp": c["timestamp"],
                "task_intent": c["task_intent"],
                "summary": c["task_intent"],
                "md_path": c["md_path"],
            }
            for c in case_items[:20]
        ],
        *[
            {
                "id": s["id"],
                "kind": "agent_skill",
                "action": "Update",
                "owner_id": s["owner_id"],
                "timestamp": s["updated_at"],
                "name": s["name"],
                "summary": s["name"],
                "md_path": s["md_path"],
            }
            for s in skill_items[:20]
        ],
    ]
    recent_activity.sort(key=lambda item: item["timestamp"] or "", reverse=True)

    return {
        "app_id": app_id,
        "project_id": project_id,
        "counts": {
            "profiles": len(profile_items),
            "episodes": len(episode_items),
            "agent_cases": len(case_items),
            "agent_skills": len(skill_items),
        },
        "profiles": profile_items,
        "episodes": episode_items,
        "atomic_facts": atomic_fact_items,
        "agent_cases": case_items,
        "agent_skills": skill_items,
        "recent_activity": recent_activity[:50],
    }


@router.get("/document")
async def get_memory_document(
    app_id: str = Query("joysafeter", min_length=1),
    project_id: str = Query(..., min_length=1),
    md_path: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Return a complete markdown document from the current memory project."""
    file_path = _resolve_project_md_path(app_id, project_id, md_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Markdown document not found")

    content = await anyio.Path(file_path).read_text(encoding="utf-8")
    return {
        "md_path": md_path,
        "content": content,
    }
