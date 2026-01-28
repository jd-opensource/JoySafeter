"""
TODO Display Manager - Real-time Rich terminal display for task progress.

006: Single Subagent Clean Architecture
Provides a global TODO panel that can be updated from anywhere in the agent execution flow.
"""

import threading
from typing import List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from app.dynamic_agent.models.todo_panel import TodoItem, TodoPanel


class TodoDisplayManager:
    """
    Singleton manager for real-time TODO panel display.

    Features:
    - Global access from anywhere in the codebase
    - Thread-safe updates
    - Rich Live terminal display
    - Auto-refresh without blocking execution
    """

    _instance: Optional["TodoDisplayManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.panel: Optional[TodoPanel] = None
        self.live: Optional[Live] = None
        self.console = Console()
        self._running = False

    @classmethod
    def get_instance(cls) -> "TodoDisplayManager":
        """Get or create singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def create_panel(self, title: str = "📋 Todos", items: Optional[List[str]] = None) -> TodoPanel:
        """
        Create a new TODO panel.

        Args:
            title: Panel title
            items: Optional initial items

        Returns:
            Created TodoPanel
        """
        self.panel = TodoPanel(title=title)
        if items:
            self.panel.add_items(items)
        return self.panel

    def start_display(self, refresh_per_second: int = 2) -> None:
        """
        Start the TODO display.

        NOTE: Live refresh is disabled to avoid conflicts with other console output.
        Instead, we print static updates when state changes.
        """
        if self.panel is None:
            self.create_panel()

        # Disable Live mode entirely - it conflicts with other console output
        # Just mark as running for static updates
        self._running = True
        self.live = None  # Explicitly disable Live

        # Print initial state once
        self.console.print(self._render())

    def stop_display(self) -> None:
        """Stop the Rich Live display."""
        if self.live:
            self.live.stop()
            self.live = None
        self._running = False

    def update(self) -> None:
        """Force update the display - prints static output."""
        if self._running and self.panel:
            # Print updated panel state
            self.console.print(self._render())

    def _render(self) -> Panel:
        """Render the current panel state."""
        if self.panel:
            return self.panel.render()

        # Empty state
        return Panel(
            Text("No tasks yet...", style="dim"),
            title="📋 Todos",
            border_style="blue",
        )

    # Convenience methods that auto-update display

    def add_task(self, description: str, task_id: Optional[str] = None) -> TodoItem:
        """Add a task and update display."""
        if self.panel is None:
            self.create_panel()
        # Type narrowing: create_panel always sets self.panel
        assert self.panel is not None
        item = self.panel.add(description, item_id=task_id)
        self.update()
        return item

    def add_tasks(self, descriptions: List[str]) -> List[TodoItem]:
        """Add multiple tasks and update display."""
        if self.panel is None:
            self.create_panel()
        # Type narrowing: create_panel always sets self.panel
        assert self.panel is not None
        items = self.panel.add_items(descriptions)
        self.update()
        return items

    def start_task(self, task_id: str) -> None:
        """Mark task as in progress and update display."""
        if self.panel:
            self.panel.start(task_id)
            self.update()

    def complete_task(self, task_id: str) -> None:
        """Mark task as completed and update display."""
        if self.panel:
            self.panel.complete(task_id)
            self.update()

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed and update display."""
        if self.panel:
            self.panel.fail(task_id, error)
            self.update()

    def replan(self, new_items: List[str], reason: str) -> None:
        """Replan with new tasks and update display."""
        if self.panel:
            self.panel.replan(new_items, reason)
            self.update()

    def get_current_task(self) -> Optional[TodoItem]:
        """Get the currently in-progress task."""
        if self.panel:
            return self.panel.get_current_item()
        return None

    def get_next_pending(self) -> Optional[TodoItem]:
        """Get the next pending task."""
        if self.panel:
            return self.panel.get_next_pending()
        return None

    def start_next_task(self) -> Optional[TodoItem]:
        """Start the next pending task."""
        if self.panel:
            next_item = self.panel.get_next_pending()
            if next_item:
                self.panel.start(next_item.id)
                self.update()
                return next_item
        return None

    def complete_current_and_start_next(self) -> Optional[TodoItem]:
        """Complete current task and start next one."""
        if self.panel:
            current = self.panel.get_current_item()
            if current:
                self.panel.complete(current.id)

            next_item = self.panel.get_next_pending()
            if next_item:
                self.panel.start(next_item.id)
                self.update()
                return next_item

            self.update()
        return None

    def is_all_done(self) -> bool:
        """Check if all tasks are completed."""
        if self.panel:
            return self.panel.all_completed()
        return True

    def get_summary(self) -> str:
        """Get progress summary string."""
        if self.panel:
            return self.panel.get_progress_summary()
        return "No tasks"

    def clear(self) -> None:
        """Clear all tasks."""
        if self.panel:
            self.panel.items.clear()
            self.panel.replan_reason = None
            self.update()

    def __enter__(self) -> "TodoDisplayManager":
        self.start_display()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop_display()


# Global instance access
def get_todo_display() -> TodoDisplayManager:
    """Get the global TODO display manager."""
    return TodoDisplayManager.get_instance()


def show_todos(items: List[str], title: str = "📋 Todos") -> TodoDisplayManager:
    """
    Quick helper to create and show a TODO panel.

    Args:
        items: List of task descriptions
        title: Panel title

    Returns:
        TodoDisplayManager instance
    """
    manager = get_todo_display()
    manager.create_panel(title=title, items=items)
    manager.start_display()
    return manager
