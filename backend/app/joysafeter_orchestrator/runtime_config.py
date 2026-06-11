"""Runtime-tunable configuration with thread-safe reads.

Ported from joysafeter-types/src/runtime_config.rs.
Values can be updated without restarting the process.
"""
import threading
from typing import Optional


class RuntimeConfig:
    def __init__(
        self,
        idle_timeout_sec: int = 600,
        stopped_max_age_sec: int = 3600,
        heartbeat_timeout_sec: int = 30,
        sandbox_failure_threshold: int = 3,
        pool_min_size: int = 2,
        pool_max_age_sec: int = 1800,
        event_batch_max_size: int = 50,
        event_batch_max_delay_ms: int = 50,
    ):
        self._lock = threading.Lock()
        self._idle_timeout_sec = idle_timeout_sec
        self._stopped_max_age_sec = stopped_max_age_sec
        self._heartbeat_timeout_sec = heartbeat_timeout_sec
        self._sandbox_failure_threshold = sandbox_failure_threshold
        self._pool_min_size = pool_min_size
        self._pool_max_age_sec = pool_max_age_sec
        self._event_batch_max_size = event_batch_max_size
        self._event_batch_max_delay_ms = event_batch_max_delay_ms

    @property
    def idle_timeout_sec(self) -> int:
        with self._lock:
            return self._idle_timeout_sec

    @idle_timeout_sec.setter
    def idle_timeout_sec(self, value: int) -> None:
        with self._lock:
            self._idle_timeout_sec = value

    @property
    def stopped_max_age_sec(self) -> int:
        with self._lock:
            return self._stopped_max_age_sec

    @stopped_max_age_sec.setter
    def stopped_max_age_sec(self, value: int) -> None:
        with self._lock:
            self._stopped_max_age_sec = value

    @property
    def heartbeat_timeout_sec(self) -> int:
        with self._lock:
            return self._heartbeat_timeout_sec

    @heartbeat_timeout_sec.setter
    def heartbeat_timeout_sec(self, value: int) -> None:
        with self._lock:
            self._heartbeat_timeout_sec = value

    @property
    def sandbox_failure_threshold(self) -> int:
        with self._lock:
            return self._sandbox_failure_threshold

    @sandbox_failure_threshold.setter
    def sandbox_failure_threshold(self, value: int) -> None:
        with self._lock:
            self._sandbox_failure_threshold = value

    @property
    def pool_min_size(self) -> int:
        with self._lock:
            return self._pool_min_size

    @pool_min_size.setter
    def pool_min_size(self, value: int) -> None:
        with self._lock:
            self._pool_min_size = value

    @property
    def pool_max_age_sec(self) -> int:
        with self._lock:
            return self._pool_max_age_sec

    @pool_max_age_sec.setter
    def pool_max_age_sec(self, value: int) -> None:
        with self._lock:
            self._pool_max_age_sec = value

    @property
    def event_batch_max_size(self) -> int:
        with self._lock:
            return self._event_batch_max_size

    @event_batch_max_size.setter
    def event_batch_max_size(self, value: int) -> None:
        with self._lock:
            self._event_batch_max_size = value

    @property
    def event_batch_max_delay_ms(self) -> int:
        with self._lock:
            return self._event_batch_max_delay_ms

    @event_batch_max_delay_ms.setter
    def event_batch_max_delay_ms(self, value: int) -> None:
        with self._lock:
            self._event_batch_max_delay_ms = value

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                attr = f"_{key}"
                if hasattr(self, attr):
                    setattr(self, attr, value)
