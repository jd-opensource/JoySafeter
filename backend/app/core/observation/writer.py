"""Batched persistence writer for Observation rows."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

import sqlalchemy as sa
from loguru import logger

from app.core.observation.model import Observation


class ObservationWriter:
    def __init__(
        self,
        db_session_factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        max_batch: int = 10,
        max_wait_ms: int = 300,
    ):
        self._db_session_factory = db_session_factory
        self._max_batch = max_batch
        self._max_wait_ms = max_wait_ms
        self._insert_buffer: list[Any] = []
        self._update_buffer: list[tuple[uuid.UUID, dict]] = []
        self._flush_task: asyncio.Task | None = None

    @property
    def _buffer_size(self) -> int:
        return len(self._insert_buffer) + len(self._update_buffer)

    async def insert(self, observation: Any) -> None:
        self._insert_buffer.append(observation)
        await self._maybe_flush()

    async def update(self, observation_id: uuid.UUID, fields: dict) -> None:
        self._update_buffer.append((observation_id, fields))
        await self._maybe_flush()

    async def flush(self) -> None:
        self._cancel_delayed()
        await self._do_flush()

    async def finalize(self) -> None:
        self._cancel_delayed()
        await self._do_flush()

    async def _maybe_flush(self) -> None:
        if self._buffer_size >= self._max_batch:
            self._cancel_delayed()
            await self._do_flush()
        elif self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        try:
            await asyncio.sleep(self._max_wait_ms / 1000)
            await self._do_flush()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.opt(exception=True).debug("observation writer delayed flush failed")
        finally:
            self._flush_task = None

    def _cancel_delayed(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None

    async def _do_flush(self) -> None:
        if not self._insert_buffer and not self._update_buffer:
            return

        inserts = self._insert_buffer[:]
        updates = self._update_buffer[:]
        self._insert_buffer.clear()
        self._update_buffer.clear()

        try:
            session = await self._db_session_factory()
            if inserts:
                session.add_all(inserts)
            for obs_id, fields in updates:
                await session.execute(
                    sa.update(Observation)
                    .where(Observation.id == obs_id)
                    .values(**fields)
                )
            await session.commit()
        except Exception:
            logger.opt(exception=True).debug("observation writer flush failed, re-buffering")
            self._insert_buffer.extend(inserts)
            self._update_buffer.extend(updates)
