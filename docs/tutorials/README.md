# JoySafeter 使用教程

本目录包含 JoySafeter 的实战教程，以真实场景为导向，帮助你快速上手平台核心功能。

---

## 教程列表

| # | 教程 | 核心内容 | 难度 |
|---|------|---------|------|
| 00 | [新手上手手册](./00-getting-started.md) | 零基础终端用户的完整主线：登录 → 模型接入 → 建 Agent → 跑会话 → 拿结果 | ⭐ 入门 |
| 01 | [引擎、协议、模型供应商与模型配置](./01-model-provider-setup.md) | 通过统一 LLM Catalog 创建 Provider/Protocol 模型配置，并按 Engine 兼容性选择 | ⭐ 入门 |
| 02 | [为 Agent 接入 MCP 工具](./02-mcp-service-setup.md) | 在 Agent 编辑器配置 URL 型 `mcp_servers`；凭据放资源 → 凭据 → MCP 凭据组（`/managed/credentials?tab=mcp`）；运行时经 gRPC 下发 | ⭐⭐ 进阶 |
| 03 | [Skills 的导入、安全扫描、投递与消费](./03-skills-usage.md) | SKILL.md → skillspector 扫描 → Rust orchestrator 打包 → 沙箱解压消费的闭环 | ⭐⭐ 进阶 |
| 04 | [构建并运行一个 Agent](./04-agent-build-and-run.md) | 引擎/模型/技能/工具/MCP 组装 → 开 Session → SSE 实时观察 → 干预/停止 | ⭐⭐ 进阶 |
| 05 | [用触发器让智能体自动运行](./05-triggers.md) | 计划（Cron）/ Webhook / 手动触发；签名鉴权、投递过滤、会话模式、自动禁用 | ⭐⭐ 进阶 |
| 06 | [用环境控制沙箱的网络与运行时](./06-environments.md) | 网络策略（限制/不限制）、允许主机、第三方服务出站鉴权（服务凭据、真实凭据不进沙箱）、数据卷 | ⭐⭐ 进阶 |

---

## 推荐学习路径

### 🚀 快速开始（15 分钟）

1. **教程 01**：在 **资源 → 凭据**（`/managed/credentials?tab=models`）配置一条模型连接。
2. **教程 04**：新建 Agent（选 `claude` 引擎），开会话发第一条消息，看 SSE 实时事件流。

### 🔧 完整能力（1 小时）

1. 完成快速开始。
2. **教程 03**：导入一个技能包，跑通“扫描 → approved → 挂到 Agent → 沙箱消费”闭环。
3. **教程 02**：给 Agent 接入一个 MCP 工具（凭据放 MCP 凭据组）。
4. **教程 04**：把工具 / 技能 / MCP 组合进同一个 Agent，构建自动化工作流。

### 🏆 进阶应用

- 组合教程 02 + 03 + 04，构建一个带自定义工具与技能的授权渗透测试 Agent。
- 用工具授权策略（`always_ask`）在高危工具前插入人工确认（教程 04 §4）。

---

## 相关文档

- [系统架构（中文）](../ARCHITECTURE_CN.md) · [Architecture (EN)](../ARCHITECTURE.md)
- [分层架构图](../architecture-unified-event-model.mmd)
