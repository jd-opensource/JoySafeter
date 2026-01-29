"""
Time-Aware Tools - Guide Agent to Complete Tasks In-Depth

This module provides two key time-aware tools:
1. get_current_time() - Get current time to help Agent understand time progress
2. get_execution_elapsed_time() - Get elapsed execution time to help Agent assess task depth and time budget

The purpose of these tools is to guide the Agent to:
- Avoid superficial analysis by promoting in-depth analysis through time pressure awareness
- Conduct more comprehensive testing when sufficient time is available
- Prioritize critical tasks when time is tight
- Adjust task depth and strategy based on elapsed time
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from langchain.tools import tool

# todo


class ExecutionTimeTracker:
    """Execution Time Tracker - Track total task execution time"""

    _instance: Optional["ExecutionTimeTracker"] = None
    _start_time: Optional[float] = None
    _session_start_times: Dict[str, float] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize_global(cls, start_time: Optional[float] = None):
        """Initialize global execution time tracking"""
        instance = cls()
        instance._start_time = start_time or time.time()
        return instance

    @classmethod
    def initialize_session(cls, session_id: str, start_time: Optional[float] = None):
        """Initialize execution time tracking for a specific session"""
        instance = cls()
        instance._session_start_times[session_id] = start_time or time.time()

    @classmethod
    def get_global_elapsed(cls) -> float:
        """Get global elapsed execution time in seconds"""
        instance = cls()
        if instance._start_time is None:
            instance.initialize_global()
        start_time = instance._start_time
        if start_time is None:
            return 0.0
        return time.time() - start_time

    @classmethod
    def get_session_elapsed(cls, session_id: str) -> float:
        """Get elapsed execution time for a specific session in seconds"""
        instance = cls()
        if session_id not in instance._session_start_times:
            instance.initialize_session(session_id)
        return time.time() - instance._session_start_times[session_id]

    @classmethod
    def reset_global(cls):
        """Reset global execution time"""
        instance = cls()
        instance._start_time = time.time()

    @classmethod
    def reset_session(cls, session_id: str):
        """Reset execution time for a specific session"""
        instance = cls()
        instance._session_start_times[session_id] = time.time()


@tool
def get_current_time() -> Dict[str, Any]:
    """
    Get current time information. Returns a dictionary containing timestamp, formatted datetime,
    ISO format, Unix timestamp, milliseconds, hour, minute, second, day of week, and date.

    Purpose:
    - Help Agent understand current time progress
    - Used for timestamp recording and logging
    - Assess whether tasks are within reasonable time ranges
    """
    now = datetime.now()
    time.time()

    return {
        # "timestamp": timestamp,
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        # "iso_format": now.isoformat(),
        # "unix_timestamp": int(timestamp),
        # "milliseconds": int((timestamp % 1) * 1000),
        # "hour": now.hour,
        # "minute": now.minute,
        # "second": now.second,
        "day_of_week": now.strftime("%A"),
        "date": now.strftime("%Y-%m-%d"),
    }


def _get_execution_elapsed_time_impl(session_id: Optional[str] = None, format_type: str = "detailed") -> Dict[str, Any]:
    """
    Get elapsed execution time information and depth recommendations.

    Parameters:
    - session_id: Session ID (if None, returns global execution time)
    - format_type: Return format type ("detailed", "simple", or "analysis")

    Returns information containing elapsed time, time budget, depth recommendation, and time pressure level.
    Used to help Agent assess task depth and time budget.

    Return (detailed format):
    {
        "elapsed_seconds": 3661.5,  # Elapsed seconds
        "elapsed_formatted": "1h 1m 1s",  # Formatted time
        "elapsed_minutes": 61.02,  # Elapsed minutes
        "elapsed_hours": 1.017,  # Elapsed hours
        "start_time": "2025-11-15 13:29:44",  # Start time
        "current_time": "2025-11-15 14:30:45",  # Current time
        "session_id": "session_123"  # Session ID
    }

    Return (analysis format):
    {
        "elapsed_seconds": 3661.5,
        "elapsed_formatted": "1h 1m 1s",
        "time_budget": {
            "total_budget": 7200,  # Total time budget in seconds
            "remaining": 3538.5,  # Remaining time
            "used_percentage": 50.85,  # Used percentage
            "remaining_percentage": 49.15
        },
        "depth_recommendation": {
            "current_depth": "medium",  # Current recommended depth
            "reason": "50.85% time used, recommend continuing in-depth analysis",
            "suggested_actions": [
                "Continue detailed vulnerability analysis",
                "Cross-verify with multiple tools",
                "Gather more contextual information"
            ]
        },
        "time_pressure": {
            "level": "moderate",  # Time pressure level: low/moderate/high/critical
            "message": "Sufficient time available for comprehensive security assessment"
        }
    }

    Purpose:
    - Help Agent understand elapsed and remaining time
    - Adjust task depth based on time budget
    - Avoid superficial analysis by conducting in-depth analysis when time is available
    - Prioritize critical tasks when time is tight
    """
    tracker = ExecutionTimeTracker()

    # Get elapsed execution time
    if session_id:
        elapsed = tracker.get_session_elapsed(session_id)
    else:
        elapsed = tracker.get_global_elapsed()

    # Format time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    formatted = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"

    # Basic information
    current_time = datetime.now()
    start_time = current_time - timedelta(seconds=elapsed)

    result = {
        "elapsed_seconds": round(elapsed, 2),
        "elapsed_formatted": formatted,
        "elapsed_minutes": round(elapsed / 60, 2),
        "elapsed_hours": round(elapsed / 3600, 2),
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": session_id or "global",
    }

    if format_type == "simple":
        return {
            "elapsed_seconds": result["elapsed_seconds"],
            "elapsed_formatted": result["elapsed_formatted"],
            "session_id": result["session_id"],
        }

    if format_type == "analysis":
        # Time budget analysis (default 2 hours)
        total_budget = 7200  # seconds
        remaining = max(0, total_budget - elapsed)
        used_percentage = (elapsed / total_budget) * 100

        # Determine depth recommendation
        if used_percentage < 25:
            current_depth = "shallow"
            depth_reason = "Just started, should conduct comprehensive initial reconnaissance"
            suggested_actions = [
                "Perform complete target analysis",
                "Gather all available information",
                "Establish comprehensive attack surface map",
                "Do not skip any reconnaissance steps",
            ]
        elif used_percentage < 50:
            current_depth = "medium"
            depth_reason = "25-50% time used, recommend continuing in-depth analysis"
            suggested_actions = [
                "Continue detailed vulnerability analysis",
                "Cross-verify with multiple tools",
                "Gather more contextual information",
                "Explore potential attack chains",
            ]
        elif used_percentage < 75:
            current_depth = "deep"
            depth_reason = "50-75% time used, should conduct in-depth analysis and verification"
            suggested_actions = [
                "Verify discovered vulnerabilities",
                "Conduct in-depth technical analysis",
                "Assess actual impact of vulnerabilities",
                "Prepare detailed report",
            ]
        elif used_percentage < 90:
            current_depth = "very_deep"
            depth_reason = "75-90% time used, should complete analysis and prepare conclusions"
            suggested_actions = [
                "Complete verification of all critical vulnerabilities",
                "Perform final cross-checks",
                "Prepare final report",
                "Summarize key findings",
            ]
        else:
            current_depth = "critical"
            depth_reason = "90%+ time used, should immediately complete analysis and provide conclusions"
            suggested_actions = [
                "Immediately complete critical tasks",
                "Summarize all findings",
                "Provide final conclusions",
                "Do not conduct new analysis",
            ]

        # Time pressure assessment
        if remaining > 3600:  # More than 1 hour
            time_pressure_level = "low"
            time_pressure_message = "Sufficient time available for comprehensive security assessment"
        elif remaining > 1800:  # 30 minutes to 1 hour
            time_pressure_level = "moderate"
            time_pressure_message = "Moderate time available, recommend balancing depth and efficiency"
        elif remaining > 600:  # 10 to 30 minutes
            time_pressure_level = "high"
            time_pressure_message = "Time is tight, should prioritize critical tasks"
        else:
            time_pressure_level = "critical"
            time_pressure_message = "Severely insufficient time, immediately complete analysis and provide conclusions"

        result.update(
            {
                "time_budget": {
                    "total_budget": total_budget,
                    "remaining": round(remaining, 2),
                    "used_percentage": round(used_percentage, 2),
                    "remaining_percentage": round(100 - used_percentage, 2),
                },
                "depth_recommendation": {
                    "current_depth": current_depth,
                    "reason": depth_reason,
                    "suggested_actions": suggested_actions,
                },
                "time_pressure": {"level": time_pressure_level, "message": time_pressure_message},
            }
        )

    return result


# Create tool wrapper
get_execution_elapsed_time = tool(_get_execution_elapsed_time_impl)


def should_continue_analysis_impl(session_id: Optional[str] = None, min_remaining_time: int = 300) -> Dict[str, Any]:
    """
    Determine whether to continue conducting in-depth analysis.

    Parameters:
    - session_id: Session ID (optional)
    - min_remaining_time: Minimum remaining time in seconds, default 300 seconds (5 minutes)

    Returns information containing whether to continue, reason, elapsed time, remaining time,
    suggested next action, and current depth level.

    Purpose:
    - Help Agent decide whether to continue in-depth analysis
    - Avoid unnecessary analysis when time is insufficient
    - Ensure comprehensive assessment when time is available
    """
    analysis = _get_execution_elapsed_time_impl(session_id, format_type="analysis")

    remaining = analysis["time_budget"]["remaining"]
    should_continue = remaining > min_remaining_time

    if should_continue:
        reason = (
            f"Sufficient time available ({int(remaining)} seconds remaining), recommend continuing in-depth analysis"
        )
        next_action = analysis["depth_recommendation"]["suggested_actions"][0]
    else:
        reason = f"Insufficient time ({int(remaining)} seconds remaining), should complete analysis"
        next_action = "Immediately complete analysis and provide final conclusions"

    return {
        "should_continue": should_continue,
        "reason": reason,
        "elapsed": analysis["elapsed_seconds"],
        "remaining": remaining,
        "next_action": next_action,
        "depth_level": analysis["depth_recommendation"]["current_depth"],
    }


def get_time_aware_guidance_impl(
    session_id: Optional[str] = None, task_type: str = "security_assessment"
) -> Dict[str, Any]:
    """
    Get detailed guidance based on time and task type.

    Parameters:
    - session_id: Session ID (optional)
    - task_type: Task type ("security_assessment", "vulnerability_hunting", "penetration_testing", or "bug_bounty")

    Returns information containing task type, current phase, time allocation, guidance,
    critical tasks, actions to avoid, depth level, and time pressure.

    Purpose:
    - Provide Agent with detailed guidance based on time and task type
    - Ensure Agent does not conduct superficial analysis
    - Adjust task depth based on time budget
    - Prioritize completion of critical tasks
    """
    analysis = _get_execution_elapsed_time_impl(session_id, format_type="analysis")
    elapsed = analysis["elapsed_seconds"]

    # Define time allocation for different task types
    time_allocations = {
        "security_assessment": {
            "reconnaissance": 1800,  # 30 minutes
            "vulnerability_scanning": 1800,  # 30 minutes
            "detailed_analysis": 1800,  # 30 minutes
            "verification": 900,  # 15 minutes
            "reporting": 900,  # 15 minutes
        },
        "vulnerability_hunting": {
            "target_analysis": 1200,  # 20 minutes
            "automated_scanning": 1800,  # 30 minutes
            "manual_testing": 2400,  # 40 minutes
            "verification": 600,  # 10 minutes
            "documentation": 600,  # 10 minutes
        },
        "penetration_testing": {
            "planning": 1200,  # 20 minutes
            "reconnaissance": 1800,  # 30 minutes
            "exploitation": 2400,  # 40 minutes
            "post_exploitation": 1200,  # 20 minutes
            "reporting": 600,  # 10 minutes
        },
        "bug_bounty": {
            "scope_analysis": 600,  # 10 minutes
            "reconnaissance": 1800,  # 30 minutes
            "vulnerability_hunting": 2400,  # 40 minutes
            "verification": 1200,  # 20 minutes
            "documentation": 600,  # 10 minutes
        },
    }

    allocation = time_allocations.get(task_type, time_allocations["security_assessment"])

    # Calculate current phase
    cumulative = 0
    current_phase = None
    phase_progress = {}

    for phase, allocated in allocation.items():
        phase_start = cumulative
        phase_end = cumulative + allocated

        if elapsed < phase_end:
            current_phase = phase

        used = min(elapsed - phase_start, allocated) if elapsed > phase_start else 0
        remaining = max(0, allocated - used)

        phase_progress[phase] = {
            "allocated": allocated,
            "used": round(max(0, used), 2),
            "remaining": round(remaining, 2),
            "percentage": round((used / allocated * 100) if allocated > 0 else 0, 2),
        }

        cumulative += allocated

    # Generate guidance
    if current_phase:
        phase_info = phase_progress[current_phase]
        if phase_info["percentage"] < 30:
            guidance = f"You just started the {current_phase} phase, should conduct comprehensive analysis without skipping any steps"
        elif phase_info["percentage"] < 70:
            guidance = f"You are in the {current_phase} phase ({phase_info['percentage']:.0f}% progress), recommend continuing in-depth analysis"
        else:
            guidance = f"You are about to complete the {current_phase} phase, should prepare to enter the next phase"
    else:
        guidance = "You have completed all phases, should prepare the final report"

    # Determine critical tasks
    critical_tasks = []
    if current_phase in ["reconnaissance", "target_analysis", "scope_analysis"]:
        critical_tasks = [
            "Gather all available information",
            "Establish comprehensive attack surface map",
            "Identify all potential targets",
        ]
    elif current_phase in ["vulnerability_scanning", "automated_scanning"]:
        critical_tasks = [
            "Run multiple scanning tools for cross-verification",
            "Collect detailed scan results",
            "Analyze all discovered vulnerabilities",
        ]
    elif current_phase in ["detailed_analysis", "vulnerability_hunting", "manual_testing"]:
        critical_tasks = [
            "Conduct in-depth technical analysis",
            "Verify findings from automated tools",
            "Explore potential attack chains",
            "Perform manual testing to discover vulnerabilities missed by automated tools",
        ]
    elif current_phase in ["verification", "exploitation", "post_exploitation"]:
        critical_tasks = [
            "Verify all discovered vulnerabilities",
            "Assess actual impact of vulnerabilities",
            "Conduct in-depth technical analysis",
            "Complete all critical tasks",
        ]
    else:
        critical_tasks = ["Complete final report", "Summarize all findings", "Provide recommendations"]

    # Actions to avoid
    avoid_actions = [
        "Do not conduct superficial analysis, ensure in-depth analysis",
        "Do not skip any critical steps",
        "Do not rely solely on automated tools, perform manual verification",
        "Do not provide conclusions without sufficient evidence",
        "Do not ignore low-risk vulnerabilities, they may lead to high-risk attack chains",
    ]

    return {
        "task_type": task_type,
        "current_phase": current_phase or "completed",
        "time_allocation": phase_progress,
        "guidance": guidance,
        "critical_tasks": critical_tasks,
        "avoid_actions": avoid_actions,
        "depth_level": analysis["depth_recommendation"]["current_depth"],
        "time_pressure": analysis["time_pressure"]["level"],
    }


# Create tool wrappers
should_continue_analysis = tool(should_continue_analysis_impl)
get_time_aware_guidance = tool(get_time_aware_guidance_impl)


# Export public API
__all__ = [
    "ExecutionTimeTracker",
    "get_current_time",
    "get_execution_elapsed_time",
    "should_continue_analysis",
    "get_time_aware_guidance",
]
