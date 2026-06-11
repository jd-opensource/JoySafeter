import asyncio
import logging
from typing import Optional

import httpx

from app.joysafeter_orchestrator.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)


class E2bSandboxProvider(SandboxProvider):
    """Cloud sandbox provider backed by the E2B REST API.

    Ported from joysafeter-sandbox/src/e2b.rs.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        template_id: str,
    ):
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._template_id = template_id

    def provider_name(self) -> str:
        return "e2b"

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _map_state(state: str) -> str:
        mapping = {
            "running": "running",
            "paused": "stopped",
        }
        return mapping.get(state, "destroyed")

    async def create(
        self,
        name: str,
        image: str,
        env: dict[str, str],
        work_dir: str,
        labels: Optional[dict[str, str]] = None,
        *,
        timeout: Optional[int] = None,
        **kwargs,
    ) -> str:
        from app.joysafeter_shared.config.settings import joysafeter_config

        eff_timeout = timeout or joysafeter_config.task_default_timeout

        body: dict = {
            "templateId": self._template_id,
            "timeout": eff_timeout,
            "metadata": {**(labels or {}), "joysafeter": "true"},
        }
        if env:
            body["envVars"] = env

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._api_url}/sandboxes",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"E2B API returned {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        external_id = data["sandboxId"]
        logger.info("E2B sandbox created: %s", external_id)
        return external_id

    async def start(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._api_url}/sandboxes/{external_id}/resume",
                headers=self._headers(),
                json={"timeout": 3600},
            )
            if resp.status_code == 409:
                return
            if resp.status_code >= 400:
                raise RuntimeError(f"E2B resume failed: {resp.text}")
        logger.info("E2B sandbox resumed: %s", external_id)

    async def stop(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._api_url}/sandboxes/{external_id}/pause",
                headers=self._headers(),
            )
            if resp.status_code == 409:
                return
            if resp.status_code >= 400:
                raise RuntimeError(f"E2B pause failed: {resp.text}")
        logger.info("E2B sandbox paused: %s", external_id)

    async def destroy(self, external_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self._api_url}/sandboxes/{external_id}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                logger.info("E2B sandbox already gone: %s", external_id)
                return
            if resp.status_code >= 400:
                raise RuntimeError(f"E2B kill failed: {resp.text}")
        logger.info("E2B sandbox killed: %s", external_id)

    async def status(self, external_id: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandboxes/{external_id}",
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
        raise NotImplementedError("E2B exec not supported via REST API")

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandboxes/{external_id}",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()

        state = data.get("state", "unknown")

        if state == "running":
            return {
                "stage": "runtime_ready",
                "progress": 100,
                "message": "E2B sandbox is running",
                "complete": True,
                "error": False,
            }
        elif state == "paused":
            return {
                "stage": "e2b_paused",
                "progress": 50,
                "message": "E2B sandbox is paused",
                "complete": False,
                "error": False,
            }
        else:
            return {
                "stage": "e2b_destroyed",
                "progress": 100,
                "message": "E2B sandbox is no longer available",
                "complete": True,
                "error": True,
                "error_message": "Sandbox terminated",
            }

    async def list_active(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._api_url}/sandboxes",
                headers=self._headers(),
                params={"metadata": "joysafeter=true"},
            )
            if resp.status_code >= 400:
                logger.warning("E2B list_active failed: %s", resp.text)
                return []
            sandboxes = resp.json()

        return [
            {
                "id": s["sandboxId"],
                "provider": "e2b",
                "status": self._map_state(s.get("state", "unknown")),
            }
            for s in sandboxes
            if self._map_state(s.get("state", "unknown")) in ("running", "creating")
        ]
