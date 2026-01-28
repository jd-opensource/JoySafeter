"""
Execution Plan Model

Provides progress tracking and visualization for CTF agent tasks.
Supports dynamic replan when retry exhausted or new information discovered.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal, Optional

StepStatus = Literal["pending", "in_progress", "completed", "failed", "skipped"]
PlanStatus = Literal["pending", "in_progress", "completed", "failed"]


@dataclass
class PlanStep:
    """A single step in the execution plan."""

    step_id: str
    description: str
    status: StepStatus = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: str = ""
    error: str = ""
    retry_count: int = 0

    def start(self) -> None:
        """Mark step as in progress."""
        self.status = "in_progress"
        self.started_at = datetime.now()

    def complete(self, result: str = "") -> None:
        """Mark step as completed."""
        self.status = "completed"
        self.completed_at = datetime.now()
        self.result = result

    def fail(self, error: str = "") -> None:
        """Mark step as failed."""
        self.status = "failed"
        self.completed_at = datetime.now()
        self.error = error

    def skip(self, reason: str = "") -> None:
        """Mark step as skipped."""
        self.status = "skipped"
        self.result = reason

    def increment_retry(self) -> int:
        """Increment retry count and return new value."""
        self.retry_count += 1
        return self.retry_count


@dataclass
class ExecutionPlan:
    """
    Execution plan for CTF agent tasks.

    Tracks progress and supports dynamic replan.
    """

    plan_id: str
    created_at: datetime
    updated_at: datetime
    status: PlanStatus
    steps: List[PlanStep] = field(default_factory=list)
    replan_history: List[dict] = field(default_factory=list)
    replan_count: int = 0  # Track number of replans (max 1 allowed)

    @classmethod
    def create(cls, steps: List[PlanStep]) -> "ExecutionPlan":
        """Create a new execution plan with given steps."""
        now = datetime.now()
        return cls(
            plan_id=str(uuid.uuid4())[:8],
            created_at=now,
            updated_at=now,
            status="pending",
            steps=steps,
        )

    @classmethod
    def from_descriptions(cls, descriptions: List[str]) -> "ExecutionPlan":
        """Create a plan from a list of step descriptions."""
        steps = [PlanStep(step_id=str(i + 1), description=desc) for i, desc in enumerate(descriptions)]
        return cls.create(steps)

    def start(self) -> None:
        """Start the execution plan."""
        self.status = "in_progress"
        self.updated_at = datetime.now()
        if self.steps:
            self.steps[0].start()

    def get_current_step(self) -> Optional[PlanStep]:
        """Get the currently executing step."""
        for step in self.steps:
            if step.status == "in_progress":
                return step
        return None

    def get_next_step(self) -> Optional[PlanStep]:
        """Get the next pending step."""
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    def advance(self, result: str = "") -> Optional[PlanStep]:
        """
        Complete current step and advance to next.
        Returns the new current step or None if plan is complete.
        """
        current = self.get_current_step()
        if current:
            current.complete(result)

        next_step = self.get_next_step()
        if next_step:
            next_step.start()
            self.updated_at = datetime.now()
            return next_step
        else:
            self.status = "completed"
            self.updated_at = datetime.now()
            return None

    def fail_current(self, error: str = "") -> None:
        """Mark current step as failed and update plan status."""
        current = self.get_current_step()
        if current:
            current.fail(error)
        self.status = "failed"
        self.updated_at = datetime.now()

    def replan(self, new_steps: List[PlanStep], reason: str) -> None:
        """
        Dynamically update the plan with new steps.

        Called when:
        - Retry exhausted and need alternative approach
        - New information discovered requiring plan adjustment
        """
        # Record history
        self.replan_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "old_steps": [s.description for s in self.steps],
                "new_steps": [s.description for s in new_steps],
            }
        )

        # Keep completed steps, replace pending ones
        completed_steps = [s for s in self.steps if s.status == "completed"]

        # Renumber new steps
        for i, step in enumerate(new_steps):
            step.step_id = str(len(completed_steps) + i + 1)

        self.steps = completed_steps + new_steps
        self.updated_at = datetime.now()

        # Start first new step if plan was in progress
        if self.status == "in_progress" and new_steps:
            new_steps[0].start()

    def to_markdown(self) -> str:
        """
        Generate Markdown format plan display.

        Format:
        ## 📋 Execution Plan

        - [x] Step 1: Initial action ✅
        - [ ] **Step 2: Main action** ⏳ (current)
        - [ ] Step 3: Final action
        """
        lines = ["## 📋 Execution Plan", ""]

        for step in self.steps:
            if step.status == "completed":
                lines.append(f"- [x] Step {step.step_id}: {step.description} ✅")
            elif step.status == "in_progress":
                lines.append(f"- [ ] **Step {step.step_id}: {step.description}** ⏳ (current)")
            elif step.status == "failed":
                lines.append(f"- [ ] Step {step.step_id}: {step.description} ❌ ({step.error})")
            elif step.status == "skipped":
                lines.append(f"- [ ] ~~Step {step.step_id}: {step.description}~~ (skipped)")
            else:  # pending
                lines.append(f"- [ ] Step {step.step_id}: {step.description}")

        # Add replan notice if there was a replan
        if self.replan_history:
            latest = self.replan_history[-1]
            lines.append("")
            lines.append(f"> 📝 Plan updated: {latest['reason']}")

        lines.append("")
        lines.append("---")

        return "\n".join(lines)

    def get_progress_summary(self) -> str:
        """Get a brief progress summary."""
        completed = sum(1 for s in self.steps if s.status == "completed")
        total = len(self.steps)
        current = self.get_current_step()

        if current:
            return f"Progress: {completed}/{total} | Current: {current.description}"
        elif self.status == "completed":
            return f"✅ Completed: {completed}/{total} steps"
        elif self.status == "failed":
            return f"❌ Failed: {completed}/{total} steps completed"
        else:
            return f"Pending: {total} steps"
