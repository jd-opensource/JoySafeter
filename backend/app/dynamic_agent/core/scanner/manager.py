"""
Scanner Manager - Orchestrates file extraction, scanning, and agent review
"""

import os
import tempfile
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

from loguru import logger

from .agent import AgentReviewer
from .engine import RegexEngine
from .llm_reviewer import LLMAgentReviewer
from .rules import load_rules
from .sast_scanner import SASTScanner


class FileManager:
    """
    Utility class to handle ZIP file extraction and cleanup.
    """

    @staticmethod
    def extract_zip(zip_path: str, extract_to: str) -> str:
        """
        Extract a ZIP file to a temporary directory securely (preventing Zip Slip).

        Args:
            zip_path: Path to the ZIP file
            extract_to: Directory to extract to

        Returns:
            Path to the extracted directory

        Raises:
            zipfile.BadZipFile: If the file is not a valid ZIP
            ValueError: If a Zip Slip attempt is detected
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # ============ Security: Prevent Zip Slip vulnerability ============
                extract_to_path = os.path.realpath(extract_to)

                # Use infolist() for better member info and extract one-by-one
                for member in zip_ref.infolist():
                    # Resolve the full path of the member
                    member_path = os.path.realpath(os.path.join(extract_to, member.filename))

                    # Check if the resolved path is within the extraction directory
                    if not member_path.startswith(extract_to_path):
                        logger.warning(f"Zip Slip attempt blocked: {member.filename}")
                        raise ValueError(f"Zip Slip vulnerability detected: {member.filename}")

                    # Check for malicious symlinks (Unix file type bit 0xA000)
                    # A symlink has the file type bits set to 0xA000 in external_attr >> 16
                    file_mode = member.external_attr >> 16
                    if file_mode & 0o170000 == 0o120000:  # S_IFLNK = 0o120000
                        # Get symlink target from the ZIP file content
                        link_target = zip_ref.read(member).decode("utf-8")
                        # Resolve symlink target and check if it stays within extraction directory
                        link_target_path = os.path.realpath(
                            os.path.join(extract_to, os.path.dirname(member.filename), link_target)
                        )
                        if not link_target_path.startswith(extract_to_path):
                            logger.warning(f"Malicious symlink detected: {member.filename} -> {link_target}")
                            raise ValueError(f"Malicious symlink detected: {member.filename}")

                    # Extract the individual member safely
                    zip_ref.extract(member, extract_to)

            logger.info(f"Extracted {zip_path} to {extract_to}")
            return extract_to
        except zipfile.BadZipFile as e:
            logger.error(f"Invalid ZIP file: {zip_path}. Error: {e}")
            raise

    @staticmethod
    def cleanup_directory(directory: str) -> None:
        """
        Clean up a temporary directory.

        Args:
            directory: Path to directory to remove
        """
        if os.path.exists(directory):
            import shutil

            shutil.rmtree(directory)
            logger.info(f"Cleaned up directory: {directory}")

    @staticmethod
    def create_temp_directory() -> str:
        """
        Create a temporary directory for extraction.

        Returns:
            Path to the temporary directory
        """
        temp_dir = tempfile.mkdtemp(prefix="scanner_")
        logger.info(f"Created temporary directory: {temp_dir}")
        return temp_dir


class ScannerManager:
    """
    Main orchestrator for whitebox scanning.

    Coordinates:
    1. ZIP file extraction
    2. SAST scanning (Semgrep + Gitleaks) OR Regex-based scanning
    3. AI Agent verification (for high-severity findings)
    4. Report generation
    """

    def __init__(self, use_sast: bool = True, use_llm_review: bool = True):
        """
        Initialize the scanner manager.

        Args:
            use_sast: Whether to use Semgrep/Gitleaks (True) or regex engine (False)
            use_llm_review: Whether to use LLM for finding verification
        """
        self.use_sast = use_sast
        self.use_llm_review = use_llm_review

        # Legacy regex-based scanner
        self.rules = load_rules()
        self.engine = RegexEngine(self.rules)
        self.agent_reviewer = AgentReviewer()

        # New SAST-based scanner
        self.sast_scanner: Optional[SASTScanner] = None
        if use_sast:
            try:
                self.sast_scanner = SASTScanner()
                logger.info("SAST Scanner initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize SAST Scanner: {e}. Falling back to regex.")
                self.sast_scanner = None
                self.use_sast = False

        # LLM-based reviewer
        self.llm_reviewer: Optional[LLMAgentReviewer] = None
        if use_llm_review:
            try:
                self.llm_reviewer = LLMAgentReviewer(max_findings_per_batch=20)
                logger.info("LLM Reviewer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM Reviewer: {e}. Using heuristic review.")
                self.llm_reviewer = None
                self.use_llm_review = False

    def run_scan(self, zip_path: str) -> Dict[str, Any]:
        """
        Run a complete whitebox scan on a ZIP file.

        Args:
            zip_path: Path to the ZIP file containing source code

        Returns:
            Dictionary containing scan results and metadata
        """
        scan_id = str(uuid.uuid4())
        start_time = time.time()
        temp_dir = None

        try:
            logger.info(f"Starting scan {scan_id} for {zip_path}")

            # Step 1: Create temp directory and extract ZIP
            temp_dir = FileManager.create_temp_directory()
            FileManager.extract_zip(zip_path, temp_dir)

            # Step 2: Run scanning
            if self.use_sast and self.sast_scanner:
                # Use Semgrep + Gitleaks
                logger.info(f"Scan {scan_id}: Running SAST scanner (Semgrep + Gitleaks)...")
                sast_result = self.sast_scanner.scan_directory(temp_dir)
                findings_dicts = sast_result.get("findings", [])

                # Step 3: LLM-based review for high-severity findings
                if self.use_llm_review and self.llm_reviewer:
                    logger.info(f"Scan {scan_id}: Running LLM verification on {len(findings_dicts)} findings...")
                    verified_findings = self.llm_reviewer.verify_findings(findings_dicts, base_path=temp_dir)
                else:
                    # Mark all as not reviewed
                    for f in findings_dicts:
                        if f.get("agent_verification") is None:
                            f["agent_verification"] = "NOT_REQUIRED"
                    verified_findings = findings_dicts

                # Calculate statistics
                stats = self._calculate_stats(verified_findings)

                # Step 4: Prepare result
                end_time = time.time()
                scan_duration_ms = int((end_time - start_time) * 1000)
                scanned_files = sum([len(files) for r, d, files in os.walk(temp_dir)])

                result = {
                    "scan_id": scan_id,
                    "scan_mode": "sast",
                    "tools_used": sast_result.get("tools_used", []),
                    "summary": stats,
                    "findings": verified_findings,
                    "scanned_files": scanned_files,
                    "scan_duration_ms": scan_duration_ms,
                }
            else:
                # Fallback to legacy regex scanner
                logger.info(f"Scan {scan_id}: Running regex scanner...")
                findings = self.engine.scan_directory(temp_dir)

                # Step 3: Agent review for high-severity findings
                logger.info(f"Scan {scan_id}: Running agent verification on {len(findings)} findings...")
                agent_verified_findings = self.agent_reviewer.verify_findings(findings)

                # Step 4: Generate statistics
                stats = self.engine.get_statistics(agent_verified_findings)

                # Step 5: Prepare result
                end_time = time.time()
                scan_duration_ms = int((end_time - start_time) * 1000)
                scanned_files = sum([len(files) for r, d, files in os.walk(temp_dir)])

                result = {
                    "scan_id": scan_id,
                    "scan_mode": "regex",
                    "summary": {
                        "total": stats["total"],
                        "high": stats["high"],
                        "medium": stats["medium"],
                        "low": stats["low"],
                        "info": stats["info"],
                    },
                    "findings": [f.to_dict() for f in agent_verified_findings],
                    "scanned_files": scanned_files,
                    "scan_duration_ms": scan_duration_ms,
                }

            logger.info(f"Scan {scan_id} completed: {result['summary']['total']} findings")
            return result

        except Exception as e:
            logger.error(f"Scan {scan_id} failed: {e}")
            raise

        finally:
            # Cleanup
            if temp_dir:
                FileManager.cleanup_directory(temp_dir)
                logger.info(f"Scan {scan_id}: Cleaned up temporary files")

    def _calculate_stats(self, findings: List[Dict]) -> Dict[str, int]:
        """
        Calculate statistics from a list of finding dictionaries.

        Args:
            findings: List of finding dictionaries

        Returns:
            Dictionary with severity counts
        """
        stats = {
            "total": len(findings),
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }

        for finding in findings:
            severity = finding.get("severity", "INFO").lower()
            if severity in stats:
                stats[severity] += 1

        return stats
