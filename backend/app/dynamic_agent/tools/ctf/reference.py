"""
CTF Reference Search Tool

Provides safe reference search capabilities for CTF challenges:
- Search CTF knowledge bases using ripgrep (rg)
- Read reference files safely
- Extract relevant snippets for solution guidance
"""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from app.dynamic_agent.core.constants import CtfReferenceSource
from app.dynamic_agent.storage.session.ctf import ReferenceHit

# Default paths for CTF reference search
# Container paths (mounted volumes)
DEFAULT_REFERENCE_PATHS = [
    "/opt/ctf/knowledge",  # CTF knowledge base (mounted from host)
    "/opt/ctf/references",  # Reference solutions
    "/opt/ctf/writeups",  # CTF writeups
    "/opt/ctf/payloads",  # Payload templates
    "./ctf_references",  # Local development
    "./writeups",  # Local writeups
]

# Local development paths (for running outside container)
_local_knowledge_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "dynamic_engine", "handlers", "knowledge", "ctf"
)
if os.path.exists(_local_knowledge_path):
    DEFAULT_REFERENCE_PATHS.insert(0, _local_knowledge_path)

# Safe file extensions to read
SAFE_EXTENSIONS = {".txt", ".md", ".py", ".sh", ".json", ".yaml", ".yml", ".xml", ".html"}

# Maximum file size to read (1MB)
MAX_FILE_SIZE = 1024 * 1024

# Maximum snippet length
MAX_SNIPPET_LENGTH = 512


@dataclass
class SearchResult:
    """Result from a reference search."""

    file_path: str
    line_number: int
    content: str
    match_context: str = ""


def _is_safe_path(path: str, base_paths: List[str]) -> bool:
    """Check if path is within allowed base paths."""
    abs_path = os.path.abspath(path)
    for base in base_paths:
        abs_base = os.path.abspath(base)
        if abs_path.startswith(abs_base):
            return True
    return False


def _is_safe_file(file_path: str) -> bool:
    """Check if file is safe to read."""
    path = Path(file_path)

    # Check extension
    if path.suffix.lower() not in SAFE_EXTENSIONS:
        return False

    # Check file size
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False

    return True


def search_references_rg(
    query: str,
    search_paths: Optional[List[str]] = None,
    max_results: int = 10,
    case_sensitive: bool = False,
) -> List[SearchResult]:
    """
    Search CTF references using ripgrep (rg).

    Args:
        query: Search query (supports regex)
        search_paths: Paths to search (defaults to DEFAULT_REFERENCE_PATHS)
        max_results: Maximum number of results to return
        case_sensitive: Whether search is case-sensitive

    Returns:
        List of SearchResult objects
    """
    if search_paths is None:
        search_paths = [p for p in DEFAULT_REFERENCE_PATHS if os.path.exists(p)]

    if not search_paths:
        logger.warning("No valid reference paths found for search")
        return []

    results = []

    for search_path in search_paths:
        if not os.path.exists(search_path):
            continue

        try:
            # Build rg command
            cmd = ["rg", "--json", "-m", str(max_results)]

            if not case_sensitive:
                cmd.append("-i")

            # Add file type filters for safety
            for ext in SAFE_EXTENSIONS:
                cmd.extend(["-g", f"*{ext}"])

            cmd.extend([query, search_path])

            # Execute with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Parse JSON output
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    import json

                    data = json.loads(line)
                    if data.get("type") == "match":
                        match_data = data.get("data", {})
                        path_data = match_data.get("path", {})
                        file_path = path_data.get("text", "")
                        line_num = match_data.get("line_number", 0)
                        lines = match_data.get("lines", {})
                        content = lines.get("text", "").strip()

                        if file_path and _is_safe_file(file_path):
                            results.append(
                                SearchResult(
                                    file_path=file_path,
                                    line_number=line_num,
                                    content=content[:MAX_SNIPPET_LENGTH],
                                )
                            )

                            if len(results) >= max_results:
                                break
                except (json.JSONDecodeError, KeyError):
                    continue

        except subprocess.TimeoutExpired:
            logger.warning(f"Search timeout for path: {search_path}")
        except FileNotFoundError:
            logger.warning("ripgrep (rg) not found, falling back to grep")
            # Fallback to grep
            results.extend(_search_with_grep(query, search_path, max_results - len(results), case_sensitive))
        except Exception as e:
            logger.error(f"Search error: {e}")

    return results[:max_results]


def _search_with_grep(
    query: str,
    search_path: str,
    max_results: int,
    case_sensitive: bool,
) -> List[SearchResult]:
    """Fallback search using grep."""
    results = []

    try:
        cmd = ["grep", "-r", "-n", "-m", str(max_results)]

        if not case_sensitive:
            cmd.append("-i")

        # Add include patterns for safe extensions
        for ext in SAFE_EXTENSIONS:
            cmd.extend(["--include", f"*{ext}"])

        cmd.extend([query, search_path])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Parse grep output: file:line:content
            match = re.match(r"^(.+?):(\d+):(.*)$", line)
            if match:
                file_path, line_num, content = match.groups()
                if _is_safe_file(file_path):
                    results.append(
                        SearchResult(
                            file_path=file_path,
                            line_number=int(line_num),
                            content=content[:MAX_SNIPPET_LENGTH],
                        )
                    )

    except Exception as e:
        logger.error(f"Grep search error: {e}")

    return results


def read_reference_file(
    file_path: str,
    start_line: int = 1,
    num_lines: int = 50,
    allowed_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Safely read a reference file.

    Args:
        file_path: Path to the file
        start_line: Starting line number (1-indexed)
        num_lines: Number of lines to read
        allowed_paths: Allowed base paths (defaults to DEFAULT_REFERENCE_PATHS)

    Returns:
        Tuple of (success, content_or_error)
    """
    if allowed_paths is None:
        allowed_paths = DEFAULT_REFERENCE_PATHS

    # Security checks
    if not _is_safe_path(file_path, allowed_paths):
        return False, f"Path not in allowed directories: {file_path}"

    if not _is_safe_file(file_path):
        return False, f"File not safe to read: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Extract requested lines (1-indexed)
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), start_idx + num_lines)

        content = "".join(lines[start_idx:end_idx])
        return True, content

    except Exception as e:
        return False, f"Error reading file: {e}"


def search_ctf_references(
    challenge_description: str,
    challenge_type: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    max_results: int = 5,
) -> List[ReferenceHit]:
    """
    Search CTF references based on challenge description.

    Args:
        challenge_description: Description of the CTF challenge
        challenge_type: Type of challenge (crypto, pwn, web, misc, etc.)
        keywords: Additional keywords to search
        max_results: Maximum number of results

    Returns:
        List of ReferenceHit objects
    """
    hits = []

    # Build search queries
    queries = []

    # Add challenge type as query
    if challenge_type:
        queries.append(challenge_type)

    # Add keywords
    if keywords:
        queries.extend(keywords)

    # Extract key terms from description
    # Simple extraction: look for technical terms
    tech_patterns = [
        r"\b(base64|hex|rot13|caesar|xor|aes|rsa|md5|sha\d*)\b",
        r"\b(sql|xss|csrf|ssrf|lfi|rfi|ssti|xxe)\b",
        r"\b(buffer\s*overflow|stack|heap|rop|ret2\w+)\b",
        r"\b(flag|ctf|challenge)\b",
    ]

    for pattern in tech_patterns:
        matches = re.findall(pattern, challenge_description.lower())
        queries.extend(matches)

    # Deduplicate queries
    queries = list(set(queries))

    # Search for each query
    seen_paths = set()
    for query in queries[:5]:  # Limit to 5 queries
        results = search_references_rg(query, max_results=3)

        for result in results:
            if result.file_path not in seen_paths:
                seen_paths.add(result.file_path)

                # Determine source type
                source = CtfReferenceSource.LOCAL_BANK
                if "writeup" in result.file_path.lower():
                    source = CtfReferenceSource.PRIOR_SOLUTION

                # Calculate confidence based on match quality
                confidence = 0.5
                if challenge_type and challenge_type.lower() in result.content.lower():
                    confidence += 0.2
                if any(kw.lower() in result.content.lower() for kw in (keywords or [])):
                    confidence += 0.2

                hits.append(
                    ReferenceHit(
                        source=source,
                        location=result.file_path,
                        snippet=result.content,
                        confidence=min(confidence, 1.0),
                    )
                )

                if len(hits) >= max_results:
                    break

        if len(hits) >= max_results:
            break

    return hits


def extract_flag_pattern(text: str) -> Optional[str]:
    """
    Extract flag pattern from text.

    Args:
        text: Text to search for flag

    Returns:
        Extracted flag or None
    """
    # Common flag patterns
    patterns = [
        r"flag\{[^}]+\}",
        r"FLAG\{[^}]+\}",
        r"ctf\{[^}]+\}",
        r"CTF\{[^}]+\}",
        r"\w+CTF\{[^}]+\}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None
