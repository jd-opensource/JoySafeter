#!/usr/bin/env python
# coding=utf-8
"""
Planning Engine for CodeAgent.

This module provides planning capabilities for complex multi-step tasks,
including initial plan generation and dynamic plan updates.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger


class PlanStatus(str, Enum):
    """Status of a plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class PlanStep:
    """A single step in a plan."""

    step_id: int
    name: str
    description: str
    method: str = ""
    expected_output: str = ""
    status: PlanStatus = PlanStatus.PENDING
    dependencies: list[int] = field(default_factory=list)
    actual_output: str = ""
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "method": self.method,
            "expected_output": self.expected_output,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "actual_output": self.actual_output,
            "error": self.error,
        }

    def format_for_prompt(self, include_status: bool = True) -> str:
        """Format step for inclusion in prompt."""
        status_symbol = {
            PlanStatus.PENDING: "○",
            PlanStatus.IN_PROGRESS: "●",
            PlanStatus.COMPLETED: "✓",
            PlanStatus.SKIPPED: "⊘",
            PlanStatus.FAILED: "✗",
            PlanStatus.BLOCKED: "⊗",
        }

        status_str = f" {status_symbol.get(self.status, '?')}" if include_status else ""

        lines = [f"### 步骤 {self.step_id}: {self.name}{status_str}"]
        lines.append(f"- 目的: {self.description}")
        if self.method:
            lines.append(f"- 方法: {self.method}")
        if self.expected_output:
            lines.append(f"- 预期输出: {self.expected_output}")
        if self.dependencies:
            lines.append(f"- 依赖: 步骤 {', '.join(map(str, self.dependencies))}")
        if self.actual_output and self.status == PlanStatus.COMPLETED:
            lines.append(f"- 实际输出: {self.actual_output[:200]}...")
        if self.error:
            lines.append(f"- 错误: {self.error}")

        return "\n".join(lines)


@dataclass
class Plan:
    """A complete execution plan."""

    task: str
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version: int = 1

    @property
    def current_step(self) -> PlanStep | None:
        """Get the current step to execute."""
        for step in self.steps:
            if step.status in (PlanStatus.PENDING, PlanStatus.IN_PROGRESS):
                # Check dependencies
                deps_completed = all(
                    (dep_step := self.get_step(dep_id)) is not None and dep_step.status == PlanStatus.COMPLETED
                    for dep_id in step.dependencies
                )
                if deps_completed:
                    return step
        return None

    def get_step(self, step_id: int) -> PlanStep | None:
        """Get a step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    @property
    def completed_steps(self) -> list[PlanStep]:
        """Get all completed steps."""
        return [s for s in self.steps if s.status == PlanStatus.COMPLETED]

    @property
    def pending_steps(self) -> list[PlanStep]:
        """Get all pending steps."""
        return [s for s in self.steps if s.status == PlanStatus.PENDING]

    @property
    def progress_pct(self) -> float:
        """Get completion percentage."""
        if not self.steps:
            return 0.0
        completed = len(self.completed_steps)
        return completed / len(self.steps) * 100

    def mark_step_started(self, step_id: int) -> None:
        """Mark a step as in progress."""
        step = self.get_step(step_id)
        if step:
            step.status = PlanStatus.IN_PROGRESS
            step.started_at = datetime.now()
            self.updated_at = datetime.now()

    def mark_step_completed(self, step_id: int, output: str = "") -> None:
        """Mark a step as completed."""
        step = self.get_step(step_id)
        if step:
            step.status = PlanStatus.COMPLETED
            step.completed_at = datetime.now()
            step.actual_output = output
            self.updated_at = datetime.now()

    def mark_step_failed(self, step_id: int, error: str) -> None:
        """Mark a step as failed."""
        step = self.get_step(step_id)
        if step:
            step.status = PlanStatus.FAILED
            step.error = error
            self.updated_at = datetime.now()

    def format_for_prompt(self, include_completed: bool = True) -> str:
        """Format plan for inclusion in prompt."""
        lines = [
            "## 任务目标",
            f"{self.goal or self.task}",
            "",
            f"## 执行步骤 (进度: {self.progress_pct:.0f}%)",
        ]

        for step in self.steps:
            if step.status == PlanStatus.COMPLETED and not include_completed:
                lines.append(f"### 步骤 {step.step_id}: {step.name} ✓ (已完成)")
            else:
                lines.append("")
                lines.append(step.format_for_prompt())

        if self.notes:
            lines.append("")
            lines.append("## 注意事项")
            for note in self.notes:
                lines.append(f"- {note}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "notes": self.notes,
            "progress_pct": self.progress_pct,
            "version": self.version,
        }


class PlanningEngine:
    """
    Engine for generating and managing execution plans.

    Features:
    - Initial plan generation from task description
    - Dynamic plan updates based on execution progress
    - Dependency tracking between steps
    - Plan versioning

    Example:
        >>> engine = PlanningEngine(llm_call=my_llm)
        >>> plan = await engine.create_plan("Build a web scraper")
        >>> print(plan.format_for_prompt())
    """

    def __init__(
        self,
        llm_call: Optional[Callable[[str], str]] = None,
        max_steps: int = 10,
        auto_update_interval: int = 3,
    ):
        """
        Initialize the planning engine.

        Args:
            llm_call: Function to call LLM for plan generation.
            max_steps: Maximum number of steps in a plan.
            auto_update_interval: Steps between automatic plan updates.
        """
        self.llm_call = llm_call
        self.max_steps = max_steps
        self.auto_update_interval = auto_update_interval

        self._current_plan: Plan | None = None
        self._plan_history: list[Plan] = []

        # Load prompts
        self._planning_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load planning prompt template."""
        prompt_path = Path(__file__).parent / "prompts" / "planning.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return ""

    async def create_plan(
        self,
        task: str,
        tools: Optional[list[str]] = None,
        context: str = "",
    ) -> Plan:
        """
        Create an initial plan for a task.

        Args:
            task: Task description.
            tools: Available tools.
            context: Additional context.

        Returns:
            Generated Plan object.
        """
        prompt = f"""请为以下任务创建一个执行计划。

## 任务
{task}

## 可用工具
{", ".join(tools) if tools else "无特定工具限制"}

## 上下文
{context or "无"}

## 要求
1. 将任务分解为 {self.max_steps} 个以内的步骤
2. 每个步骤应该具体可执行
3. 标明步骤之间的依赖关系
4. 考虑可能的风险和应对策略

## 输出格式
请按以下 JSON 格式输出：
```json
{{
  "goal": "任务总目标",
  "steps": [
    {{
      "step_id": 1,
      "name": "步骤名称",
      "description": "步骤描述",
      "method": "实现方法",
      "expected_output": "预期输出",
      "dependencies": []
    }}
  ],
  "notes": ["注意事项1", "注意事项2"]
}}
```"""

        if self.llm_call:
            try:
                import json

                response = await self._call_llm(prompt)

                # Extract JSON from response
                json_match = response.find("```json")
                if json_match != -1:
                    json_end = response.find("```", json_match + 7)
                    json_str = response[json_match + 7 : json_end]
                else:
                    json_str = response

                plan_data = json.loads(json_str)

                plan = Plan(
                    task=task,
                    goal=plan_data.get("goal", task),
                    notes=plan_data.get("notes", []),
                )

                for step_data in plan_data.get("steps", []):
                    step = PlanStep(
                        step_id=step_data.get("step_id", len(plan.steps) + 1),
                        name=step_data.get("name", f"Step {len(plan.steps) + 1}"),
                        description=step_data.get("description", ""),
                        method=step_data.get("method", ""),
                        expected_output=step_data.get("expected_output", ""),
                        dependencies=step_data.get("dependencies", []),
                    )
                    plan.steps.append(step)

                self._current_plan = plan
                logger.info(f"Created plan with {len(plan.steps)} steps")
                return plan

            except Exception as e:
                logger.error(f"Failed to parse plan: {e}")

        # Fallback: simple single-step plan
        plan = Plan(
            task=task,
            goal=task,
            steps=[
                PlanStep(
                    step_id=1,
                    name="执行任务",
                    description=task,
                )
            ],
        )
        self._current_plan = plan
        return plan

    async def update_plan(
        self,
        progress: str,
        issues: Optional[list[str]] = None,
    ) -> Plan:
        """
        Update the current plan based on progress.

        Args:
            progress: Description of current progress.
            issues: List of issues encountered.

        Returns:
            Updated Plan object.
        """
        if not self._current_plan:
            raise ValueError("No current plan to update")

        prompt = f"""请根据当前进度更新执行计划。

## 原计划
{self._current_plan.format_for_prompt()}

## 当前进度
{progress}

## 遇到的问题
{chr(10).join(f"- {issue}" for issue in (issues or [])) or "暂无"}

## 要求
1. 保留已完成的步骤
2. 根据实际情况调整后续步骤
3. 添加必要的新步骤
4. 移除不再需要的步骤

## 输出格式
请按与原计划相同的 JSON 格式输出更新后的计划。"""

        if self.llm_call:
            try:
                import json

                response = await self._call_llm(prompt)

                # Extract JSON
                json_match = response.find("```json")
                if json_match != -1:
                    json_end = response.find("```", json_match + 7)
                    json_str = response[json_match + 7 : json_end]
                else:
                    json_str = response

                plan_data = json.loads(json_str)

                # Archive current plan
                self._plan_history.append(self._current_plan)

                # Create updated plan
                new_plan = Plan(
                    task=self._current_plan.task,
                    goal=plan_data.get("goal", self._current_plan.goal),
                    notes=plan_data.get("notes", []),
                    version=self._current_plan.version + 1,
                )

                for step_data in plan_data.get("steps", []):
                    # Check if step exists in old plan
                    old_step = self._current_plan.get_step(step_data.get("step_id", -1))

                    step = PlanStep(
                        step_id=step_data.get("step_id", len(new_plan.steps) + 1),
                        name=step_data.get("name", f"Step {len(new_plan.steps) + 1}"),
                        description=step_data.get("description", ""),
                        method=step_data.get("method", ""),
                        expected_output=step_data.get("expected_output", ""),
                        dependencies=step_data.get("dependencies", []),
                        status=old_step.status if old_step else PlanStatus.PENDING,
                        actual_output=old_step.actual_output if old_step else "",
                    )
                    new_plan.steps.append(step)

                self._current_plan = new_plan
                logger.info(f"Updated plan to version {new_plan.version}")
                return new_plan

            except Exception as e:
                logger.error(f"Failed to update plan: {e}")

        return self._current_plan

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM and handle async."""
        import asyncio

        if self.llm_call is None:
            raise ValueError("llm_call is not set")

        result = self.llm_call(prompt)

        if asyncio.iscoroutine(result):
            return str(await result)

        if hasattr(result, "__anext__") and not isinstance(result, str):
            chunks = []
            async for chunk in result:  # type: ignore[misc]
                chunks.append(str(chunk))
            return "".join(chunks)

        return str(result)

    @property
    def current_plan(self) -> Plan | None:
        """Get the current plan."""
        return self._current_plan

    @property
    def current_step(self) -> PlanStep | None:
        """Get the current step to execute."""
        if self._current_plan:
            return self._current_plan.current_step
        return None

    def advance_step(self, output: str = "") -> PlanStep | None:
        """
        Mark current step as completed and move to next.

        Args:
            output: Output from the completed step.

        Returns:
            The next step to execute, or None if done.
        """
        if not self._current_plan:
            return None

        current = self._current_plan.current_step
        if current:
            self._current_plan.mark_step_completed(current.step_id, output)

        return self._current_plan.current_step

    def fail_step(self, error: str) -> None:
        """Mark current step as failed."""
        if self._current_plan:
            current = self._current_plan.current_step
            if current:
                self._current_plan.mark_step_failed(current.step_id, error)

    def reset(self) -> None:
        """Reset the planning engine."""
        if self._current_plan:
            self._plan_history.append(self._current_plan)
        self._current_plan = None


def create_planning_engine(
    llm: Optional[Callable] = None,
    **kwargs,
) -> PlanningEngine:
    """
    Factory function to create a PlanningEngine.

    Args:
        llm: LLM function for plan generation.
        **kwargs: Additional arguments for PlanningEngine.

    Returns:
        Configured PlanningEngine instance.
    """
    return PlanningEngine(llm_call=llm, **kwargs)


__all__ = [
    "PlanStatus",
    "PlanStep",
    "Plan",
    "PlanningEngine",
    "create_planning_engine",
]
