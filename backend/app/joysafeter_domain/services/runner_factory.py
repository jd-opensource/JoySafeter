"""Factory for creating ExecutionRunner with port adapters."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.agent.cli_backends.execution_runner import ExecutionRunner
from app.joysafeter_domain.services.execution_event_adapter import ExecutionEventAdapter
from app.joysafeter_domain.services.execution_reader_adapter import ExecutionReaderAdapter


def create_execution_runner(db: AsyncSession) -> ExecutionRunner:
    return ExecutionRunner(ExecutionEventAdapter(db), ExecutionReaderAdapter(db))
