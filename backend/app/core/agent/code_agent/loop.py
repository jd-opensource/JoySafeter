#!/usr/bin/env python
# coding=utf-8
"""
CodeAgent Loop - The core Thought-Code-Observation iteration engine.

This module implements the main execution loop for CodeAgent, handling
the iterative process of thinking, generating code, executing it,
and observing results.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from .executor import LocalPythonExecutor, PythonExecutor
from .memory import AgentMemory, PlanningStep, StepMetrics
from .parser import (
    ParsingError,
    clean_code,
    extract_thought_and_code,
    format_observation,
    validate_python_syntax,
)

# JSON schema for structured code agent response
CODEAGENT_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "code_agent_response",
        "schema": {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "The reasoning and planning for the current step",
                },
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
            },
            "required": ["thought", "code"],
        },
    },
}


@dataclass
class LoopConfig:
    """Configuration for the CodeAgent loop."""

    # Maximum number of steps before stopping
    max_steps: int = 20

    # Maximum consecutive errors before stopping
    max_consecutive_errors: int = 3

    # Maximum total execution time in seconds
    max_execution_time: float = 300.0

    # Whether to enable planning
    enable_planning: bool = False

    # Whether to update plan during execution
    enable_plan_updates: bool = False

    # Interval (in steps) between plan updates
    plan_update_interval: int = 5

    # Maximum observation length in characters
    max_observation_length: int = 10000

    # Whether to stream step events
    streaming: bool = True

    # Verbose logging
    verbose: bool = False

    # Use structured outputs (JSON schema) if LLM supports it
    use_structured_outputs: bool = False

    # Response format for structured outputs (passed to LLM)
    response_format: dict | None = None


@dataclass
class StepEvent:
    """Event emitted during loop execution."""

    event_type: str  # "thought", "code", "observation", "error", "final_answer", "planning"
    content: Any
    step_number: int
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "type": self.event_type,
            "content": self.content,
            "step": self.step_number,
            "metadata": self.metadata or {},
        }


class CodeAgentLoop:
    """
    The core execution loop for CodeAgent.

    Implements the Thought → Code → Observation cycle:
    1. LLM generates thought and code
    2. Code is executed in the Python executor
    3. Observation (output/error) is fed back to LLM
    4. Repeat until final_answer() is called or max steps reached
    """

    def __init__(
        self,
        llm_call: Callable[[str], str | AsyncGenerator[str, None]],
        executor: Optional[PythonExecutor] = None,
        tools: Optional[dict[str, Callable]] = None,
        config: Optional[LoopConfig] = None,
    ):
        """
        Initialize the CodeAgent loop.

        Args:
            llm_call: Function to call the LLM. Takes prompt string, returns response.
                      Can be sync or async, can return string or async generator.
            executor: Python executor to use. Defaults to LocalPythonExecutor.
            tools: Tools to inject into the executor.
            config: Loop configuration.
        """
        self.llm_call = llm_call
        self.config = config or LoopConfig()
        self.memory = AgentMemory(max_steps=self.config.max_steps * 2)

        # Initialize executor
        if executor is None:
            self.executor = LocalPythonExecutor(enable_data_analysis=True)
        else:
            self.executor = executor  # type: ignore[assignment]

        # Inject tools
        if tools:
            self.executor.send_tools(tools)

        # State
        self._current_step = 0
        self._consecutive_errors = 0
        self._is_running = False
        self._should_stop = False

        # Load prompts
        self._system_prompt = self._load_prompt("system.md")
        self._planning_prompt = self._load_prompt("planning.md")

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt template from file."""
        prompt_path = Path(__file__).parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        logger.warning(f"Prompt file not found: {prompt_path}")
        return ""

    def _format_system_prompt(
        self,
        task: str,
        tool_descriptions: str = "",
    ) -> str:
        """Format the system prompt with task and tools."""
        prompt = self._system_prompt
        prompt = prompt.replace("{{task}}", task)
        prompt = prompt.replace("{{tool_descriptions}}", tool_descriptions or "无可用工具")
        return prompt

    def _build_prompt(self, task: str, history: str = "") -> str:
        """Build the full prompt including history."""
        tool_desc = self._get_tool_descriptions()
        system_prompt = self._format_system_prompt(task, tool_desc)

        if history:
            return f"{system_prompt}\n\n## 执行历史\n\n{history}\n\n请继续执行任务。"
        return system_prompt

    def _get_tool_descriptions(self) -> str:
        """Get descriptions of available tools."""
        tools = getattr(self.executor, "static_tools", {})
        descriptions = []

        for name, func in tools.items():
            if name.startswith("_") or name in ("print", "final_answer"):
                continue
            doc = getattr(func, "__doc__", "") or "无描述"
            doc = doc.strip().split("\n")[0]  # First line only
            descriptions.append(f"- `{name}`: {doc}")

        return "\n".join(descriptions) if descriptions else "无额外工具"

    async def run(self, task: str) -> Any:
        """
        Run the agent loop on a task.

        Args:
            task: The task description.

        Returns:
            The final answer.

        Raises:
            RuntimeError: If max steps reached without final answer.
        """
        result = None
        async for event in self.run_stream(task):
            if event.event_type == "final_answer":
                result = event.content
        return result

    async def run_stream(self, task: str) -> AsyncGenerator[StepEvent, None]:
        """
        Run the agent loop with streaming events.

        Args:
            task: The task description.

        Yields:
            StepEvent objects for each significant event.
        """
        import time

        self._is_running = True
        self._should_stop = False
        self._current_step = 0
        self._consecutive_errors = 0

        # Initialize memory
        self.memory.reset()
        self.memory.task = task
        self.memory.system_prompt = self._format_system_prompt(task)

        start_time = time.time()

        try:
            # Optional: Initial planning
            if self.config.enable_planning:
                async for event in self._do_planning(task, initial=True):
                    yield event

            # Main execution loop
            while self._current_step < self.config.max_steps and not self._should_stop:
                # Check timeout
                if time.time() - start_time > self.config.max_execution_time:
                    yield StepEvent(
                        event_type="error",
                        content="Execution timeout reached",
                        step_number=self._current_step,
                    )
                    break

                # Execute one step
                async for event in self._step():
                    yield event

                    if event.event_type == "final_answer":
                        self._should_stop = True
                        return

                    if event.event_type == "error":
                        self._consecutive_errors += 1
                        if self._consecutive_errors >= self.config.max_consecutive_errors:
                            yield StepEvent(
                                event_type="error",
                                content=f"Too many consecutive errors ({self._consecutive_errors})",
                                step_number=self._current_step,
                            )
                            self._should_stop = True
                            return
                    else:
                        self._consecutive_errors = 0

                self._current_step += 1

                # Optional: Update planning
                if (
                    self.config.enable_plan_updates
                    and self._current_step > 0
                    and self._current_step % self.config.plan_update_interval == 0
                ):
                    async for event in self._do_planning(task, initial=False):
                        yield event

            # Max steps reached without final answer
            if not self._should_stop:
                yield StepEvent(
                    event_type="error",
                    content=f"Max steps ({self.config.max_steps}) reached without final answer",
                    step_number=self._current_step,
                )

        finally:
            self._is_running = False
            self.memory.complete()

    async def _step(self) -> AsyncGenerator[StepEvent, None]:
        """Execute a single Thought-Code-Observation step."""
        step = self.memory.create_action_step()
        step.metrics = StepMetrics()

        # Build prompt with history
        history = self.memory.get_history_for_prompt(include_thoughts=True)
        prompt = self._build_prompt(self.memory.task, history)

        # Get LLM response
        try:
            llm_output = await self._call_llm(prompt)
            step.llm_output = llm_output
        except Exception as e:
            step.error = f"LLM call failed: {str(e)}"
            step.metrics.complete()
            self.memory.add_step(step)
            yield StepEvent("error", step.error, step.step_number)
            return

        # Parse thought and code
        try:
            thought, code = extract_thought_and_code(llm_output)
            step.thought = thought
            step.code = clean_code(code)
        except ParsingError as e:
            step.error = f"Failed to parse LLM output: {str(e)}"
            step.metrics.complete()
            self.memory.add_step(step)
            yield StepEvent("error", step.error, step.step_number)
            return

        # Emit thought event
        if step.thought:
            yield StepEvent("thought", step.thought, step.step_number)

        # Emit code event
        if step.code:
            yield StepEvent("code", step.code, step.step_number)
        else:
            step.error = "No code generated"
            step.metrics.complete()
            self.memory.add_step(step)
            yield StepEvent("error", step.error, step.step_number)
            return

        # Validate syntax
        is_valid, syntax_error = validate_python_syntax(step.code)
        if not is_valid:
            step.error = f"Syntax error: {syntax_error}"
            step.observation = step.error
            step.metrics.complete()
            self.memory.add_step(step)
            yield StepEvent("observation", step.observation, step.step_number)
            return

        # Execute code
        try:
            result = self.executor(step.code)

            if result.is_final_answer:
                step.is_final_answer = True
                step.final_answer = result.output
                step.observation = format_observation(
                    result.output,
                    result.logs,
                    max_length=self.config.max_observation_length,
                )
                step.metrics.complete()
                self.memory.add_step(step)
                yield StepEvent("final_answer", result.output, step.step_number)
                return

            if result.error:
                step.error = result.error
                step.observation = format_observation(
                    None,
                    result.logs,
                    result.error,
                    max_length=self.config.max_observation_length,
                )
            else:
                step.observation = format_observation(
                    result.output,
                    result.logs,
                    max_length=self.config.max_observation_length,
                )

        except Exception as e:
            step.error = f"Execution error: {str(e)}"
            step.observation = step.error
            logger.exception(f"Error executing code: {e}")

        step.metrics.complete()
        self.memory.add_step(step)

        yield StepEvent(
            "observation",
            step.observation,
            step.step_number,
            {"error": step.error} if step.error else {},
        )

    async def _do_planning(
        self,
        task: str,
        initial: bool = True,
    ) -> AsyncGenerator[StepEvent, None]:
        """Execute a planning step."""
        planning_step = PlanningStep(is_update=not initial)
        planning_step.metrics = StepMetrics()

        if initial:
            prompt = self._planning_prompt.split("---")[0]  # Initial planning section
            prompt = prompt.replace("{{task}}", task)
            prompt = prompt.replace("{{tool_descriptions}}", self._get_tool_descriptions())
        else:
            prompt = self._planning_prompt.split("---")[1]  # Update planning section
            prompt = prompt.replace("{{task}}", task)
            prompt = prompt.replace("{{original_plan}}", self.memory.current_plan)
            prompt = prompt.replace("{{progress}}", self._get_progress_summary())
            prompt = prompt.replace("{{issues}}", self._get_issues_summary())
            planning_step.previous_plan = self.memory.current_plan

        try:
            llm_output = await self._call_llm(prompt)
            planning_step.llm_output = llm_output
            planning_step.plan = llm_output
            self.memory.current_plan = llm_output

            planning_step.metrics.complete()
            self.memory.add_step(planning_step)

            yield StepEvent(
                "planning",
                planning_step.plan,
                self._current_step,
                {"is_update": not initial},
            )

        except Exception as e:
            logger.error(f"Planning failed: {e}")
            yield StepEvent(
                "error",
                f"Planning failed: {str(e)}",
                self._current_step,
            )

    def _get_progress_summary(self) -> str:
        """Get a summary of execution progress."""
        action_steps = self.memory.action_steps
        completed = sum(1 for s in action_steps if s.success)
        failed = sum(1 for s in action_steps if s.error)
        return f"已执行 {len(action_steps)} 步，成功 {completed} 步，失败 {failed} 步"

    def _get_issues_summary(self) -> str:
        """Get a summary of encountered issues."""
        action_steps = self.memory.action_steps
        issues = [s.error for s in action_steps if s.error]
        if not issues:
            return "暂无问题"
        return "\n".join(f"- {issue}" for issue in issues[-3:])  # Last 3 issues

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM and get response."""
        result = self.llm_call(prompt)

        # Handle async generator (streaming)
        if hasattr(result, "__anext__") and not isinstance(result, str):
            chunks = []
            async for chunk in result:  # type: ignore[misc]
                chunks.append(chunk)
            return "".join(chunks)

        # Handle coroutine
        if asyncio.iscoroutine(result):
            return str(await result)

        # Handle sync result
        return str(result)

    def stop(self) -> None:
        """Request the loop to stop."""
        self._should_stop = True

    @property
    def is_running(self) -> bool:
        """Check if the loop is currently running."""
        return self._is_running

    @property
    def current_step(self) -> int:
        """Get the current step number."""
        return self._current_step


def create_simple_llm_call(model_name: str = "gpt-4"):
    """
    Create a simple LLM call function using langchain.

    Args:
        model_name: The model to use.

    Returns:
        Async function that calls the LLM.
    """
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=model_name, temperature=0)

        async def call_llm(prompt: str) -> str:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            if isinstance(content, list):
                # Handle list of content blocks
                return " ".join(str(item) for item in content)
            return str(content)

        return call_llm

    except ImportError:
        logger.warning("langchain_openai not installed, returning mock LLM")

        async def mock_call_llm(prompt: str) -> str:
            return "Thought: This is a mock response.\n\nCode:\n```python\nfinal_answer('Mock response')\n```"

        return mock_call_llm


__all__ = [
    "LoopConfig",
    "StepEvent",
    "CodeAgentLoop",
    "create_simple_llm_call",
]
