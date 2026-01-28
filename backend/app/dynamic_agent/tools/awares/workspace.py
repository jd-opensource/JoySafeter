from langchain_core.tools import tool

from app.dynamic_agent.core.shared_constants import WORKSPACE


@tool()
def workspace_tool() -> str:
    """
    The base workspace for command  will execute, where all output files or other temp files can be stored
    :return: workspace dir
    """
    return f"The base workspace for command execute will in {WORKSPACE}"
