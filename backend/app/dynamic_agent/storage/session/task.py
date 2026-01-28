"""
Task state management.

Tracks execution state of security testing tasks.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskState:
    """Task execution state."""

    task_id: str
    session_id: str
    task_type: str  # tool_execution, scan, analysis
    status: TaskStatus

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Task details
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    # Execution results
    result: Optional[Any] = None
    error: Optional[str] = None

    # Progress information
    progress: float = 0.0  # 0-100
    progress_message: Optional[str] = None

    # Resource usage
    container_id: Optional[str] = None
    execution_time_ms: Optional[int] = None


class TaskStateManager:
    """Task state manager."""

    def __init__(self, persistence_backend):
        self.backend = persistence_backend
        self._active_tasks: Dict[str, TaskState] = {}

    async def create_task(
        self,
        session_id: str,
        task_type: str,
        tool_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> TaskState:
        """Create a new task."""
        from uuid import uuid4

        task_id = str(uuid4())

        task = TaskState(
            task_id=task_id,
            session_id=session_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            tool_name=tool_name,
            parameters=parameters or {},
        )

        self._active_tasks[task_id] = task
        await self.backend.save_task(task)

        return task

    async def start_task(self, task_id: str, container_id: Optional[str] = None):
        """Start task execution."""
        task = self._active_tasks.get(task_id)
        if not task:
            task = await self.backend.load_task(task_id)

        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            task.container_id = container_id
            self._active_tasks[task_id] = task
            await self.backend.save_task(task)

    async def update_progress(self, task_id: str, progress: float, message: Optional[str] = None):
        """Update task progress."""
        task = self._active_tasks.get(task_id)
        if task:
            task.progress = min(100.0, max(0.0, progress))
            task.progress_message = message
            await self.backend.save_task(task)

    async def complete_task(self, task_id: str, result: Any, execution_time_ms: Optional[int] = None):
        """Complete task successfully."""
        task = self._active_tasks.get(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.result = result
            task.progress = 100.0
            task.execution_time_ms = execution_time_ms
            await self.backend.save_task(task)
            del self._active_tasks[task_id]

    async def fail_task(self, task_id: str, error: str):
        """Mark task as failed."""
        task = self._active_tasks.get(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.error = error
            await self.backend.save_task(task)
            del self._active_tasks[task_id]

    async def cancel_task(self, task_id: str):
        """Cancel task execution."""
        task = self._active_tasks.get(task_id)
        if task:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            await self.backend.save_task(task)
            del self._active_tasks[task_id]

    async def get_task(self, task_id: str) -> Optional[TaskState]:
        """Get task state."""
        if task_id in self._active_tasks:
            return self._active_tasks[task_id]

        result = await self.backend.load_task(task_id)
        if result is None:
            return None
        # Convert TaskResponse to TaskState if needed
        # Note: This assumes TaskResponse can be converted to TaskState
        return result  # type: ignore[no-any-return]

    async def get_session_tasks(self, session_id: str, status: Optional[TaskStatus] = None) -> List[TaskState]:
        """Get all tasks for a session."""
        result = await self.backend.get_tasks_by_session(session_id, status)
        return result if isinstance(result, list) else []  # type: ignore[return-value]

    async def get_active_tasks(self, session_id: str) -> List[TaskState]:
        """Get active tasks for a session."""
        return await self.get_session_tasks(session_id, TaskStatus.RUNNING)

    async def get_completed_tasks(self, session_id: str) -> List[TaskState]:
        """Get completed tasks for a session."""
        return await self.get_session_tasks(session_id, TaskStatus.COMPLETED)
