"""
Prompt Registry - Singleton registry for managing and accessing prompts.

This module provides the central PromptRegistry class that:
- Discovers and loads all prompts at startup (T011)
- Provides access by prompt_id (T012)
- Supports category-based queries (T013)
- Lists all available prompts (T014)
- Validates all prompts (T015)
- Detects circular dependencies (T015a)
- Supports manual reload (T031)
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from .exceptions import (
    CircularDependencyError,
    PromptNotFoundError,
    PromptValidationError,
)
from .loader import discover_prompts, load_prompt
from .models import LoadedPrompt


class PromptRegistry:
    """
    Singleton registry for managing and accessing prompts.

    Discovers prompts from the file system at initialization and provides
    runtime access by prompt_id or category.

    Usage:
        registry = PromptRegistry.get_instance()
        prompt = registry.get("base/main_agent")
        rendered = prompt.render(hint_summary="...")
    """

    _instance: Optional["PromptRegistry"] = None

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the registry.

        Args:
            base_dir: Base directory containing prompt files.
                     Defaults to the 'prompts' directory containing this file.
        """
        if base_dir is None:
            # Default to the directory containing this file
            base_dir = Path(__file__).parent

        self._base_dir = base_dir
        self._prompts: dict[str, LoadedPrompt] = {}
        self._loaded = False

    @classmethod
    def get_instance(cls, base_dir: Optional[Path] = None) -> "PromptRegistry":
        """
        Get or create the singleton instance.

        Args:
            base_dir: Base directory for prompts (only used on first call)

        Returns:
            The singleton PromptRegistry instance
        """
        if cls._instance is None:
            cls._instance = cls(base_dir)
            cls._instance._load_all()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None

    def _load_all(self) -> None:
        """
        Discover and load all prompts from the base directory.

        Called automatically on first access via get_instance().
        """
        self._prompts.clear()

        prompt_files = discover_prompts(self._base_dir)

        for file_path in prompt_files:
            try:
                prompt = load_prompt(file_path, self._base_dir, validate=True)

                # Check for duplicate prompt_id
                if prompt.prompt_id in self._prompts:
                    logger.warning(
                        f"Duplicate prompt_id '{prompt.prompt_id}': "
                        f"'{file_path}' shadows '{self._prompts[prompt.prompt_id].file_path}'"
                    )

                self._prompts[prompt.prompt_id] = prompt
                logger.debug(f"Loaded prompt: {prompt.prompt_id}")

            except Exception as e:
                logger.error(f"Failed to load prompt '{file_path}': {e}")

        self._loaded = True
        logger.info(f"Loaded {len(self._prompts)} prompts from {self._base_dir}")

    def get(self, prompt_id: str) -> LoadedPrompt:
        """
        Get a prompt by its ID.

        Args:
            prompt_id: Prompt identifier (e.g., 'base/main_agent')

        Returns:
            The LoadedPrompt instance

        Raises:
            PromptNotFoundError: If prompt_id does not exist
        """
        if not self._loaded:
            self._load_all()

        if prompt_id not in self._prompts:
            available = list(self._prompts.keys())[:10]
            raise PromptNotFoundError(
                prompt_id,
                f"Prompt not found: '{prompt_id}'. "
                f"Available prompts: {available}{'...' if len(self._prompts) > 10 else ''}",
            )

        return self._prompts[prompt_id]

    def get_by_category(self, category: str) -> list[LoadedPrompt]:
        """
        Get all prompts in a category.

        Args:
            category: Category name (e.g., 'system', 'tools', 'agents')

        Returns:
            List of LoadedPrompt instances in the category
        """
        if not self._loaded:
            self._load_all()

        return [prompt for prompt in self._prompts.values() if prompt.metadata.category == category]

    def list_all(self) -> list[str]:
        """
        List all available prompt IDs.

        Returns:
            Sorted list of all prompt IDs
        """
        if not self._loaded:
            self._load_all()

        return sorted(self._prompts.keys())

    def reload(self) -> None:
        """
        Re-discover and reload all prompts from disk.

        Call this after modifying prompt files to pick up changes
        without restarting the application.
        """
        logger.info("Reloading all prompts...")
        self._load_all()

    def validate_all(self) -> list[PromptValidationError]:
        """
        Validate all loaded prompts.

        Checks:
        - All required metadata fields are present
        - Version format is valid semver
        - Prompt IDs are unique (T015)
        - No circular dependencies (T015a)
        - All dependencies exist

        Returns:
            List of validation errors (empty if all valid)
        """
        if not self._loaded:
            self._load_all()

        errors: list[PromptValidationError] = []

        # Check for duplicate IDs (already warned during load, but collect errors)
        seen_ids: dict[str, Path] = {}
        for prompt_id, prompt in self._prompts.items():
            if prompt_id in seen_ids:
                errors.append(
                    PromptValidationError(
                        prompt_id=prompt_id,
                        message=f"Duplicate prompt_id. Also defined at: {seen_ids[prompt_id]}",
                        field="prompt_id",
                    )
                )
            seen_ids[prompt_id] = prompt.file_path

        # Check dependencies exist
        for prompt in self._prompts.values():
            for dep_id in prompt.metadata.dependencies:
                if dep_id not in self._prompts:
                    errors.append(
                        PromptValidationError(
                            prompt_id=prompt.prompt_id,
                            message=f"Dependency not found: '{dep_id}'",
                            field="dependencies",
                        )
                    )

        # Check for circular dependencies (T015a)
        try:
            self._detect_circular_dependencies()
        except CircularDependencyError as e:
            errors.append(e)

        return errors

    def _detect_circular_dependencies(self) -> None:
        """
        Detect circular dependencies between prompts.

        Uses DFS to find cycles in the dependency graph.

        Raises:
            CircularDependencyError: If a cycle is detected
        """
        # Build adjacency list
        graph: dict[str, list[str]] = {
            prompt_id: prompt.metadata.dependencies for prompt_id, prompt in self._prompts.items()
        }

        # Track visit state: 0=unvisited, 1=in_progress, 2=completed
        state: dict[str, int] = {pid: 0 for pid in graph}
        path: list[str] = []

        def dfs(node: str) -> None:
            if state.get(node, 0) == 1:
                # Found cycle - extract it
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                raise CircularDependencyError(cycle)

            if state.get(node, 0) == 2:
                return

            state[node] = 1
            path.append(node)

            for dep in graph.get(node, []):
                if dep in graph:  # Only check existing prompts
                    dfs(dep)

            path.pop()
            state[node] = 2

        for prompt_id in graph:
            if state[prompt_id] == 0:
                dfs(prompt_id)

    def __len__(self) -> int:
        """Return the number of loaded prompts."""
        return len(self._prompts)

    def __contains__(self, prompt_id: str) -> bool:
        """Check if a prompt_id exists."""
        return prompt_id in self._prompts


# Convenience function
def get_registry() -> PromptRegistry:
    """
    Get the singleton PromptRegistry instance.

    Shorthand for PromptRegistry.get_instance().

    Returns:
        The PromptRegistry singleton
    """
    return PromptRegistry.get_instance()
