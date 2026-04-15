"""
CLI container lifecycle management via Docker.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class ContainerConfig:
    image: str = "joysafeter/cli-agent:latest"
    memory_limit: str = "2g"
    cpu_quota: int = 200000
    network_mode: str = "bridge"
    working_dir: str = "/workspace"
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ContainerInfo:
    container_id: str
    name: str
    status: str
    working_dir: str


class CLIContainerService:
    """Manages Docker container lifecycle for CLI agent executions."""

    def __init__(self, default_config: Optional[ContainerConfig] = None):
        self.default_config = default_config or ContainerConfig()

    async def create_container(
        self,
        *,
        execution_id: uuid.UUID,
        config: Optional[ContainerConfig] = None,
        env: Optional[dict[str, str]] = None,
    ) -> ContainerInfo:
        cfg = config or self.default_config
        name = f"cli-agent-{execution_id!s:.12}"

        docker_cmd = [
            "docker", "create",
            "--name", name,
            "-w", cfg.working_dir,
            f"--memory={cfg.memory_limit}",
            f"--cpu-quota={cfg.cpu_quota}",
            f"--network={cfg.network_mode}",
        ]
        for k, v in cfg.labels.items():
            docker_cmd.extend(["--label", f"{k}={v}"])
        docker_cmd.extend(["--label", f"execution_id={execution_id}"])

        env_file_path: Optional[str] = None
        if env:
            env_file_path = self._write_env_file(env)
            docker_cmd.extend(["--env-file", env_file_path])

        docker_cmd.append(cfg.image)
        docker_cmd.append("sleep")
        docker_cmd.append("infinity")

        try:
            container_id = await self._run_docker(docker_cmd)
            container_id = container_id.strip()
        finally:
            if env_file_path:
                try:
                    os.unlink(env_file_path)
                except OSError:
                    pass

        await self._run_docker(["docker", "start", container_id])

        logger.info(f"Created container {container_id[:12]} for execution {execution_id}")
        return ContainerInfo(
            container_id=container_id,
            name=name,
            status="running",
            working_dir=cfg.working_dir,
        )

    @staticmethod
    def _write_env_file(env: dict[str, str]) -> str:
        """Write env vars to a temp file (mode 0600) and return its path."""
        fd, path = tempfile.mkstemp(prefix="cli_agent_env_", suffix=".env")
        try:
            with os.fdopen(fd, "w") as f:
                for k, v in env.items():
                    f.write(f"{k}={v}\n")
            os.chmod(path, 0o600)
        except Exception:
            os.unlink(path)
            raise
        return path

    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        try:
            await self._run_docker(
                ["docker", "stop", "-t", str(timeout), container_id]
            )
            logger.info(f"Stopped container {container_id[:12]}")
        except RuntimeError as exc:
            logger.warning(f"Failed to stop container {container_id[:12]}: {exc}")

    async def remove_container(self, container_id: str, force: bool = True) -> None:
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(container_id)
        try:
            await self._run_docker(cmd)
            logger.info(f"Removed container {container_id[:12]}")
        except RuntimeError as exc:
            logger.warning(f"Failed to remove container {container_id[:12]}: {exc}")

    async def copy_to_container(
        self, container_id: str, src_path: str, dest_path: str
    ) -> None:
        await self._run_docker(
            ["docker", "cp", src_path, f"{container_id}:{dest_path}"]
        )

    async def exec_in_container(
        self, container_id: str, cmd: list[str], workdir: Optional[str] = None
    ) -> str:
        docker_cmd = ["docker", "exec"]
        if workdir:
            docker_cmd.extend(["-w", workdir])
        docker_cmd.append(container_id)
        docker_cmd.extend(cmd)
        return await self._run_docker(docker_cmd)

    async def inspect_container(self, container_id: str) -> str:
        return await self._run_docker(
            ["docker", "inspect", "--format", "{{.State.Status}}", container_id]
        )

    async def _run_docker(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Docker command failed (exit {proc.returncode}): {stderr.decode()[:1000]}"
            )
        return stdout.decode()
