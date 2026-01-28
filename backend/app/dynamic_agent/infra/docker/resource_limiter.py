"""
Docker container resource limit configuration
"""

from dataclasses import dataclass
from typing import Any, Optional

import psutil

from .exceptions import ResourceLimitError


@dataclass
class ResourceLimits:
    """
    Docker container resource limit configuration

    Attributes:
        cpu_limit: CPU limit as float representing number of cores (e.g., 0.5 for half core)
        memory_limit: Memory limit in bytes (e.g., 512MB = 536870912)
        memory_swap: Swap memory limit in bytes (-1 means unlimited)
        disk_limit: Disk limit in bytes (e.g., 10GB = 10737418240)
        cpu_shares: CPU weight (relative priority, default 1024)
        pids_limit: Process limit (-1 means unlimited)
    """

    cpu_limit: Optional[float] = None
    memory_limit: Optional[int] = None
    memory_swap: Optional[int] = None
    disk_limit: Optional[int] = None
    cpu_shares: int = 1024
    pids_limit: int = -1

    def __post_init__(self):
        """Validate resource limit parameters"""
        self._validate()

    @staticmethod
    def _get_host_resources() -> dict:
        """
        Get host machine total resources

        Returns:
            dict: Host resources with keys 'cpu_count', 'memory_bytes', 'disk_bytes'
        """
        cpu_count = psutil.cpu_count(logical=True) or 1
        memory_bytes = psutil.virtual_memory().total

        # Get disk space for root partition
        disk_usage = psutil.disk_usage("/")
        disk_bytes = disk_usage.total

        return {
            "cpu_count": cpu_count,
            "memory_bytes": memory_bytes,
            "disk_bytes": disk_bytes,
        }

    def _validate(self):
        """Validate resource limit parameters against host resources"""
        host_resources = self._get_host_resources()
        max_cpu = host_resources["cpu_count"] * 0.98
        max_memory = host_resources["memory_bytes"] * 0.98
        max_disk = host_resources["disk_bytes"] * 0.98

        if self.cpu_limit is not None:
            if self.cpu_limit <= 0:
                raise ResourceLimitError("CPU limit must be greater than 0")
            if self.cpu_limit > 256:  # Reasonable upper limit
                raise ResourceLimitError("CPU limit too high (max 256 cores)")
            if self.cpu_limit > max_cpu:
                raise ResourceLimitError(
                    f"CPU limit ({self.cpu_limit} cores) exceeds 98% of host capacity ({max_cpu:.2f} cores)"
                )

        if self.memory_limit is not None:
            if self.memory_limit < 4194304:  # Minimum 4MB
                raise ResourceLimitError("Memory limit too low (minimum 4MB)")
            if self.memory_limit > 1099511627776:  # Maximum 1TB
                raise ResourceLimitError("Memory limit too high (maximum 1TB)")
            if self.memory_limit > max_memory:
                raise ResourceLimitError(
                    f"Memory limit ({self.memory_limit / 1024 / 1024 / 1024:.2f} GB) exceeds 98% of host capacity "
                    f"({max_memory / 1024 / 1024 / 1024:.2f} GB)"
                )

        if self.memory_swap is not None:
            if self.memory_swap != -1 and self.memory_swap < 0:
                raise ResourceLimitError("Swap memory limit must be -1 or positive")
            if self.memory_limit and self.memory_swap > 0:
                if self.memory_swap < self.memory_limit:
                    raise ResourceLimitError("Swap memory limit cannot be less than memory limit")

        if self.disk_limit is not None:
            if self.disk_limit < 1048576:  # Minimum 1MB
                raise ResourceLimitError("Disk limit too low (minimum 1MB)")
            if self.disk_limit > 1099511627776:  # Maximum 1TB
                raise ResourceLimitError("Disk limit too high (maximum 1TB)")
            if self.disk_limit > max_disk:
                raise ResourceLimitError(
                    f"Disk limit ({self.disk_limit / 1024 / 1024 / 1024:.2f} GB) exceeds 98% of host capacity "
                    f"({max_disk / 1024 / 1024 / 1024:.2f} GB)"
                )

        if self.cpu_shares < 2 or self.cpu_shares > 262144:
            raise ResourceLimitError("CPU shares must be between 2-262144")

        if self.pids_limit < -1 or self.pids_limit == 0:
            raise ResourceLimitError("Process limit must be -1 (unlimited) or positive")

    def to_docker_kwargs(self) -> dict:
        """
        Convert to Docker API parameters

        Returns:
            dict: Docker container creation parameters
        """
        kwargs = {}

        if self.cpu_limit is not None:
            # Docker uses nano_cpus, 1 CPU = 1e9 nano_cpus
            kwargs["nano_cpus"] = int(self.cpu_limit * 1e9)

        if self.memory_limit is not None:
            kwargs["mem_limit"] = self.memory_limit

        if self.memory_swap is not None:
            kwargs["memswap_limit"] = self.memory_swap

        if self.cpu_shares != 1024:
            kwargs["cpu_shares"] = self.cpu_shares

        if self.pids_limit != -1:
            kwargs["pids_limit"] = self.pids_limit

        return kwargs

    @staticmethod
    def from_human_readable(
        cpu: Optional[str] = None, memory: Optional[str] = None, disk: Optional[str] = None, **kwargs
    ) -> "ResourceLimits":
        """
        Create resource limits from human-readable format

        Args:
            cpu: CPU limit, e.g., "0.5", "1", "2.5"
            memory: Memory limit, e.g., "512M", "1G", "2.5G"
            disk: Disk limit, e.g., "1G", "10G", "100G"
            **kwargs: Other parameters

        Returns:
            ResourceLimits: Resource limit object

        Example:
            >>> limits = ResourceLimits.from_human_readable(
            ...     cpu="1",
            ...     memory="512M",
            ...     disk="10G"
            ... )
        """
        parsed: dict[str, Any] = {}

        if cpu:
            parsed["cpu_limit"] = float(cpu)

        if memory:
            parsed["memory_limit"] = _parse_size(memory)

        if disk:
            parsed["disk_limit"] = _parse_size(disk)

        parsed.update(kwargs)
        return ResourceLimits(**parsed)  # type: ignore[arg-type]


def _parse_size(size_str: str) -> int:
    """
    Parse human-readable size string

    Args:
        size_str: Size string, e.g., "512M", "1G", "2.5G"

    Returns:
        int: Number of bytes

    Raises:
        ValueError: Invalid format
    """
    size_str = size_str.strip().upper()

    units = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
    }

    for unit, multiplier in sorted(units.items(), key=lambda x: len(x[0]), reverse=True):
        if size_str.endswith(unit):
            try:
                value = float(size_str[: -len(unit)])
                return int(value * multiplier)
            except ValueError:
                raise ValueError(f"Invalid size format: {size_str}")

    # If no unit, assume bytes
    try:
        return int(float(size_str))
    except ValueError:
        raise ValueError(f"Invalid size format: {size_str}")
