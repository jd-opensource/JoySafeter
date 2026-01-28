from langchain_core.tools import tool
from loguru import logger


@tool
def final_response(response: str) -> str:
    """Final response tool for synthesizing complete, contextual answers.

    Use this tool when you need to provide a comprehensive final response that:
    - Synthesizes all findings from the task
    - Considers the full context and execution history
    - Provides actionable recommendations or conclusions
    - Addresses the original user request completely

    Args:
        response: Your complete, well-structured final response including:
                  - Executive summary (brief overview)
                  - Key findings (main discoveries)
                  - Detailed results (complete information with evidence)
                  - Recommendations (next steps or solutions)
                  - Supporting context (relevant background)

    Returns:
        str: The formatted final response for the user
    """
    logger.info(f"📝 Final response: {response[:200]}...")  # Log first 200 chars
    return "Final response generated"
