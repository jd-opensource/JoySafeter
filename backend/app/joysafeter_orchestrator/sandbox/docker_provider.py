import asyncio
import json
import logging
import uuid
from typing import Any, Optional

import aiodocker

from app.joysafeter_orchestrator.sandbox.provider import SandboxProvider
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)


async def _retry_docker(
    coro_factory,
    *,
    operation: str,
    data: dict[str, object] | None = None,
    max_retries: int = 2,
    delay: float = 1.0,
):
    """Retry a Docker operation on transient errors (connection, 500, 503).
    Does NOT retry create() — only start/stop/destroy to avoid duplicates."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except (aiodocker.exceptions.DockerError, OSError, ConnectionError) as e:
            last_error = e
            err_msg = str(e)
            # Don't retry on 404 (Not Found) or 409 (Conflict)
            if "404" in err_msg or "No such container" in err_msg or "409" in err_msg:
                raise
            if attempt < max_retries:
                log_boundary_failure(
                    logger,
                    boundary="docker_provider",
                    code="DOCKER_OPERATION_RETRYING",
                    message="Docker operation failed, retrying",
                    operation=operation,
                    error=e,
                    data={
                        **(data or {}),
                        "attempt": attempt + 1,
                        "max_attempts": max_retries + 1,
                        "retry_delay_sec": delay,
                    },
                )
                await asyncio.sleep(delay)
            else:
                raise
    if last_error is not None:
        raise last_error  # unreachable, but satisfies type checker
    raise RuntimeError("Docker operation failed with no captured error")


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
        from app.joysafeter_shared.config.settings import joysafeter_config

        container_name = f"joysafeter-{name}"
        env = dict(env)
        sandbox_id = (labels or {}).get("joysafeter.sandbox_id", name)

        net_type = None
        if networking:
            net_type = networking.get("type") or networking.get("net_type")

        network_mode = None
        if net_type == "limited":
            network_mode = "none"
            socket_vol = self._socket_volume or "joysafeter-sockets"
            env["JOYSAFETER_ORCHESTRATOR_URL"] = f"unix:///sockets/{sandbox_id}/grpc.sock"
            env["JOYSAFETER_ORCHESTRATOR_URL"] = env["JOYSAFETER_ORCHESTRATOR_URL"]
        else:
            if self._network:
                network_mode = self._network
            if "JOYSAFETER_ORCHESTRATOR_URL" not in env:
                env["JOYSAFETER_ORCHESTRATOR_URL"] = f"http://host.docker.internal:{joysafeter_config.grpc_port}"
            env.setdefault("JOYSAFETER_ORCHESTRATOR_URL", env["JOYSAFETER_ORCHESTRATOR_URL"])

        binds: list[str] = []
        if work_dir:
            binds.append(f"{work_dir}:/workspace")

        if net_type == "limited":
            socket_vol = self._socket_volume or "joysafeter-sockets"
            binds.append(f"{socket_vol}:/sockets:ro")

        for mount in memory_mounts or []:
            host_path = mount.get("host_path", "")
            mount_name = mount.get("name", "default")
            access = mount.get("access", "read_write")
            ro_flag = ":ro" if access == "read_only" else ""
            target = f"/mnt/memory/{mount_name}"
            binds.append(f"{host_path}:{target}{ro_flag}")

        all_labels = {"joysafeter": "true"}
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

        # ---- P0.1 hardening (mirror of Rust orchestrator docker.rs) ---------
        # Drop the default-14 Linux capabilities, forbid privilege escalation,
        # cap PID count, and force the unprivileged uid:gid. Coding agents
        # don't need any of these capabilities — they run as the `agent`
        # user inside the container and only issue user-mode syscalls — so
        # these defaults are pure security upside with zero operational cost.
        # Disable individually via the matching JOYSAFETER_SANDBOX_* env vars
        # only when debugging a stuck capability.
        if joysafeter_config.sandbox_drop_all_caps:
            host_config["CapDrop"] = ["ALL"]
        sec_opts: list[str] = list(host_config.get("SecurityOpt") or [])
        if joysafeter_config.sandbox_no_new_privileges:
            sec_opts.append("no-new-privileges:true")
        if sec_opts:
            host_config["SecurityOpt"] = sec_opts
        if joysafeter_config.sandbox_pids_limit and joysafeter_config.sandbox_pids_limit > 0:
            host_config["PidsLimit"] = int(joysafeter_config.sandbox_pids_limit)

        config: dict[str, Any] = {
            "Image": image,
            "Env": [f"{k}={v}" for k, v in env.items()],
            "Labels": all_labels,
            "HostConfig": host_config,
        }
        if work_dir:
            config["WorkingDir"] = "/workspace"
        run_as_user = (joysafeter_config.sandbox_run_as_user or "").strip()
        if run_as_user:
            config["User"] = run_as_user

        try:
            container = await self._docker.containers.create_or_replace(
                name=container_name,
                config=config,
            )
        except aiodocker.exceptions.DockerError as e:
            raise RuntimeError(f"docker create failed: {e.message}") from e

        try:
            await container.start()
        except aiodocker.exceptions.DockerError as e:
            try:
                await container.delete(force=True)
            except Exception as cleanup_error:
                log_boundary_failure(
                    logger,
                    boundary="docker_provider",
                    code="DOCKER_CREATE_START_CLEANUP_FAILED",
                    message="Failed to delete container after Docker start failure",
                    operation="cleanup_failed_create",
                    error=cleanup_error,
                    data={"external_id": container_name, "image": image},
                    retryable=False,
                    user_action=None,
                )
            raise RuntimeError(f"docker start failed: {e.message}") from e

        return container_name

    async def _start_container(self, external_id: str) -> None:
        try:
            container = await self._docker.containers.get(external_id)
            await container.start()
        except aiodocker.exceptions.DockerError as e:
            raise RuntimeError(f"docker start failed: {e.message}") from e

    async def start(self, external_id: str) -> None:
        await _retry_docker(
            lambda: self._start_container(external_id),
            operation="start_container",
            data={"external_id": external_id},
        )

    async def stop(self, external_id: str) -> None:
        async def _do_stop():
            try:
                container = await self._docker.containers.get(external_id)
                await container.stop(t=10)
            except aiodocker.exceptions.DockerError as e:
                msg = e.message
                if "No such container" in msg or "304" in msg or "not running" in msg:
                    return
                raise RuntimeError(f"docker stop failed: {msg}") from e

        await _retry_docker(_do_stop, operation="stop_container", data={"external_id": external_id})

    async def destroy(self, external_id: str) -> None:
        async def _do_destroy():
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

        await _retry_docker(_do_destroy, operation="destroy_container", data={"external_id": external_id})

    async def status(self, external_id: str) -> str:
        try:
            container = await self._docker.containers.get(external_id)
            info = await container.show()
            status: str = info.get("State", {}).get("Status", "unknown")
            return status
        except Exception as e:
            log_boundary_failure(
                logger,
                boundary="docker_provider",
                code="DOCKER_STATUS_FAILED",
                message="Failed to read Docker container status",
                operation="status_container",
                error=e,
                data={"external_id": external_id},
            )
            return "unknown"

    async def exec(
        self, external_id: str, cmd: list[str], env: Optional[dict[str, str]] = None
    ) -> tuple[int, str, str]:
        try:
            container = await self._docker.containers.get(external_id)
            environment = [f"{k}={v}" for k, v in env.items()] if env else None

            exec_instance = await container.exec(
                cmd,
                stdout=True,
                stderr=True,
                environment=environment,
            )
            resp = exec_instance.start()
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
            log_boundary_failure(
                logger,
                boundary="docker_provider",
                code="DOCKER_EXEC_FAILED",
                message="Docker exec failed",
                operation="exec_container",
                error=e,
                data={"external_id": external_id, "command": cmd[0] if cmd else ""},
            )
            return 1, "", f"exec failed: {e.message}"

    async def list_active(self) -> list[dict]:
        try:
            containers = await self._docker.containers.list(
                all=True,
                filters=json.dumps(
                    {
                        "label": ["joysafeter=true"],
                        "status": ["running", "exited"],
                    }
                ),
            )
            results = []
            for c in containers:
                info = c._container
                names = info.get("Names", [])
                name = names[0].lstrip("/") if names else ""
                results.append(
                    {
                        "id": info.get("Id", ""),
                        "name": name,
                        "status": info.get("State", ""),
                        "image": info.get("Image", ""),
                        "labels": info.get("Labels", {}) or {},
                    }
                )
            return results
        except Exception as e:
            log_boundary_failure(
                logger,
                boundary="docker_provider",
                code="DOCKER_LIST_ACTIVE_FAILED",
                message="Failed to list active Docker sandboxes",
                operation="list_active",
                error=e,
            )
            return []

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        try:
            container = await self._docker.containers.get(external_id)
            info = await container.show()
        except Exception as e:
            log_boundary_failure(
                logger,
                boundary="docker_provider",
                code="DOCKER_PROVISIONING_STATUS_FAILED",
                message="Failed to read Docker provisioning status",
                operation="provisioning_status",
                error=e,
                data={"external_id": external_id},
            )
            return {
                "stage": "provider_failed",
                "progress": 0,
                "message": "Container not found",
                "complete": False,
                "error": True,
            }

        state = info.get("State", {})
        docker_status = state.get("Status", "unknown").lower()
        running = state.get("Running", False)
        restarting = state.get("Restarting", False)
        exit_code = state.get("ExitCode", 0)
        error_str = state.get("Error", "")

        if running:
            return {
                "stage": "runtime_booting",
                "progress": 90,
                "message": "Container is running, waiting for runner ready",
                "complete": True,
                "error": False,
            }
        elif restarting or "created" in docker_status or "starting" in docker_status:
            return {
                "stage": "container_starting",
                "progress": 60,
                "message": "Container is starting",
                "complete": False,
                "error": False,
            }
        elif "exited" in docker_status or "dead" in docker_status:
            msg = error_str if error_str else f"Container exited with code {exit_code}"
            return {
                "stage": "provider_failed",
                "progress": 100,
                "message": "Container exited before runtime ready",
                "complete": True,
                "error": True,
                "error_message": msg,
            }
        else:
            return {
                "stage": "provider_pending",
                "progress": 40,
                "message": f"Provider state: {docker_status}",
                "complete": False,
                "error": False,
            }

    async def setup_networking(self, sandbox_id: uuid.UUID, networking: dict) -> None:
        net_type = networking.get("type") or networking.get("net_type")
        if net_type == "limited" and self._envoy_manager:
            await self._envoy_manager.setup_for_sandbox(sandbox_id, networking)
        elif net_type == "limited" and not self._envoy_manager:
            log_boundary_failure(
                logger,
                boundary="docker_provider",
                code="DOCKER_LIMITED_NETWORKING_ENVOY_MISSING",
                message="Limited networking requested without Envoy manager",
                operation="setup_networking",
                data={"sandbox_id": str(sandbox_id)},
                retryable=False,
                user_action="check_configuration",
            )

    async def teardown_networking(self, sandbox_id: uuid.UUID) -> None:
        if self._envoy_manager:
            await self._envoy_manager.teardown_for_sandbox(sandbox_id)

    async def inject_files(self, external_id: str, session_id: uuid.UUID) -> None:
        """Inject session files into a running Docker container via docker cp."""
        import os
        import tempfile

        from sqlalchemy import select

        from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
        from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
        from app.joysafeter_orchestrator.sandbox.archive_utils import (
            auto_extract_archive_into_container,
        )
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_shared.storage import get_storage

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JoySafeterSessionFile, JoySafeterFile)
                .join(JoySafeterFile, JoySafeterSessionFile.file_id == JoySafeterFile.id)
                .where(JoySafeterSessionFile.session_id == session_id)
            )
            rows = result.all()

        if not rows:
            return

        storage = get_storage()
        for session_file, file_record in rows:
            mount_path = session_file.mount_path
            normalized = os.path.normpath(mount_path)
            if ".." in normalized or not normalized.startswith("/workspace/"):
                log_boundary_failure(
                    logger,
                    boundary="docker_provider",
                    code="DOCKER_FILE_INJECTION_PATH_TRAVERSAL_BLOCKED",
                    message="Docker file injection path traversal blocked",
                    operation="inject_session_file",
                    data={"external_id": external_id, "session_id": str(session_id), "mount_path": mount_path},
                    retryable=False,
                    user_action="correct_request",
                )
                continue
            data = await storage.get(file_record.storage_key)

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                parent_dir = os.path.dirname(normalized)
                await self._exec_docker("exec", external_id, "mkdir", "-p", parent_dir)
                await self._exec_docker("cp", tmp_path, f"{external_id}:{normalized}")
                try:
                    await auto_extract_archive_into_container(
                        self._exec_docker,
                        external_id,
                        normalized,
                        data,
                    )
                except Exception as extract_error:
                    log_boundary_failure(
                        logger,
                        boundary="docker_provider",
                        code="DOCKER_FILE_AUTO_EXTRACT_FAILED",
                        message="Failed to auto-extract injected archive",
                        operation="auto_extract_injected_archive",
                        error=extract_error,
                        data={
                            "external_id": external_id,
                            "session_id": str(session_id),
                            "mount_path": mount_path,
                        },
                    )
            except Exception as e:
                log_boundary_failure(
                    logger,
                    boundary="docker_provider",
                    code="DOCKER_FILE_INJECTION_FAILED",
                    message="Failed to inject file into Docker container",
                    operation="inject_session_file",
                    error=e,
                    data={"external_id": external_id, "session_id": str(session_id), "mount_path": mount_path},
                )
            finally:
                os.unlink(tmp_path)

        logger.info("Injected %d files into %s", len(rows), external_id)

    async def _exec_docker(self, *args: str) -> None:
        proc = await asyncio.subprocess.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker {args[0]} failed: {stderr.decode() if stderr else ''}")
