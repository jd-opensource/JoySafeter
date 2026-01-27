from typing import List

from langchain_core.tools import BaseTool

from app.dynamic_agent.tools.builtin.ask_human_tool import ask_human  # Human intervention tool
from app.dynamic_agent.tools.builtin.python_coder.python_coder_tool import python_coder_tool
from app.dynamic_agent.tools.builtin.todo_tool import TODO_TOOLS  # 006: TODO management tools

base_tools: List[BaseTool] = [python_coder_tool, ask_human] + TODO_TOOLS
