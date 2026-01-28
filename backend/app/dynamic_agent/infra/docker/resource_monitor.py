"""
Docker container resource monitoring
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import docker
from docker.models.containers import Container

from .exceptions import ContainerNotFoundError, ResourceMonitorError


@dataclass
class ResourceSnapshot:
    """
    Resource usage snapshot

    Attributes:
        timestamp: Snapshot timestamp
        cpu_percent: CPU usage percentage (0-100)
        memory_usage: Memory usage in bytes
        memory_limit: Memory limit in bytes
        memory_percent: Memory usage percentage (0-100)
        network_rx_bytes: Network received bytes
        network_tx_bytes: Network transmitted bytes
        block_read_bytes: Block device read bytes
        block_write_bytes: Block device write bytes
        pids_current: Current process count
    """

    timestamp: datetime
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    memory_percent: float
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    block_read_bytes: int = 0
    block_write_bytes: int = 0
    pids_current: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_usage": self.memory_usage,
            "memory_limit": self.memory_limit,
            "memory_percent": round(self.memory_percent, 2),
            "network_rx_bytes": self.network_rx_bytes,
            "network_tx_bytes": self.network_tx_bytes,
            "block_read_bytes": self.block_read_bytes,
            "block_write_bytes": self.block_write_bytes,
            "pids_current": self.pids_current,
        }


@dataclass
class ResourceMetrics:
    """
    Resource usage metrics statistics

    Attributes:
        snapshots: List of resource snapshots
        start_time: Start time
        end_time: End time
    """

    snapshots: List[ResourceSnapshot] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def add_snapshot(self, snapshot: ResourceSnapshot):
        """Add snapshot"""
        if not self.start_time:
            self.start_time = snapshot.timestamp
        self.end_time = snapshot.timestamp
        self.snapshots.append(snapshot)

    def get_avg_cpu(self) -> float:
        """Get average CPU usage percentage"""
        if not self.snapshots:
            return 0.0
        return sum(s.cpu_percent for s in self.snapshots) / len(self.snapshots)

    def get_max_cpu(self) -> float:
        """Get maximum CPU usage percentage"""
        if not self.snapshots:
            return 0.0
        return max(s.cpu_percent for s in self.snapshots)

    def get_avg_memory(self) -> int:
        """Get average memory usage in bytes"""
        if not self.snapshots:
            return 0
        return int(sum(s.memory_usage for s in self.snapshots) / len(self.snapshots))

    def get_max_memory(self) -> int:
        """Get maximum memory usage in bytes"""
        if not self.snapshots:
            return 0
        return max(s.memory_usage for s in self.snapshots)

    def get_avg_memory_percent(self) -> float:
        """Get average memory usage percentage"""
        if not self.snapshots:
            return 0.0
        return sum(s.memory_percent for s in self.snapshots) / len(self.snapshots)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (self.end_time - self.start_time).total_seconds()
            if self.start_time and self.end_time
            else 0,
            "snapshot_count": len(self.snapshots),
            "avg_cpu_percent": round(self.get_avg_cpu(), 2),
            "max_cpu_percent": round(self.get_max_cpu(), 2),
            "avg_memory_bytes": self.get_avg_memory(),
            "max_memory_bytes": self.get_max_memory(),
            "avg_memory_percent": round(self.get_avg_memory_percent(), 2),
            "snapshots": [s.to_dict() for s in self.snapshots],
        }


class ResourceMonitor:
    """
    Docker container resource monitor

    Example:
        >>> monitor = ResourceMonitor()
        >>> metrics = monitor.collect_metrics(container_id, duration=60, interval=1)
        >>> print(metrics.get_avg_cpu())
    """

    def __init__(self, client: Optional[docker.DockerClient] = None):
        """
        Initialize resource monitor

        Args:
            client: Docker client instance, auto-connect if None
        """
        self.client = client or docker.from_env()
        self.metrics: Dict[str, ResourceMetrics] = {}

    def get_container_stats(self, container: Container) -> ResourceSnapshot:
        """
        Get container real-time resource statistics

        Args:
            container: Docker container object

        Returns:
            ResourceSnapshot: Resource snapshot

        Raises:
            ResourceMonitorError: Failed to get statistics
        """
        try:
            stats = container.stats(stream=False)
            return self._parse_stats(stats)
        except Exception as e:
            raise ResourceMonitorError(f"Failed to get container statistics: {e}")

    def _parse_stats(self, stats: dict) -> ResourceSnapshot:
        """
        Parse Docker statistics

        Args:
            stats: Docker statistics dictionary

        Returns:
            ResourceSnapshot: Resource snapshot
        """
        # Parse CPU usage
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get(
            "total_usage", 0
        )
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

        cpu_percent = 0.0
        if system_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * len(cpu_stats.get("cpus", [])) * 100.0

        # Parse memory usage
        memory_stats = stats.get("memory_stats", {})
        memory_usage = memory_stats.get("usage", 0)
        memory_limit = memory_stats.get("limit", 0)
        memory_percent = 0.0
        if memory_limit > 0:
            memory_percent = (memory_usage / memory_limit) * 100.0

        # Parse network statistics
        networks = stats.get("networks", {})
        network_rx_bytes = 0
        network_tx_bytes = 0
        for net_stats in networks.values():
            network_rx_bytes += net_stats.get("rx_bytes", 0)
            network_tx_bytes += net_stats.get("tx_bytes", 0)

        # Parse block device statistics
        blkio_stats = stats.get("blkio_stats", {})
        block_read_bytes = 0
        block_write_bytes = 0
        for io_stat in blkio_stats.get("io_service_bytes_recursive", []):
            if io_stat.get("op") == "Read":
                block_read_bytes += io_stat.get("value", 0)
            elif io_stat.get("op") == "Write":
                block_write_bytes += io_stat.get("value", 0)

        # Parse process count
        pids_stats = stats.get("pids_stats", {})
        pids_current = pids_stats.get("current", 0)

        return ResourceSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu_percent,
            memory_usage=memory_usage,
            memory_limit=memory_limit,
            memory_percent=memory_percent,
            network_rx_bytes=network_rx_bytes,
            network_tx_bytes=network_tx_bytes,
            block_read_bytes=block_read_bytes,
            block_write_bytes=block_write_bytes,
            pids_current=pids_current,
        )

    def collect_metrics(
        self,
        container_id: str,
        duration: int = 60,
        interval: float = 1.0,
    ) -> ResourceMetrics:
        """
        Collect container resource metrics

        Args:
            container_id: Container ID
            duration: Collection duration in seconds
            interval: Collection interval in seconds

        Returns:
            ResourceMetrics: Resource metrics

        Raises:
            ContainerNotFoundError: Container not found
            ResourceMonitorError: Collection failed

        Example:
            >>> metrics = monitor.collect_metrics('container_id', duration=30, interval=1)
            >>> print(f"Average CPU: {metrics.get_avg_cpu()}%")
            >>> print(f"Max memory: {metrics.get_max_memory()} bytes")
        """
        try:
            container = self.client.containers.get(container_id)
        except Exception:
            raise ContainerNotFoundError(f"Container not found: {container_id}")

        metrics = ResourceMetrics()
        start_time = time.time()

        while time.time() - start_time < duration:
            try:
                snapshot = self.get_container_stats(container)
                metrics.add_snapshot(snapshot)
                time.sleep(interval)
            except Exception as e:
                raise ResourceMonitorError(f"Failed to collect metrics: {e}")

        self.metrics[container_id] = metrics
        return metrics

    def get_metrics(self, container_id: str) -> Optional[ResourceMetrics]:
        """
        Get collected metrics

        Args:
            container_id: Container ID

        Returns:
            ResourceMetrics: Resource metrics, None if not collected
        """
        return self.metrics.get(container_id)

    def clear_metrics(self, container_id: str):
        """
        Clear collected metrics

        Args:
            container_id: Container ID
        """
        self.metrics.pop(container_id, None)
