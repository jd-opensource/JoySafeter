# JoySafeter 使用教程

本目录包含 JoySafeter 的经典实际案例教程，每个教程都以实际场景为导向，帮助你快速上手平台核心功能。

---

## 教程列表

| # | 教程 | 核心内容 | 难度 |
|---|------|---------|------|
| 01 | [模型配置：内置供应商与自定义供应商](./01-model-provider-setup.md) | OpenAI / OpenAI Compatible / Ollama 接入 | ⭐ 入门 |
| 02 | [添加 MCP 服务](./02-mcp-service-setup.md) | 内置工具加载 / 自定义 MCP 工具注册 | ⭐⭐ 进阶 |
| 03 | [导入 Skills](./03-skills-usage.md) | 从“导入成功”到“Agent 可用”的可验证闭环（DB → 同步 → Sandbox/Graph → 消费） | ⭐⭐ 进阶 |
| 04a | [教程 04a：基于 LangGraph 的确定性工作流](./04a-langgraph-building.md) | 深入解析如何构建线性、条件分支、循环与并行等高度可控的标准工作流（LanggraphModelBuilder）。 | ⭐️⭐️⭐️ |
| 04b | [教程 04b：DeepAgents 动态多智能体协作](./04b-deepagents-building.md) | 高阶玩法：使用星型拓扑架构，让 Manager 节点动态、自发地调遣专业 SubAgent 处理复杂不可预见的分支任务。 | ⭐️⭐️⭐️⭐️ 高级 |
| 05 | [Copilot 使用指南](./05-copilot-usage.md) | 实时对话 / 中断介入 / AI 决策辅助 | ⭐ 入门 |
| 06 | [OpenClaw（沙盒后端）配置与使用](./06-openclaw-usage.md) | 沙盒启动 / Skills 同步 / 预加载 / Copilot 消费闭环 | ⭐⭐ 进阶 |

---

## 推荐学习路径

### 🚀 快速开始（10 分钟）

1. **教程 01**：配置模型（OpenAI 或本地 Ollama）
2. **教程 05**：用 Copilot 与 Agent 进行第一次对话
3. **教程 04**（案例 1）：构建一个简单的线性 3 步工作流

### 🔧 完整功能（1 小时）

1. 完成快速开始路径
2. **教程 06**：启动 OpenClaw，并验证 skills 同步与预加载链路（后续所有“可执行工具/脚本”的前提）
3. **教程 03**：导入 Skills，并跑通“DB →（可选）OpenClaw → Sandbox/Graph → Agent 消费”的闭环
4. **教程 02**：添加自定义 MCP 工具（让 Skill 不只是文档，而是可调用的工具能力）
5. **教程 04**（案例 2-5）：掌握条件分支、循环、并行、DeepAgents

### 🏆 高级应用

- 结合教程 02 + 04 + 05，构建完整的自动化渗透测试工作流
- 使用 DeepAgents 模式（教程 04 案例 6）构建 Manager-Worker 多 Agent 系统
- 通过 Copilot 的 Human-in-the-Loop（教程 05 案例 B）实现审批流程

---

## 相关文档

- [系统架构](../ARCHITECTURE.md)
- [Graph Builder 架构详解](../GRAPH_BUILDER_ARCHITECTURE.md)
- [MCP 工具分析](../mcp-tools-analysis.md)
- [DeepResearch 完整指南](../deepresearch-complete-guide.md)

---

## 贡献教程

如果你有新的实际案例想分享，欢迎提交 PR：
1. 在本目录新建 `0N-your-tutorial-name.md`
2. 遵循现有教程的格式（场景说明、分步骤、常见问题）
3. 在本 README 的教程列表中添加索引
