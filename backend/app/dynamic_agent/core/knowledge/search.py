"""CTF Knowledge Search (side-effect free: no caches / singletons)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .parser import normalize_knowledge


def search_yaml_with_keywords(
    knowledge_path: Path,
    ensure_loaded: Callable[[], Any],
    keywords: list[str],
) -> list[str]:
    """
    Search YAML knowledge files using keyword matching.

    Matches keywords against:
    - File names
    - Tags
    - Category
    - Description
    - Indicators

    Returns hints sorted by relevance score (descending).
    """
    hints: list[str] = []
    scored_results: list[tuple[int, list[str]]] = []  # (score, hints_list)

    # Preserve previous behavior: best-effort ensure loader is initialized
    ensure_loaded()

    for yaml_file in knowledge_path.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data:
                    continue

                # Build searchable text from YAML
                name = data.get("name", "").lower()
                category = data.get("category", "").lower()
                tags = [t.lower() for t in data.get("tags", [])]
                description = data.get("description", "").lower()

                # Include indicators in searchable text
                indicators = [ind.lower() for ind in data.get("indicators", [])]
                searchable = f"{name} {category} {' '.join(tags)} {description} {' '.join(indicators)}"

                # Check if any keyword matches
                matched_keywords = [kw for kw in keywords if kw.lower() in searchable]

                # Also check indicators specifically for partial matches
                indicator_matches = 0
                for kw in keywords:
                    kw_lower = kw.lower()
                    for ind in indicators:
                        if kw_lower in ind or ind in kw_lower:
                            indicator_matches += 1

                # Calculate relevance score
                score = len(matched_keywords) * 2 + indicator_matches

                if matched_keywords or indicator_matches > 0:
                    logger.info(
                        f"📚 Matched knowledge: {yaml_file.name} (score: {score}, keywords: {matched_keywords})"
                    )

                    # Build structured hints for this knowledge entry
                    entry_hints: list[str] = []

                    # Extract attack_steps with clear sequential dependency
                    attack_steps = data.get("attack_steps", [])
                    total_steps = len(attack_steps)

                    if total_steps > 0:
                        # Add header emphasizing sequential execution
                        entry_hints.append(
                            f"⚠️ [{name}] CRITICAL: Execute steps IN ORDER (Step N requires Step N-1 to complete first)"
                        )

                    for i, step in enumerate(attack_steps):
                        action = step.get("action", "")
                        method = step.get("method", "")
                        endpoint = step.get("endpoint", "")
                        endpoint_patterns = step.get("endpoint_patterns", [])
                        payload = step.get("payload", "")
                        expected_output = step.get("expected_output", "")
                        depends_on = step.get("depends_on", [])
                        step_num = step.get("step", i + 1)
                        notes = step.get("notes", "")

                        # Build structured hint with method, depends_on
                        if i == 0:
                            hint = f"[{name}] 🔴 Step {step_num}/{total_steps} (START HERE): {action}"
                        else:
                            deps_str = (
                                f"AFTER Step {', '.join(map(str, depends_on))}"
                                if depends_on
                                else f"AFTER Step {step_num - 1}"
                            )
                            hint = f"[{name}] Step {step_num}/{total_steps} ({deps_str}): {action}"

                        if method and endpoint:
                            hint += f" → {method} {endpoint}"
                        elif endpoint:
                            hint += f" → {endpoint}"

                        # Handle multiple endpoint patterns
                        if endpoint_patterns:
                            hint += f" → Try these endpoints: {', '.join(endpoint_patterns)}"

                        if payload and payload not in ("None", ""):
                            hint += f" (payload: {payload})"
                        if expected_output:
                            hint += f" [expect: {expected_output}]"
                        if notes:
                            hint += f" | Note: {notes}"
                        entry_hints.append(hint)

                    # Extract discovery_hints (preferred over key_values)
                    discovery_hints = data.get("discovery_hints", [])
                    if discovery_hints:
                        entry_hints.append(f"[{name}] 🔍 DISCOVERY STRATEGIES (use these to find targets):")
                        for dh in discovery_hints:
                            dh_type = dh.get("type", "unknown")
                            dh_desc = dh.get("description", "")
                            dh_method = dh.get("method", "")
                            dh_pattern = dh.get("pattern", "")
                            dh_range = dh.get("range", dh.get("id_range_hint", ""))

                            hint_line = f"  - [{dh_type}] {dh_desc}"
                            if dh_method:
                                hint_line += f" | Method: {dh_method}"
                            if dh_pattern:
                                hint_line += f" | Pattern: {dh_pattern}"
                            if dh_range:
                                hint_line += f" | Range: {dh_range}"
                            entry_hints.append(hint_line)
                    else:
                        # Fallback: Extract key_values only if no discovery_hints
                        # (for backward compatibility with old YAML files)
                        key_values = data.get("key_values", {})
                        for k, v in key_values.items():
                            # Skip hardcoded answers, only include non-sensitive values
                            if "flag" not in k.lower() and "answer" not in k.lower():
                                entry_hints.append(f"[{name}] 🔑 {k} = {v}")

                    scored_results.append((score, entry_hints))

        except Exception as e:
            logger.warning(f"Error parsing {yaml_file}: {e}")

    # Sort by relevance score (descending) and flatten
    scored_results.sort(key=lambda x: x[0], reverse=True)
    for _, entry_hints in scored_results:
        hints.extend(entry_hints)

    # Silent fallback - return empty list if no matches (no error)
    return hints


def search_by_query(
    knowledge_path: Path,
    ensure_loaded: Callable[[], Any],
    query: str,
) -> list[dict[str, Any]]:
    """
    Search knowledge base by natural language query.

    Returns:
        List of matching knowledge entries with tricks (top 5).
    """
    matches: list[tuple[int, dict[str, Any]]] = []

    ensure_loaded()

    # Tokenize query for matching
    query_lower = query.lower()
    query_tokens = set(query_lower.split())

    for yaml_file in knowledge_path.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data:
                    continue

                # Normalize to new format
                normalized = normalize_knowledge(data)

                # Build searchable text
                name = normalized.get("name", "").lower()
                category = normalized.get("category", "").lower()
                tags = [t.lower() for t in normalized.get("tags", [])]
                indicators = [ind.lower() for ind in normalized.get("indicators", [])]

                searchable = f"{name} {category} {' '.join(tags)} {' '.join(indicators)}"

                # Calculate relevance score
                score = 0

                # Exact phrase match (highest weight)
                if query_lower in searchable:
                    score += 10

                # Token matches
                for token in query_tokens:
                    if len(token) > 2:  # Skip short tokens
                        if token in searchable:
                            score += 2
                        # Tag matching with higher weight for exact matches
                        for tag in tags:
                            if token == tag:
                                # Exact tag match - highest priority for specific attack types
                                score += 8
                            elif token in tag or tag in token:
                                score += 1

                # Name exact match bonus (e.g., "xss" in "xss_blacklist_bypass")
                for token in query_tokens:
                    if len(token) > 2 and token in name:
                        score += 5

                # Indicator matches (important for problem identification)
                for indicator in indicators:
                    for token in query_tokens:
                        if token in indicator:
                            score += 3

                if score > 0:
                    # Build match result
                    match = {
                        "name": normalized.get("name", "unknown"),
                        "file_name": yaml_file.name,  # Include original filename
                        "category": normalized.get("category", "misc"),
                        "relevance": min(score / 20.0, 1.0),  # Normalize to 0-1
                        "tricks": normalized.get("tricks", []),
                        "indicators": normalized.get("indicators", []),
                    }
                    matches.append((score, match))
                    logger.debug(f"Match: {yaml_file.name} (score: {score})")

        except Exception as e:
            logger.warning(f"Error searching {yaml_file}: {e}")

    # Sort by score descending and return top matches
    matches.sort(key=lambda x: x[0], reverse=True)
    return [m[1] for m in matches[:5]]


def get_default_hints(challenge_type: str) -> list[str]:
    """Get default hints when no references are found."""
    defaults = {
        "web": [
            "curl -s <target_url> | grep -i flag",
            "curl -s <target_url>/robots.txt",
            "curl -s <target_url>/admin",
            "Check HTML comments for hints",
        ],
        "pwn": [
            "file <binary> to identify type",
            "checksec <binary> for protections",
            "strings <binary> | grep -i flag",
            "Use pwntools for exploitation",
        ],
        "crypto": [
            "Identify cipher type first",
            "Check for weak keys or IVs",
            "Try common encodings: base64, hex, rot13",
            "Use Python crypto libraries",
        ],
        "reversing": [
            "file <binary> to identify type",
            "strings <binary> | grep -i flag",
            "Use Ghidra/IDA for static analysis",
            "Look for strcmp/check functions",
        ],
        "misc": [
            "file <target> to identify type",
            "binwalk <target> for embedded files",
            "exiftool <target> for metadata",
            "strings <target> | grep -i flag",
        ],
        "forensics": [
            "volatility for memory analysis",
            "foremost for file carving",
            "Check file timestamps and metadata",
            "Look for deleted/hidden files",
        ],
    }
    return defaults.get(challenge_type, defaults["misc"])
