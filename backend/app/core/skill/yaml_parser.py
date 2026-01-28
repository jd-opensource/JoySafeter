"""YAML frontmatter parser for SKILL.md files."""

import os
import re
from typing import Any, Dict, Optional, Tuple

import yaml

# Pattern to match YAML frontmatter at the beginning of a file
# Matches: ---\n<yaml content>\n---\n
YAML_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# File extensions that are commonly used and safe
COMMON_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",  # Documentation
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",  # Scripts
    ".sh",
    ".bash",
    ".zsh",  # Shell scripts
    ".json",
    ".yaml",
    ".yml",
    ".toml",  # Config files
    ".html",
    ".css",
    ".scss",  # Web assets
    ".svg",
    ".xml",  # Other formats
}

# File extensions that should trigger a warning (potentially unsafe/binary)
WARNED_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bin",
    ".so",
    ".dylib",  # Executables
    ".class",
    ".jar",
    ".war",  # Java
    ".o",
    ".a",
    ".lib",  # Object files
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",  # Archives
    ".db",
    ".sqlite",
    ".sqlite3",  # Databases
}

# System files that should be automatically filtered
SYSTEM_FILES = {
    ".DS_Store",  # macOS
    "Thumbs.db",  # Windows
    ".gitkeep",  # Git
    "desktop.ini",  # Windows
    ".Spotlight-V100",  # macOS
    ".Trashes",  # macOS
    "__MACOSX",  # macOS (zip extraction artifact)
}


def parse_skill_md(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse SKILL.md content, extract YAML frontmatter and markdown body.

    Args:
        content: The full content of a SKILL.md file

    Returns:
        A tuple of (frontmatter_dict, markdown_body)
        - frontmatter_dict: Parsed YAML frontmatter as a dictionary
        - markdown_body: The remaining markdown content after frontmatter
    """
    if not content:
        return {}, ""

    match = YAML_FRONTMATTER_PATTERN.match(content)
    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            # If YAML parsing fails, treat entire content as body
            return {}, content
        body = content[match.end() :]
        return frontmatter, body

    return {}, content


def generate_skill_md(name: str, description: str, body: str = "") -> str:
    """Generate SKILL.md content with YAML frontmatter.

    Args:
        name: The skill name (required)
        description: The skill description (required)
        body: The markdown body content (optional)

    Returns:
        Complete SKILL.md content with YAML frontmatter
    """
    # Escape any special characters in the description for YAML
    # Use literal block style if description contains newlines
    if "\n" in description:
        desc_yaml = f"description: |\n  {description.replace(chr(10), chr(10) + '  ')}"
    else:
        # Quote the description if it contains special YAML characters
        if any(
            c in description
            for c in [":", "#", "[", "]", "{", "}", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]
        ):
            desc_yaml = f'description: "{description}"'
        else:
            desc_yaml = f"description: {description}"

    frontmatter = f"""---
name: {name}
{desc_yaml}
---"""

    if body:
        return f"{frontmatter}\n\n{body}"
    return frontmatter


def validate_file_extension(path: str) -> Tuple[bool, Optional[str]]:
    """Validate file extension and return warning if needed.

    This is a relaxed validation that allows any file structure,
    but warns about potentially unsafe or binary file extensions.

    Args:
        path: The file path to validate

    Returns:
        A tuple of (is_common, warning_message)
        - is_common: True if the file extension is commonly used
        - warning_message: Warning message if extension is potentially unsafe, None otherwise
    """
    if not path:
        return False, "File path cannot be empty"

    # Get file extension
    ext = os.path.splitext(path)[1].lower()

    # No extension is allowed (could be a script or config file)
    if not ext:
        return True, None

    # Check for warned extensions
    if ext in WARNED_EXTENSIONS:
        return False, f"File '{path}' has extension '{ext}' which may be binary or unsafe"

    # Check if it's a common extension
    is_common = ext in COMMON_EXTENSIONS

    # For uncommon extensions, return a soft warning
    if not is_common:
        return False, f"File '{path}' has uncommon extension '{ext}'"

    return True, None


def get_file_extension(path: str) -> str:
    """Get the file extension from a path.

    Args:
        path: The file path

    Returns:
        The file extension (including the dot), lowercase
    """
    return os.path.splitext(path)[1].lower() if path else ""


def is_system_file(path: str) -> bool:
    """Check if a file is a system file that should be filtered.

    Args:
        path: The file path

    Returns:
        True if the file is a system file, False otherwise
    """
    if not path:
        return False

    filename = os.path.basename(path)

    # Check exact matches (case-insensitive)
    if filename.lower() in {f.lower() for f in SYSTEM_FILES}:
        return True

    # Check for .DS_Store in any part of the path
    if ".ds_store" in path.lower():
        return True

    # Check for __MACOSX directory files
    if "__macosx" in path.lower():
        return True

    return False


def is_valid_text_content(content: str) -> Tuple[bool, Optional[str]]:
    """Check if content is valid UTF-8 text (not binary).

    Args:
        content: The file content to validate

    Returns:
        A tuple of (is_valid, error_message)
        - is_valid: True if content is valid text, False otherwise
        - error_message: Error message if invalid, None otherwise
    """
    if content is None:
        return False, "Content is None"

    # Check for NULL bytes (0x00) - binary files contain these
    if "\x00" in content:
        return False, "File contains NULL bytes (binary file)"

    # Check if content can be encoded/decoded as UTF-8
    try:
        # Try to encode and decode to ensure it's valid UTF-8
        content.encode("utf-8").decode("utf-8")
    except UnicodeDecodeError as e:
        return False, f"File is not valid UTF-8 text: {str(e)}"
    except UnicodeEncodeError as e:
        return False, f"File encoding error: {str(e)}"

    # Check for high ratio of non-printable characters (excluding common whitespace)
    # This is a heuristic to detect binary files
    non_printable = sum(1 for c in content if ord(c) < 32 and c not in "\n\r\t")
    total_chars = len(content)

    if total_chars > 0 and non_printable / total_chars > 0.05:
        return False, "File contains too many non-printable characters (likely binary file)"

    return True, None


def extract_metadata_from_frontmatter(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    """Extract standard metadata fields from frontmatter.

    Supports Agent Skills specification fields:
    - name, description (required)
    - license, compatibility, metadata, allowed_tools (optional)

    Args:
        frontmatter: Parsed YAML frontmatter dictionary

    Returns:
        Dictionary with extracted metadata following Agent Skills specification
    """
    # Parse allowed_tools from space-delimited string (per spec)
    allowed_tools = []
    if frontmatter.get("allowed-tools"):
        # Support both "allowed-tools" (with hyphen) and "allowed_tools" (with underscore)
        allowed_tools_str = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools", "")
        if isinstance(allowed_tools_str, str):
            allowed_tools = [tool.strip() for tool in allowed_tools_str.split() if tool.strip()]
        elif isinstance(allowed_tools_str, list):
            allowed_tools = allowed_tools_str

    # Extract metadata dict (per spec: dict[str, str])
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    # Ensure all values are strings (per spec)
    metadata = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}

    return {
        "name": frontmatter.get("name", ""),
        "description": frontmatter.get("description", ""),
        "tags": frontmatter.get("tags", []),
        "license": frontmatter.get("license"),
        "compatibility": frontmatter.get("compatibility"),
        "metadata": metadata,
        "allowed_tools": allowed_tools,
        # Legacy fields (for backward compatibility)
        "version": frontmatter.get("version"),
        "author": frontmatter.get("author"),
    }
