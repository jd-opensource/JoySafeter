#!/usr/bin/env python
# coding=utf-8
"""
CodeAgent - Main agent class for code-based task solving.

This module implements the main CodeAgent class that uses the
Thought-Code-Observation pattern to solve tasks through code generation
and execution.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any, Optional

from .executor import (
    LocalPythonExecutor,
    PythonExecutor,
    create_default_final_answer,
)
from .loop import CodeAgentLoop, LoopConfig, StepEvent
from .memory import ActionStep, AgentMemory, PlanningStep
from .monitoring import AgentLogger, LogLevel, Monitor
from .tools import Tool

# Type alias for final answer check functions
FinalAnswerCheck = Callable[[Any, AgentMemory, "CodeAgent"], bool]


class CodeAgent:
    """
    A code-based agent that solves tasks by generating and executing Python code.

    The agent follows a Thought → Code → Observation iterative pattern:
    1. Thinks about what to do next
    2. Generates Python code to execute
    3. Observes the results
    4. Repeats until reaching a final answer

    Features:
    - Secure code execution via AST interpretation
    - State persistence across execution steps
    - Tool injection for extended capabilities
    - Optional planning mode for complex tasks
    - Streaming execution events

    Example:
        >>> agent = CodeAgent(
        ...     llm=my_llm_function,
        ...     tools={"search": web_search, "fetch": http_fetch},
        ... )
        >>> result = await agent.run("Calculate the sum of primes under 100")
        >>> print(result)  # 1060
    """

    def __init__(
        self,
        llm: Callable[[str], str | AsyncGenerator[str, None]],
        tools: Optional[dict[str, Callable | Tool]] = None,
        executor: Optional[PythonExecutor] = None,
        config: Optional[LoopConfig] = None,
        name: str = "CodeAgent",
        description: Optional[str] = None,
        enable_data_analysis: bool = True,
        additional_authorized_imports: Optional[list[str]] = None,
        managed_agents: list["CodeAgent"] | None = None,
        final_answer_checks: list[FinalAnswerCheck] | None = None,
        step_callbacks: dict[type, list[Callable]] | None = None,
        logger: AgentLogger | None = None,
        verbosity: LogLevel = LogLevel.INFO,
    ):
        """
        Initialize the CodeAgent.

        Args:
            llm: Function to call the LLM. Takes prompt string, returns response.
                 Can be sync or async, can return string or async generator.
            tools: Dictionary of tools to inject into the executor.
            executor: Custom Python executor. If None, uses LocalPythonExecutor.
            config: Loop configuration options.
            name: Name of the agent.
            description: Description of the agent's purpose.
            enable_data_analysis: Enable data analysis modules (pandas, numpy, etc.).
            additional_authorized_imports: Additional Python modules to authorize.
            managed_agents: List of sub-agents that this agent can call as tools.
            final_answer_checks: List of validation functions for the final answer.
            step_callbacks: Dict mapping step types to callback functions.
            logger: Custom AgentLogger instance.
            verbosity: Log level for the agent.
        """
        self.name = name
        self.description = description or "A code-based agent for solving tasks"
        self.llm = llm
        self.verbosity = verbosity

        # Initialize logger and monitor
        self.logger = logger or AgentLogger(level=verbosity)
        self.monitor = Monitor(logger=self.logger)

        # Prepare tools - support both Callable and Tool instances
        self._tools: dict[str, Callable | Tool] = {"final_answer": create_default_final_answer()}
        if tools:
            for tool_name, tool_obj in tools.items():
                if isinstance(tool_obj, Tool):
                    self._tools[tool_obj.name] = tool_obj
                else:
                    self._tools[tool_name] = tool_obj

        # Setup managed agents as tools
        self.managed_agents: dict[str, "CodeAgent"] = {}
        if managed_agents:
            for agent in managed_agents:
                self.managed_agents[agent.name] = agent
                # Create a tool wrapper for the agent
                self._tools[agent.name] = self._create_agent_tool(agent)

        # Final answer validation checks
        self.final_answer_checks = final_answer_checks or []

        # Step callbacks registry
        self.step_callbacks = step_callbacks or {}

        # Initialize executor
        if executor is not None:
            self.executor = executor
        else:
            self.executor = LocalPythonExecutor(
                enable_data_analysis=enable_data_analysis,
                additional_authorized_imports=additional_authorized_imports,
            )

        self.executor.send_tools(self._tools)

        # Initialize loop
        self.config = config or LoopConfig()
        self._loop: CodeAgentLoop | None = None

        self.logger.log(
            f"CodeAgent '{name}' initialized with {len(self._tools)} tools, "
            f"{len(self.managed_agents)} managed agents, "
            f"executor={type(self.executor).__name__}",
            level=LogLevel.DEBUG,
        )

    @property
    def tools(self) -> dict[str, Callable | Tool]:
        """Get the available tools."""
        return self._tools

    @property
    def inputs(self) -> dict[str, dict[str, str | bool]]:
        """Get the input schema for this agent (when used as a managed agent)."""
        return {
            "task": {
                "type": "string",
                "description": "The task to perform.",
            },
            "additional_args": {
                "type": "object",
                "description": "Optional additional arguments.",
                "nullable": True,
            },
        }

    @property
    def output_type(self) -> str:
        """Get the output type for this agent."""
        return "any"

    def _create_agent_tool(self, agent: "CodeAgent") -> Callable:
        """
        Create a tool wrapper for a managed agent.

        Args:
            agent: The managed agent to wrap.

        Returns:
            A callable that invokes the agent.
        """

        async def agent_tool(task: str, additional_args: dict | None = None) -> Any:
            """
            Call a managed sub-agent.

            Args:
                task: The task to perform.
                additional_args: Optional additional context.

            Returns:
                The agent's result.
            """
            # Build the full task with additional args if provided
            full_task = task
            if additional_args:
                full_task += f"\n\nAdditional context: {additional_args}"

            return await agent.run(full_task)

        # Add metadata
        agent_tool.__name__ = agent.name
        agent_tool.__doc__ = agent.description

        return agent_tool

    def _validate_final_answer(
        self,
        final_answer: Any,
        memory: AgentMemory,
    ) -> tuple[bool, str]:
        """
        Validate the final answer using registered checks.

        Args:
            final_answer: The answer to validate.
            memory: The agent's memory.

        Returns:
            Tuple of (is_valid, error_message).
        """
        for check_fn in self.final_answer_checks:
            try:
                result = check_fn(final_answer, memory, self)
                if not result:
                    return False, f"Final answer check failed: {check_fn.__name__}"
            except Exception as e:
                return False, f"Final answer check error: {e}"
        return True, ""

    def _trigger_callbacks(
        self,
        step: ActionStep | PlanningStep,
        **kwargs,
    ) -> None:
        """
        Trigger registered callbacks for a step.

        Args:
            step: The step that was completed.
            **kwargs: Additional context for callbacks.
        """
        step_type = type(step)
        callbacks = self.step_callbacks.get(step_type, [])

        for callback in callbacks:
            try:
                callback(step, agent=self, **kwargs)
            except Exception as e:
                self.logger.log_error(f"Callback error: {e}")

    def add_tool(self, name: str, tool_obj: Callable | Tool) -> None:
        """
        Add a tool to the agent.

        Args:
            name: Name of the tool.
            tool_obj: The tool function or Tool instance.
        """
        if isinstance(tool_obj, Tool):
            self._tools[tool_obj.name] = tool_obj
            self.executor.send_tools({tool_obj.name: tool_obj})
        else:
            self._tools[name] = tool_obj
            self.executor.send_tools({name: tool_obj})
        self.logger.log(f"Added tool: {name}", level=LogLevel.DEBUG)

    def remove_tool(self, name: str) -> None:
        """
        Remove a tool from the agent.

        Args:
            name: Name of the tool to remove.
        """
        if name in self._tools and name != "final_answer":
            del self._tools[name]
            self.logger.log(f"Removed tool: {name}", level=LogLevel.DEBUG)

    def add_managed_agent(self, agent: "CodeAgent") -> None:
        """
        Add a managed sub-agent.

        Args:
            agent: The agent to add as a managed agent.
        """
        self.managed_agents[agent.name] = agent
        self._tools[agent.name] = self._create_agent_tool(agent)
        self.executor.send_tools({agent.name: self._tools[agent.name]})
        self.logger.log(f"Added managed agent: {agent.name}", level=LogLevel.DEBUG)

    def add_final_answer_check(self, check: FinalAnswerCheck) -> None:
        """
        Add a final answer validation check.

        Args:
            check: A function that takes (answer, memory, agent) and returns bool.
        """
        self.final_answer_checks.append(check)

    def register_step_callback(
        self,
        step_type: type,
        callback: Callable,
    ) -> None:
        """
        Register a callback for a step type.

        Args:
            step_type: The step class (ActionStep, PlanningStep, etc.)
            callback: The callback function.
        """
        if step_type not in self.step_callbacks:
            self.step_callbacks[step_type] = []
        self.step_callbacks[step_type].append(callback)

    async def run(self, task: str) -> Any:
        """
        Run the agent on a task.

        Args:
            task: The task description.

        Returns:
            The final answer.

        Raises:
            RuntimeError: If execution fails without producing a final answer.
            ValueError: If final answer validation fails.
        """
        self.monitor.start()
        self.logger.log_task(task, f"Agent: {self.name}")

        self._loop = CodeAgentLoop(
            llm_call=self.llm,
            executor=self.executor,
            config=self.config,
        )

        try:
            result = await self._loop.run(task)

            # Validate final answer
            if self.final_answer_checks:
                is_valid, error_msg = self._validate_final_answer(result, self._loop.memory)
                if not is_valid:
                    raise ValueError(error_msg)

            self.logger.log_final_answer(result)
            return result
        finally:
            self.monitor.stop()
            self._loop = None

    async def run_stream(self, task: str) -> AsyncGenerator[StepEvent, None]:
        """
        Run the agent with streaming events.

        Args:
            task: The task description.

        Yields:
            StepEvent objects for each significant event.
        """
        self.monitor.start()
        self.logger.log_task(task, f"Agent: {self.name}")

        self._loop = CodeAgentLoop(
            llm_call=self.llm,
            executor=self.executor,
            config=self.config,
        )

        try:
            async for event in self._loop.run_stream(task):
                # Update monitor on step completion
                if event.event_type == "observation":
                    step = self._loop.memory.get_last_action_step()
                    if step:
                        self.monitor.update_metrics(step)
                        self._trigger_callbacks(step)

                # Validate final answer
                if event.event_type == "final_answer" and self.final_answer_checks:
                    is_valid, error_msg = self._validate_final_answer(event.content, self._loop.memory)
                    if not is_valid:
                        yield StepEvent(
                            event_type="error",
                            content=error_msg,
                            step_number=event.step_number,
                        )
                        return

                    self.logger.log_final_answer(event.content)

                yield event
        finally:
            self.monitor.stop()
            self._loop = None

    def run_sync(self, task: str) -> Any:
        """
        Synchronous wrapper for run().

        Args:
            task: The task description.

        Returns:
            The final answer.
        """
        return asyncio.run(self.run(task))

    def stop(self) -> None:
        """Request the current execution to stop."""
        if self._loop:
            self._loop.stop()

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running."""
        return self._loop is not None and self._loop.is_running

    @property
    def current_step(self) -> int:
        """Get the current step number."""
        return self._loop.current_step if self._loop else 0

    @property
    def memory(self) -> AgentMemory | None:
        """Get the current memory state."""
        return self._loop.memory if self._loop else None

    def reset(self) -> None:
        """Reset the agent state."""
        self.executor.reset()
        self.monitor.reset()
        self._loop = None
        self.logger.log(f"Agent '{self.name}' reset", level=LogLevel.DEBUG)

    def visualize(self) -> None:
        """Visualize the agent structure including tools and managed agents."""
        self.logger.visualize_agent_tree(self)

    def get_run_summary(self) -> dict:
        """Get a summary of the last run's metrics."""
        return self.monitor.get_summary()

    def __repr__(self) -> str:
        return f"CodeAgent(name='{self.name}', tools={len(self._tools)}, managed_agents={len(self.managed_agents)})"


def get_code_agent(
    llm: Optional[Callable[[str], str | AsyncGenerator[str, None]]] = None,
    tools: Optional[dict[str, Callable]] = None,
    model_name: str = "gpt-4",
    **kwargs,
) -> CodeAgent:
    """
    Factory function to create a configured CodeAgent.

    Args:
        llm: Custom LLM function. If None, creates one from model_name.
        tools: Tools to inject.
        model_name: Model name for default LLM.
        **kwargs: Additional arguments for CodeAgent.

    Returns:
        Configured CodeAgent instance.
    """
    if llm is None:
        from .loop import create_simple_llm_call

        llm = create_simple_llm_call(model_name)

    return CodeAgent(llm=llm, tools=tools, **kwargs)


class DataAnalysisAgent(CodeAgent):
    """
    A CodeAgent specialized for data analysis tasks.

    Pre-configured with data analysis tools and optimized prompts.
    """

    def __init__(
        self,
        llm: Callable[[str], str | AsyncGenerator[str, None]],
        **kwargs,
    ):
        # Default config for data analysis
        config = kwargs.pop("config", None) or LoopConfig(
            max_steps=30,  # More steps for complex analysis
            enable_planning=True,  # Enable planning for multi-step analysis
            max_observation_length=20000,  # Larger outputs for data
        )

        super().__init__(
            llm=llm,
            config=config,
            name="DataAnalysisAgent",
            description="A specialized agent for data analysis and visualization",
            enable_data_analysis=True,
            **kwargs,
        )

        # Add data analysis helper tools
        self._add_data_analysis_tools()

    def _add_data_analysis_tools(self) -> None:
        """Add built-in data analysis tools."""

        def describe_dataframe(df) -> str:
            """Get a comprehensive description of a DataFrame."""
            import io

            buffer = io.StringIO()
            buffer.write(f"Shape: {df.shape}\n\n")
            buffer.write("Columns:\n")
            buffer.write(df.dtypes.to_string())
            buffer.write("\n\nSample (first 5 rows):\n")
            buffer.write(df.head().to_string())
            buffer.write("\n\nStatistics:\n")
            buffer.write(df.describe().to_string())
            return buffer.getvalue()

        def save_plot(fig, filename: str) -> str:
            """Save a matplotlib figure to file."""
            import os

            output_dir = "/tmp/plots"
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)
            fig.savefig(filepath, dpi=150, bbox_inches="tight")
            return f"Plot saved to {filepath}"

        self.add_tool("describe_dataframe", describe_dataframe)
        self.add_tool("save_plot", save_plot)


__all__ = [
    "CodeAgent",
    "get_code_agent",
    "DataAnalysisAgent",
]
