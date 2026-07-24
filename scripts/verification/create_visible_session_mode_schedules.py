#!/usr/bin/env python3
"""Create visible schedule rows for manually checking session_mode in the UI.

Unlike verify_trigger_session_modes_http.py, this script intentionally leaves the
created agent/session/schedules in the real database so the schedules page can
show fresh/reuse/pinned rows.

It uses real HTTP API calls for resource creation:
  POST /api/v1/agents
  POST /api/v1/sessions
  POST /api/v1/schedules

Direct DB access is only used to create a temporary API key, remove any previous
visible demo rows with the same prefix, and delete that temporary API key at the
end.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_api_key import JoySafeterApiKey
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_shared.database import AsyncSessionLocal

API_BASE = os.environ.get("JOYSAFETER_API_BASE", "http://127.0.0.1:8000/api/v1")
DEMO_NAME = os.environ.get("SESSION_MODE_DEMO_NAME", "session-mode-visible-demo")
RAW_API_KEY = f"visible_demo_{uuid.uuid4().hex}"


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
        name=f"{DEMO_NAME}-api-key",
        key_hash=hashlib.sha256(RAW_API_KEY.encode()).hexdigest(),
        key_prefix=RAW_API_KEY[:18],
        created_by=user_id,
        role="editor",
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key


async def remove_previous_demo(db: AsyncSession) -> None:
    agent_ids = [row[0] for row in (await db.execute(select(JoySafeterAgent.id).where(JoySafeterAgent.name == DEMO_NAME))).all()]
    schedule_ids = [
        row[0]
        for row in (await db.execute(select(JoySafeterSchedule.id).where(JoySafeterSchedule.name.like(f"{DEMO_NAME}-%")))).all()
    ]
    session_ids = []
    task_ids = []
    if agent_ids:
        session_ids = [row[0] for row in (await db.execute(select(JoySafeterSession.id).where(JoySafeterSession.agent_id.in_(agent_ids)))).all()]
        task_ids = [row[0] for row in (await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.agent_id.in_(agent_ids)))).all()]
    if schedule_ids:
        task_ids.extend([row[0] for row in (await db.execute(select(JoySafeterTask.id).where(JoySafeterTask.schedule_id.in_(schedule_ids)))).all()])
    task_ids = list(dict.fromkeys(task_ids))
    session_ids = list(dict.fromkeys(session_ids))
    if session_ids:
        await db.execute(delete(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id.in_(session_ids)))
    if task_ids:
        await db.execute(delete(JoySafeterTask).where(JoySafeterTask.id.in_(task_ids)))
    if schedule_ids:
        await db.execute(delete(JoySafeterSchedule).where(JoySafeterSchedule.id.in_(schedule_ids)))
    if session_ids:
        await db.execute(delete(JoySafeterSession).where(JoySafeterSession.id.in_(session_ids)))
    if agent_ids:
        await db.execute(delete(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id.in_(agent_ids)))
        await db.execute(delete(JoySafeterAgent).where(JoySafeterAgent.id.in_(agent_ids)))
    await db.execute(delete(JoySafeterApiKey).where(JoySafeterApiKey.name == f"{DEMO_NAME}-api-key"))
    await db.commit()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await remove_previous_demo(db)
        project_id, org_id, user_id = await choose_real_scope(db)
        api_key = await create_temp_api_key(db, project_id, org_id, user_id)
        try:
            print(f"using API base={API_BASE}")
            print(f"using project={project_id} org={org_id} user={user_id}")
            probe = curl_json("GET", "/schedules?limit=1", RAW_API_KEY)
            print(f"auth ok existing_schedule_probe={len(probe) if isinstance(probe, list) else 'unknown'}")

            agent = curl_json(
                "POST",
                "/agents",
                RAW_API_KEY,
                {
                    "name": DEMO_NAME,
                    "engine_kind": "claude",
                    "model": "verify",
                    "system_prompt": "visible schedule session mode demo",
                    "description": "Demo agent for visible schedule session_mode rows",
                    "metadata": {"demo": DEMO_NAME},
                },
            )
            agent_id = agent["id"]
            agent_uuid = api_resource_uuid(agent_id, "agent_")
            print(f"created visible demo agent={agent_id}")

            pinned_session = curl_json(
                "POST",
                "/sessions",
                RAW_API_KEY,
                {"agent": agent_id, "title": f"{DEMO_NAME} pinned session", "metadata": {"demo": DEMO_NAME, "role": "pinned"}},
            )
            pinned_uuid = api_resource_uuid(pinned_session["id"], "sess_")
            print(f"created visible pinned session={pinned_session['id']}")

            created = []
            for mode in ("fresh", "reuse", "pinned"):
                body: dict[str, Any] = {
                    "name": f"{DEMO_NAME}-{mode}",
                    "agent_id": agent_uuid,
                    "prompt": f"Visible schedule demo for {mode} session mode",
                    "cron_expr": "0 9 * * *",
                    "timezone": "Asia/Shanghai",
                    "description": f"Visible demo row for session_mode={mode}",
                    "enabled": False,
                    "session_mode": mode,
                    "concurrency_policy": "allow",
                    "timeout_sec": 60,
                    "max_retries": 0,
                }
                if mode == "pinned":
                    body["pinned_session_id"] = pinned_uuid
                schedule = curl_json("POST", "/schedules", RAW_API_KEY, body)
                created.append(schedule)
                print(f"created schedule {schedule['name']} id={schedule['id']} session_mode={schedule.get('session_mode')}")

            print("VISIBLE_DEMO_READY open /managed/schedules and search: session-mode-visible-demo")
        finally:
            await db.execute(delete(JoySafeterApiKey).where(JoySafeterApiKey.id == api_key.id))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
