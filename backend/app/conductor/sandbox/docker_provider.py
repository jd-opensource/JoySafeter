import json
import logging
import uuid
from typing import Any, Optional

import aiodocker

from app.conductor.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)


class DockerSandboxProvider(SandboxProvider):
    def __init__(
        self,
        network: Optional[str] = None,
        socket_volume: Optional[str] = None,
        envoy_manager: Any = None,
    ):
        self._network = network
        self._socket_volume = socket_volume
        self._envoy_manager = envoy_manager
        self._docker = aiodocker.Docker()

    async def close(self) -> None:
        await self._docker.close()

    def provider_name(self) -> str:
        return "docker"

    async def create(
        self,
        name: str,
        image: str,
        env: dict[str, str],
        work_dir: str,
        labels: Optional[dict[str, str]] = None,
        *,
        networking: Optional[dict] = None,
        memory_mounts: Optional[list[dict]] = None,
        cpu: Optional[float] = None,
        memory_mb: Optional[int] = None,
        **kwargs,
    ) -> str:
        from app.conductor.config import conductor_config

        container_name = f"conductor-{name}"
        env = dict(env)
        sandbox_id = (labels or {}).get("conductor.sandbox_id", name)

        net_type = None
        if networking:
            net_type = networking.get("type") or networking.get("net_type")

        network_mode = None
        if net_type == "limited":
            network_mode = "none"
            socket_vol = self._socket_volume or "conductor-sockets"
            env["CONDUCTOR_ORCHESTRATOR_URL"] = f"unix:///sockets/{sandbox_id}/grpc.sock"
        else:
            if self._network:
                network_mode = self._network
            if "CONDUCTOR_ORCHESTRATOR_URL" not in env:
                env["CONDUCTOR_ORCHESTRATOR_URL"] = (
                    f"http://host.docker.internal:{conductor_config.grpc_port}"
                )

        binds: list[str] = []
        if work_dir:
            binds.append(f"{work_dir}:/workspace")

        if net_type == "limited":
            socket_vol = self._socket_volume or "conductor-sockets"
            binds.append(f"{socket_vol}:/sockets:ro")

        for mount in memory_mounts or []:
            host_path = mount.get("host_path", "")
            mount_name = mount.get("name", "default")
            access = mount.get("access", "read_write")
            ro_flag = ":ro" if access == "read_only" else ""
            target = f"/mnt/memory/{mount_name}"
            binds.append(f"{host_path}:{target}{ro_flag}")

        all_labels = {"conductor": "true"}
        if labels:
            all_labels.update(labels)

        host_config: dict[str, Any] = {
            "Binds": binds or None,
            "ExtraHosts": ["host.docker.internal:host-gateway"],
        }
        if network_mode:
            host_config["NetworkMode"] = network_mode
        if cpu is not None:
            host_config["NanoCpus"] = int(cpu * 1e9)
        if memory_mb is not None:
            host_config["Memory"] = memory_mb * 1024 * 1024

        config: dict[str, Any] = {
            "Image": image,
            "Env": [f"{k}={v}" for k, v in env.items()],
            "Labels": all_labels,
            "HostConfig": host_config,
        }
        if work_dir:
            config["WorkingDir"] = "/workspace"

        try:
            container = await self._docker.containers.create_or_replace(
                name=container_name, config=config,
            )
        except aiodocker.exceptions.DockerError as e:
            raise RuntimeError(f"docker create failed: {e.message}") from e

        try:
            await container.start()
        except aiodocker.exceptions.DockerError as e:
            try:
                await container.delete(force=True)
            except Exception:
                pass
            raise RuntimeError(f"docker start failed: {e.message}") from e

        return container_name

    async def _start_container(self, external_id: str) -> None:
        try:
            container = await self._docker.containers.get(external_id)
            await container.start()
        except aiodocker.exceptions.DockerError as e:
            raise RuntimeError(f"docker start failed: {e.message}") from e

    async def start(self, external_id: str) -> None:
        await self._start_container(external_id)

    async def stop(self, external_id: str) -> None:
        try:
            container = await self._docker.containers.get(external_id)
            await container.stop(t=10)
        except aiodocker.exceptions.DockerError as e:
            msg = e.message
            if "No such container" in msg or "304" in msg or "not running" in msg:
                return
            raise RuntimeError(f"docker stop failed: {msg}") from e

    async def destroy(self, external_id: str) -> None:
        try:
            container = await self._docker.containers.get(external_id)
            await container.stop(t=10)
        except Exception:
            pass
        try:
            container = await self._docker.containers.get(external_id)
            await container.delete(force=True)
        except aiodocker.exceptions.DockerError as e:
            if "No such container" not in e.message:
                raise RuntimeError(f"docker rm failed: {e.message}") from e

    async def status(self, external_id: str) -> str:
        try:
            container = await self._docker.containers.get(external_id)
            info = await container.show()
            return info.get("State", {}).get("Status", "unknown")
        except Exception:
            return "unknown"

    async def exec(
        self, external_id: str, cmd: list[str], env: Optional[dict[str, str]] = None
    ) -> tuple[int, str, str]:
        try:
            container = await self._docker.containers.get(external_id)
            exec_config: dict[str, Any] = {
                "AttachStdout": True,
                "AttachStderr": True,
                "Cmd": cmd,
            }
            if env:
                exec_config["Env"] = [f"{k}={v}" for k, v in env.items()]

            exec_instance = await container.exec(exec_config)
            resp = await exec_instance.start()
            output = await resp.read_out()

            stdout_parts = []
            stderr_parts = []
            while output:
                if output.stream == 1:
                    stdout_parts.append(output.data.decode())
                elif output.stream == 2:
                    stderr_parts.append(output.data.decode())
                output = await resp.read_out()

            inspect = await exec_instance.inspect()
            exit_code = inspect.get("ExitCode", 1)
            return exit_code, "".join(stdout_parts), "".join(stderr_parts)
        except aiodocker.exceptions.DockerError as e:
            return 1, "", f"exec failed: {e.message}"

    async def list_active(self) -> list[dict]:
        try:
            containers = await self._docker.containers.list(
                all=True,
                filters=json.dumps({
                    "label": ["conductor=true"],
                    "status": ["running", "exited"],
                }),
            )
            results = []
            for c in containers:
                info = c._container
                names = info.get("Names", [])
                name = names[0].lstrip("/") if names else ""
                results.append({
                    "id": info.get("Id", ""),
                    "name": name,
                    "status": info.get("State", ""),
                    "image": info.get("Image", ""),
                })
            return results
        except Exception:
            return []

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        try:
            container = await self._docker.containers.get(external_id)
            info = await container.show()
        except Exception:
            return {
                "stage": "provider_failed", "progress": 0,
                "message": "Container not found",
                "complete": False, "error": True,
            }

        state = info.get("State", {})
        docker_status = state.get("Status", "unknown").lower()
        running = state.get("Running", False)
        restarting = state.get("Restarting", False)
        exit_code = state.get("ExitCode", 0)
        error_str = state.get("Error", "")

        if running:
            return {
                "stage": "runtime_booting", "progress": 90,
                "message": "Container is running, waiting for runner ready",
                "complete": True, "error": False,
            }
        elif restarting or "created" in docker_status or "starting" in docker_status:
            return {
                "stage": "container_starting", "progress": 60,
                "message": "Container is starting",
                "complete": False, "error": False,
            }
        elif "exited" in docker_status or "dead" in docker_status:
            msg = error_str if error_str else f"Container exited with code {exit_code}"
            return {
                "stage": "provider_failed", "progress": 100,
                "message": "Container exited before runtime ready",
                "complete": True, "error": True, "error_message": msg,
            }
        else:
            return {
                "stage": "provider_pending", "progress": 40,
                "message": f"Provider state: {docker_status}",
                "complete": False, "error": False,
            }

    async def setup_networking(self, sandbox_id: uuid.UUID, networking: dict) -> None:
        net_type = networking.get("type") or networking.get("net_type")
        if net_type == "limited" and self._envoy_manager:
            await self._envoy_manager.setup_for_sandbox(sandbox_id, networking)
        elif net_type == "limited" and not self._envoy_manager:
            logger.warning("Limited networking requested but no envoy manager configured")

    async def teardown_networking(self, sandbox_id: uuid.UUID) -> None:
        if self._envoy_manager:
            await self._envoy_manager.teardown_for_sandbox(sandbox_id)
