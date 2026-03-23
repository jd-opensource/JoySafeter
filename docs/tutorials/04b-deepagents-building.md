# 教程 04b：高级多智能体（DeepAgents）动态协作编排

> **适合人群**：业务场景过于复杂、无法用“固定连线”穷举处理分支，希望打造具有高阶自我管理能力的“全能 AI 团队（Manager-Workers）”的架构师。
> **前置要求**：已熟练掌握 04a 中的基础图构建器，并理解什么是 `systemPrompt` 与 `Skills`。

---

## 0. 这回是”动态的星型团队”而非”固定的流水线”

> **版本说明**：本教程基于 DeepAgents v0.4 内核。如果你使用的是更早版本，部分 API 行为可能有差异。

如果在前一节 04a 中，你学到的是工厂的”流水生产线（LangGraph）”。
那么这一节，带你构建的是一家真正的**公司（DeepAgents）**。

在 JoySafeter 的底层源码 `GraphBuilderFactory` 中，一旦它扫描到你的画布上**有任何一个节点的主动配置里勾选了 `useDeepAgents = True`**。后端的编译引擎就会彻底切轨，抛弃了原来循规蹈矩的边，重构整个网络为一种支持自我思考分发的**动态星型拓扑（Star Topology）**。

- **动态发派**：你连的线不再是“必须从 A 走到 B”的强制通道。连线在这里只是一个“汇报关系图”。
- **Manager 是唯一的灵魂**：带有 `useDeepAgents` 属性的那个特殊节点就是老板。它能通过内置的 `task()` 高级函数，像给下属发邮件一样，**异步、非发散、根据当前用户这句话的态度自由决定发派给谁**。

---

## 1. 深度构建实战：安全防御司令部

让我们来复刻一个全自动的“安全事件应急响应团队（CERT）”。

### 1.1 第一步：确立总指挥（The Manager）

在画板中央拖入一个 Agent 节点。
- **名称**：`security_manager`
- **勾选关键开关**：在右侧配置栏，必须打钩选中 **【Use DeepAgents】**。
- **System Prompt（架构师的灵魂所在）**：
  在 DeepAgents 模式下，大模型需要极其清晰的团队花名册：
  ```markdown
  你是一个高级安全防御司令官。
  你目前麾下拥有这些专业的 SubAgent 专家兵种（你可以视情况随时调派他们）：
  - `web_investigator`：擅长网页木马与 XSS 反查。
  - `network_investigator`：擅长流量抓包与内网渗透回溯。
  - `report_writer`：只负责把调查结果清洗汇编成高管能看的 Markdown 早报。

  请分析用户给出的被攻击现象，动态组合并分派任务给最合适的人。必须等到他们都汇报结果后，由你整合最终方案回复给人类。
  ```
- **Description（关键字段）**：在这个模式下，Manager 必须要在下方的“Agent Description”框里填入简单明了的短句，比如：“安全响应总指挥官”。

### 1.2 第二步：招兵买马（SubAgents / Workers）

拖入另外三个普通的 Agent 节点。**（这些节点绝对不能勾选 Use DeepAgents！）**
分别命名并配置：
1. `web_investigator`
2. `network_investigator`
3. `report_writer`

> 🚨 **重点：赋能专家**
> 这三个小兵节点既然是干活的，请务必在他们各自麾下的 `systemPrompt` 里写清楚他们的单兵专业能力。
> **并一定要给他们挂载上专属的技能（Skills）**！比如，给 `network_investigator` 挂上 nmap 的代码脚本。给司令兵（Manager）配枪是没用的，得发给干活的兵。
> 别忘了，同样要填写简短的“Agent Description”框，比如“流量抓包专家”。（这是给 Manager 看的花名册简历）。

### 1.3 第三步：连起“汇报关系”（Topology Constraints）

由于底层采用的是树形递归框架，DeepAgents 模式拥有几条绝对不可触碰的代码“天规”：

1. **唯一入口**：`START` 节点或连出源头必须**只连接、且有且仅连接到那个 Manager 节点**的头上。
2. **老板下发制**：从 Manager 节点，拉出 3 根普普通通的线（`normal`类型的边），分别连接到那三个小兵。
3. **禁止平级走动**：小兵和小兵之间（`web_investigator` 和 `report_writer`）**绝不允许横向连线**。底层代码会自动抛出 `invalid_edge_between_subagents` 错误。如果他们要数据互通，必须通过向沙盒系统文件来 `write/read` 交换情报。
4. **禁止越级汇报（无回路）**：小兵**绝不能拉一根紫色的循回边回到 Manager 身上**。系统会在他们执行完毕时隐式地将他们的摘要汇总上抛回给 Manager，拉线就成了拓扑死锁循环。

---

## 2. 实操：一键导入并运行你的 DeepAgents 团队

为了让你直观感受“老板分活”的威力，我们提供了一个 **“多兵种安全应急小组”** 的导入 JSON。

### 2.1 复制以下测试 JSON

```json
{
  "name": "DeepAgents 安全小组 demo",
  "description": "演示 Manager 节点如何动态调遣 SubAgents 进行异步协作。",
  "nodes": [
    {
      "id": "a1b1c1d1-e1f1-4111-a1b1-c1d1e1f1a1b1",
      "type": "agent",
      "label": "安全响应中心 (Manager)",
      "config": {
        "useDeepAgents": true,
        "systemPrompt": "你是一个安全应急响应 Manager。你会通过调用子智能体来处理安全威胁。请分析用户问题，分派给 web_analyst 或 report_specialist。",
        "description": "安全指挥官",
        "model": "gpt-4o"
      }
    },
    {
      "id": "b2b2c2d2-e2f2-4222-b2b2-c2d2e2f2b2b2",
      "type": "agent",
      "label": "Web 漏洞专家 (Worker)",
      "config": {
        "systemPrompt": "你是一个 Web 安全专家。你的任务是分析日志并识别木马或 SQL 注入特征。",
        "description": "web_analyst",
        "model": "gpt-4o"
      }
    },
    {
      "id": "c3c3c3d3-e3f3-4333-c3c3-c3d3e3f3c3c3",
      "type": "agent",
      "label": "报告编写员 (Worker)",
      "config": {
        "systemPrompt": "你是一个专业的文案。根据专家提供的技术数据，生成一份极其正式的安全通报。",
        "description": "report_specialist",
        "model": "gpt-4o"
      }
    }
  ],
  "edges": [
    {
      "source": "a1b1c1d1-e1f1-4111-a1b1-c1d1e1f1a1b1",
      "target": "b2b2c2d2-e2f2-4222-b2b2-c2d2e2f2b2b2",
      "edge_type": "normal"
    },
    {
      "source": "a1b1c1d1-e1f1-4111-a1b1-c1d1e1f1a1b1",
      "target": "c3c3c3d3-e3f3-4333-c3c3-c3d3e3f3c3c3",
      "edge_type": "normal"
    }
  ]
}
```

### 2.2 验证运行

1. **导入后**：你会发现画布变成了一个“1 对多”的星型结构，Manager 到 Worker 的连线是灰色实线（虽然线是死的，但 Manager 的思维是活的）。
2. **在 Runner 输入**：“我的服务器 /var/www/html 下出现了几个奇怪的 .php 文件，帮我看看是什么，并出一份通报。”
3. **观察行为**：你会看到 Manager 节点并不是“一锅端”，它会先调用 `web_analyst`，得到分析后再调用 `report_specialist`。如果是多件任务，它还会**同时异步并发**拉起多个专家。

---

## 3. 闭环验证：一句话唤起一支军队

保存这幅干净漂亮的“1 带 3”树状图。
打开调试器（Runner），输入：
> “刚才办公区路由器一直遭受大量的异常请求攻击，但我又怀疑是钓鱼邮件让员工点了，你去给我出个综合调查简报出来。”

**观测点：此时发生了什么？**

1. Manager 收到这段废话，它开始进行大模型自我思考（Thought Process）。
2. 后台抛出了一个并发操作事件：Manager 没有按死步骤走，它通过调用 `task(name="network_investigator", prompt="去查路由...")` 和 `task(name="web_investigator", prompt="去查邮件...")` **同时拉起了两个专业专家进异步并发！**
   并且，它这回没有调遣 `report_writer`（因为目前还是调查取证，时机没到）。
3. 当两个调查兵各自在互不干扰的上下文 Context 中狂舞 nmap 等沙盒工具，并分别执行完毕后。
4. 结果静默上浮回了 Manager 面前。Manager 得到了两份硬核数据，然后它又发起了第二次调用：
   `task(name="report_writer", prompt="拿这份合并的脱敏数据去写一封信...")`。
5. 最终，一份规整清晰的文字吐在了你的公屏上，没有附带那些杂乱的终端日志栈。

**这就是 DeepAgents 引擎的威力——动态决策图景。**
在这个模式下，你只需专注招什么样的专业人才（配什么样的 Skill 并且写好 prompt），连同线告诉谁是老板，其他千变万化的执行分支规划，大模型底层会在每一次聊天时**即时计算排查**，完全免去了你手写几十根不同 Router 判断线的噩梦。

---

## 4. Langfuse 链路追踪：看透 Manager 的"思考过程"

DeepAgents 的动态调度虽然强大，但"老板到底怎么想的"有时让人摸不着头脑。JoySafeter 集成的 **Langfuse 可观测性** 在此场景下尤为重要：

1. **进入追踪面板**：在左侧导航栏点击 **Traces**，或在 Runner 执行完毕后点击执行记录旁的 **View Trace** 链接。
2. **你能看到什么**：
   - **Manager 的决策过程**：LLM 输入/输出的完整内容，包括它如何分析用户需求、选择调度哪些 SubAgent
   - **任务分派时序**：Manager 先后（或并发）调用了哪些 Worker，每个 Worker 的执行耗时
   - **Worker 的执行详情**：每个 SubAgent 内部的 tool 调用、代码执行结果
   - **整体成本**：token 消耗、总延迟、各阶段耗时的瀑布图
3. **调试技巧**：如果 Manager 总是"分错人"或"漏掉某个专家"，在 Trace 中查看 Manager 的 System Prompt 注入内容——往往是花名册描述不够清晰导致的。

> 配置 Langfuse 连接：进入 **Settings → Observability**，填入 Langfuse Host、Public Key 和 Secret Key。

---

> 🚀 **全盘掌握终极预告**：至此，你已经从模型环境（01）、MCP（02）、Skills技能库连沙盒（03）、到最高阶的大型固定工作流（04a）与动态管理团队（04b）全部通关实操落地。恭喜你成为 JoySafeter 真正的架构玩家！如果想用 AI 来帮你写以上这些复杂的图 JSON？请移步**教程05：Copilot 深度解析。**
