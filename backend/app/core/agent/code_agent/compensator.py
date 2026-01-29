#!/usr/bin/env python
# coding=utf-8
"""
Tool Compensator for CodeAgent.

This module provides mechanisms to compensate for missing tools by:
1. Using fallback code templates
2. Auto-installing missing packages
3. Dynamically generating tool implementations via LLM
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class CompensationResult:
    """Result of tool compensation."""

    success: bool
    code: str = ""
    error: str | None = None
    method: str = ""  # "template", "install", "generate"

    def __bool__(self) -> bool:
        return self.success


# ============================================================================
# Fallback Code Templates
# ============================================================================

FALLBACK_TEMPLATES = {
    # Web/HTTP operations
    "web_search": '''
import urllib.request
import urllib.parse
import json

def web_search(query: str) -> str:
    """Search the web using DuckDuckGo."""
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json"
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read())
        return data.get("AbstractText", "No results found")
''',
    "http_get": '''
import urllib.request
import json

def http_get(url: str) -> str:
    """Perform HTTP GET request."""
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")
''',
    "http_post": '''
import urllib.request
import json

def http_post(url: str, data: dict) -> str:
    """Perform HTTP POST request."""
    encoded_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return response.read().decode("utf-8")
''',
    # File operations
    "read_file": '''
def read_file(path: str) -> str:
    """Read file contents."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
''',
    "write_file": '''
def write_file(path: str, content: str) -> str:
    """Write content to file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File written: {path}"
''',
    "list_files": '''
import os

def list_files(directory: str = ".") -> list:
    """List files in directory."""
    return os.listdir(directory)
''',
    # Data operations
    "load_csv": '''
import csv

def load_csv(path: str) -> list:
    """Load CSV file as list of dicts."""
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
''',
    "save_csv": '''
import csv

def save_csv(path: str, data: list, headers: list = None) -> str:
    """Save list of dicts to CSV file."""
    if not data:
        return "No data to save"
    headers = headers or list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)
    return f"Saved {len(data)} rows to {path}"
''',
    "load_json": '''
import json

def load_json(path: str) -> dict:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
''',
    "save_json": '''
import json

def save_json(path: str, data: dict, indent: int = 2) -> str:
    """Save data to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    return f"Saved to {path}"
''',
    # Math/Statistics
    "calculate_statistics": '''
import statistics

def calculate_statistics(numbers: list) -> dict:
    """Calculate basic statistics for a list of numbers."""
    return {
        "mean": statistics.mean(numbers),
        "median": statistics.median(numbers),
        "stdev": statistics.stdev(numbers) if len(numbers) > 1 else 0,
        "min": min(numbers),
        "max": max(numbers),
        "sum": sum(numbers),
        "count": len(numbers),
    }
''',
    # Text processing
    "extract_urls": '''
import re

def extract_urls(text: str) -> list:
    """Extract URLs from text."""
    pattern = r'https?://[^\\s<>"{}|\\\\^`\\[\\]]+'
    return re.findall(pattern, text)
''',
    "extract_emails": '''
import re

def extract_emails(text: str) -> list:
    """Extract email addresses from text."""
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}'
    return re.findall(pattern, text)
''',
}

# Package to tool mapping
PACKAGE_TOOL_MAP = {
    "requests": ["http_get", "http_post", "web_search"],
    "pandas": ["load_csv", "save_csv", "load_json"],
    "beautifulsoup4": ["scrape_webpage"],
    "selenium": ["browser_automation"],
}

# Tool to package mapping
TOOL_PACKAGE_MAP = {
    "http_get": "requests",
    "http_post": "requests",
    "web_search": "requests",
    "scrape_webpage": "beautifulsoup4",
    "browser_automation": "selenium",
}


class ToolCompensator:
    """
    Compensates for missing tools in CodeAgent.

    Strategies:
    1. Template-based: Use predefined code templates
    2. Install-based: Auto-install missing packages
    3. LLM-based: Generate tool implementations dynamically

    Example:
        >>> compensator = ToolCompensator()
        >>> result = await compensator.compensate("web_search", {"query": "python"})
        >>> if result.success:
        ...     print(result.code)
    """

    def __init__(
        self,
        templates: Optional[dict[str, str]] = None,
        llm_generator: Optional[Callable[[str, dict], Awaitable[str]]] = None,
        allow_install: bool = False,
        allowed_packages: Optional[list[str]] = None,
    ):
        """
        Initialize the tool compensator.

        Args:
            templates: Custom fallback templates (merged with defaults).
            llm_generator: Async function to generate code via LLM.
            allow_install: Allow auto-installation of packages.
            allowed_packages: List of packages allowed for auto-install.
        """
        self.templates = {**FALLBACK_TEMPLATES}
        if templates:
            self.templates.update(templates)

        self.llm_generator = llm_generator
        self.allow_install = allow_install
        self.allowed_packages = allowed_packages or list(PACKAGE_TOOL_MAP.keys())

        # Track compensations
        self._compensation_count = 0
        self._compensation_history: list[CompensationResult] = []

    def has_template(self, tool_name: str) -> bool:
        """Check if a template exists for the tool."""
        return tool_name in self.templates

    def get_template(self, tool_name: str) -> str | None:
        """Get the template code for a tool."""
        return self.templates.get(tool_name)

    async def compensate(
        self,
        tool_name: str,
        params: Optional[dict] = None,
        context: str = "",
    ) -> CompensationResult:
        """
        Compensate for a missing tool.

        Args:
            tool_name: Name of the missing tool.
            params: Parameters that would be passed to the tool.
            context: Additional context for code generation.

        Returns:
            CompensationResult with generated code or error.
        """
        params = params or {}

        # Strategy 1: Try template
        if tool_name in self.templates:
            result = CompensationResult(
                success=True,
                code=self.templates[tool_name],
                method="template",
            )
            self._record_compensation(result)
            logger.info(f"Compensated '{tool_name}' using template")
            return result

        # Strategy 2: Try package installation
        if self.allow_install and tool_name in TOOL_PACKAGE_MAP:
            package = TOOL_PACKAGE_MAP[tool_name]
            if package in self.allowed_packages:
                install_result = await self._try_install_package(package)
                if install_result.success:
                    # After install, try template again or generate
                    if tool_name in self.templates:
                        result = CompensationResult(
                            success=True,
                            code=self.templates[tool_name],
                            method="install",
                        )
                        self._record_compensation(result)
                        return result

        # Strategy 3: Try LLM generation
        if self.llm_generator is not None:
            result = await self._try_llm_generation(tool_name, params, context)
            if result.success:
                self._record_compensation(result)
                return result

        # Failed to compensate
        result = CompensationResult(
            success=False,
            error=f"Could not compensate for missing tool: {tool_name}",
        )
        self._record_compensation(result)
        return result

    async def _try_install_package(self, package: str) -> CompensationResult:
        """Try to install a Python package."""
        import subprocess

        try:
            logger.info(f"Attempting to install package: {package}")
            result = subprocess.run(
                ["pip", "install", "-q", package],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return CompensationResult(
                    success=True,
                    code=f"# Package '{package}' installed",
                    method="install",
                )
            else:
                return CompensationResult(
                    success=False,
                    error=f"Failed to install {package}: {result.stderr}",
                )

        except Exception as e:
            return CompensationResult(
                success=False,
                error=f"Error installing {package}: {e}",
            )

    async def _try_llm_generation(
        self,
        tool_name: str,
        params: dict,
        context: str,
    ) -> CompensationResult:
        """Try to generate tool implementation via LLM."""
        if self.llm_generator is None:
            return CompensationResult(
                success=False,
                error="No LLM generator available",
            )

        try:
            prompt = f"""Generate a Python function to implement the tool '{tool_name}'.

Parameters that will be passed: {params}

Context: {context}

Requirements:
1. Function name must be exactly: {tool_name}
2. Handle errors gracefully
3. Return appropriate type based on the tool name
4. Use only standard library if possible
5. Add docstring explaining usage

Generate ONLY the function code, no explanation."""

            code = await self.llm_generator(prompt, params)

            # Validate generated code
            if not self._validate_generated_code(code, tool_name):
                return CompensationResult(
                    success=False,
                    error="Generated code failed validation",
                )

            return CompensationResult(
                success=True,
                code=code,
                method="generate",
            )

        except Exception as e:
            return CompensationResult(
                success=False,
                error=f"LLM generation failed: {e}",
            )

    def _validate_generated_code(self, code: str, tool_name: str) -> bool:
        """Validate LLM-generated code."""
        import ast

        try:
            # Check syntax
            ast.parse(code)

            # Check function name exists
            if f"def {tool_name}(" not in code:
                return False

            # Basic security checks
            dangerous_patterns = [
                r"__import__",
                r"eval\s*\(",
                r"exec\s*\(",
                r"os\.system",
                r"subprocess\.",
            ]

            for pattern in dangerous_patterns:
                if re.search(pattern, code):
                    logger.warning(f"Dangerous pattern found in generated code: {pattern}")
                    return False

            return True

        except SyntaxError:
            return False

    def _record_compensation(self, result: CompensationResult) -> None:
        """Record compensation attempt."""
        self._compensation_count += 1
        self._compensation_history.append(result)

        # Keep only last 100 entries
        if len(self._compensation_history) > 100:
            self._compensation_history = self._compensation_history[-100:]

    def add_template(self, tool_name: str, code: str) -> None:
        """Add or update a template."""
        self.templates[tool_name] = code
        logger.debug(f"Added template for tool: {tool_name}")

    def get_stats(self) -> dict:
        """Get compensation statistics."""
        successful = sum(1 for r in self._compensation_history if r.success)
        by_method: dict[str, int] = {}
        for r in self._compensation_history:
            if r.success:
                by_method[r.method] = by_method.get(r.method, 0) + 1

        return {
            "total_attempts": self._compensation_count,
            "successful": successful,
            "failed": self._compensation_count - successful,
            "by_method": by_method,
        }


def create_compensator(
    llm: Optional[Callable] = None,
    allow_install: bool = False,
) -> ToolCompensator:
    """
    Factory function to create a configured ToolCompensator.

    Args:
        llm: LLM function for code generation.
        allow_install: Allow package auto-installation.

    Returns:
        Configured ToolCompensator instance.
    """

    async def llm_generator(prompt: str, params: dict) -> str:
        if llm is None:
            raise ValueError("No LLM provided")
        result = llm(prompt)
        if hasattr(result, "__await__"):
            return str(await result)  # type: ignore[misc]
        return str(result)

    return ToolCompensator(
        llm_generator=llm_generator if llm else None,
        allow_install=allow_install,
    )


__all__ = [
    "CompensationResult",
    "ToolCompensator",
    "create_compensator",
    "FALLBACK_TEMPLATES",
    "PACKAGE_TOOL_MAP",
    "TOOL_PACKAGE_MAP",
]
