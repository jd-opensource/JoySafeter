# 教程 05：Copilot（AI 辅助编排）深度解析与使用指南

> **适合人群**：希望通过自然语言快速生成复杂业务流、探索多智能体协作（Multi-Agent）架构，以及想要了解 JoySafeter 核心工作流引擎机制的进阶用户。
> **目标**：明确 Copilot 在 JoySafeter 项目中的真实定位，掌握标准模式与 DeepAgents 高级模式的差异，并学会如何通过清晰的 prompt 构建出高可用性、符合规则的复杂 Agent 链路。

---

## 0. 重新认识 Copilot：它到底是什么？

在 JoySafeter 架构中，Copilot **绝不仅仅是一个右侧的聊天窗口（Chatbot）**。

它的真实身份是 **“AI工作流构建器（Graph Workflow Generator）”**。Copilot 的核心任务是将用户的“非结构化自然语言需求”，编译映射为前端画布可直接渲染、后端可稳定执行的 **JSON 图操作原语（GraphActions）**，如：`create_node`（创建节点）、`connect_nodes`（连线）和 `update_config`（更新参数）。

---

## 1. 核心架构与实现原理（”Under the Hood”）

Copilot 已全面迁移至 **Run Center 模型**，与 Chat 和 Skill Creator 共享同一 WebSocket 通信层。

### 1.1 通信架构（Shared Chat WS + Run Center）

所有 Copilot 交互都通过 **`/ws/chat` 共享 WebSocket** 进行：

1. **创建 Run**：前端调用 `runService.createRun({ agent_name: “copilot”, graph_id, message })` 在 Run Center 注册本次任务。
2. **发送消息**：通过 `getChatWsClient().sendChat()` 发送 `chat.start` 帧，携带 `extension: { kind: “copilot”, runId, graphContext, conversationHistory, mode }`。
3. **后端执行**：`ChatWsHandler` 解析协议后路由到 `execute_copilot_turn()`，消费 `CopilotService._get_copilot_stream()` 产生的事件流。
4. **事件持久化**：每个事件通过 `_emit_event()` 同时推送到 WS 客户端，并通过 `_mirror_run_stream_event()` 持久化到 `agent_run_events` 表。
5. **状态投影**：`run_reducers/copilot.py` 维护实时投影（stage、content、thought_steps、tool_calls 等），存储于 `agent_run_snapshots`。

### 1.2 标准模式 vs DeepAgents 模式

为了兼顾”快速简单修改”与”复杂架构生成”，后端的 Copilot 被设计为**双引擎模式（Dual-Mode Engine）**：

**标准模式（Standard Mode）**
- **触发条件**：小范围针对性修改（如修改单个节点配置）。
- **特点**：速度快，LLM 直接在当前图基础上下发单一工具调用（如只修改某一个 node 的 `systemPrompt`），然后通过前端 `ActionProcessor` 应用到 ReactFlow 画布上。

**DeepAgents 高级模式**
当检测到需要”从零生成完整工作流”或”构建多智能体团队”时，触发深度编排链路：
1. **需求分析师（requirements-analyst）**：分析 Prompt 和画布现状，判断是 `create` 还是 `update` 模式，输出 `/analysis.json`。
2. **架构设计师（workflow-architect）**：勾勒节点/边结构，为每个 Agent 编写详细的 `systemPrompt`，输出 `/blueprint.json`。
3. **质检员循环（Validator & Reflexion Loop）**：严格校验蓝图（prompt 长度、无头节点、孤立节点等），不合格自动打回修复，最大 3 次重试。
4. **渲染指令下发**：校验通过的 JSON 转化为 `GraphAction` 指令流通过 WS 事件推送给浏览器，触发画布重绘。系统自动应用 `apply_auto_layout` 算法确保布局整洁。

### 1.3 页面刷新恢复

得益于 Run Center 持久化，Copilot 支持页面刷新后无缝恢复：
- 前端检测到未完成的 `currentRunId` 后，先获取 `runService.getRunSnapshot()` 恢复最新状态。
- 若 run 仍在执行中，通过 `/ws/runs` 订阅后续实时事件。

---

## 2. 核心架构规则限制（必须遵守的“天规”）

如果你希望完美指挥 DeepAgents Copilot 替你工作，必须清楚系统“设计师”被强制写入了哪些拓扑规则，切勿要求它做违背原则的拓扑图：

- **角色限制**：多代理模型严格被限制在 **2层架构（Manager → Subagents）** 且子代理数量严格限制在 **3~8 个** 之间，防止上下文灾难膨胀。
- **连线铁律**：
  - **有向层级**：所有控制边必须由 Manager 节点出发，指向下属执行 Agent。
  - **禁止平级互联**：规定子代理（Subagent）之间**严禁互相连线**！他们通过共享读写 `/workspace` 的文件进行状态交换。
  - **唯一入口**：严禁任何节点通过“回旋镖”线路反向连接到总入口 Manager，Manager 是图中执行环境绝对的起点。
- **终端隔离**：子代理永远是分支的终端页节点，不能有出边，更不允许拥有自己的“下一级子代理”。

---

## 3. 经典实操用例（从入门到可闭环验证）

下面，我们将抛离“随便聊聊”的旧式案例。让我们来看一些如何触发它深层能力的**有效命令（Prompts）**。

### 实战 Case 1: 触发 DeepAgents 创建多智能体研究团队
> **验证目标**：让 Copilot 走一次完整的 **分析 -> 设计 -> 校验 -> 生成** 流程。

- **你在画布右侧输入的 Prompt**：
  > “我需要一整套深度的行业研究架构协助我的工作。请给我配备一个主总监，底下带三个兵：一个专门负责全网爬取资讯，一个负责清洗数据和抽取核心金句，最后还要跟一个报告撰写人专门输出 Markdown 格式的周报。”

- **观测点**：
  - 观察生成过程。如果它触发了 DeepAgents，生成时间会显著变长。
  - Copilot 头像处会逐级提示：它先后调用了 `requirements-analyst`，接着是 `workflow-architect`，随后 `validator` 在排查错误（可能发生极速闪烁）。
  - 最终画板出现：1个总监督节点，指向底下3个功能明确的无互相连接的分支节点，且所有节点的提示词（`systemPrompt`）都达到了数百字以上的工业级水准。

### 实战 Case 2:  故意制造“弱依赖”，验证 Validator 的自我修复机制（Reflexion Loop）
> **验证目标**：利用规则机制“黑盒测试”质检子代理的拦截与退回（Fallback）工作。

- **你在画布右侧输入的 Prompt**：
  > “给我新建一个节点叫‘随意聊天’，随便陪我聊两句就行，什么配置都不要。”

- **观测点**：
  - 后端的规则中写明：**所有 Agent 节点的 prompt 坚决不得少于 100 字符**。
  - 虽然你要求“随便两句”，但 `Validator` 子代理在后台检查 `/blueprint.json` 时，抓到了这条致命错误 `[CRITICAL]: weak_prompt`。
  - 于是它将被打回要求 Architect 强制重构。最终落在你画布上的，会是一个看似你只要求了寥寥几句，但系统提示词依然写得极度严密、限制输出风格的完善指令环境。

### 实战 Case 3: 增量上下文更新 (Update Mode)
> **验证目标**：验证 Standard 机制对特定节点的精准局部打击能力，而非每次都“推倒重来”。

- **前置动作**：在画布里随意选中一个叫 `analyst_001` 或 `worker` 的节点。
- **你在画布右侧输入的 Prompt**：
  > “把当前选中这个分析师节点的数据输出规则全改掉，要求它强制采用 JSON 格式输出，并且每条分析必须要携带 0~1 的置信度字段。”

- **观测点**：
  - 由于你没要求创建大的拓扑流，仅请求修改内容。Copilot 分析器将模式定性为 `Update` 而非 `Create`。
  - 系统只会发送 `update_config` 这个极轻的动作原语给前台。其他节点的属性毫无波澜，只有被点名的节点 `systemPrompt` 神不知鬼不觉里多了要求输出置信度的 JSON 规范。此时你可一键验证执行闭环。

---

## 下一步

读到这里，你已经清楚掌握了生成端的心智模型。现在，你可以尝试将它与前面教程中的：
- **模型设定（教程 01）**：给生成的团队配置更高级的模型基座。
- **Skills 导入库（教程 03/06）**：让自动生成的 Agent 人手携带一把强力技能（Skills）。
组合起来，构建出强大、安全并绝对合规的真正 AI 应用工程图了！
