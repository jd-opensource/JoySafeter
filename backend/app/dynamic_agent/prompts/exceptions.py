"""
Custom exceptions for the centralized prompt management system.

These exceptions provide clear error messages for prompt-related issues.
"""

from typing import Optional


class PromptNotFoundError(KeyError):
    """
    Raised when a requested prompt ID does not exist in the registry.

    Attributes:
        prompt_id: The prompt ID that was not found
        message: Detailed error message
    """

    def __init__(self, prompt_id: str, message: Optional[str] = None):
        self.prompt_id = prompt_id
        self.message = message or f"Prompt not found: '{prompt_id}'"
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class PromptValidationError(ValueError):
    """
    Raised when a prompt fails validation.

    Attributes:
        prompt_id: The prompt ID that failed validation
        message: Detailed error message
        field: Optional field name that caused the error
    """

    def __init__(self, prompt_id: str, message: str, field: Optional[str] = None):
        self.prompt_id = prompt_id
        self.message = message
        self.field = field
        super().__init__(f"Validation error for '{prompt_id}': {message}")

    def __str__(self) -> str:
        if self.field:
            return f"Validation error for '{self.prompt_id}' (field: {self.field}): {self.message}"
        return f"Validation error for '{self.prompt_id}': {self.message}"


class PromptLoadError(Exception):
    """
    Raised when a prompt file cannot be loaded.

    Attributes:
        file_path: Path to the file that failed to load
        message: Detailed error message
        cause: Optional underlying exception
    """

    def __init__(self, file_path: str, message: str, cause: Optional[Exception] = None):
        self.file_path = file_path
        self.message = message
        self.cause = cause
        super().__init__(f"Failed to load prompt from '{file_path}': {message}")

    def __str__(self) -> str:
        base = f"Failed to load prompt from '{self.file_path}': {self.message}"
        if self.cause:
            base += f" (caused by: {self.cause})"
        return base


class CircularDependencyError(PromptValidationError):
    """
    Raised when circular dependencies are detected between prompts.

    Attributes:
        cycle: List of prompt IDs forming the cycle
    """

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        cycle_str = " -> ".join(cycle)
        super().__init__(
            prompt_id=cycle[0] if cycle else "unknown",
            message=f"Circular dependency detected: {cycle_str}",
            field="dependencies",
        )
