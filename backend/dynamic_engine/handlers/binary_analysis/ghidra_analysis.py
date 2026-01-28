import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class GhidraHandler(AbstractHandler):
    """Handler for ghidra functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["ghidra"]

    def handle(self, data: Dict) -> Any:
        """Execute ghidra with enhanced logging"""
        try:
            binary = data.get("binary", "")
            project_name = data.get("project_name", "hexstrike_analysis")
            script_file = data.get("script_file", "")
            analysis_timeout = data.get("analysis_timeout", 300)
            output_format = data.get("output_format", "xml")
            additional_args = data.get("additional_args", "")
            if not binary:
                logger.warning("🔧 Ghidra called without binary parameter")
                return {"error": "Binary parameter is required"}
            project_dir = f"/tmp/ghidra_projects/{project_name}"
            os.makedirs(project_dir, exist_ok=True)
            command = f"analyzeHeadless {project_dir} {project_name} -import {binary} -deleteProject"
            if script_file:
                command += f" -postScript {script_file}"
            if output_format == "xml":
                command += f" -postScript ExportXml.java {project_dir}/analysis.xml"
            if additional_args:
                command += f" {additional_args}"
            logger.info(f"🔧 Starting Ghidra analysis: {binary}")
            result = execute_command(command, timeout=analysis_timeout)
            logger.info(f"📊 Ghidra analysis completed for {binary}")
            return result
        except Exception as e:
            logger.error(f"💥 Error in ghidra endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
