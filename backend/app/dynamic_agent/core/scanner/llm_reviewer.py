"""
LLM Agent Reviewer - Uses LLM to verify vulnerability findings

This module provides AI-powered verification of SAST findings to reduce false positives.
"""

import json
import os
from pathlib import Path
from typing import Dict, List

from loguru import logger


class LLMAgentReviewer:
    """
    LLM-powered reviewer for SAST findings.

    Loads the vulnerability_review.md prompt template and uses LLM to analyze
    each finding in context of the actual source code.
    """

    def __init__(self, max_findings_per_batch: int = 20):
        """
        Initialize the LLM reviewer.

        Args:
            max_findings_per_batch: Maximum findings to process with LLM per scan
        """
        self.max_findings_per_batch = max_findings_per_batch
        self.prompt_template = self._load_prompt_template()
        self._llm = None

    def _load_prompt_template(self) -> str:
        """Load the vulnerability review prompt template."""
        prompt_path = (
            Path(__file__).parent.parent.parent / "prompts" / "scenes" / "source_code_audit" / "vulnerability_review.md"
        )

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
            logger.info(f"Loaded prompt template from {prompt_path}")
            return template
        except FileNotFoundError:
            logger.warning(f"Prompt template not found at {prompt_path}, using default")
            return self._get_default_template()

    def _get_default_template(self) -> str:
        """Return a default prompt template if file not found."""
        return """You are a security expert reviewing a vulnerability finding.

Finding:
- Tool: {{tool}}
- Rule: {{rule_id}}
- Severity: {{severity}}
- File: {{file_path}}
- Line: {{line_number}}
- Message: {{message}}

Code:
```
{{code_snippet}}
```

Respond with JSON:
{"verdict": "TRUE_POSITIVE|FALSE_POSITIVE|UNCERTAIN", "confidence": "HIGH|MEDIUM|LOW", "analysis": "brief explanation"}"""

    def _get_llm(self):
        """Get or create LLM instance."""
        if self._llm is None:
            try:
                from app.dynamic_agent.infra.llm import get_default_llm

                self._llm = get_default_llm()
                logger.info("LLM instance created for agent review")
            except Exception as e:
                logger.error(f"Failed to create LLM instance: {e}")
                raise
        return self._llm

    def _read_code_context(self, file_path: str, line_number: int, context_lines: int = 10) -> str:
        """
        Read code context around the finding.

        Args:
            file_path: Path to the source file
            line_number: Line number of the finding
            context_lines: Number of lines before and after to include

        Returns:
            Code snippet with context
        """
        try:
            if not os.path.exists(file_path):
                return ""

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            start = max(0, line_number - context_lines - 1)
            end = min(len(lines), line_number + context_lines)

            # Add line numbers to context
            context_lines_with_numbers = []
            for i, line in enumerate(lines[start:end], start=start + 1):
                marker = ">>> " if i == line_number else "    "
                context_lines_with_numbers.append(f"{marker}{i:4d} | {line.rstrip()}")

            return "\n".join(context_lines_with_numbers)

        except Exception as e:
            logger.warning(f"Could not read context from {file_path}: {e}")
            return ""

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".java": "java",
            ".go": "go",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".cs": "csharp",
            ".rs": "rust",
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, "text")

    def _build_prompt(self, finding: Dict, base_path: str = "") -> str:
        """
        Build the prompt for LLM review.

        Args:
            finding: Finding dictionary
            base_path: Base path to resolve relative file paths

        Returns:
            Formatted prompt string
        """
        # Resolve file path
        file_path = finding.get("file_path", "")
        if base_path and not os.path.isabs(file_path):
            full_path = os.path.join(base_path, file_path)
        else:
            full_path = file_path

        # Get extended context from file
        line_number = finding.get("line_number", 0)
        extended_context = self._read_code_context(full_path, line_number)

        # Use extended context if available, otherwise use the snippet
        code_snippet = extended_context if extended_context else finding.get("code_snippet", "")

        # Detect language
        language = self._detect_language(file_path)

        # Build prompt from template
        prompt = self.prompt_template
        replacements = {
            "{{tool}}": finding.get("tool", "unknown"),
            "{{rule_id}}": finding.get("rule_id", "unknown"),
            "{{type}}": finding.get("type", "security"),
            "{{severity}}": finding.get("severity", "MEDIUM"),
            "{{file_path}}": file_path,
            "{{line_number}}": str(line_number),
            "{{message}}": finding.get("message", ""),
            "{{language}}": language,
            "{{code_snippet}}": code_snippet,
        }

        for key, value in replacements.items():
            prompt = prompt.replace(key, value)

        return prompt

    def _parse_llm_response(self, response: str) -> Dict:
        """
        Parse LLM response to extract verdict.

        Args:
            response: Raw LLM response text

        Returns:
            Parsed verdict dictionary
        """
        default_result = {
            "verdict": "UNCERTAIN",
            "confidence": "LOW",
            "analysis": "Could not parse LLM response",
        }

        try:
            # Try to find JSON in the response
            # Look for JSON block
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "{" in response and "}" in response:
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_str = response[json_start:json_end]
            else:
                # Try to parse verdict from text
                response_upper = response.upper()
                if "TRUE_POSITIVE" in response_upper or "TRUE POSITIVE" in response_upper:
                    return {"verdict": "TRUE_POSITIVE", "confidence": "MEDIUM", "analysis": response[:200]}
                elif "FALSE_POSITIVE" in response_upper or "FALSE POSITIVE" in response_upper:
                    return {"verdict": "FALSE_POSITIVE", "confidence": "MEDIUM", "analysis": response[:200]}
                return default_result

            result = json.loads(json_str)

            # Normalize verdict
            verdict = result.get("verdict", "UNCERTAIN").upper().replace(" ", "_")
            if verdict not in ["TRUE_POSITIVE", "FALSE_POSITIVE", "UNCERTAIN"]:
                verdict = "UNCERTAIN"

            return {
                "verdict": verdict,
                "confidence": result.get("confidence", "MEDIUM").upper(),
                "analysis": result.get("analysis", "")[:500],
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            return default_result

    def verify_finding(self, finding: Dict, base_path: str = "") -> Dict:
        """
        Verify a single finding using LLM.

        Args:
            finding: Finding dictionary
            base_path: Base path for resolving relative file paths

        Returns:
            Finding with agent_verification and agent_comment updated
        """
        # Skip low severity findings
        severity = finding.get("severity", "LOW").upper()
        if severity in ["LOW", "INFO"]:
            finding["agent_verification"] = "NOT_REQUIRED"
            finding["agent_comment"] = "Low severity - agent verification not required"
            return finding

        try:
            # Build prompt
            prompt = self._build_prompt(finding, base_path)

            # Call LLM
            llm = self._get_llm()
            response = llm.invoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            # Parse response
            result = self._parse_llm_response(response_text)

            # Map verdict to agent_verification format
            verdict_map = {
                "TRUE_POSITIVE": "VERIFIED",
                "FALSE_POSITIVE": "FALSE_POSITIVE",
                "UNCERTAIN": "UNCERTAIN",
            }

            finding["agent_verification"] = verdict_map.get(result["verdict"], "UNCERTAIN")
            finding["agent_comment"] = result.get("analysis", "")
            finding["agent_confidence"] = result.get("confidence", "MEDIUM")

            logger.info(f"Finding {finding.get('id', 'unknown')} verified as {finding['agent_verification']}")

        except Exception as e:
            logger.error(f"Error verifying finding: {e}")
            finding["agent_verification"] = "UNCERTAIN"
            finding["agent_comment"] = f"Agent review failed: {str(e)}"

        return finding

    def verify_findings(self, findings: List[Dict], base_path: str = "") -> List[Dict]:
        """
        Verify multiple findings.

        Args:
            findings: List of finding dictionaries
            base_path: Base path for resolving relative file paths

        Returns:
            List of findings with verification results
        """
        verified = []
        review_count = 0

        for finding in findings:
            severity = finding.get("severity", "LOW").upper()

            # Only review HIGH/MEDIUM severity up to the batch limit
            if severity in ["HIGH", "MEDIUM"] and review_count < self.max_findings_per_batch:
                verified_finding = self.verify_finding(finding, base_path)
                review_count += 1
            else:
                # Mark as not required or uncertain (if over limit)
                if severity in ["LOW", "INFO"]:
                    finding["agent_verification"] = "NOT_REQUIRED"
                    finding["agent_comment"] = "Low severity - agent verification not required"
                else:
                    finding["agent_verification"] = "UNCERTAIN"
                    finding["agent_comment"] = "Exceeded batch limit for LLM review"
                verified_finding = finding

            verified.append(verified_finding)

        logger.info(f"Verified {review_count} findings with LLM, {len(findings) - review_count} skipped")
        return verified
