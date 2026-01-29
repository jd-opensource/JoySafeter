#!/usr/bin/env python3
"""
HexStrike AI - Tool Executor
Core command execution engine with caching and monitoring
"""

import logging
import re
import subprocess
import threading
import time
import traceback
from subprocess import Popen
from typing import Any, Dict, Optional

from dynamic_engine.mcp.config import COMMAND_TIMEOUT
from dynamic_engine.runtime.command.process_manager import ProcessManager

logger = logging.getLogger(__name__)


def _sanitize_command_for_logging(command: str) -> str:
    """
    Sanitize command string for logging by masking sensitive data.

    Args:
        command: The command string to sanitize

    Returns:
        Sanitized command string with sensitive data masked
    """
    # Patterns to match sensitive data
    patterns = [
        (r"--password(?:=|\s+)(\S+)", "--password ****"),
        (r"--pass(?:word-file|wd)?(?:=|\s+)(\S+)", "--password-file ****"),
        (r"-p\s*\S+", "-p ****"),
        (r"-p\S+", "-p****"),
        (r"SSH_AUTH_SOCK[^\s]*", "SSH_AUTH_SOCK=****"),
        (r"--token(?:=|\s+)(\S+)", "--token ****"),
        (r"--api-key(?:=|\s+)(\S+)", "--api-key ****"),
        (r"--secret(?:=|\s+)(\S+)", "--secret ****"),
    ]

    result = command
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result


class EnhancedCommandExecutor:
    """Enhanced command executor with caching, progress tracking, and better output handling"""

    def __init__(self, command: str, timeout: int = COMMAND_TIMEOUT):
        self.command = command
        self.timeout = timeout
        self.process: Optional[Popen[str]] = None
        self.stdout_data = ""
        self.stderr_data = ""
        self.stdout_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None
        self.return_code: Optional[int] = None
        self.timed_out = False
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def _read_stdout(self):
        """Thread function to continuously read and display stdout"""
        try:
            for line in iter(self.process.stdout.readline, ""):
                if line:
                    self.stdout_data += line
                    # Real-time output display
                    logger.info(f"📤 STDOUT: {line.strip()}")
        except Exception as e:
            logger.error(f"Error reading stdout: {e}")

    def _read_stderr(self):
        """Thread function to continuously read and display stderr"""
        try:
            for line in iter(self.process.stderr.readline, ""):
                if line:
                    self.stderr_data += line
                    # Real-time error output display
                    logger.warning(f"📥 STDERR: {line.strip()}")
        except Exception as e:
            logger.error(f"Error reading stderr: {e}")

    def execute(self) -> Dict[str, Any]:
        """Execute the command with enhanced monitoring and output"""
        self.start_time = time.time()

        logger.info(f"🚀 EXECUTING: {_sanitize_command_for_logging(self.command)}")
        logger.info(f"⏱️  TIMEOUT: {self.timeout}s | PID: Starting...")

        try:
            self.process = subprocess.Popen(
                self.command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )

            pid = self.process.pid
            logger.info(f"🆔 PROCESS: PID {pid} started")

            # Register process with ProcessManager (v5.0 enhancement)
            ProcessManager.register_process(pid, self.command, self.process)

            # Start threads to read output continuously
            self.stdout_thread = threading.Thread(target=self._read_stdout)
            self.stderr_thread = threading.Thread(target=self._read_stderr)
            self.stdout_thread.daemon = True
            self.stderr_thread.daemon = True
            self.stdout_thread.start()
            self.stderr_thread.start()

            # Wait for the process to complete or timeout
            try:
                self.return_code = self.process.wait(timeout=self.timeout)
                self.end_time = time.time()

                # Process completed, join the threads
                if self.stdout_thread is not None:
                    self.stdout_thread.join(timeout=1)
                if self.stderr_thread is not None:
                    self.stderr_thread.join(timeout=1)

                execution_time = self.end_time - self.start_time

                # Cleanup process from registry (v5.0 enhancement)
                ProcessManager.cleanup_process(pid)

                if self.return_code == 0:
                    logger.info(
                        f"✅ SUCCESS: Command completed | Exit Code: {self.return_code} | Duration: {execution_time:.2f}s"
                    )
                else:
                    logger.warning(
                        f"⚠️  WARNING: Command completed with errors | Exit Code: {self.return_code} | Duration: {execution_time:.2f}s"
                    )

            except subprocess.TimeoutExpired:
                self.end_time = time.time()
                execution_time = (self.end_time or 0.0) - (self.start_time or 0.0)

                # Process timed out but we might have partial results
                self.timed_out = True
                if self.process is not None:
                    logger.warning(
                        f"⏰ TIMEOUT: Command timed out after {self.timeout}s | Terminating PID {self.process.pid}"
                    )

                    # Try to terminate gracefully first
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # Force kill if it doesn't terminate
                        if self.process is not None:
                            logger.error(f"🔪 FORCE KILL: Process {self.process.pid} not responding to termination")
                            self.process.kill()

                self.return_code = -1

            # Always consider it a success if we have output, even with timeout
            success = True if self.timed_out and (self.stdout_data or self.stderr_data) else (self.return_code == 0)

            # Minimal response to reduce token usage for LLM
            result = {
                "stdout": self.stdout_data,
                # "stderr": self.stderr_data if not self.stdout_data else '',
                "stderr": self.stderr_data,
                "return_code": self.return_code if self.return_code is not None else -1,
                "success": success,
            }
            # Only include timeout info if actually timed out
            if self.timed_out:
                result["timed_out"] = True
            return result

        except Exception as e:
            logger.error(f"💥 ERROR: Command execution failed: {str(e)}")
            logger.error(f"🔍 TRACEBACK: {traceback.format_exc()}")

            return {
                "stdout": self.stdout_data,
                "stderr": f"Error: {str(e)}\n{self.stderr_data}",
                "return_code": -1,
                "success": False,
            }


def execute_command(command: str, timeout: Optional[int] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a shell command with enhanced features

    Args:
        command: The command to execute
        timeout: Command timeout in seconds
        cwd: Working directory for command execution

    Returns:
        A dictionary containing the stdout, stderr, return code, and metadata
    """
    if timeout is None:
        timeout = COMMAND_TIMEOUT

    # Execute command
    executor = EnhancedCommandExecutor(command, timeout=timeout)
    result = executor.execute()

    return result
