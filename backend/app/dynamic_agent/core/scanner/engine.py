"""
Regex-based Scanning Engine
"""

import os
import re
from pathlib import Path
from typing import Dict, List

from .rules import Finding, VulnerabilityRule


class RegexEngine:
    """
    Regex-based vulnerability scanner engine.

    Scans files for patterns defined in VulnerabilityRule instances.
    """

    def __init__(self, rules: List[VulnerabilityRule]):
        """
        Initialize the regex engine with a set of rules.

        Args:
            rules: List of VulnerabilityRule instances
        """
        self.rules = rules
        self._compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[str, List[re.Pattern]]:
        """
        Compile all regex patterns for better performance.

        Returns:
            Dictionary mapping rule_id to list of compiled patterns
        """
        compiled = {}
        for rule in self.rules:
            patterns = []
            for pattern in rule.patterns:
                try:
                    compiled_pattern = re.compile(pattern, re.MULTILINE)
                    patterns.append(compiled_pattern)
                except re.error as e:
                    print(f"Warning: Invalid regex pattern in rule {rule.id}: {pattern}. Error: {e}")
            compiled[rule.id] = patterns
        return compiled

    def _get_file_language(self, file_path: str) -> str:
        """
        Determine the programming language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            File extension (e.g., '.py', '.js')
        """
        return Path(file_path).suffix.lower()

    def _extract_context(self, lines: List[str], match_start: int, match_end: int, context_lines: int = 5) -> str:
        """
        Extract context around a match (lines before and after).

        Args:
            lines: All lines in the file
            match_start: Starting position of the match
            match_end: Ending position of the match
            context_lines: Number of lines to extract before and after

        Returns:
            Context string
        """
        # Find line numbers
        len(lines)

        # Count lines up to match_start
        line_num_start = 0
        char_count = 0
        for i, line in enumerate(lines):
            if char_count + len(line) >= match_start:
                line_num_start = i
                break
            char_count += len(line) + 1  # +1 for newline

        # Count lines up to match_end
        char_count = 0
        for i, line in enumerate(lines):
            if char_count + len(line) >= match_end:
                line_num_end = i
                break
            char_count += len(line) + 1

        # Extract context lines
        context_start = max(0, line_num_start - context_lines)
        context_end = min(len(lines), line_num_end + context_lines + 1)

        context = "\n".join(lines[context_start:context_end])
        return context

    def scan_file(self, file_path: str, content: str) -> List[Finding]:
        """
        Scan a single file for vulnerabilities.

        Args:
            file_path: Path to the file
            content: File content as string

        Returns:
            List of Finding instances
        """
        findings = []
        lines = content.split("\n")
        file_ext = self._get_file_language(file_path)

        for rule in self.rules:
            # Skip rules that don't apply to this file type
            if file_ext not in rule.languages:
                continue

            patterns = self._compiled_patterns.get(rule.id, [])
            if not patterns:
                continue

            for pattern in patterns:
                # Find all matches
                for match in pattern.finditer(content):
                    # Get the matched line
                    match_start = match.start()
                    match_end = match.end()

                    # Extract code snippet (just the matched text)
                    code_snippet = match.group(0)

                    # Extract context
                    context = self._extract_context(lines, match_start, match_end)

                    # Find line number
                    char_count = 0
                    line_number = 1
                    for line in lines:
                        if char_count + len(line) >= match_start:
                            break
                        char_count += len(line) + 1
                        line_number += 1

                    # Create Finding
                    finding = Finding(
                        id=f"{rule.id}_{file_path}_{line_number}_{hash(match.group(0))}",
                        rule_id=rule.id,
                        name=rule.name,
                        severity=rule.severity,
                        file_path=file_path,
                        line_number=line_number,
                        code_snippet=code_snippet,
                        context=context,
                    )
                    findings.append(finding)

        return findings

    def scan_directory(self, directory: str) -> List[Finding]:
        """
        Scan all files in a directory.

        Args:
            directory: Path to directory

        Returns:
            List of Finding instances
        """
        findings = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    file_findings = self.scan_file(file_path, content)
                    findings.extend(file_findings)
                except Exception as e:
                    # Skip files that can't be read
                    print(f"Warning: Could not read file {file_path}: {e}")
                    continue

        return findings

    def get_statistics(self, findings: List[Finding]) -> Dict[str, int]:
        """
        Get statistics about findings.

        Args:
            findings: List of Finding instances

        Returns:
            Dictionary with statistics
        """
        stats = {
            "total": len(findings),
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }

        for finding in findings:
            severity = finding.severity.lower()
            if severity in stats:
                stats[severity] += 1

        return stats
