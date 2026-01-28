"""
Session Context - 007: Intent-First Clean Context Architecture

Dynamic context, injected at the beginning of each User Message.
Supports Intent Persistence and KV Cache-friendly architecture.
"""

from collections import OrderedDict
from dataclasses import dataclass, field

# Avoid circular imports
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from app.dynamic_agent.models.todo_panel import TodoPanel


@dataclass
class SessionContext:
    """
    Dynamic context, injected at the beginning of each User Message.

    Attributes:
        intent: User intent extracted by LLM (one sentence, ≤100 characters)
        progress: Progress string "completed/total steps completed"
        findings: Key findings {key: value}, retains up to 10 most recent entries
        todo_status: TODO status string
        replan_reason: Replan reason (if any)
    """

    intent: str = ""
    progress: str = "0/0"
    findings: OrderedDict = field(default_factory=OrderedDict)
    todo_status: str = ""
    replan_reason: Optional[str] = None

    MAX_FINDINGS: int = 10

    def add_finding(self, key: str, value: str) -> None:
        """
        Add a finding, removing the oldest entry when MAX_FINDINGS is exceeded.

        Args:
            key: Finding key (e.g., "cookie", "flag", "user_id")
            value: Finding value
        """
        # If key already exists, delete it first before adding (to maintain latest order)
        if key in self.findings:
            del self.findings[key]

        self.findings[key] = value

        # Remove oldest entries when limit is exceeded
        while len(self.findings) > self.MAX_FINDINGS:
            self.findings.popitem(last=False)

    def add_findings_from_dict(self, values: Dict[str, Any]) -> None:
        """
        Add findings in bulk from a dictionary.

        Args:
            values: Dictionary of key-value pairs to add
        """
        for key, value in values.items():
            self.add_finding(key, str(value))

    def clear_findings(self) -> None:
        """Clear all findings."""
        self.findings.clear()

    def set_progress(self, completed: int, total: int) -> None:
        """
        Set progress.

        Args:
            completed: Number of completed steps
            total: Total number of steps
        """
        self.progress = f"{completed}/{total}"

    def set_replan_reason(self, reason: str) -> None:
        """
        Set replan reason.

        Args:
            reason: Reason for replan
        """
        self.replan_reason = reason

    def clear_replan_reason(self) -> None:
        """Clear replan reason."""
        self.replan_reason = None

    def update_from_todo_panel(self, todo_panel: "TodoPanel") -> None:
        """
        Update TODO status from TodoPanel.

        Args:
            todo_panel: TodoPanel instance
        """
        if todo_panel is None or not hasattr(todo_panel, "items"):
            self.todo_status = ""
            return

        status_parts = []
        for item in todo_panel.items:
            status_icon = {
                "pending": "⏸️",
                "in_progress": "⏳",
                "completed": "✅",
                "failed": "❌",
            }.get(item.status, "❓")

            # Truncate overly long descriptions
            desc = item.description[:20] + "..." if len(item.description) > 20 else item.description
            status_parts.append(f"{status_icon}{desc}")

        self.todo_status = " | ".join(status_parts)

        # Update progress
        completed = sum(1 for item in todo_panel.items if item.status == "completed")
        total = len(todo_panel.items)
        self.set_progress(completed, total)

    def to_xml(self) -> str:
        """
        Generate XML format context block.

        Returns:
            XML formatted session_context string
        """
        # Separate discovery hints from regular findings
        discovery_type = self.findings.get("last_discovery_type")
        suggested_next = self.findings.get("suggested_next")

        # Regular findings (exclude discovery hints)
        regular_findings = {
            k: v for k, v in self.findings.items() if k not in ("last_discovery_type", "suggested_next")
        }

        if regular_findings:
            findings_lines = [f"    {k}: {v}" for k, v in regular_findings.items()]
            findings_str = "\n".join(findings_lines)
        else:
            findings_str = "    (none)"

        parts = [
            "<session_context>",
            f"🎯 Intent: {self.intent}",
            f"📊 Progress: {self.progress}",
            "🔑 Findings:",
            findings_str,
            f"📋 TODO: {self.todo_status or '(no tasks)'}",
        ]

        # Highlight discovery for replan decision
        if discovery_type and discovery_type != "none":
            parts.append(f"⚡ DISCOVERY: {discovery_type} - Consider replan_tasks()")
            if suggested_next:
                parts.append(f"💡 Suggested: {suggested_next}")

        if self.replan_reason:
            parts.append(f"🔄 Replan: {self.replan_reason}")

        parts.append("</session_context>")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return (
            f"SessionContext(intent='{self.intent[:30]}...', "
            f"progress='{self.progress}', "
            f"findings={len(self.findings)} items, "
            f"replan={self.replan_reason is not None})"
        )
