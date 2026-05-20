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
            "-w", "/workspace",
            "-v", f"{work_dir}:/workspace",
        ]

        env = dict(env)

        net_type = None
        if networking:
            net_type = networking.get("type") or networking.get("net_type")

        if net_type == "limited":
            cmd.extend(["--network", "none"])
            if self._socket_volume:
                cmd.extend(["-v", f"{self._socket_volume}:/tmp/conductor-sockets:ro"])
            env["CONDUCTOR_ORCHESTRATOR_URL"] = "unix:///tmp/conductor-sockets/grpc.sock"
        else:
            if self._network:
                cmd.extend(["--network", self._network])
            if "CONDUCTOR_ORCHESTRATOR_URL" not in env:
                env["CONDUCTOR_ORCHESTRATOR_URL"] = (
                    f"http://host.docker.internal:{conductor_config.grpc_port}"
                )

        sandbox_id = (labels or {}).get("conductor.sandbox_id", name)
        env.setdefault("CONDUCTOR_SANDBOX_ID", sandbox_id)

        for mount in memory_mounts or []:
            host_path = mount.get("host_path", "")
            mount_name = mount.get("name", "default")
            read_only = mount.get("read_only", False)
            target = f"/mnt/memory/{mount_name}"
            vol = f"{host_path}:{target}"
            if read_only:
                vol += ":ro"
            cmd.extend(["-v", vol])

        if cpu is not None:
            cmd.extend(["--cpus", str(cpu)])
        if memory_mb is not None:
            cmd.extend(["--memory", f"{memory_mb}m"])

        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])

        all_labels = {"conductor.managed": "true"}
        if labels:
            all_labels.update(labels)
        for k, v in all_labels.items():
            cmd.extend(["--label", f"{k}={v}"])

        cmd.append(image)
        cmd.extend(["sleep", "infinity"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker create failed: {stderr.decode()}")
        return container_name

    async def start(self, external_id: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "start", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker start failed: {stderr.decode()}")

    async def stop(self, external_id: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "stop", "-t", "10", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def destroy(self, external_id: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", external_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

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
            "--filter", "label=conductor.managed=true",
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
            return {"stage": "unknown", "progress": 0, "message": "Container not found", "complete": False, "error": True}
        try:
            state = json.loads(stdout.decode().strip())
            docker_status = state.get("Status", "unknown")
            running = state.get("Running", False)
            error_msg = state.get("Error", "")
            if running:
                return {"stage": "running", "progress": 100, "message": "Container running", "complete": True, "error": False}
            if error_msg:
                return {"stage": "error", "progress": 0, "message": error_msg, "complete": False, "error": True}
            return {"stage": docker_status, "progress": 50, "message": f"Container {docker_status}", "complete": False, "error": False}
        except json.JSONDecodeError:
            return {"stage": "unknown", "progress": 0, "message": "Failed to parse state", "complete": False, "error": True}

    async def setup_networking(self, sandbox_id: uuid.UUID, networking: dict) -> None:
        net_type = networking.get("type") or networking.get("net_type")
        if net_type == "limited" and self._envoy_manager:
            await self._envoy_manager.setup_for_sandbox(sandbox_id, networking)
        elif net_type == "limited" and not self._envoy_manager:
            logger.warning("Limited networking requested but no envoy manager configured")

    async def teardown_networking(self, sandbox_id: uuid.UUID) -> None:
        if self._envoy_manager:
            await self._envoy_manager.teardown_for_sandbox(sandbox_id)
