#!/usr/bin/env python
# coding=utf-8
"""
Memory management for CodeAgent.

This module implements AgentMemory, ActionStep, and related types
for managing agent execution history and state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class StepType(str, Enum):
    """Types of steps in agent execution."""

    SYSTEM_PROMPT = "system_prompt"
    USER_MESSAGE = "user_message"
    THOUGHT = "thought"
    ACTION = "action"  # Code execution
    OBSERVATION = "observation"
    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"
    PLANNING = "planning"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class StepMetrics:
    """Metrics for a single step."""

    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def complete(self) -> None:
        """Mark the step as complete and calculate duration."""
        self.end_time = datetime.now()
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000


@dataclass
class ChatMessage:
    """Represents a chat message for LLM interaction."""

    role: str  # "system", "user", "assistant"
    content: str

    def dict(self) -> dict[str, str]:
        """Convert to dictionary."""
        return {"role": self.role, "content": self.content}


@dataclass
class ActionStep:
    """
    Represents a single code action step in the agent's execution.

    This is the core unit of the Thought-Code-Observation cycle.
    """

    # Step identification
    step_number: int

    # The thought/reasoning before the action
    thought: str = ""

    # The code to execute
    code: str = ""

    # The observation/output from executing the code
    observation: str = ""

    # Raw LLM output that produced this step
    llm_output: str = ""

    # Error if any
    error: str | None = None

    # Whether this step produced the final answer
    is_final_answer: bool = False

    # The final answer if is_final_answer is True
    final_answer: Any = None

    # Metrics
    metrics: StepMetrics = field(default_factory=StepMetrics)

    # Metadata
    metadata: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if this step executed successfully."""
        return self.error is None

    def format_for_prompt(self, include_thought: bool = True) -> str:
        """Format this step for inclusion in a prompt."""
        parts = []

        if include_thought and self.thought:
            parts.append(f"Thought: {self.thought}")

        if self.code:
            parts.append(f"Code:\n```python\n{self.code}\n```")

        if self.observation:
            parts.append(f"Observation: {self.observation}")

        if self.error:
            parts.append(f"Error: {self.error}")

        return "\n\n".join(parts)

    def to_messages(self, summary_mode: bool = False) -> list[ChatMessage]:
        """
        Convert this step to a list of chat messages.

        Args:
            summary_mode: If True, include only essential information.

        Returns:
            List of ChatMessage objects.
        """
        messages = []

        # Assistant message with thought and code
        assistant_content = ""
        if self.thought:
            assistant_content += f"Thought: {self.thought}\n\n"
        if self.code:
            if summary_mode:
                # In summary mode, just indicate code was run
                assistant_content += f"Code: [executed {len(self.code.splitlines())} lines]"
            else:
                assistant_content += f"Code:\n```python\n{self.code}\n```"

        if assistant_content:
            messages.append(ChatMessage(role="assistant", content=assistant_content.strip()))

        # User message with observation (code output is user feedback)
        if self.observation or self.error:
            if self.error:
                obs_content = f"Error: {self.error}"
            else:
                if summary_mode and len(self.observation) > 500:
                    obs_content = f"Observation: {self.observation[:500]}... [truncated]"
                else:
                    obs_content = f"Observation: {self.observation}"
            messages.append(ChatMessage(role="user", content=obs_content))

        return messages

    def __repr__(self) -> str:
        return f"ActionStep(step={self.step_number}, success={self.success}, final={self.is_final_answer})"


@dataclass
class PlanningStep:
    """
    Represents a planning step in the agent's execution.

    Used when the agent needs to create or update a plan.
    """

    # The plan content
    plan: str = ""

    # Whether this is an update to an existing plan
    is_update: bool = False

    # The previous plan (if updating)
    previous_plan: str = ""

    # Raw LLM output
    llm_output: str = ""

    # Metrics
    metrics: StepMetrics = field(default_factory=StepMetrics)

    def format_for_prompt(self) -> str:
        """Format this planning step for inclusion in a prompt."""
        if self.is_update:
            return f"Updated Plan:\n{self.plan}"
        return f"Plan:\n{self.plan}"

    def to_messages(self, summary_mode: bool = False) -> list[ChatMessage]:
        """
        Convert this step to a list of chat messages.

        Args:
            summary_mode: If True, include only essential information.

        Returns:
            List of ChatMessage objects.
        """
        prefix = "Updated Plan" if self.is_update else "Plan"
        content = f"{prefix}:\n{self.plan}"

        if summary_mode and len(content) > 500:
            content = content[:500] + "... [truncated]"

        return [ChatMessage(role="assistant", content=content)]


@dataclass
class ToolCallStep:
    """Represents a tool call step."""

    tool_name: str
    tool_args: dict = field(default_factory=dict)
    tool_result: Any = None
    error: str | None = None
    metrics: StepMetrics = field(default_factory=StepMetrics)


@dataclass
class MessageStep:
    """Represents a message step (system or user)."""

    role: str  # "system", "user", "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


class AgentMemory:
    """
    Memory management for CodeAgent execution.

    Stores and manages the history of steps during agent execution,
    including thoughts, actions, observations, and planning.
    """

    def __init__(self, max_steps: int = 100):
        """
        Initialize agent memory.

        Args:
            max_steps: Maximum number of steps to retain.
        """
        self.max_steps = max_steps
        self._steps: list[ActionStep | PlanningStep | ToolCallStep | MessageStep] = []
        self._task: str = ""
        self._task_images: list[str] = []
        self._system_prompt: str = ""
        self._current_plan: str = ""
        self._start_time: datetime = datetime.now()
        self._end_time: datetime | None = None

        # Token usage
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    @property
    def task(self) -> str:
        """Get the current task."""
        return self._task

    @task.setter
    def task(self, value: str) -> None:
        """Set the current task."""
        self._task = value

    @property
    def system_prompt(self) -> str:
        """Get the system prompt."""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        """Set the system prompt."""
        self._system_prompt = value

    @property
    def current_plan(self) -> str:
        """Get the current plan."""
        return self._current_plan

    @current_plan.setter
    def current_plan(self, value: str) -> None:
        """Set the current plan."""
        self._current_plan = value

    @property
    def steps(self) -> list[ActionStep | PlanningStep | ToolCallStep | MessageStep]:
        """Get all steps."""
        return self._steps

    @property
    def action_steps(self) -> list[ActionStep]:
        """Get only action steps."""
        return [s for s in self._steps if isinstance(s, ActionStep)]

    @property
    def step_count(self) -> int:
        """Get the number of action steps."""
        return len(self.action_steps)

    def add_step(self, step: ActionStep | PlanningStep | ToolCallStep | MessageStep) -> None:
        """
        Add a step to memory.

        Args:
            step: The step to add.
        """
        self._steps.append(step)

        # Trim if exceeding max
        if len(self._steps) > self.max_steps:
            # Keep first step (usually system prompt) and last steps
            self._steps = [self._steps[0]] + self._steps[-(self.max_steps - 1) :]

    def create_action_step(self) -> ActionStep:
        """Create a new action step with the next step number."""
        step_num = len(self.action_steps) + 1
        step = ActionStep(step_number=step_num)
        return step

    def get_last_step(self) -> ActionStep | PlanningStep | ToolCallStep | MessageStep | None:
        """Get the last step."""
        return self._steps[-1] if self._steps else None

    def get_last_action_step(self) -> ActionStep | None:
        """Get the last action step."""
        action_steps = self.action_steps
        return action_steps[-1] if action_steps else None

    def get_history_for_prompt(
        self,
        max_tokens: Optional[int] = None,
        include_system: bool = True,
        include_thoughts: bool = True,
    ) -> str:
        """
        Get formatted history for inclusion in a prompt.

        Args:
            max_tokens: Maximum tokens to include (approximate).
            include_system: Include system prompt.
            include_thoughts: Include thought sections.

        Returns:
            Formatted history string.
        """
        parts = []

        if include_system and self._system_prompt:
            parts.append(f"System: {self._system_prompt}")

        if self._task:
            parts.append(f"Task: {self._task}")

        if self._current_plan:
            parts.append(f"Current Plan:\n{self._current_plan}")

        for step in self._steps:
            if isinstance(step, ActionStep):
                parts.append(step.format_for_prompt(include_thought=include_thoughts))
            elif isinstance(step, PlanningStep):
                parts.append(step.format_for_prompt())
            elif isinstance(step, MessageStep):
                parts.append(f"{step.role.capitalize()}: {step.content}")

        history = "\n\n---\n\n".join(parts)

        # Truncate if needed (rough approximation: 4 chars per token)
        if max_tokens and len(history) > max_tokens * 4:
            history = history[-(max_tokens * 4) :]
            history = "...[truncated]\n\n" + history

        return history

    def get_total_duration_ms(self) -> float:
        """Get total execution duration in milliseconds."""
        end = self._end_time or datetime.now()
        return (end - self._start_time).total_seconds() * 1000

    def complete(self) -> None:
        """Mark execution as complete."""
        self._end_time = datetime.now()

    def reset(self) -> None:
        """Reset memory to initial state."""
        self._steps = []
        self._task = ""
        self._task_images = []
        self._current_plan = ""
        self._start_time = datetime.now()
        self._end_time = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def to_dict(self) -> dict:
        """Convert memory to dictionary for serialization."""
        return {
            "task": self._task,
            "system_prompt": self._system_prompt,
            "current_plan": self._current_plan,
            "step_count": self.step_count,
            "total_duration_ms": self.get_total_duration_ms(),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "steps": [
                {
                    "type": type(s).__name__,
                    "data": s.__dict__ if hasattr(s, "__dict__") else str(s),
                }
                for s in self._steps
            ],
        }

    def to_messages(self, summary_mode: bool = False) -> list[ChatMessage]:
        """
        Convert the entire memory to a list of chat messages.

        This is useful for sending the conversation history to an LLM
        in a standardized message format.

        Args:
            summary_mode: If True, use condensed representations.

        Returns:
            List of ChatMessage objects representing the conversation.
        """
        messages = []

        # System prompt
        if self._system_prompt:
            messages.append(ChatMessage(role="system", content=self._system_prompt))

        # Task as user message
        if self._task:
            task_content = f"Task: {self._task}"
            if self._current_plan:
                task_content += f"\n\nCurrent Plan:\n{self._current_plan}"
            messages.append(ChatMessage(role="user", content=task_content))

        # All steps
        for step in self._steps:
            if hasattr(step, "to_messages"):
                step_messages = step.to_messages(summary_mode=summary_mode)
                messages.extend(step_messages)
            elif isinstance(step, MessageStep):
                messages.append(ChatMessage(role=step.role, content=step.content))

        return messages

    def get_full_steps(self) -> list[Dict[str, Any]]:
        """
        Get all steps as dictionaries with full information.

        Returns:
            List of step dictionaries.
        """
        result: list[Dict[str, Any]] = []
        for step in self._steps:
            step_dict: Dict[str, Any] = {
                "type": type(step).__name__,
            }
            if isinstance(step, ActionStep):
                step_dict.update(
                    {
                        "step_number": step.step_number,
                        "thought": step.thought,
                        "code": step.code,
                        "observation": step.observation,
                        "error": step.error,
                        "is_final_answer": step.is_final_answer,
                        "success": step.success,
                    }
                )
            elif isinstance(step, PlanningStep):
                step_dict.update(
                    {
                        "plan": step.plan,
                        "is_update": step.is_update,
                    }
                )
            elif isinstance(step, MessageStep):
                step_dict.update(
                    {
                        "role": step.role,
                        "content": step.content,
                    }
                )
            result.append(step_dict)
        return result

    def return_full_code(self) -> str:
        """
        Return all executed code as a single concatenated string.

        Useful for debugging or reviewing what code was run.

        Returns:
            All executed code blocks joined with newlines.
        """
        code_blocks = []
        for step in self.action_steps:
            if step.code:
                code_blocks.append(f"# Step {step.step_number}")
                code_blocks.append(step.code)
        return "\n\n".join(code_blocks)

    def __repr__(self) -> str:
        return f"AgentMemory(steps={len(self._steps)}, action_steps={self.step_count})"


__all__ = [
    "StepType",
    "StepMetrics",
    "ChatMessage",
    "ActionStep",
    "PlanningStep",
    "ToolCallStep",
    "MessageStep",
    "AgentMemory",
]
