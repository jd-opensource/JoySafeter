"""
TodoPanel - Rich TODO panel for progress visualization.

006: Single Subagent Clean Architecture
- TodoItem: Individual task item with status tracking
- TodoPanel: Rich Live panel for real-time progress display
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Status type
TodoStatus = Literal["pending", "in_progress", "completed", "failed"]

# Status icons
STATUS_ICONS = {
    "pending": "⏸️",
    "in_progress": "⏳",
    "completed": "✅",
    "failed": "❌",
}

# Status colors
STATUS_COLORS = {
    "pending": "dim",
    "in_progress": "yellow",
    "completed": "green",
    "failed": "red",
}


@dataclass
class TodoItem:
    """
    Individual TODO item with status tracking.

    Attributes:
        id: Unique identifier
        description: Task description
        status: Current status (pending, in_progress, completed, failed)
        created_at: Creation timestamp
        started_at: When task started (in_progress)
        completed_at: When task completed/failed
        error_summary: Error message if failed
        duration_ms: Execution duration
        metadata: Additional metadata
    """

    id: str
    description: str
    status: TodoStatus = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_summary: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_new: bool = False  # Flag for replan items

    def start(self) -> None:
        """Mark item as in progress."""
        self.status = "in_progress"
        self.started_at = datetime.now()

    def complete(self) -> None:
        """Mark item as completed."""
        self.status = "completed"
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)

    def fail(self, error: str) -> None:
        """Mark item as failed with error message."""
        self.status = "failed"
        self.completed_at = datetime.now()
        self.error_summary = error[:100] if len(error) > 100 else error
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)

    def get_icon(self) -> str:
        """Get status icon."""
        return STATUS_ICONS.get(self.status, "❓")

    def get_color(self) -> str:
        """Get status color."""
        return STATUS_COLORS.get(self.status, "white")


class TodoPanel:
    """
    Rich TODO panel for real-time progress visualization.

    Features:
    - Real-time status updates
    - Strikethrough for completed items
    - Collapsible completed items
    - Replan notification display
    """

    def __init__(
        self,
        title: str = "📋 Task Progress",
        max_visible: int = 10,
    ):
        """
        Initialize TodoPanel.

        Args:
            title: Panel title
            max_visible: Maximum visible items (completed items collapse)
        """
        self.title = title
        self.max_visible = max_visible
        self.items: List[TodoItem] = []
        self.replan_reason: Optional[str] = None
        self.replan_count: int = 0
        self._live: Optional[Live] = None
        self._console = Console()

    def add(self, description: str, item_id: Optional[str] = None) -> TodoItem:
        """
        Add a new TODO item.

        Args:
            description: Task description
            item_id: Optional custom ID

        Returns:
            Created TodoItem
        """
        item = TodoItem(
            id=item_id or str(uuid.uuid4())[:8],
            description=description,
        )
        self.items.append(item)
        self._refresh()
        return item

    def add_items(self, descriptions: List[str]) -> List[TodoItem]:
        """
        Add multiple TODO items.

        Args:
            descriptions: List of task descriptions

        Returns:
            List of created TodoItems
        """
        items = []
        for desc in descriptions:
            item = TodoItem(
                id=str(uuid.uuid4())[:8],
                description=desc,
            )
            self.items.append(item)
            items.append(item)
        self._refresh()
        return items

    def get(self, item_id: str) -> Optional[TodoItem]:
        """Get item by ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def start(self, item_id: str) -> None:
        """Mark item as in progress. Only one task can be in_progress at a time."""
        item = self.get(item_id)
        if item:
            # First, reset any other in_progress items to pending
            for other in self.items:
                if other.id != item_id and other.status == "in_progress":
                    other.status = "pending"
                    other.started_at = None
            item.start()
            self._refresh()

    def complete(self, item_id: str) -> None:
        """Mark item as completed."""
        item = self.get(item_id)
        if item:
            item.complete()
            self._refresh()

    def fail(self, item_id: str, error: str) -> None:
        """Mark item as failed."""
        item = self.get(item_id)
        if item:
            item.fail(error)
            self._refresh()

    def replan(self, new_items: List[str], reason: str) -> None:
        """
        Replace pending items with new plan.

        Args:
            new_items: List of new task descriptions
            reason: Reason for replan
        """
        # Remove all pending items
        self.items = [item for item in self.items if item.status != "pending"]

        # Add new items with 'is_new' flag
        for desc in new_items:
            item = TodoItem(
                id=str(uuid.uuid4())[:8],
                description=desc,
                is_new=True,
            )
            self.items.append(item)

        self.replan_reason = reason
        self.replan_count += 1
        self._refresh()

    def clear_replan_notice(self) -> None:
        """Clear replan notification."""
        self.replan_reason = None
        for item in self.items:
            item.is_new = False
        self._refresh()

    def render(self) -> Panel:
        """
        Render TODO panel as Rich Panel.

        Returns:
            Rich Panel with formatted TODO list
        """
        # Build table
        table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column("Status", width=4, no_wrap=True)
        table.add_column("Task", ratio=1, overflow="ellipsis")
        table.add_column("Time", width=8, justify="right", no_wrap=True)

        # Separate completed and active items
        completed_items = [i for i in self.items if i.status == "completed"]
        active_items = [i for i in self.items if i.status != "completed"]

        # Show collapsed completed count if > 3
        if len(completed_items) > 3:
            table.add_row(
                "✅",
                Text(f"Completed ({len(completed_items)})", style="dim"),
                "",
            )
        else:
            # Show individual completed items
            for item in completed_items:
                self._add_item_row(table, item)

        # Show active items (up to max_visible)
        visible_active = active_items[: self.max_visible]
        for item in visible_active:
            self._add_item_row(table, item)

        # Show overflow indicator
        if len(active_items) > self.max_visible:
            remaining = len(active_items) - self.max_visible
            table.add_row("", Text(f"... +{remaining} more", style="dim"), "")

        # Build content group
        from rich.console import RenderableType

        content_parts: List[RenderableType] = []

        # Add replan notice if present (truncated for readability)
        if self.replan_reason:
            # Truncate long reason
            reason = self.replan_reason
            if len(reason) > 60:
                reason = reason[:57] + "..."
            notice = Text(f"🔄 {reason}", style="yellow italic")
            content_parts.append(notice)
            content_parts.append(Text(""))  # Spacer

        content_parts.append(table)  # type: ignore[arg-type]

        # Create panel with dynamic title showing progress
        completed_count = len(completed_items)
        total_count = len(self.items)
        progress_title = f"{self.title} [{completed_count}/{total_count}]" if total_count > 0 else self.title

        panel = Panel(
            Group(*content_parts),
            title=progress_title,
            border_style="blue",
            padding=(0, 1),
        )

        return panel

    def _add_item_row(self, table: Table, item: TodoItem) -> None:
        """Add a single item row to the table."""
        icon = item.get_icon()
        color = item.get_color()

        # Truncate long descriptions
        desc_text = item.description
        if len(desc_text) > 50:
            desc_text = desc_text[:47] + "..."

        # Description with strikethrough for completed
        if item.status == "completed":
            desc = Text(desc_text, style=f"{color} strike")
        elif item.is_new:
            desc = Text(f"🆕 {desc_text}", style=color)
        else:
            desc = Text(desc_text, style=color)

        # Info column (duration or error)
        info: Union[str, Text] = ""
        if item.duration_ms > 0:
            if item.duration_ms < 1000:
                info = f"{item.duration_ms}ms"
            else:
                info = f"{item.duration_ms / 1000:.1f}s"
        elif item.error_summary:
            info = Text("❌", style="red")

        table.add_row(icon, desc, info)

    def start_live(self, refresh_per_second: int = 4) -> None:
        """
        Start live display mode.

        Args:
            refresh_per_second: Refresh rate
        """
        if self._live is None:
            self._live = Live(
                self.render(),
                console=self._console,
                refresh_per_second=refresh_per_second,
                transient=True,
            )
            self._live.start()

    def stop_live(self) -> None:
        """Stop live display mode."""
        if self._live:
            self._live.stop()
            self._live = None

    def update(self) -> None:
        """Force refresh the live display."""
        self._refresh()

    def _refresh(self) -> None:
        """Internal refresh method - disabled to avoid screen spam."""
        # Live refresh disabled - conflicts with other console output
        pass

    def __enter__(self) -> "TodoPanel":
        """Context manager entry."""
        self.start_live()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop_live()

    # Convenience methods

    def get_progress_summary(self) -> str:
        """Get progress summary string."""
        total = len(self.items)
        completed = sum(1 for i in self.items if i.status == "completed")
        failed = sum(1 for i in self.items if i.status == "failed")
        in_progress = sum(1 for i in self.items if i.status == "in_progress")

        return f"{completed}/{total} completed, {in_progress} in progress, {failed} failed"

    def get_current_item(self) -> Optional[TodoItem]:
        """Get the currently in-progress item."""
        for item in self.items:
            if item.status == "in_progress":
                return item
        return None

    def get_next_pending(self) -> Optional[TodoItem]:
        """Get the next pending item."""
        for item in self.items:
            if item.status == "pending":
                return item
        return None

    def all_completed(self) -> bool:
        """Check if all items are completed or failed."""
        return all(item.status in ("completed", "failed") for item in self.items)

    @classmethod
    def from_execution_plan(cls, plan: Any, title: str = "📋 Task Progress") -> "TodoPanel":
        """
        Create TodoPanel from ExecutionPlan.

        Args:
            plan: ExecutionPlan instance
            title: Panel title

        Returns:
            TodoPanel with items from plan
        """
        panel = cls(title=title)

        if hasattr(plan, "steps"):
            for step in plan.steps:
                item = TodoItem(
                    id=step.step_id if hasattr(step, "step_id") else str(uuid.uuid4())[:8],
                    description=step.description if hasattr(step, "description") else str(step),
                )
                # Map status
                if hasattr(step, "status"):
                    if step.status == "completed":
                        item.status = "completed"
                    elif step.status == "in_progress":
                        item.status = "in_progress"
                    elif step.status == "failed":
                        item.status = "failed"

                panel.items.append(item)

        return panel
