#!/usr/bin/env python3
"""Real HTTP API verification for trigger session_mode.

This script verifies the user-facing API path, not just internal services:
  1. Creates a temporary API key in the real DB so HTTP calls can authenticate.
  2. Uses HTTP API to create an agent, one pinned session, and three cron triggers.
  3. Uses HTTP API POST /triggers/{id}/run to fire fresh/reuse/pinned.
  4. Marks created tasks terminal in DB between runs so session reuse can be tested.
  5. Cleans all temporary records.

Only DB setup/cleanup and task finalization are direct DB operations. Resource
creation and trigger execution are real HTTP API calls.

Run:
    cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
      POSTGRES_USER=conductor POSTGRES_PASSWORD=conductor POSTGRES_DB=joysafeter \
      .venv/bin/python ../scripts/verification/verify_trigger_session_modes_http.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent, SessionStatus
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_shared.database import AsyncSessionLocal

API_BASE = os.environ.get("JOYSAFETER_API_BASE", "http://127.0.0.1:8000/api/v1")
STAMP = f"http-session-mode-{uuid.uuid4().hex[:10]}"
RAW_API_KEY = f"verify_{uuid.uuid4().hex}"


def api_resource_uuid(value: str, prefix: str) -> str:
    return value.removeprefix(prefix)


def curl_json(method: str, path: str, api_key: str, body: dict[str, Any] | None = None) -> Any:
    cmd = [
        "curl",
        "-sS",
        "-X",
        method,
        "-H",
        f"X-Api-Key: {api_key}",
        "-H",
        "Content-Type: application/json",
    ]
    if body is not None:
        cmd.extend(["--data", json.dumps(body, ensure_ascii=False)])
    cmd.append(f"{API_BASE}{path}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed {method} {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json response {method} {path}: {result.stdout[:500]}") from exc
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data["data"]
    if isinstance(data, dict) and data.get("code") and data.get("message"):
        raise RuntimeError(f"api error {method} {path}: {data}")
    return data


async def choose_real_scope(db: AsyncSession) -> tuple[str, str, str]:
    result = await db.execute(
        select(Project.id, Project.org_id, ProjectMember.user_id)
        .select_from(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.archived_at.is_(None))
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise RuntimeError("No active project/member found in real database")
    return str(row[0]), str(row[1]), str(row[2])


async def create_temp_api_key(db: AsyncSession, project_id: str, org_id: str, user_id: str) -> JoySafeterApiKey:
    api_key = JoySafeterApiKey(
        project_id=project_id,
        org_id=org_id,
        name=STAMP,
        key_hash=hashlib.sha256(RAW_API_KEY.encode()).hexdigest(),
        key_prefix=RAW_API_KEY[:18],
        created_by=user_id,
        role="editor",
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key


async def finish_task(db: AsyncSession, task_id: str, session_id: str) -> None:
    task_uuid = uuid.UUID(api_resource_uuid(task_id, "task_"))
    session_uuid = uuid.UUID(api_resource_uuid(session_id, "sess_"))
    now = datetime.now(timezone.utc)
    await db.execute(
        update(JoySafeterTask)
        .where(JoySafeterTask.id == task_uuid)
        .values(status=JoySafeterTaskStatus.COMPLETED.value, completed_at=now)
    )
    await db.execute(
        update(JoySafeterSession)
        .where(JoySafeterSession.id == session_uuid)
        .values(status=SessionStatus.IDLE.value)
    )
    await db.commit()


async def cleanup(db: AsyncSession, api_key_id: uuid.UUID | None) -> None:
    trigger_ids = [
        row[0]
        for row in (await db.execute(select(JoySafeterTrigger.id).where(JoySafeterTrigger.name.like(f"{STAMP}%")))).all()
    ]
    agent_ids = [
        row[0]
        for row in (await db.execute(select(JoySafeterAgent.id).where(JoySafeterAgent.name == STAMP))).all()
    ]
    session_ids: list[uuid.UUID] = []
    task_ids: list[uuid.UUID] = []
    if agent_ids:
        session_ids = [
            row[0]
            for row in (await db.execute(select(JoySafeterSession.id).where(JoySafeterSession.agent_id.in_(agent_ids)))).all()
        ]
        task_ids = [
            row[0]
            for row in (await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.agent_id.in_(agent_ids)))).all()
        ]
    if trigger_ids:
        extra_task_ids = [
            row[0]
            for row in (await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.schedule_id.in_(trigger_ids)))).all()
        ]
        task_ids.extend(extra_task_ids)
    task_ids = list(dict.fromkeys(task_ids))
    session_ids = list(dict.fromkeys(session_ids))

    if session_ids:
        await db.execute(delete(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id.in_(session_ids)))
    if task_ids:
        await db.execute(delete(JoySafeterTask).where(JoySafeterTask.id.in_(task_ids)))
    if trigger_ids:
        await db.execute(delete(JoySafeterTrigger).where(JoySafeterTrigger.id.in_(trigger_ids)))
    if session_ids:
        await db.execute(delete(JoySafeterSession).where(JoySafeterSession.id.in_(session_ids)))
    if agent_ids:
        await db.execute(delete(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id.in_(agent_ids)))
        await db.execute(delete(JoySafeterAgent).where(JoySafeterAgent.id.in_(agent_ids)))
    if api_key_id is not None:
        await db.execute(delete(JoySafeterApiKey).where(JoySafeterApiKey.id == api_key_id))
    await db.commit()
    print(f"cleanup remaining resources for {STAMP}: done")


async def main() -> None:
    api_key_id: uuid.UUID | None = None
    async with AsyncSessionLocal() as db:
        project_id, org_id, user_id = await choose_real_scope(db)
        api_key = await create_temp_api_key(db, project_id, org_id, user_id)
        api_key_id = api_key.id
        print(f"using real HTTP API base={API_BASE}")
        print(f"using real scope project={project_id} org={org_id} user={user_id}")

        try:
            auth_probe = curl_json("GET", "/triggers?type=cron&limit=1", RAW_API_KEY)
            print(f"auth ok trigger_count_probe={len(auth_probe) if isinstance(auth_probe, list) else 'unknown'}")

            agent = curl_json(
                "POST",
                "/agents",
                RAW_API_KEY,
                {
                    "name": STAMP,
                    "engine_kind": "claude",
                    "model": "verify",
                    "system_prompt": "verify system",
                    "description": "temporary HTTP API session_mode verification",
                    "metadata": {"verify": STAMP},
                },
            )
            agent_id = agent["id"]
            agent_uuid = api_resource_uuid(agent_id, "agent_")
            print(f"created agent via API id={agent_id}")

            pinned_session = curl_json(
                "POST",
                "/sessions",
                RAW_API_KEY,
                {"agent": agent_id, "title": f"{STAMP} pinned", "metadata": {"verify": STAMP, "role": "pinned"}},
            )
            pinned_session_id = pinned_session["id"]
            pinned_uuid = api_resource_uuid(pinned_session_id, "sess_")
            print(f"created pinned session via API id={pinned_session_id}")

            def create_trigger(mode: str, pinned: str | None = None) -> dict[str, Any]:
                body: dict[str, Any] = {
                    "name": f"{STAMP}-{mode}",
                    "type": "cron",
                    "agent_id": agent_uuid,
                    "prompt_template": f"HTTP API {mode} mode verification",
                    "enabled": False,
                    "session_mode": mode,
                    "cron_expr": "0 0 1 1 *",
                    "timezone": "Asia/Shanghai",
                    "concurrency_policy": "allow",
                    "timeout_sec": 60,
                    "max_retries": 0,
                }
                if pinned:
                    body["pinned_session_id"] = pinned
                return curl_json("POST", "/triggers", RAW_API_KEY, body)

            fresh_trigger = create_trigger("fresh")
            reuse_trigger = create_trigger("reuse")
            pinned_trigger = create_trigger("pinned", pinned_uuid)
            print(
                "created triggers via API "
                f"fresh={fresh_trigger['id']} reuse={reuse_trigger['id']} pinned={pinned_trigger['id']}"
            )

            fresh_run_1 = curl_json("POST", f"/triggers/{fresh_trigger['id']}/run", RAW_API_KEY, {})
            assert fresh_run_1["session_id"] != pinned_session_id, fresh_run_1
            print(f"fresh  API run#1 ok session={fresh_run_1['session_id']} task={fresh_run_1['task_id']}")
            await finish_task(db, fresh_run_1["task_id"], fresh_run_1["session_id"])
            fresh_run_2 = curl_json("POST", f"/triggers/{fresh_trigger['id']}/run", RAW_API_KEY, {})
            assert fresh_run_2["session_id"] not in {fresh_run_1["session_id"], pinned_session_id}, fresh_run_2
            print(f"fresh  API run#2 ok session={fresh_run_2['session_id']} task={fresh_run_2['task_id']}")
            await finish_task(db, fresh_run_2["task_id"], fresh_run_2["session_id"])

            reuse_run_1 = curl_json("POST", f"/triggers/{reuse_trigger['id']}/run", RAW_API_KEY, {})
            print(f"reuse  API run#1 ok session={reuse_run_1['session_id']} task={reuse_run_1['task_id']}")
            await finish_task(db, reuse_run_1["task_id"], reuse_run_1["session_id"])
            reuse_run_2 = curl_json("POST", f"/triggers/{reuse_trigger['id']}/run", RAW_API_KEY, {})
            assert reuse_run_2["session_id"] == reuse_run_1["session_id"], reuse_run_2
            print(f"reuse  API run#2 ok session={reuse_run_2['session_id']} task={reuse_run_2['task_id']}")
            await finish_task(db, reuse_run_2["task_id"], reuse_run_2["session_id"])

            pinned_run = curl_json("POST", f"/triggers/{pinned_trigger['id']}/run", RAW_API_KEY, {})
            assert pinned_run["session_id"] == pinned_session_id, pinned_run
            print(f"pinned API run ok session={pinned_run['session_id']} task={pinned_run['task_id']}")
            await finish_task(db, pinned_run["task_id"], pinned_run["session_id"])

            print("PASS real HTTP API trigger create/run session_mode fresh/reuse/pinned")
        finally:
            await cleanup(db, api_key_id)


if __name__ == "__main__":
    asyncio.run(main())
