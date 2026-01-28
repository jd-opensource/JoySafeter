"""
Display models for Rich CLI output.

This module contains data models for rendering Agent execution state
using the Rich library. These models are used by RichConsoleCallback
to provide structured, visual CLI output.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# T004: ToolStatus enum
class ToolStatus(str, Enum):
    """Status of a tool execution."""

    PENDING = "pending"  # ⏳ Waiting to execute
    RUNNING = "running"  # 🔄 Currently executing
    SUCCESS = "success"  # ✅ Completed successfully
    FAILED = "failed"  # ❌ Failed with error


# T005: StepStatus enum
class StepStatus(str, Enum):
    """Status of an execution plan step."""

    PENDING = "pending"  # ⏳ Waiting to execute
    IN_PROGRESS = "in_progress"  # 🔄 Currently executing
    COMPLETED = "completed"  # ✅ Completed successfully
    FAILED = "failed"  # ❌ Failed with error
    SKIPPED = "skipped"  # ⏭️ Skipped


# T006: ToolCallDisplay dataclass
@dataclass
class ToolCallDisplay:
    """Display data for a single tool call."""

    run_id: str  # Unique identifier
    tool_name: str  # Tool name
    input_data: Dict[str, Any]  # Input parameters
    output_data: Optional[str] = None  # Output result
    status: ToolStatus = ToolStatus.PENDING
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None

    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate execution duration in milliseconds."""
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return None

    @property
    def duration_str(self) -> str:
        """Format duration as human-readable string."""
        if self.duration_ms is None:
            return ""
        seconds = self.duration_ms / 1000
        if seconds < 1:
            return f"{self.duration_ms}ms"
        return f"{seconds:.1f}s"

    @property
    def is_truncated(self) -> bool:
        """Check if output should be truncated (>20 lines or >2000 chars)."""
        if not self.output_data:
            return False
        lines = self.output_data.count("\n") + 1
        return lines > 20 or len(self.output_data) > 2000

    def get_truncated_output(self, max_lines: int = 20, max_chars: int = 2000) -> str:
        """Get truncated output with summary."""
        if not self.output_data:
            return ""

        lines = self.output_data.split("\n")
        total_lines = len(lines)

        if total_lines <= max_lines and len(self.output_data) <= max_chars:
            return self.output_data

        # Truncate by lines first
        truncated_lines = lines[:max_lines]
        result = "\n".join(truncated_lines)

        # Then truncate by chars if needed
        if len(result) > max_chars:
            result = result[:max_chars]

        return f"{result}\n... ({total_lines} lines total)"


# T007: ThinkingDisplay dataclass
@dataclass
class ThinkingDisplay:
    """Display data for LLM thinking process."""

    content: str  # Thinking content (from think tool)
    timestamp: datetime = field(default_factory=datetime.now)
    is_collapsed: bool = True  # Default to collapsed

    @property
    def summary(self) -> str:
        """Generate a summary of the thinking content."""
        first_line = self.content.split("\n")[0]
        if len(first_line) > 80:
            return first_line[:77] + "..."
        return first_line


# T008: ExecutionStep dataclass
@dataclass
class ExecutionStep:
    """A single step in an execution plan."""

    index: int  # Step number (1-based)
    description: str  # Step description
    status: StepStatus = StepStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None

    @property
    def status_icon(self) -> str:
        """Get status icon for display."""
        icons = {
            StepStatus.PENDING: "⏳",
            StepStatus.IN_PROGRESS: "🔄",
            StepStatus.COMPLETED: "✅",
            StepStatus.FAILED: "❌",
            StepStatus.SKIPPED: "⏭️",
        }
        return icons.get(self.status, "❓")


# T009: ExecutionPlan dataclass
@dataclass
class ExecutionPlan:
    """Execution plan state management."""

    steps: List[ExecutionStep] = field(default_factory=list)
    current_step_index: int = 0  # Current step (0-based)
    start_time: datetime = field(default_factory=datetime.now)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)

    @property
    def progress_percentage(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100

    def advance(self) -> None:
        """Advance to the next step."""
        if self.current_step_index < len(self.steps):
            self.steps[self.current_step_index].status = StepStatus.COMPLETED
            self.steps[self.current_step_index].end_time = datetime.now()
        self.current_step_index += 1
        if self.current_step_index < len(self.steps):
            self.steps[self.current_step_index].status = StepStatus.IN_PROGRESS
            self.steps[self.current_step_index].start_time = datetime.now()

    def mark_failed(self, error_message: Optional[str] = None) -> None:
        """Mark current step as failed."""
        if self.current_step_index < len(self.steps):
            self.steps[self.current_step_index].status = StepStatus.FAILED
            self.steps[self.current_step_index].end_time = datetime.now()
            self.steps[self.current_step_index].error_message = error_message

    @classmethod
    def from_descriptions(cls, descriptions: List[str]) -> "ExecutionPlan":
        """Create an execution plan from step descriptions."""
        steps = [ExecutionStep(index=i + 1, description=desc) for i, desc in enumerate(descriptions)]
        return cls(steps=steps)


# T010: DisplayState dataclass
@dataclass
class DisplayState:
    """Global state for CLI display."""

    is_live: bool = False  # Whether in Live context
    current_phase: str = "idle"  # idle | thinking | tool_call | result
    execution_plan: Optional[ExecutionPlan] = None
    active_tools: Dict[str, ToolCallDisplay] = field(default_factory=dict)
    thinking_history: List[ThinkingDisplay] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since start."""
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def elapsed_str(self) -> str:
        """Format elapsed time as human-readable string."""
        seconds = self.elapsed_seconds
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    def reset(self) -> None:
        """Reset state for new execution."""
        self.is_live = False
        self.current_phase = "idle"
        self.execution_plan = None
        self.active_tools.clear()
        self.thinking_history.clear()
        self.start_time = datetime.now()
