"""
TODO Tool - Allows Agent to manage task progress visualization.

006: Single Subagent Clean Architecture
Provides tools for the agent to:
- Plan tasks at the beginning
- Mark tasks as in-progress/completed/failed
- Replan when needed
"""

from typing import List, Optional

from langchain_core.tools import tool

from app.dynamic_agent.infra.metadata_context import MetadataContext


def _get_todo_display():
    """Get TODO display from metadata or global instance."""
    metadata = MetadataContext.get() or {}
    todo_display = metadata.get("todo_display")

    if todo_display is None:
        # Fallback to global instance
        from app.dynamic_agent.infra.todo_display import get_todo_display

        todo_display = get_todo_display()

    return todo_display


def _update_session_context():
    """Update agent_session_context with current TODO status."""
    metadata = MetadataContext.get() or {}
    agent_session_context = metadata.get("agent_session_context")
    todo_display = _get_todo_display()

    if agent_session_context and todo_display and todo_display.panel:
        # Update progress
        completed = sum(1 for item in todo_display.panel.items if item.status == "completed")
        total = len(todo_display.panel.items)
        agent_session_context.set_progress(completed, total)

        # Update TODO status
        agent_session_context.update_from_todo_panel(todo_display.panel)


@tool("plan_tasks")
def plan_tasks(tasks: List[str]) -> str:
    """
    Plan the tasks to complete for this CTF challenge.
    Call this FIRST before starting any work to create a visual task list.

    Args:
        tasks: List of task descriptions (e.g., ["Scan target ports", "Find login page", "Try SQL injection"])

    Returns:
        Confirmation message with task IDs
    """
    todo_display = _get_todo_display()

    if not tasks:
        return "❌ Error: No tasks provided. Please provide a list of tasks."

    # Clear existing tasks and add new ones
    todo_display.clear()
    items = todo_display.add_tasks(tasks)

    # Start the first task
    if items:
        todo_display.start_task(items[0].id)

    # Simplified task list (no IDs - LLM doesn't need them)
    task_list = "\n".join([f"  {i + 1}. {item.description}" for i, item in enumerate(items)])

    # Update session context with new progress
    _update_session_context()

    return f"""✅ {len(items)} tasks planned:
{task_list}

Started: {items[0].description if items else "None"}"""


@tool("complete_task")
def complete_task(task_id: Optional[str] = None) -> str:
    """
    Mark the current task as completed and start the next one.

    Args:
        task_id: Optional specific task ID. If not provided, completes the current in-progress task.

    Returns:
        Status message with next task info
    """
    todo_display = _get_todo_display()

    if todo_display.panel is None or not todo_display.panel.items:
        return "❌ No tasks planned. Use 'plan_tasks' first."

    if task_id:
        todo_display.complete_task(task_id)
        todo_display.start_next_task()
    else:
        todo_display.complete_current_and_start_next()

    # Update session context with new progress
    _update_session_context()

    if todo_display.is_all_done():
        return "🎉 All tasks completed!"

    return "✅ Task completed."


@tool("fail_task")
def fail_task(error: str, task_id: Optional[str] = None) -> str:
    """
    Mark the current task as failed.

    Args:
        error: Brief description of why the task failed
        task_id: Optional specific task ID. If not provided, fails the current in-progress task.

    Returns:
        Status message
    """
    todo_display = _get_todo_display()

    if todo_display.panel is None:
        return "❌ No tasks planned."

    current = todo_display.get_current_task()
    target_id = task_id or (current.id if current else None)

    if target_id:
        todo_display.fail_task(target_id, error)
        _update_session_context()
        return f"❌ Task [{target_id}] marked as failed: {error}"
    else:
        return "❌ No current task to fail."


@tool("replan_tasks")
def replan_tasks(new_tasks: List[str], reason: str) -> str:
    """
    Replace remaining tasks with a new plan.
    Use this when the original plan isn't working and you need a different approach.

    Args:
        new_tasks: List of new task descriptions
        reason: Brief explanation of why replanning is needed

    Returns:
        Confirmation message
    """
    todo_display = _get_todo_display()

    if not new_tasks:
        return "❌ Error: No new tasks provided."

    todo_display.replan(new_tasks, reason)

    # Start the first new task
    next_item = todo_display.start_next_task()

    # Update session context with new progress
    _update_session_context()

    return f"""🔄 Plan updated: {reason}

New tasks:
{chr(10).join([f"  - {t}" for t in new_tasks])}

Starting: {next_item.description if next_item else "None"}"""


@tool("get_task_status")
def get_task_status() -> str:
    """
    Get the current status of all tasks.

    Returns:
        Current task list with status
    """
    todo_display = _get_todo_display()

    if todo_display.panel is None or not todo_display.panel.items:
        return "📋 No tasks planned yet. Use 'plan_tasks' to create a task list."

    lines = [f"📋 Task Progress: {todo_display.get_summary()}", ""]

    for item in todo_display.panel.items:
        status_icon = {
            "pending": "⏸️",
            "in_progress": "⏳",
            "completed": "✅",
            "failed": "❌",
        }.get(item.status, "❓")

        line = f"  {status_icon} [{item.id}] {item.description}"
        if item.status == "completed":
            line = f"  {status_icon} ~~[{item.id}] {item.description}~~"
        if item.error_summary:
            line += f" ({item.error_summary})"
        lines.append(line)

    return "\n".join(lines)


# Export all tools
TODO_TOOLS = [
    plan_tasks,
    complete_task,
    fail_task,
    replan_tasks,
    get_task_status,
]
