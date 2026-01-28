"""
Data models for the centralized prompt management system.

This module defines the core data structures used to represent prompts
and their metadata throughout the system.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PromptMetadata:
    """
    Metadata parsed from YAML frontmatter of a prompt file.

    Attributes:
        name: Human-readable prompt name
        description: Brief description of purpose
        purpose: When/why to use this prompt
        usage_context: Which component uses this prompt
        version: Semantic version string (e.g., "1.0.0")
        category: Category derived from folder path (e.g., "system", "tools")
        prompt_id: Unique identifier derived from relative path (e.g., "base/main_agent")
        dependencies: List of other prompt IDs this prompt depends on
        variables: List of variable names used in the prompt content
    """

    name: str
    description: str
    purpose: str
    usage_context: str
    version: str
    category: str
    prompt_id: str
    dependencies: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)


@dataclass
class LoadedPrompt:
    """
    A fully loaded prompt with metadata and content.

    Attributes:
        metadata: Parsed YAML frontmatter as PromptMetadata
        content: Raw prompt content with placeholders
        file_path: Absolute path to the source file
    """

    metadata: PromptMetadata
    content: str
    file_path: Path

    def render(self, **kwargs) -> str:
        """
        Render the prompt content with variable substitution.

        Only replaces explicitly declared variables from metadata.
        Other {patterns} like FLAG{...} or JSON are preserved.

        Args:
            **kwargs: Variable values to substitute

        Returns:
            Rendered prompt content with variables replaced
        """
        result = self.content

        # Only replace variables that are declared in metadata
        declared_vars = set(self.metadata.variables)

        for key, value in kwargs.items():
            if key in declared_vars:
                result = result.replace(f"{{{key}}}", str(value))

        return result

    @property
    def prompt_id(self) -> str:
        """Shortcut to get prompt_id from metadata."""
        return self.metadata.prompt_id

    @property
    def name(self) -> str:
        """Shortcut to get name from metadata."""
        return self.metadata.name
