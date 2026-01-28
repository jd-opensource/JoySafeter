"""
Task Manager for managing task execution and callback integration.

This module provides a high-level interface for creating tasks and integrating
the LangChain callback handler for execution tracking.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger

from app.dynamic_agent.observability.tracking import TaskExecutionTrackingHandler
from app.dynamic_agent.storage.models import ExecutionStepResponse, TaskStatus
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO


class TaskManager:
    """Manages task creation and execution tracking."""

    def __init__(self, task_dao: TaskDAO):
        """Initialize task manager.

        Args:
            task_dao: TaskDAO instance for database operations
        """
        self.task_dao = task_dao
        # Singleton tracking handler (queue-based, no DAO needed)
        self._tracking_handler = TaskExecutionTrackingHandler()

    async def create_task(
        self,
        session_id: str,
        user_input: str,
        message_id: Optional[int] = None,
        metadata: Optional[dict] = None,
        parent_id: Optional[UUID] = None,
        created_by_step_id: Optional[UUID] = None,
    ) -> tuple[UUID, TaskExecutionTrackingHandler]:
        """Create a new task and return its ID with shared callback handler.

        The returned handler is a singleton that uses MetadataContext to determine
        which task_id to track, allowing it to serve multiple agents.

        Args:
            session_id: ID of the chat session
            user_input: User's input message
            message_id: Optional ID of the message triggering the task
            metadata: Optional metadata
            parent_id: Optional parent task ID for creating subtasks
            created_by_step_id: Optional step ID that created this task

        Returns:
            Tuple of (task_id, shared_callback_handler)
        """
        try:
            # Create task in database
            task = await self.task_dao.create_task(
                session_id=session_id,
                user_input=user_input,
                message_id=message_id,
                metadata=metadata or {},
                parent_id=parent_id,
                created_by_step_id=created_by_step_id,
            )

            # Ideally create_task sets it to PENDING, we update to RUNNING immediately?
            # Or just rely on the agent to start. But tracking handler assumes task exists.

            await self.task_dao.update_task(task_id=task.id, status=TaskStatus.RUNNING)

            # Return singleton handler (uses MetadataContext for task_id)
            logger.info(f"Created task {task.id} for session {session_id}")
            return task.id, self._tracking_handler

        except Exception as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            raise

    async def complete_task(
        self,
        task_id: UUID,
        result_summary: Optional[str] = None,
    ) -> None:
        """Mark a task as completed.

        Args:
            task_id: ID of the task
            result_summary: Optional summary of results
        """
        try:
            await self.task_dao.update_task(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result_summary=result_summary,
                completed_at=datetime.utcnow(),
            )
            logger.info(f"Completed task {task_id}")
        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}", exc_info=True)
            raise

    async def update_task_metadata(self, task_id: UUID, metadata_updates: dict) -> None:
        """Update task metadata by merging with existing metadata.

        Args:
            task_id: ID of the task to update
            metadata_updates: Dictionary of metadata key-value pairs to add/update
        """
        try:
            await self.task_dao.update_task_metadata(task_id=task_id, metadata_updates=metadata_updates)
            logger.info(f"Updated metadata for task {task_id}")
        except Exception as e:
            logger.error(f"Error updating metadata for task {task_id}: {e}", exc_info=True)
            raise

    async def fail_task(
        self,
        task_id: UUID,
        error_message: Optional[str] = None,
    ) -> None:
        """Mark a task as failed.

        Args:
            task_id: ID of the task
            error_message: Optional error message
        """
        try:
            await self.task_dao.update_task(
                task_id=task_id, status=TaskStatus.FAILED, result_summary=error_message, completed_at=datetime.utcnow()
            )
            logger.error(f"Task {task_id} failed: {error_message}")
        except Exception as e:
            logger.error(f"Error failing task {task_id}: {e}", exc_info=True)
            raise

    async def get_task_tree(self, task_id: UUID) -> Optional[Dict[str, Any]]:
        """Get complete task execution tree.

        Args:
            task_id: ID of the task

        Returns:
            Task dictionary with execution steps tree
        """
        try:
            task = await self.task_dao.get_task_by_id(task_id)
            if not task:
                return None

            steps = await self.task_dao.get_all_steps_for_task(task_id)
            step_tree = self._build_execution_tree(steps)

            return {
                "id": str(task.id),
                "session_id": str(task.session_id),
                "message_id": task.message_id,
                "user_input": task.user_input,
                "status": task.status.value,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "result_summary": task.result_summary,
                "metadata": task.metadata,
                "steps": step_tree,
            }
        except Exception as e:
            logger.error(f"Error getting task tree {task_id}: {e}", exc_info=True)
            raise

    def _build_execution_tree(self, steps: List[ExecutionStepResponse]) -> List[Dict[str, Any]]:
        """Build a nested tree structure from flat steps list."""
        step_map = {step.id: self._step_to_dict(step) for step in steps}
        root_steps = []

        for step in steps:
            current_node = step_map[step.id]
            if step.parent_step_id:
                parent = step_map.get(step.parent_step_id)
                if parent:
                    parent["children"].append(current_node)
                else:
                    # Orphaned step, treat as root or log warning
                    root_steps.append(current_node)
            else:
                root_steps.append(current_node)

        return root_steps

    def _step_to_dict(self, step: ExecutionStepResponse) -> Dict[str, Any]:
        """Convert ExecutionStepResponse to dictionary."""
        return {
            "id": str(step.id),
            "task_id": str(step.task_id),
            "parent_step_id": str(step.parent_step_id) if step.parent_step_id else None,
            "step_type": step.step_type,
            "name": step.name,
            "input_data": step.input_data,
            "output_data": step.output_data,
            "status": step.status.value,
            "start_time": step.start_time.isoformat(),
            "end_time": step.end_time.isoformat() if step.end_time else None,
            "error_message": step.error_message,
            "agent_trace": step.agent_trace,
            "children": [],
            "created_at": step.created_at.isoformat(),
        }
