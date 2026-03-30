# 教程 04c：Code 模式 — 用 Python 代码构建 Agent 图

> **适合人群**：熟悉 Python 和 LangGraph 的开发者，希望用代码而非拖拽来定义图结构。
> **前置要求**：已完成教程 01（模型配置）。

---

## 0. Code 模式是什么

Code 模式让你直接在浏览器中编写标准 LangGraph Python 代码来定义图结构。后端在沙箱中执行你的代码，提取 `StateGraph` 实例，编译并运行。

**核心优势：**
- 零学习成本 — LangGraph 官方文档就是你的文档
- 完整的 Python 表达力 — 循环、条件、函数、类都能用
- 代码即配置 — 可以 git 管理、code review、复用

---

## 1. 创建 Code 模式 Agent

1. 在左侧 sidebar 点击 **+** 按钮
2. 在弹出的对话框中选择 **Code** 模式
3. 输入 Agent 名称，点击 **Create**
4. 自动跳转到代码编辑器页面

编辑器会预填一个 starter template：

```python
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated


class State(TypedDict):
    messages: Annotated[list, add_messages]


def assistant(state: State):
    # Your logic here
    return {"messages": state["messages"]}


graph = StateGraph(State)
graph.add_node("assistant", assistant)

graph.add_edge(START, "assistant")
graph.add_edge("assistant", END)
```

---

## 2. 编写你的图

### 2.1 定义 State

用标准 Python `TypedDict` 定义图的状态：

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
    score: int
    context: dict
```

### 2.2 定义节点函数

每个节点是一个普通 Python 函数，接收 state，返回更新：

```python
def classifier(state: State):
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""
    # 你的分类逻辑
    return {"score": len(last_message) % 100}

def responder(state: State):
    score = state.get("score", 0)
    if score > 50:
        return {"messages": [("assistant", "High score response")]}
    return {"messages": [("assistant", "Low score response")]}
```

### 2.3 构建图

用标准 LangGraph API 连接节点：

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(State)

graph.add_node("classifier", classifier)
graph.add_node("responder", responder)

graph.add_edge(START, "classifier")
graph.add_edge("classifier", "responder")
graph.add_edge("responder", END)
```

### 2.4 条件路由

```python
def route_by_score(state: State):
    if state.get("score", 0) > 80:
        return "vip_handler"
    return "standard_handler"

graph.add_conditional_edges("classifier", route_by_score)
```

---

## 3. 保存和运行

- **Ctrl/Cmd + S**：保存代码
- **Save 按钮**：保存代码到服务器
- **Run 按钮**：保存 + 执行，结果显示在编辑器下方

运行结果面板会显示：
- 执行结果（JSON 格式）
- 执行时间
- 错误信息（如果有）

---

## 4. 安全限制

Code 模式在沙箱中执行，有以下限制：

| 限制 | 说明 |
|------|------|
| **可用模块** | `langgraph`、`langchain`、`typing`、`json`、`re`、`math`、`pydantic` 等 |
| **禁止模块** | `os`、`sys`、`subprocess`、`socket`、`io`、`pathlib` 等 |
| **禁止函数** | `open`、`eval`、`exec`、`compile`、`globals`、`locals` |
| **执行超时** | 代码编译 10 秒，图运行 30 秒 |

如果需要文件操作或网络请求，请使用 DeepAgents Canvas 模式配合 MCP 工具。

---

## 5. 完整示例：多步骤分析 Agent

```python
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated


class State(TypedDict):
    messages: Annotated[list, add_messages]
    analysis: str
    confidence: float


def analyze(state: State):
    messages = state["messages"]
    last = messages[-1].content if messages else ""
    # 简单分析逻辑
    analysis = f"Analyzed: {last[:50]}..."
    confidence = min(len(last) / 100, 1.0)
    return {"analysis": analysis, "confidence": confidence}


def decide(state: State):
    if state.get("confidence", 0) > 0.7:
        return "respond"
    return "clarify"


def respond(state: State):
    return {"messages": [("assistant", f"Analysis complete: {state['analysis']}")]}


def clarify(state: State):
    return {"messages": [("assistant", "Could you provide more details?")]}


graph = StateGraph(State)
graph.add_node("analyze", analyze)
graph.add_node("respond", respond)
graph.add_node("clarify", clarify)

graph.add_edge(START, "analyze")
graph.add_conditional_edges("analyze", decide)
graph.add_edge("respond", END)
graph.add_edge("clarify", END)
```

---

## 6. Code 模式 vs Canvas 模式

| | Code 模式 | Canvas 模式 (DeepAgents) |
|---|-----------|------------------------|
| **定义方式** | Python 代码 | 拖拽节点和连线 |
| **灵活性** | 完整 Python 表达力 | 预定义节点类型 |
| **适合场景** | 自定义逻辑、复杂路由 | 多智能体协作、Manager-Worker |
| **工具支持** | 沙箱内可用模块 | MCP 工具、Docker 沙箱 |
| **学习成本** | 需要了解 LangGraph | 可视化操作，门槛低 |

> 💡 **建议**：如果你的场景是多个 Agent 协作完成任务，用 Canvas 模式（DeepAgents）。如果你需要精确控制图的逻辑流程，用 Code 模式。
