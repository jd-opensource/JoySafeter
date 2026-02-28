"""
OpenClaw Instance Service — per-user Docker container lifecycle management.

Each user gets a dedicated OpenClaw container with an isolated gateway port
and authentication token. The service handles creation, start/stop, health
checking, and port allocation.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.openclaw_instance import OpenClawInstance
from app.services.base import BaseService

OPENCLAW_IMAGE = "joysafeter-openclaw:latest"
OPENCLAW_NETWORK = "joysafeter-network"
PORT_RANGE_START = 19001
PORT_RANGE_END = 19999
GATEWAY_READY_TIMEOUT = 300
GATEWAY_READY_POLL_INTERVAL = 2


class OpenClawInstanceService(BaseService[OpenClawInstance]):
    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_instance_by_user(self, user_id: str) -> Optional[OpenClawInstance]:
        result = await self.db.execute(select(OpenClawInstance).where(OpenClawInstance.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_instance(self, instance_id: str) -> Optional[OpenClawInstance]:
        result = await self.db.execute(select(OpenClawInstance).where(OpenClawInstance.id == instance_id))
        return result.scalar_one_or_none()

    def _is_running_in_docker(self) -> bool:
        """Check if the current process is running inside a Docker container."""
        # Check for the .dockerenv file which is present in most standard Docker containers
        if os.path.exists("/.dockerenv"):
            return True
        # Also check cgroup for docker entries (more robust but sometimes restricted)
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
                content = f.read()
                if "docker" in content or "kubepods" in content:
                    return True
        except Exception:
            pass
        return False

    def get_gateway_url(self, instance: OpenClawInstance) -> str:
        """Get the URL to communicate with the OpenClaw container instance.

        If we are running inside docker (on the same network), we use the internal
        container name and port 18789. Otherwise (local dev), we use 127.0.0.1
        and the mapped host port.
        """
        if self._is_running_in_docker() and instance.container_id:
            # We assume the backend is on the same network (e.g., joysafeter-network)
            # The internal port of the OpenClaw service is always 18789
            container_name = f"openclaw-user-{instance.user_id[:12]}"
            return f"http://{container_name}:18789"
        else:
            # Running locally on host
            return f"http://127.0.0.1:{instance.gateway_port}"

    async def _allocate_port(self) -> int:
        """Find the next available port in the range."""
        result = await self.db.execute(select(func.max(OpenClawInstance.gateway_port)))
        max_port = result.scalar_one_or_none()
        if max_port is None or max_port < PORT_RANGE_START:
            return PORT_RANGE_START
        next_port = max_port + 1
        if next_port > PORT_RANGE_END:
            result = await self.db.execute(
                select(OpenClawInstance.gateway_port).order_by(OpenClawInstance.gateway_port)
            )
            used_ports = {row[0] for row in result.all()}
            for p in range(PORT_RANGE_START, PORT_RANGE_END + 1):
                if p not in used_ports:
                    return p
            raise RuntimeError("No available ports for OpenClaw instances")
        return next_port

    async def ensure_instance_running(self, user_id: str) -> OpenClawInstance:
        """Get or create + start the user's OpenClaw container."""
        instance = await self.get_instance_by_user(user_id)

        if instance and instance.status == "running":
            ok = await self._health_check(instance)
            if ok:
                instance.last_active_at = datetime.now(timezone.utc)
                await self.db.commit()
                return instance
            instance.status = "failed"
            instance.error_message = "Health check failed, restarting"
            await self.db.commit()

        if not instance:
            port = await self._allocate_port()
            token = secrets.token_urlsafe(32)
            instance = OpenClawInstance(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=f"openclaw-{user_id[:8]}",
                status="pending",
                gateway_port=port,
                gateway_token=token,
            )
            self.db.add(instance)
            await self.db.commit()
            await self.db.refresh(instance)

        try:
            await self._update_status(instance.id, "starting")
            container_id = await self._create_container(instance)
            await self._update_status(instance.id, "starting", container_id=container_id)
            await self._wait_for_gateway(instance)
            await self._update_status(instance.id, "running", container_id=container_id)
            await self.db.refresh(instance)
            return instance
        except Exception as e:
            logger.error(f"Failed to start OpenClaw instance for user {user_id}: {e}")
            await self._update_status(instance.id, "failed", error_message=str(e))
            await self.db.refresh(instance)
            raise RuntimeError(f"Failed to start OpenClaw instance: {e}")

    async def _create_container(self, instance: OpenClawInstance) -> str:
        """Create and start a Docker container for the instance."""
        import subprocess

        container_name = f"openclaw-user-{instance.user_id[:12]}"

        # Stop and remove existing container if any
        if instance.container_id:
            try:
                subprocess.run(["docker", "rm", "-f", instance.container_id], capture_output=True, timeout=15)
            except Exception:
                pass

        # Also try to remove by name
        try:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=15)
        except Exception:
            pass

        env_vars = {
            "OPENCLAW_GATEWAY_TOKEN": instance.gateway_token,
        }

        # Pass through AI provider keys from host environment
        import os

        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "AI_GATEWAY_BASE_URL",
            "AI_GATEWAY_API_KEY",
            "AI_GATEWAY_PROVIDER",
            "AI_GATEWAY_MODEL",
        ):
            val = os.environ.get(key)
            if val:
                env_vars[key] = val

        # Validate required AI Gateway variables
        for required_key in ("AI_GATEWAY_BASE_URL", "AI_GATEWAY_API_KEY", "AI_GATEWAY_MODEL"):
            if required_key not in env_vars:
                raise ValueError(f"Missing required environment variable: {required_key}")

        # Also pass config overrides
        if instance.config_json:
            for k, v in instance.config_json.items():
                env_vars[k] = str(v)

        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{instance.gateway_port}:18789",
            "--restart",
            "unless-stopped",
        ]

        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])

        # Try to attach to the JoySafeter network
        try:
            result = subprocess.run(["docker", "network", "inspect", OPENCLAW_NETWORK], capture_output=True, timeout=10)
            if result.returncode == 0:
                cmd.extend(["--network", OPENCLAW_NETWORK])
        except Exception:
            pass

        cmd.append(OPENCLAW_IMAGE)

        run_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if run_result.returncode != 0:
            raise RuntimeError(f"docker run failed: {run_result.stderr.strip()}")

        container_id = run_result.stdout.strip()[:12]
        logger.info(
            f"Created OpenClaw container {container_id} for user {instance.user_id} on port {instance.gateway_port}"
        )
        return container_id

    async def _wait_for_gateway(self, instance: OpenClawInstance) -> None:
        """Poll the gateway until it responds to HTTP requests."""
        url = f"{self.get_gateway_url(instance)}/v1/chat/completions"
        deadline = asyncio.get_event_loop().time() + GATEWAY_READY_TIMEOUT

        while asyncio.get_event_loop().time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.options(url)
                    if resp.status_code < 500:
                        logger.info(f"OpenClaw gateway ready on port {instance.gateway_port}")
                        return
            except Exception:
                pass
            await asyncio.sleep(GATEWAY_READY_POLL_INTERVAL)

        # Last resort: check if container is still running
        import subprocess

        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", instance.container_id or ""],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout.strip() != "true":
            logs = subprocess.run(
                ["docker", "logs", "--tail", "30", instance.container_id or ""],
                capture_output=True,
                text=True,
                timeout=10,
            )
            raise RuntimeError(f"Container died during startup. Logs:\n{logs.stderr or logs.stdout}")

        raise RuntimeError(f"Gateway not ready within {GATEWAY_READY_TIMEOUT}s")

    async def _health_check(self, instance: OpenClawInstance) -> bool:
        """Quick health check via HTTP OPTIONS to the gateway."""
        try:
            url = f"{self.get_gateway_url(instance)}/v1/chat/completions"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.options(url)
                return resp.status_code < 500
        except Exception:
            return False

    async def stop_instance(self, user_id: str) -> Optional[OpenClawInstance]:
        instance = await self.get_instance_by_user(user_id)
        if not instance:
            return None

        if instance.container_id:
            import subprocess

            try:
                subprocess.run(["docker", "stop", instance.container_id], capture_output=True, timeout=30)
            except Exception as e:
                logger.warning(f"Failed to stop container {instance.container_id}: {e}")

        await self._update_status(instance.id, "stopped")
        await self.db.refresh(instance)
        return instance

    async def restart_instance(self, user_id: str) -> OpenClawInstance:
        await self.stop_instance(user_id)
        return await self.ensure_instance_running(user_id)

    async def delete_instance(self, user_id: str) -> bool:
        instance = await self.get_instance_by_user(user_id)
        if not instance:
            return False

        # Remove container
        if instance.container_id:
            import subprocess

            try:
                subprocess.run(["docker", "rm", "-f", instance.container_id], capture_output=True, timeout=15)
            except Exception:
                pass

        await self.db.delete(instance)
        await self.db.commit()
        return True

    async def get_instance_status(self, user_id: str) -> Dict[str, Any]:
        instance = await self.get_instance_by_user(user_id)
        if not instance:
            return {"exists": False, "status": None}

        alive = False
        if instance.status == "running":
            alive = await self._health_check(instance)
            if not alive:
                instance.status = "failed"
                instance.error_message = "Health check failed"
                await self.db.commit()

        return {
            "exists": True,
            "id": instance.id,
            "status": instance.status,
            "gatewayPort": instance.gateway_port,
            "gatewayToken": instance.gateway_token,
            "containerId": instance.container_id,
            "alive": alive,
            "lastActiveAt": instance.last_active_at.isoformat() if instance.last_active_at else None,
            "errorMessage": instance.error_message,
            "createdAt": instance.created_at.isoformat() if instance.created_at else None,
        }

    async def _update_status(
        self,
        instance_id: str,
        status: str,
        container_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        values: Dict[str, Any] = {
            "status": status,
            "last_active_at": datetime.now(timezone.utc),
        }
        if container_id is not None:
            values["container_id"] = container_id
        if error_message is not None:
            values["error_message"] = error_message
        elif status in ("running", "starting"):
            values["error_message"] = None

        await self.db.execute(update(OpenClawInstance).where(OpenClawInstance.id == instance_id).values(**values))
        await self.db.commit()

    async def approve_all_pending_devices(self, user_id: str) -> bool:
        """Approve all pending device pairing requests for the user's instance."""
        import json
        import subprocess

        instance = await self.get_instance_by_user(user_id)
        if not instance or instance.status != "running" or not instance.container_id:
            return False
        try:
            result = subprocess.run(
                ["docker", "exec", instance.container_id, "openclaw", "devices", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return False
            devices = json.loads(result.stdout) if result.stdout else {}
            pending = devices.get("pending", [])
            for p in pending:
                device_id = p.get("deviceId")
                if device_id:
                    subprocess.run(
                        ["docker", "exec", instance.container_id, "openclaw", "devices", "approve", device_id],
                        capture_output=True,
                        timeout=15,
                    )
            return True
        except Exception as e:
            logger.warning(f"approve_all_pending_devices failed for user {user_id}: {e}")
            return False
