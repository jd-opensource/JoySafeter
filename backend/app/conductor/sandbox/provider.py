import uuid
from abc import ABC, abstractmethod
from typing import Optional


class SandboxProvider(ABC):
    @abstractmethod
    async def create(self, name: str, image: str, env: dict[str, str], work_dir: str, labels: Optional[dict[str, str]] = None, **kwargs) -> str:
        """Create a container, return external_id."""
        ...

    @abstractmethod
    async def start(self, external_id: str) -> None: ...

    @abstractmethod
    async def stop(self, external_id: str) -> None: ...

    @abstractmethod
    async def destroy(self, external_id: str) -> None: ...

    @abstractmethod
    async def status(self, external_id: str) -> str: ...

    @abstractmethod
    async def exec(self, external_id: str, cmd: list[str], env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
        """Run a command inside the container, return (exit_code, stdout, stderr)."""
        ...

    @abstractmethod
    def provider_name(self) -> str: ...

    async def provisioning_status(self, external_id: str) -> Optional[dict]:
        """Return provisioning progress (stage, progress, message, complete, error).

        Default returns None (not supported). Cloud providers override this.
        """
        return None

    async def list_active(self) -> list[dict]:
        """List all active sandboxes managed by this provider.

        Default returns empty. Cloud providers override this.
        """
        return []

    async def setup_networking(
        self, sandbox_id: uuid.UUID, networking: dict
    ) -> None:
        """Set up network isolation for a sandbox before container creation."""
        net_type = networking.get("type") or networking.get("net_type")
        if net_type == "limited":
            raise RuntimeError(
                f"Provider '{self.provider_name()}' does not support limited networking"
            )

    async def teardown_networking(self, sandbox_id: uuid.UUID) -> None:
        """Tear down network isolation for a sandbox. Default is a no-op."""
        pass
