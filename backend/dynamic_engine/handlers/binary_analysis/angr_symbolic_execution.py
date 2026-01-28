import logging
import os
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.runtime.command.command_executor import execute_command

logger = logging.getLogger(__name__)


class AngrHandler(AbstractHandler):
    """Handler for angr functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return ["angr"]

    def handle(self, data: Dict) -> Any:
        try:
            binary = data.get("binary", "")
            script_content = data.get("script_content", "")
            find_address = data.get("find_address", "")
            avoid_addresses = data.get("avoid_addresses", "")
            analysis_type = data.get("analysis_type", "symbolic")  # symbolic, cfg, static
            additional_args = data.get("additional_args", "")

            if not binary:
                logger.warning("🔧 angr called without binary parameter")
                return {"error": "Binary parameter is required"}

            # Create angr script
            script_file = "/tmp/angr_analysis.py"

            if script_content:
                with open(script_file, "w") as f:
                    f.write(script_content)
            else:
                # Generate basic angr template
                template = f"""#!/usr/bin/env python3
    import angr
    import sys

    # Load binary
    project = angr.Project('{binary}', auto_load_libs=False)
    print(f"Loaded binary: {binary}")
    print(f"Architecture: {{project.arch}}")
    print(f"Entry point: {{hex(project.entry)}}")

    """
                if analysis_type == "symbolic":
                    template += f"""
    # Symbolic execution
    state = project.factory.entry_state()
    simgr = project.factory.simulation_manager(state)

    # Find and avoid addresses
    find_addr = {find_address if find_address else "None"}
    avoid_addrs = {avoid_addresses.split(",") if avoid_addresses else "[]"}

    if find_addr:
        simgr.explore(find=find_addr, avoid=avoid_addrs)
        if simgr.found:
            print("Found solution!")
            solution_state = simgr.found[0]
            print(f"Input: {{solution_state.posix.dumps(0)}}")
        else:
            print("No solution found")
    else:
        print("No find address specified, running basic analysis")
    """
                elif analysis_type == "cfg":
                    template += """
    # Control Flow Graph analysis
    cfg = project.analyses.CFGFast()
    print(f"CFG nodes: {len(cfg.graph.nodes())}")
    print(f"CFG edges: {len(cfg.graph.edges())}")

    # Function analysis
    for func_addr, func in cfg.functions.items():
        print(f"Function: {func.name} at {hex(func_addr)}")
    """

                with open(script_file, "w") as f:
                    f.write(template)

            command = f"python3 {script_file}"

            if additional_args:
                command += f" {additional_args}"

            logger.info(f"🔧 Starting angr analysis: {binary}")
            result = execute_command(command, timeout=600)  # Longer timeout for symbolic execution

            # Cleanup
            try:
                os.remove(script_file)
            except Exception:
                pass

            logger.info("📊 angr analysis completed")
            return result
        except Exception as e:
            logger.error(f"💥 Error in angr endpoint: {str(e)}")
            return {"error": f"Server error: {str(e)}"}
