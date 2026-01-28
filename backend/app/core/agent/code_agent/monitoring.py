#!/usr/bin/env python
# coding=utf-8
"""
Monitoring and logging for CodeAgent.

This module provides monitoring, token tracking, timing, and logging
utilities for agent execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Optional

try:
    from rich import box
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.tree import Tree

    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    Console = None  # type: ignore[assignment, misc]

if TYPE_CHECKING:
    from .memory import ActionStep, PlanningStep


__all__ = ["AgentLogger", "LogLevel", "Monitor", "TokenUsage", "Timing"]


# Color constants for rich output
YELLOW_HEX = "#d4b702"
BLUE_HEX = "#1E90FF"


@dataclass
class TokenUsage:
    """
    Token usage information for a step or entire run.

    Attributes:
        input_tokens: Number of tokens in the input/prompt.
        output_tokens: Number of tokens in the output/response.
        total_tokens: Total tokens used (auto-calculated).
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int = field(init=False)

    def __post_init__(self):
        self.total_tokens = self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """Add two TokenUsage instances together."""
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    def __repr__(self) -> str:
        return f"TokenUsage(input={self.input_tokens}, output={self.output_tokens}, total={self.total_tokens})"


@dataclass
class Timing:
    """
    Timing information for a step or run.

    Attributes:
        start_time: Unix timestamp when the operation started.
        end_time: Unix timestamp when the operation ended (None if still running).
    """

    start_time: float
    end_time: float | None = None

    @classmethod
    def start_now(cls) -> "Timing":
        """Create a new Timing starting now."""
        return cls(start_time=time.time())

    def stop(self) -> None:
        """Mark the timing as complete."""
        self.end_time = time.time()

    @property
    def duration(self) -> float | None:
        """Get the duration in seconds (None if not complete)."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    @property
    def duration_ms(self) -> float | None:
        """Get the duration in milliseconds (None if not complete)."""
        duration = self.duration
        return duration * 1000 if duration is not None else None

    def dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }

    def __repr__(self) -> str:
        return f"Timing(duration={self.duration:.3f}s)" if self.duration else "Timing(running)"


class Monitor:
    """
    Monitors agent execution, tracking step durations and token usage.

    The monitor collects metrics during agent execution and can provide
    summary statistics at the end.

    Attributes:
        step_durations: List of durations for each step.
        total_input_token_count: Total input tokens across all steps.
        total_output_token_count: Total output tokens across all steps.
    """

    def __init__(self, logger: "AgentLogger | None" = None):
        """
        Initialize the monitor.

        Args:
            logger: Optional logger for output. If None, metrics are tracked silently.
        """
        self.logger = logger
        self.step_durations: list[float] = []
        self.total_input_token_count: int = 0
        self.total_output_token_count: int = 0
        self._start_time: float | None = None
        self._end_time: float | None = None

    def start(self) -> None:
        """Start monitoring a new run."""
        self._start_time = time.time()
        self._end_time = None

    def stop(self) -> None:
        """Stop monitoring the current run."""
        self._end_time = time.time()

    def get_total_token_counts(self) -> TokenUsage:
        """Get the total token usage across all steps."""
        return TokenUsage(
            input_tokens=self.total_input_token_count,
            output_tokens=self.total_output_token_count,
        )

    def get_total_duration(self) -> float | None:
        """Get the total run duration in seconds."""
        if self._start_time is None:
            return None
        end = self._end_time or time.time()
        return end - self._start_time

    def reset(self) -> None:
        """Reset all metrics."""
        self.step_durations = []
        self.total_input_token_count = 0
        self.total_output_token_count = 0
        self._start_time = None
        self._end_time = None

    def update_metrics(
        self,
        step_log: "ActionStep | PlanningStep | None" = None,
        duration: float | None = None,
        token_usage: TokenUsage | None = None,
    ) -> None:
        """
        Update metrics with a new step's data.

        Args:
            step_log: A memory step with timing and token_usage attributes.
            duration: Alternatively, provide duration directly.
            token_usage: Alternatively, provide token usage directly.
        """
        # Get duration from step_log if available
        if step_log is not None:
            if hasattr(step_log, "metrics") and step_log.metrics is not None:
                step_duration = step_log.metrics.duration_ms / 1000 if step_log.metrics.duration_ms else None
            else:
                step_duration = duration
        else:
            step_duration = duration

        if step_duration is not None:
            self.step_durations.append(step_duration)

        # Update token counts
        if token_usage is not None:
            self.total_input_token_count += token_usage.input_tokens
            self.total_output_token_count += token_usage.output_tokens
        elif step_log is not None:
            if hasattr(step_log, "metrics") and step_log.metrics is not None:
                self.total_input_token_count += step_log.metrics.input_tokens
                self.total_output_token_count += step_log.metrics.output_tokens

        # Log if logger is available
        if self.logger is not None:
            step_num = len(self.step_durations)
            console_outputs = f"[Step {step_num}"
            if step_duration is not None:
                console_outputs += f": Duration {step_duration:.2f}s"
            if self.total_input_token_count > 0 or self.total_output_token_count > 0:
                console_outputs += (
                    f" | Tokens: {self.total_input_token_count:,} in, {self.total_output_token_count:,} out"
                )
            console_outputs += "]"
            self.logger.log(console_outputs, level=LogLevel.DEBUG)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all metrics."""
        return {
            "step_count": len(self.step_durations),
            "total_duration": self.get_total_duration(),
            "step_durations": self.step_durations,
            "average_step_duration": (
                sum(self.step_durations) / len(self.step_durations) if self.step_durations else None
            ),
            "token_usage": self.get_total_token_counts().dict(),
        }

    def __repr__(self) -> str:
        return f"Monitor(steps={len(self.step_durations)}, tokens={self.get_total_token_counts()})"


class LogLevel(IntEnum):
    """Log levels for agent output."""

    OFF = -1  # No output
    ERROR = 0  # Only errors
    INFO = 1  # Normal output (default)
    DEBUG = 2  # Detailed output


class AgentLogger:
    """
    Logger for agent execution with rich formatting support.

    Provides methods for logging various types of content including
    code, markdown, tasks, and structured data with optional rich formatting.
    """

    console: Optional[Console]

    def __init__(
        self,
        level: LogLevel = LogLevel.INFO,
        console: Console | None = None,
        use_rich: bool = True,
    ):
        """
        Initialize the logger.

        Args:
            level: Minimum log level to display.
            console: Optional rich Console instance.
            use_rich: Whether to use rich formatting (requires rich package).
        """
        self.level = level
        self._use_rich = use_rich and HAS_RICH

        if self._use_rich:
            if console is not None:
                self.console = console
            else:
                self.console = Console(highlight=False)
        else:
            self.console = None

    def log(
        self,
        *args,
        level: int | str | LogLevel = LogLevel.INFO,
        **kwargs,
    ) -> None:
        """
        Log a message.

        Args:
            *args: Arguments to print.
            level: Log level for this message.
            **kwargs: Additional arguments for print/console.print.
        """
        # Convert string level to LogLevel
        if isinstance(level, str):
            level = LogLevel[level.upper()]

        # Check if we should log
        if level > self.level:
            return

        if self._use_rich and self.console:
            self.console.print(*args, **kwargs)
        else:
            # Strip rich markup for plain output
            print(*args)

    def log_error(self, error_message: str) -> None:
        """Log an error message."""
        if self._use_rich and self.console:
            self.console.print(
                _escape_brackets(error_message),
                style="bold red",
            )
        else:
            print(f"ERROR: {error_message}")

    def log_code(
        self,
        title: str,
        content: str,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        """
        Log a code block with syntax highlighting.

        Args:
            title: Title for the code block.
            content: The code content.
            level: Log level.
        """
        if level > self.level:
            return

        if self._use_rich and self.console:
            self.console.print(
                Panel(
                    Syntax(
                        content,
                        lexer="python",
                        theme="monokai",
                        word_wrap=True,
                    ),
                    title=f"[bold]{title}",
                    title_align="left",
                    box=box.HORIZONTALS,
                )
            )
        else:
            print(f"\n=== {title} ===")
            print(content)
            print("=" * (len(title) + 8))

    def log_markdown(
        self,
        content: str,
        title: str | None = None,
        level: LogLevel = LogLevel.INFO,
        style: str = YELLOW_HEX,
    ) -> None:
        """
        Log markdown content.

        Args:
            content: Markdown content to log.
            title: Optional title.
            level: Log level.
            style: Color style for the title.
        """
        if level > self.level:
            return

        if self._use_rich and self.console:
            markdown_content = Syntax(
                content,
                lexer="markdown",
                theme="github-dark",
                word_wrap=True,
            )
            if title:
                self.console.print(
                    Group(
                        Rule(
                            f"[bold italic]{title}",
                            align="left",
                            style=style,
                        ),
                        markdown_content,
                    )
                )
            else:
                self.console.print(markdown_content)
        else:
            if title:
                print(f"\n--- {title} ---")
            print(content)

    def log_task(
        self,
        content: str,
        subtitle: str = "",
        title: str | None = None,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        """
        Log a new task.

        Args:
            content: Task description.
            subtitle: Subtitle text.
            title: Optional title override.
            level: Log level.
        """
        if level > self.level:
            return

        if self._use_rich and self.console:
            panel_title = "[bold]New run"
            if title:
                panel_title += f" - {title}"

            self.console.print(
                Panel(
                    f"\n[bold]{_escape_brackets(content)}\n",
                    title=panel_title,
                    subtitle=subtitle,
                    border_style=YELLOW_HEX,
                    subtitle_align="left",
                )
            )
        else:
            print(f"\n{'=' * 50}")
            if title:
                print(f"New run - {title}")
            else:
                print("New run")
            print(f"{'=' * 50}")
            print(content)
            if subtitle:
                print(f"({subtitle})")
            print()

    def log_rule(self, title: str, level: LogLevel = LogLevel.INFO) -> None:
        """
        Log a horizontal rule with title.

        Args:
            title: Text to display in the rule.
            level: Log level.
        """
        if level > self.level:
            return

        if self._use_rich and self.console:
            self.console.print(
                Rule(
                    f"[bold white]{title}",
                    characters="━",
                    style=YELLOW_HEX,
                )
            )
        else:
            print(f"\n{'━' * 20} {title} {'━' * 20}")

    def log_step(
        self,
        step_number: int,
        thought: str = "",
        code: str = "",
        observation: str = "",
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        """
        Log a complete agent step.

        Args:
            step_number: The step number.
            thought: The agent's reasoning.
            code: The code generated.
            observation: The execution result.
            level: Log level.
        """
        if level > self.level:
            return

        self.log_rule(f"Step {step_number}", level=level)

        if thought:
            self.log_markdown(thought, title="Thought", level=level)

        if code:
            self.log_code("Code", code, level=level)

        if observation:
            self.log_markdown(observation, title="Observation", level=level)

    def log_final_answer(
        self,
        answer: Any,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        """
        Log the final answer.

        Args:
            answer: The final answer.
            level: Log level.
        """
        if level > self.level:
            return

        if self._use_rich and self.console:
            self.console.print(
                Panel(
                    f"[bold green]{_escape_brackets(str(answer))}",
                    title="[bold]Final Answer",
                    border_style="green",
                )
            )
        else:
            print(f"\n{'=' * 50}")
            print("FINAL ANSWER:")
            print(answer)
            print(f"{'=' * 50}\n")

    def visualize_agent_tree(self, agent) -> None:
        """
        Visualize the agent hierarchy as a tree.

        Args:
            agent: The root agent to visualize.
        """
        if not self._use_rich or not self.console:
            # Simple text representation
            print(f"Agent: {agent.name}")
            if hasattr(agent, "tools") and agent.tools:
                print("  Tools:")
                for name in agent.tools:
                    print(f"    - {name}")
            return

        def create_tools_section(tools_dict):
            table = Table(show_header=True, header_style="bold")
            table.add_column("Name", style=BLUE_HEX)
            table.add_column("Description")

            for name, tool in tools_dict.items():
                description = getattr(tool, "description", str(tool))
                if len(description) > 80:
                    description = description[:77] + "..."
                table.add_row(name, description)

            return Group(f"🛠️ [italic {BLUE_HEX}]Tools:", table)

        def get_agent_headline(agent, name: str | None = None):
            name_part = f"{name} | " if name else ""
            class_name = agent.__class__.__name__
            return f"[bold {YELLOW_HEX}]{name_part}{class_name}"

        def build_agent_tree(parent_tree, agent_obj):
            if hasattr(agent_obj, "tools") and agent_obj.tools:
                parent_tree.add(create_tools_section(agent_obj.tools))

            if hasattr(agent_obj, "managed_agents") and agent_obj.managed_agents:
                agents_branch = parent_tree.add(f"🤖 [italic {BLUE_HEX}]Managed agents:")
                for name, managed_agent in agent_obj.managed_agents.items():
                    agent_tree = agents_branch.add(get_agent_headline(managed_agent, name))
                    if hasattr(managed_agent, "description"):
                        agent_tree.add(f"📝 Description: {managed_agent.description}")
                    build_agent_tree(agent_tree, managed_agent)

        main_tree = Tree(get_agent_headline(agent))
        if hasattr(agent, "description") and agent.description:
            main_tree.add(f"📝 Description: {agent.description}")
        build_agent_tree(main_tree, agent)
        self.console.print(main_tree)


def _escape_brackets(text: str) -> str:
    """Escape brackets for rich output."""
    if not isinstance(text, str):
        text = str(text)
    return text.replace("[", "\\[").replace("]", "\\]")
