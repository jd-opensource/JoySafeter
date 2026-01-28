from langchain_core.tools import tool
from loguru import logger

from app.dynamic_agent.tools.builtin.think_tool.think_prompts import THINK_PROMPT


@tool(description=THINK_PROMPT)
def think_tool(thought: str) -> str:
    """Strategic reasoning tool for analyzing results and planning next steps.

    Args:
        thought: Your analysis, hypothesis, or reasoning about current situation
    """

    from app.dynamic_agent.tools.builtin.check_iteration_tool.check_iteration_tool import build_iteration_info

    logger.info(f"💭 thinking: {thought}")
    return f"""thought is logged.

------
extra info about iteration limit:
{build_iteration_info()}
------

"""
