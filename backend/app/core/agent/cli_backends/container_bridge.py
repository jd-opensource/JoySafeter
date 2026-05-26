from __future__ import annotations

import asyncio

from loguru import logger


class ContainerProcessBridge:
    async def exec_streaming(
        self,
        container_id: str,
        cmd: list[str],
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        docker_cmd = ["docker", "exec", "-i"]
        if workdir:
            docker_cmd.extend(["-w", workdir])
        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])
        docker_cmd.append(container_id)
        docker_cmd.extend(cmd)

        logger.debug(f"container exec: {' '.join(docker_cmd[:6])}...")

        return await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
