"""
OpenClaw Instance Service — per-user Docker container lifecycle management.

Each user gets a dedicated OpenClaw container with an isolated gateway port
and authentication token. The service handles creation, start/stop, health
checking, and port allocation.
"""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import tarfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import docker
import httpx
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.openclaw_instance import OpenClawInstance
from app.services.base import BaseService

OPENCLAW_IMAGE = os.environ.get("OPENCLAW_IMAGE", "jdopensource/joysafeter-openclaw:latest")
OPENCLAW_NETWORK = os.environ.get("OPENCLAW_NETWORK", "joysafeter-network")
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
            logger.debug("Failed to read /proc/1/cgroup for Docker detection", exc_info=True)
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
            container_id = await self._create_container(instance, recreate=False)
            await self._update_status(instance.id, "starting", container_id=container_id)

            # Sync skills into the OpenClaw container
            await self.sync_skills_to_container(user_id, container_id)

            await self._wait_for_gateway(instance)
            await self._update_status(instance.id, "running", container_id=container_id)
            await self.db.refresh(instance)
            return instance
        except Exception as e:
            logger.error(f"Failed to start OpenClaw instance for user {user_id}: {e}")
            await self._update_status(instance.id, "failed", error_message=str(e))
            await self.db.refresh(instance)
            raise RuntimeError(f"Failed to start OpenClaw instance: {e}")

    async def _create_container(self, instance: OpenClawInstance, recreate: bool = False) -> str:
        """Create and start a Docker container for the instance, or start an existing one."""
        container_name = f"openclaw-user-{instance.user_id[:12]}"
        logger.info(
            f"_create_container called: recreate={recreate}, "
            f"container_id={instance.container_id}, container_name={container_name}, "
            f"instance_status={instance.status}"
        )

        try:
            client = docker.from_env()
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Docker daemon: {e}")

        # Try to find and start existing container
        if not recreate:
            try:
                # Try by instance.container_id first
                if instance.container_id:
                    logger.info(f"Trying to get container by ID: {instance.container_id}")
                    container = client.containers.get(instance.container_id)
                else:
                    logger.info(f"No container_id, trying by name: {container_name}")
                    container = client.containers.get(container_name)

                logger.info(
                    f"Found existing container: id={container.id[:12]}, "
                    f"status={container.status}, name={container.name}"
                )

                if container.status != "running":
                    logger.info(f"Container not running (status={container.status}), calling start()...")
                    await asyncio.to_thread(container.start)
                    logger.info("container.start() completed successfully")

                logger.info(f"Re-started existing OpenClaw container {container.id[:12]} for user {instance.user_id}")
                return str(container.id)[:12]
            except docker.errors.NotFound as e:
                # Fall through to create new if not found
                logger.warning(f"Container NOT FOUND (NotFound): {e}")
                pass
            except Exception as e:
                logger.warning(f"Failed to reuse existing container (exception type={type(e).__name__}): {e}")
        else:
            logger.info("recreate=True, skipping reuse attempt")

        logger.info("Proceeding to CREATE NEW container (reuse failed or recreate=True)")

        # Stop and remove existing container if any (for recreate or if reuse failed)
        if instance.container_id:
            try:
                container = client.containers.get(instance.container_id)
                container.remove(force=True)
                logger.info(f"Removed old container by ID: {instance.container_id}")
            except docker.errors.NotFound:
                logger.info(f"Old container by ID not found for removal: {instance.container_id}")
                pass
            except Exception as e:
                logger.warning(f"Failed to remove container {instance.container_id}: {e}")

        # Also try to remove by name
        try:
            container = client.containers.get(container_name)
            container.remove(force=True)
            logger.info(f"Removed old container by name: {container_name}")
        except docker.errors.NotFound:
            logger.info(f"Old container by name not found for removal: {container_name}")
            pass
        except Exception as e:
            logger.warning(f"Failed to remove container {container_name}: {e}")

        env_vars = {
            "OPENCLAW_GATEWAY_TOKEN": instance.gateway_token,
        }

        # Pass through AI provider keys from host environment
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "AI_GATEWAY_BASE_URL",
            "AI_GATEWAY_API_KEY",
            "AI_GATEWAY_PROVIDER",
            "AI_GATEWAY_MODEL",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_MODEL",
        ):
            val = os.environ.get(key)
            if val:
                env_vars[key] = val

        # Validate required AI Gateway variables (either AI_GATEWAY or ANTHROPIC variants)
        has_ai_gw = all(k in env_vars for k in ("AI_GATEWAY_BASE_URL", "AI_GATEWAY_API_KEY", "AI_GATEWAY_MODEL"))
        has_anthropic = all(k in env_vars for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"))

        if not (has_ai_gw or has_anthropic):
            raise ValueError("Missing required environment variables for AI Gateway (need AI_GATEWAY_* or ANTHROPIC_*)")

        # Also pass config overrides
        if instance.config_json:
            for k, v in instance.config_json.items():
                env_vars[k] = str(v)

        # Check if the network exists
        network_name = None
        candidates = [OPENCLAW_NETWORK, f"deploy_{OPENCLAW_NETWORK}"]
        for cand in candidates:
            try:
                client.networks.get(cand)
                network_name = cand
                break
            except docker.errors.NotFound:
                pass

        if not network_name:
            logger.warning(
                f"Could not find Docker network {OPENCLAW_NETWORK} or deploy_{OPENCLAW_NETWORK}. Defaulting to None (bridge network)."
            )

        try:
            # We must use a separate thread or asyncio.to_thread for blocking docker operations
            container = await asyncio.to_thread(
                client.containers.run,
                OPENCLAW_IMAGE,
                detach=True,
                name=container_name,
                ports={"18789/tcp": instance.gateway_port},
                environment=env_vars,
                network=network_name,
                restart_policy={"Name": "unless-stopped"},
            )
        except Exception as e:
            raise RuntimeError(f"docker run failed: {str(e)}")

        container_id = str(container.id)[:12]
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
                logger.debug("Failed to poll OpenClaw gateway readiness on port %s", instance.gateway_port, exc_info=True)
            await asyncio.sleep(GATEWAY_READY_POLL_INTERVAL)

        # Last resort: check if container is still running
        try:
            client = docker.from_env()
            container = await asyncio.to_thread(client.containers.get, instance.container_id)
            if container.status != "running":
                logs = await asyncio.to_thread(container.logs, tail=30)
                logs_str = logs.decode("utf-8") if isinstance(logs, bytes) else str(logs)
                raise RuntimeError(f"Container died during startup. Logs:\n{logs_str}")
        except docker.errors.NotFound:
            raise RuntimeError("Container was removed during startup.")
        except Exception as e:
            logger.warning(f"Failed to check container status: {e}")

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
            try:
                client = docker.from_env()
                container = await asyncio.to_thread(client.containers.get, instance.container_id)
                await asyncio.to_thread(container.stop, timeout=10)
            except docker.errors.NotFound:
                pass
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
            try:
                client = docker.from_env()
                container = await asyncio.to_thread(client.containers.get, instance.container_id)
                await asyncio.to_thread(container.remove, force=True)
            except docker.errors.NotFound:
                pass
            except Exception as e:
                logger.warning(f"Failed to remove container {instance.container_id}: {e}")

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

        instance = await self.get_instance_by_user(user_id)
        if not instance or instance.status != "running" or not instance.container_id:
            return False

        try:
            client = docker.from_env()
            container = await asyncio.to_thread(client.containers.get, instance.container_id)

            # List devices
            exit_code, output = await asyncio.to_thread(
                container.exec_run, cmd=["openclaw", "devices", "list", "--json"]
            )

            if exit_code != 0:
                logger.warning(
                    f"Failed to list OpenClaw devices: {output.decode('utf-8') if isinstance(output, bytes) else output}"
                )
                return False

            output_str = output.decode("utf-8") if isinstance(output, bytes) else output
            devices = json.loads(output_str) if output_str else {}
            pending = devices.get("pending", [])

            success_all = True
            for p in pending:
                device_id = p.get("deviceId")
                if device_id:
                    approve_exit_code, _ = await asyncio.to_thread(
                        container.exec_run, cmd=["openclaw", "devices", "approve", device_id]
                    )
                    if approve_exit_code != 0:
                        success_all = False
            return success_all
        except docker.errors.NotFound:
            return False
        except Exception as e:
            logger.warning(f"approve_all_pending_devices failed for user {user_id}: {e}")
            return False

    async def sync_skills_to_container(self, user_id: str, container_id: str) -> int:
        """Push the user's active skills to the OpenClaw container's /workspace/skills directory.
        Returns the number of skills synced, or -1 on failure.
        """
        from app.services.skill_service import SkillService
        from app.utils.path_utils import sanitize_skill_name

        try:
            skill_service = SkillService(self.db)
            skills = await skill_service.list_skills(current_user_id=user_id, include_public=True)
            if not skills:
                # Still create the directory even if there are no skills
                try:
                    client = docker.from_env()
                    container = await asyncio.to_thread(client.containers.get, container_id)
                    await asyncio.to_thread(container.exec_run, cmd=["mkdir", "-p", "/workspace/skills"])
                except Exception:
                    logger.debug("Failed to create /workspace/skills directory in container %s", container_id, exc_info=True)
                return 0

            client = docker.from_env()
            container = await asyncio.to_thread(client.containers.get, container_id)

            # Ensure the skills directory exists
            await asyncio.to_thread(container.exec_run, cmd=["mkdir", "-p", "/workspace/skills"])

            tar_stream = io.BytesIO()
            synced_count = 0
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                for skill in skills:
                    # Get full skill with its files relationship
                    full_skill = await skill_service.get_skill(skill.id, current_user_id=user_id)
                    if not full_skill or not full_skill.files:
                        continue

                    folder_name = sanitize_skill_name(full_skill.name)

                    for skill_file in full_skill.files:
                        if skill_file.content is None:
                            continue

                        file_content = (
                            skill_file.content.encode("utf-8")
                            if isinstance(skill_file.content, str)
                            else skill_file.content
                        )
                        file_path = f"{folder_name}/{skill_file.path}"

                        tarinfo = tarfile.TarInfo(name=file_path)
                        tarinfo.size = len(file_content)
                        tarinfo.mode = 0o644

                        tar.addfile(tarinfo, io.BytesIO(file_content))

                    synced_count += 1

            tar_stream.seek(0)

            success = await asyncio.to_thread(container.put_archive, "/workspace/skills", tar_stream.read())
            logger.info(f"Synced {synced_count} skills to OpenClaw container {container_id} for user {user_id}")
            return synced_count if success else -1
        except docker.errors.NotFound:
            logger.warning(f"Container {container_id} not found when trying to sync skills")
            return -1
        except Exception as e:
            logger.error(f"Failed to sync skills to OpenClaw container {container_id}: {e}", exc_info=True)
            return -1

    async def delete_skill_from_container(self, user_id: str, container_id: str, skill_name: str) -> bool:
        """Delete a specific skill directory from the OpenClaw container."""
        from app.utils.path_utils import sanitize_skill_name

        try:
            folder_name = sanitize_skill_name(skill_name)
            client = docker.from_env()
            container = await asyncio.to_thread(client.containers.get, container_id)

            # Execute rm -rf directly in the container
            exit_code, _ = await asyncio.to_thread(
                container.exec_run, cmd=["rm", "-rf", f"/workspace/skills/{folder_name}"]
            )

            if exit_code == 0:
                logger.info(f"Deleted skill {skill_name} from OpenClaw container {container_id} for user {user_id}")
                return True
            else:
                logger.warning(
                    f"Failed to delete skill {skill_name} from container {container_id}, exit code {exit_code}"
                )
                return False
        except docker.errors.NotFound:
            logger.warning(f"Container {container_id} not found when trying to delete skill {skill_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_name} from container {container_id}: {e}", exc_info=True)
            return False
