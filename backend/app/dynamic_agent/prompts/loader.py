"""
Prompt loader for parsing and loading prompt files.

This module handles:
- YAML frontmatter parsing (T008)
- Prompt file discovery (T009)
- Variable interpolation (T010)
- Field validation (T027, T028, T028a)
"""

import re
from pathlib import Path

import frontmatter
from loguru import logger

from .exceptions import PromptLoadError, PromptValidationError
from .models import LoadedPrompt, PromptMetadata

# Required metadata fields
REQUIRED_FIELDS = ["name", "description", "purpose", "usage_context", "version"]

# Semver pattern for version validation
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def discover_prompts(base_dir: Path) -> list[Path]:
    """
    Discover all prompt files in the given directory.

    Recursively searches for all .md files in the base directory
    and its subdirectories.

    Args:
        base_dir: Base directory to search for prompts

    Returns:
        List of absolute paths to prompt files
    """
    if not base_dir.exists():
        logger.warning(f"Prompts directory does not exist: {base_dir}")
        return []

    prompt_files = list(base_dir.rglob("*.md"))

    # Filter out non-prompt files (like README, CATALOG)
    prompt_files = [
        f
        for f in prompt_files
        if not f.name.upper().startswith("README")
        and not f.name.upper().startswith("PROMPTS_CATALOG")
        and not f.name.upper().startswith("CONTRIBUTING")
    ]

    logger.debug(f"Discovered {len(prompt_files)} prompt files in {base_dir}")
    return prompt_files


def load_prompt(file_path: Path, base_dir: Path, validate: bool = True) -> LoadedPrompt:
    """
    Load a single prompt file.

    Parses YAML frontmatter, extracts metadata, and creates a LoadedPrompt.

    Args:
        file_path: Path to the prompt file
        base_dir: Base prompts directory (for deriving prompt_id)
        validate: Whether to validate required fields

    Returns:
        LoadedPrompt instance

    Raises:
        PromptLoadError: If file cannot be read or parsed
        PromptValidationError: If validation fails
    """
    # Validate encoding (T028a)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except UnicodeDecodeError as e:
        raise PromptLoadError(str(file_path), "File is not valid UTF-8 encoding", cause=e)
    except Exception as e:
        raise PromptLoadError(str(file_path), f"Failed to read file: {e}", cause=e)

    # Parse frontmatter
    try:
        post = frontmatter.loads(raw_content)
    except Exception as e:
        raise PromptLoadError(str(file_path), f"Failed to parse YAML frontmatter: {e}", cause=e)

    metadata_dict = dict(post.metadata)
    content = post.content

    # Derive prompt_id and category from path
    try:
        relative_path = file_path.relative_to(base_dir)
        prompt_id = str(relative_path.with_suffix("")).replace("\\", "/")
        category = relative_path.parts[0] if len(relative_path.parts) > 1 else "default"
    except ValueError:
        # File is not under base_dir
        prompt_id = file_path.stem
        category = "default"

    # Add derived fields
    metadata_dict["prompt_id"] = prompt_id
    metadata_dict["category"] = metadata_dict.get("category", category)

    # Set defaults for optional fields
    metadata_dict.setdefault("dependencies", [])
    metadata_dict.setdefault("variables", [])

    # Validate if requested (T027, T028)
    if validate:
        _validate_metadata(metadata_dict, prompt_id)

    # Create metadata object
    try:
        metadata = PromptMetadata(
            name=metadata_dict.get("name", prompt_id),
            description=metadata_dict.get("description", ""),
            purpose=metadata_dict.get("purpose", ""),
            usage_context=metadata_dict.get("usage_context", ""),
            version=metadata_dict.get("version", "1.0.0"),
            category=metadata_dict["category"],
            prompt_id=metadata_dict["prompt_id"],
            dependencies=metadata_dict["dependencies"],
            variables=metadata_dict["variables"],
        )
    except Exception as e:
        raise PromptLoadError(str(file_path), f"Failed to create metadata: {e}", cause=e)

    return LoadedPrompt(metadata=metadata, content=content, file_path=file_path.resolve())


def _validate_metadata(metadata: dict, prompt_id: str) -> None:
    """
    Validate prompt metadata fields.

    Checks for required fields (T027) and version format (T028).

    Args:
        metadata: Metadata dictionary to validate
        prompt_id: Prompt ID for error messages

    Raises:
        PromptValidationError: If validation fails
    """
    # Check required fields (T027)
    for field in REQUIRED_FIELDS:
        if field not in metadata or not metadata[field]:
            raise PromptValidationError(prompt_id=prompt_id, message=f"Missing required field: {field}", field=field)

    # Validate version format (T028)
    version = metadata.get("version", "")
    if version and not SEMVER_PATTERN.match(version):
        raise PromptValidationError(
            prompt_id=prompt_id,
            message=f"Invalid version format: '{version}'. Expected semver (e.g., '1.0.0')",
            field="version",
        )


class SafeDict(dict):
    """
    Dict subclass for safe string formatting.

    Returns {key} for missing keys instead of raising KeyError,
    allowing partial variable substitution.
    """

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def render_prompt(content: str, **kwargs) -> str:
    """
    Render prompt content with variable substitution.

    Uses SafeDict to safely handle missing variables - they remain
    as {variable_name} in the output.

    Args:
        content: Prompt content with {variable} placeholders
        **kwargs: Variable values to substitute

    Returns:
        Rendered content with variables replaced
    """
    return content.format_map(SafeDict(**kwargs))
