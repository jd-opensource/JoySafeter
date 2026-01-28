"""
Awareness Tools Module - Time Awareness and Task Autonomy

Exports all awareness tools for Agent use, including:
1. Time awareness tools - Help Agent understand time progress
2. Task autonomy tools - Guide Agent to complete tasks autonomously, exhausting all methods
"""

from app.dynamic_agent.tools.awares.task_autonomy import TaskState, should_continue_task
from app.dynamic_agent.tools.awares.time_awares import (
    ExecutionTimeTracker,
    get_current_time,
    get_execution_elapsed_time,
    get_time_aware_guidance,
    should_continue_analysis,
)

__all__ = [
    # Time awareness tools
    "ExecutionTimeTracker",
    "get_current_time",
    "get_execution_elapsed_time",
    "should_continue_analysis",
    "get_time_aware_guidance",
    # Task autonomy tools
    "TaskState",
    "should_continue_task",
]

# Export LangChain tools list
time_aware_tools = [get_current_time, get_execution_elapsed_time, should_continue_analysis, get_time_aware_guidance]

# Task autonomy tools list
task_autonomy_tools = [should_continue_task]

# All awareness tools
all_aware_tools = time_aware_tools + task_autonomy_tools
