import asyncio
import io
import logging
import re
import tarfile
import uuid
from typing import Optional

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)

_SAFE_PKG_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-\[\]@/:<>=!,~^*]+$")


class ImageBuildError(Exception):
    pass


class ImageBuilder:
    """Builds custom Docker images from environment Packages configuration.

    Generates a Dockerfile with package install commands, builds it via Docker CLI,
    and tags with a versioned name.

    Ported from joysafeter-sandbox/src/image_builder.rs.
    """

    def __init__(self, default_base: str = "joysafeter-claudecode:latest"):
        self._default_base = default_base

    @staticmethod
    def _sanitize_packages(pkgs: list[str]) -> list[str]:
        safe = []
        for p in pkgs:
            p = p.strip()
            if not p or not _SAFE_PKG_NAME.match(p):
                log_boundary_failure(
                    logger,
                    boundary="image_builder",
                    code="IMAGE_BUILDER_UNSAFE_PACKAGE_REJECTED",
                    message="Rejected unsafe package name",
                    operation="sanitize_packages",
                    data={"package": p},
                    retryable=False,
                    user_action="correct_request",
                )
                continue
            safe.append(p)
        return safe

    @staticmethod
    def _packages_install_commands(packages: dict) -> list[str]:
        cmds: list[str] = []
        apt = ImageBuilder._sanitize_packages(packages.get("apt", []))
        if apt:
            pkg_list = " ".join(apt)
            cmds.append(
                f"apt-get update && apt-get install -y --no-install-recommends {pkg_list} && rm -rf /var/lib/apt/lists/*"
            )
        pip = ImageBuilder._sanitize_packages(packages.get("pip", []))
        if pip:
            cmds.append(f"pip install --no-cache-dir {' '.join(pip)}")
        npm = ImageBuilder._sanitize_packages(packages.get("npm", []))
        if npm:
            cmds.append(f"npm install -g {' '.join(npm)}")
        cargo = ImageBuilder._sanitize_packages(packages.get("cargo", []))
        if cargo:
            cmds.append(f"cargo install {' '.join(cargo)}")
        gem = ImageBuilder._sanitize_packages(packages.get("gem", []))
        if gem:
            cmds.append(f"gem install {' '.join(gem)}")
        go = ImageBuilder._sanitize_packages(packages.get("go", []))
        if go:
            for pkg in go:
                cmds.append(f"go install {pkg}")
        return cmds

    @staticmethod
    def _is_packages_empty(packages: dict) -> bool:
        return not any(packages.get(k) for k in ("apt", "pip", "npm", "cargo", "gem", "go"))

    async def build_environment_image(
        self,
        env_id: uuid.UUID,
        version: int,
        packages: dict,
    ) -> Optional[str]:
        if self._is_packages_empty(packages):
            return None

        install_cmds = self._packages_install_commands(packages)
        run_lines = "\n".join(f"RUN {cmd}" for cmd in install_cmds)

        dockerfile = f"FROM {self._default_base}\nUSER root\n{run_lines}\nUSER agent\n"

        short_id = str(env_id).split("-")[0]
        tag = f"joysafeter/env-{short_id}:v{version}"

        # Create tar context with Dockerfile
        tar_bytes = self._create_tar_context(dockerfile)

        logger.info("Building environment image %s", tag)

        # Build via docker CLI (pipe tar context via stdin)
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "build",
            "-t",
            tag,
            "--rm",
            "--force-rm",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=tar_bytes)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            log_boundary_failure(
                logger,
                boundary="image_builder",
                code="IMAGE_BUILDER_DOCKER_BUILD_FAILED",
                message="Docker build failed for environment image",
                operation="build_environment_image",
                data={"env_id": str(env_id), "version": version, "tag": tag},
            )
            raise ImageBuildError(f"Build failed: {error_msg}")

        logger.info("Environment image %s built successfully", tag)
        return tag

    @staticmethod
    def _create_tar_context(dockerfile: str) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            dockerfile_bytes = dockerfile.encode("utf-8")
            info = tarfile.TarInfo(name="Dockerfile")
            info.size = len(dockerfile_bytes)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(dockerfile_bytes))
        return buf.getvalue()
