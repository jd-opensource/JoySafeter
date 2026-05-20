import asyncio
import logging
from typing import Optional

import httpx

from app.conductor.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)


class DaytonaSandboxProvider(SandboxProvider):
    """Cloud sandbox provider backed by the Daytona REST API.

    Ported from conductor-sandbox/src/daytona.rs.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        target: str = "default",
        snapshot: str = "",
    ):
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._target = target
        self._snapshot = snapshot

    def provider_name(self) -> str:
        return "daytona"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Daytona-Source": "conductor",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _map_state(state: str) -> str:
        mapping = {
            "started": "running",
            "stopped": "stopped",
            "archived": "stopped",
            "creating": "creating",
            "starting": "creating",
            "pulling_snapshot": "creating",
            "restoring": "creating",
            "building_snapshot": "creating",
            "pending_build": "creating",
            "stopping": "stopping",
            "archiving": "stopping",
            "destroyed": "destroyed",
        }
        return mapping.get(state, "destroyed")

    async def create(
        self,
        name: str,
        image: str,
        env: dict[str, str],
        work_dir: str,
        labels: Optional[dict[str, str]] = None,
    ) -> str:
        has_snapshot = bool(self._snapshot)

        body: dict = {
            "env": env,
            "labels": {**(labels or {}), "conductor": "true"},
            "target": self._target,
            "autoStopInterval": 15,
            "autoArchiveInterval": 30,
            "public": False,
        }

        if has_snapshot:
            body["snapshot"] = self._snapshot
        else:
            body["cpu"] = 2
            body["memory"] = 4
            body["disk"] = 20

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._api_url}/sandbox",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Daytona API returned {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        external_id = data["id"]
        logger.info("Daytona sandbox created: %s", external_id)
        return external_id

    async def start(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._api_url}/sandbox/{external_id}/start",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Daytona start failed: {resp.text}")
        logger.info("Daytona sandbox started: %s", external_id)

    async def stop(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._api_url}/sandbox/{external_id}/stop",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Daytona stop failed: {resp.text}")
        logger.info("Daytona sandbox stopped: %s", external_id)

    async def destroy(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self._api_url}/sandbox/{external_id}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                logger.info("Daytona sandbox already gone: %s", external_id)
                return
            if resp.status_code >= 400:
                raise RuntimeError(f"Daytona delete failed: {resp.text}")
        logger.info("Daytona sandbox destroyed: %s", external_id)

    async def status(self, external_id: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandbox/{external_id}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return "destroyed"
            if resp.status_code >= 400:
                return "unknown"
            data = resp.json()
        state = data.get("state", "unknown")
        return self._map_state(state)

    async def exec(
        self, external_id: str, cmd: list[str], env: Optional[dict[str, str]] = None
    ) -> tuple[int, str, str]:
        raise NotImplementedError("Daytona exec not supported via REST API")

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandbox/{external_id}",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()

        state = data.get("state", "unknown")

        if state == "started":
            return {
                "stage": "runtime_ready",
                "progress": 100,
                "message": "Daytona sandbox is running",
                "complete": True,
                "error": False,
            }
        elif state in ("creating", "pulling_snapshot", "building_snapshot", "pending_build"):
            return {
                "stage": "daytona_creating",
                "progress": 40,
                "message": f"Daytona sandbox state: {state}",
                "complete": False,
                "error": False,
            }
        elif state in ("starting", "restoring"):
            return {
                "stage": "daytona_starting",
                "progress": 70,
                "message": f"Daytona sandbox state: {state}",
                "complete": False,
                "error": False,
            }
        elif state == "error":
            return {
                "stage": "daytona_error",
                "progress": 100,
                "message": "Daytona sandbox entered error state",
                "complete": True,
                "error": True,
                "error_message": "Sandbox failed on Daytona side",
            }
        else:
            return {
                "stage": "daytona_unknown",
                "progress": 50,
                "message": f"Daytona sandbox state: {state}",
                "complete": False,
                "error": False,
            }

    async def list_active(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandbox",
                headers=self._headers(),
                params={"labels": '{"conductor":"true"}'},
            )
            if resp.status_code >= 400:
                logger.warning("Daytona list_active failed: %s", resp.text)
                return []
            sandboxes = resp.json()

        return [
            {
                "id": s["id"],
                "provider": "daytona",
                "status": self._map_state(s.get("state", "unknown")),
            }
            for s in sandboxes
            if self._map_state(s.get("state", "unknown")) in ("running", "creating")
        ]
