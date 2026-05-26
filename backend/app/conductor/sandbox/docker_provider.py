import asyncio
import json
import logging
import uuid
from typing import Any, Optional

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
        cmd = [
            "docker", "create",
            "--name", container_name,
            "--add-host", "host.docker.internal:host-gateway",
        ]

        if work_dir:
            cmd.extend(["-w", "/workspace"])
            cmd.extend(["-v", f"{work_dir}:/workspace"])

        env = dict(env)

        sandbox_id = (labels or {}).get("conductor.sandbox_id", name)

        net_type = None
        if networking:
            net_type = networking.get("type") or networking.get("net_type")

        if net_type == "limited":
            cmd.extend(["--network", "none"])
            socket_vol = self._socket_volume or "conductor-sockets"
            cmd.extend(["-v", f"{socket_vol}:/sockets:ro"])
            env["CONDUCTOR_ORCHESTRATOR_URL"] = f"unix:///sockets/{sandbox_id}/grpc.sock"
        else:
            if self._network:
                cmd.extend(["--network", self._network])
            if "CONDUCTOR_ORCHESTRATOR_URL" not in env:
                env["CONDUCTOR_ORCHESTRATOR_URL"] = (
                    f"http://host.docker.internal:{conductor_config.grpc_port}"
                )

        for mount in memory_mounts or []:
            host_path = mount.get("host_path", "")
            mount_name = mount.get("name", "default")
            access = mount.get("access", "read_write")
            ro_flag = ":ro" if access == "read_only" else ""
            target = f"/mnt/memory/{mount_name}"
            cmd.extend(["-v", f"{host_path}:{target}{ro_flag}"])

        if cpu is not None:
            cmd.extend(["--cpus", str(cpu)])
        if memory_mb is not None:
            cmd.extend(["--memory", f"{memory_mb}m"])

        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])

        all_labels = {"conductor": "true"}
        if labels:
            all_labels.update(labels)
        for k, v in all_labels.items():
            cmd.extend(["--label", f"{k}={v}"])

        cmd.append(image)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker create failed: {stderr.decode()}")

        await self._start_container(container_name)
        return container_name

    async def _start_container(self, external_id: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "start", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("docker start failed for %s, rolling back container", external_id)
            await self.destroy(external_id)
            raise RuntimeError(f"docker start failed: {stderr.decode()}")

    async def start(self, external_id: str) -> None:
        await self._start_container(external_id)

    async def stop(self, external_id: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "stop", "-t", "10", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = stderr.decode()
            if "No such container" in msg or "304" in msg or "not running" in msg:
                return
            raise RuntimeError(f"docker stop failed: {msg}")

    async def destroy(self, external_id: str) -> None:
        stop_proc = await asyncio.create_subprocess_exec(
            "docker", "stop", "-t", "10", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await stop_proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker rm failed: {stderr.decode()}")

    async def status(self, external_id: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return "unknown"
        return stdout.decode().strip()

    async def exec(
        self, external_id: str, cmd: list[str], env: Optional[dict[str, str]] = None
    ) -> tuple[int, str, str]:
        docker_cmd = ["docker", "exec"]
        for k, v in (env or {}).items():
            docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append(external_id)
        docker_cmd.extend(cmd)

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def list_active(self) -> list[dict]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-a",
            "--filter", "label=conductor=true",
            "--filter", "status=running",
            "--filter", "status=exited",
            "--format", "{{json .}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        results = []
        for line in stdout.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                results.append({
                    "id": data.get("ID", ""),
                    "name": data.get("Names", ""),
                    "status": data.get("State", data.get("Status", "")),
                    "image": data.get("Image", ""),
                })
            except json.JSONDecodeError:
                continue
        return results

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{json .State}}", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return {"stage": "provider_failed", "progress": 0, "message": "Container not found", "complete": False, "error": True}
        try:
            state = json.loads(stdout.decode().strip())
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
        except json.JSONDecodeError:
            return {"stage": "provider_failed", "progress": 0, "message": "Failed to parse state", "complete": False, "error": True}

    async def setup_networking(self, sandbox_id: uuid.UUID, networking: dict) -> None:
        net_type = networking.get("type") or networking.get("net_type")
        if net_type == "limited" and self._envoy_manager:
            await self._envoy_manager.setup_for_sandbox(sandbox_id, networking)
        elif net_type == "limited" and not self._envoy_manager:
            logger.warning("Limited networking requested but no envoy manager configured")

    async def teardown_networking(self, sandbox_id: uuid.UUID) -> None:
        if self._envoy_manager:
            await self._envoy_manager.teardown_for_sandbox(sandbox_id)
