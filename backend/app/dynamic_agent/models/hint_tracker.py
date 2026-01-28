"""
Hint Tracker Model

Tracks execution status of knowledge base hints.
Prevents repeated attempts on failed hints and skips dependent hints.
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional

HintStatus = Literal["pending", "executing", "success", "failed", "skipped"]


@dataclass
class HintExecutionState:
    """State of a single hint execution."""

    hint_id: str
    content: str
    status: HintStatus = "pending"
    attempts: int = 0
    last_error: str = ""
    depends_on: List[str] = field(default_factory=list)

    def is_actionable(self) -> bool:
        """Check if this hint can be executed."""
        return self.status == "pending"

    def is_terminal(self) -> bool:
        """Check if this hint has reached a terminal state."""
        return self.status in ("success", "failed", "skipped")


class HintTracker:
    """
    Tracks hint execution status within a single task.

    Features:
    - Prevents repeated attempts on failed hints
    - Automatically skips hints that depend on failed hints
    - Generates status summary for prompt injection
    """

    def __init__(self, hints: List[str]):
        """
        Initialize tracker with list of hint strings.

        Args:
            hints: List of hint content strings
        """
        self.hints: List[HintExecutionState] = [
            HintExecutionState(hint_id=str(i), content=h) for i, h in enumerate(hints)
        ]
        self._failed_ids: set = set()

    def get_hint(self, hint_id: str) -> Optional[HintExecutionState]:
        """Get hint by ID."""
        for hint in self.hints:
            if hint.hint_id == hint_id:
                return hint
        return None

    def mark_executing(self, hint_id: str) -> None:
        """Mark a hint as currently executing."""
        hint = self.get_hint(hint_id)
        if hint:
            hint.status = "executing"
            hint.attempts += 1

    def mark_success(self, hint_id: str) -> None:
        """Mark a hint as successfully executed."""
        hint = self.get_hint(hint_id)
        if hint:
            hint.status = "success"

    def mark_failed(self, hint_id: str, error: str = "") -> None:
        """
        Mark a hint as failed.

        Also marks any hints that depend on this one as skipped.
        """
        hint = self.get_hint(hint_id)
        if hint:
            hint.status = "failed"
            hint.last_error = error
            self._failed_ids.add(hint_id)

            # Skip dependent hints
            self._skip_dependents(hint_id)

    def mark_skipped(self, hint_id: str, reason: str = "") -> None:
        """Mark a hint as skipped."""
        hint = self.get_hint(hint_id)
        if hint:
            hint.status = "skipped"
            hint.last_error = reason

    def _skip_dependents(self, failed_id: str) -> None:
        """Skip all hints that depend on a failed hint."""
        for hint in self.hints:
            if failed_id in hint.depends_on and hint.status == "pending":
                hint.status = "skipped"
                hint.last_error = f"Skipped: depends on failed hint {failed_id}"

    def get_next_actionable(self) -> Optional[HintExecutionState]:
        """
        Get the next hint that can be executed.

        Returns None if no actionable hints remain.
        """
        for hint in self.hints:
            if hint.is_actionable():
                # Check if any dependencies have failed
                if any(dep in self._failed_ids for dep in hint.depends_on):
                    self.mark_skipped(hint.hint_id, "Dependency failed")
                    continue
                return hint
        return None

    def has_pending(self) -> bool:
        """Check if there are any pending hints."""
        return any(h.status == "pending" for h in self.hints)

    def get_stats(self) -> dict:
        """Get execution statistics."""
        stats = {
            "total": len(self.hints),
            "pending": 0,
            "executing": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        for hint in self.hints:
            stats[hint.status] += 1
        return stats

    def to_prompt_summary(self) -> str:
        """
        Generate a status summary for prompt injection.

        Format:
        **Hint Status:**
        - ✅ Hint 0: Login successful
        - ❌ Hint 1: Access denied (failed)
        - ⏭️ Hint 2: Skipped (depends on 1)
        - ⏳ Hint 3: Pending
        """
        if not self.hints:
            return ""

        lines = ["**Hint Execution Status:**"]

        for hint in self.hints:
            content_preview = hint.content[:50] + "..." if len(hint.content) > 50 else hint.content

            if hint.status == "success":
                lines.append(f"- ✅ Hint {hint.hint_id}: {content_preview}")
            elif hint.status == "failed":
                error_preview = hint.last_error[:30] if hint.last_error else "failed"
                lines.append(f"- ❌ Hint {hint.hint_id}: {content_preview} ({error_preview})")
            elif hint.status == "skipped":
                lines.append(f"- ⏭️ Hint {hint.hint_id}: {content_preview} (skipped)")
            elif hint.status == "executing":
                lines.append(f"- ⏳ Hint {hint.hint_id}: {content_preview} (executing)")
            else:  # pending
                lines.append(f"- ⬜ Hint {hint.hint_id}: {content_preview}")

        stats = self.get_stats()
        lines.append("")
        lines.append(
            f"Progress: {stats['success']}/{stats['total']} completed, {stats['failed']} failed, {stats['skipped']} skipped"
        )

        return "\n".join(lines)
