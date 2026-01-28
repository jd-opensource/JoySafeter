"""
Task Autonomy Tool - Guide Agent to Complete Tasks Autonomously

A single unified tool that guides the Agent to exhaust all available methods
before returning, maintaining autonomous task completion mindset.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from langchain.tools import tool


class TaskState:
    """Simple task state tracker"""

    _tasks: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_or_create(cls, task_id: str, description: str = "", max_attempts: int = 10) -> Dict[str, Any]:
        """Get or create task state"""
        if task_id not in cls._tasks:
            cls._tasks[task_id] = {
                "description": description,
                "start_time": datetime.now(),
                "attempts": 0,
                "max_attempts": max_attempts,
                "findings": [],
                "blockers": [],
                "methods": [],
            }
        return cls._tasks[task_id]

    @classmethod
    def record_attempt(
        cls,
        task_id: str,
        method: str,
        success: bool,
        result: str,
        finding: Optional[str] = None,
        blocker: Optional[str] = None,
    ):
        """Record an attempt"""
        task = cls.get_or_create(task_id)
        task["attempts"] += 1
        task["methods"].append(
            {"method": method, "success": success, "result": result, "timestamp": datetime.now().isoformat()}
        )
        if finding:
            task["findings"].append(finding)
        if blocker:
            task["blockers"].append(blocker)


@tool
def should_continue_task(
    task_id: str, description: str = "", max_attempts: int = 10, last_success: bool = False
) -> Dict[str, Any]:
    """
    Determine if Agent should continue exploring methods to complete the task.

    This tool guides the Agent to exhaust all available methods before giving up.
    Do NOT return until all methods are exhausted.

    Parameters:
    - task_id: Unique task identifier
    - description: Task description (for initialization)
    - max_attempts: Maximum number of attempts allowed
    - last_success: Whether the last method was successful

    Returns guidance on whether to continue and what to do next.

    Purpose:
    - Prevent premature task termination
    - Encourage exhaustive exploration
    - Maintain autonomous task completion mindset
    - Provide clear next steps
    """

    task = TaskState.get_or_create(task_id, description, max_attempts)
    attempts = task["attempts"]
    remaining = max_attempts - attempts
    progress = (attempts / max_attempts) * 100

    # Determine if should continue
    should_continue = remaining > 0

    # Generate guidance based on progress
    if attempts == 0:
        guidance = "Task not started. Begin exploration immediately with primary method."
        urgency = "normal"
        suggestions = [
            "Try primary method for this task type",
            "Document approach and results",
            "Prepare alternative methods",
        ]
    elif last_success and remaining > 0:
        guidance = f"Method succeeded! Continue exploring ({remaining} attempts left) for comprehensive coverage."
        urgency = "normal"
        suggestions = [
            "Verify findings with alternative methods",
            "Cross-check results for accuracy",
            "Explore edge cases and variations",
        ]
    elif remaining > 3:
        guidance = f"Still have {remaining} attempts. Must continue exploration with different methods."
        urgency = "normal"
        suggestions = [
            "Try alternative method or approach",
            "Adjust parameters or configuration",
            "Combine multiple techniques",
        ]
    elif remaining > 0:
        guidance = f"Limited attempts remaining ({remaining}). Use them wisely on most promising methods."
        urgency = "high"
        suggestions = [
            "Focus on high-impact techniques",
            "Prepare final verification steps",
            "Ensure all critical paths explored",
        ]
    else:
        guidance = "All attempts exhausted. Prepare final conclusions and report."
        urgency = "critical"
        suggestions = ["Summarize all findings", "Prepare final report", "Document lessons learned"]

    # Record this check
    if attempts > 0:
        TaskState.record_attempt(task_id, f"check_attempt_{attempts}", last_success, guidance)

    return {
        "should_continue": should_continue,
        "task_id": task_id,
        "current_attempt": attempts,
        "attempts_remaining": remaining,
        "max_attempts": max_attempts,
        "progress_percentage": round(progress, 1),
        "guidance": guidance,
        "urgency": urgency,
        "next_steps": suggestions,
        "findings_count": len(task["findings"]),
        "blockers_count": len(task["blockers"]),
        "critical_message": "Do NOT give up until all methods are exhausted!",
    }


# Export the tool
__all__ = ["should_continue_task", "TaskState"]
