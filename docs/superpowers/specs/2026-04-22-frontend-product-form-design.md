# 前端产品形态设计 — Agent 中心化

Date: 2026-04-22
Status: Draft

## 产品定位

Agent 是核心产品概念。用户围绕 Agent 完成所有操作：

- **构建** — 多种方式定义 Agent（Prompt 指令、Graph 可视化编排、Code 代码、Hybrid 混合）
- **发布** — 版本冻结 → 发布 Release → 激活
- **驱动** — 通过 Mission 任务分配、对话、API 触发 Agent 执行
- **观测** — 查看 Agent 状态、运行历史、深度执行可视化（事件流、工具调用、决策树）

## 信息架构

```
Sidebar
├── Agents          → /agents                    # 核心入口
├── Runs            → /runs                      # 全局运行中心
├── Missions        → /missions                  # 任务看板
├── ──────────
├── Skills          → /skills                    # 技能库
├── Tools           → /tools                     # MCP/工具
├── ──────────
├── Memory          → /memory                    # 知识库
└── Settings        → /settings                  # 设置
```

删除的入口：`/chat`（吸收进 Agent Threads）、`/discover`（空壳）、`/workspace/[id]/[agentId]`（Graph Builder 吸收进 Agent Edit）

## Agent 详情页架构

```
/agents/[agentId]/
├── (overview)      — 概览：状态、active release、最近 runs、快捷操作
├── /edit           — 构建器：根据 definition_kind 切换编辑器
│   ├── prompt      → PromptEditor（指令编辑器）
│   ├── graph       → GraphBuilder（ReactFlow 画布，复用现有 84 个文件）
│   ├── code        → CodeEditor（CodeMirror）
│   └── hybrid      → 组合编辑器
├── /versions       — 版本历史：冻结、对比
├── /releases       — 发布管理：发布、激活、退役
├── /threads        — 对话列表
│   └── /[threadId] — 对话界面（触发 Run）
├── /runs           — 该 Agent 的运行历史（新增）
└── /monitor        — 实时监控面板（新增，复用 ExecutionTree/Timeline）
```

## 核心页面设计

### 1. Agent 概览页 `/agents/[agentId]`

```
┌─────────────────────────────────────────────────────┐
│ ← Agents    [Agent Name]  [slug]  [●active]         │
│─────────────────────────────────────────────────────│
│ Overview | Edit | Versions | Releases | Threads | Runs│
│─────────────────────────────────────────────────────│
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ Active Release│  │ Draft Version│  │ Status     │ │
│  │ v3 #release-2│  │ v4 (draft)   │  │ 2 running  │ │
│  │ sandbox      │  │ prompt       │  │ 5 completed│ │
│  │ [Retire]     │  │ [Edit →]     │  │ [View →]   │ │
│  └──────────────┘  └──────────────┘  └────────────┘ │
│                                                      │
│  Recent Runs                                         │
│  ┌─────────────────────────────────────────────────┐ │
│  │ #run-12  mission  running   2m ago  [View →]    │ │
│  │ #run-11  chat     succeeded 15m ago [View →]    │ │
│  │ #run-10  api      failed    1h ago  [View →]    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Quick Actions                                       │
│  [💬 New Thread]  [▶ Run Now]  [📋 Assign Mission]  │
└─────────────────────────────────────────────────────┘
```

### 2. Agent 构建器 `/agents/[agentId]/edit`

根据 `current_draft_version.definition_kind` 动态切换编辑器：

**prompt 模式：**
```
┌─────────────────────────────────────────────────────┐
│ Edit Draft (v4)  [definition_kind: prompt]           │
│─────────────────────────────────────────────────────│
│                                                      │
│  System Prompt                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ You are a security analyst agent...             │ │
│  │                                                 │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Instructions                                        │
│  ┌─────────────────────────────────────────────────┐ │
│  │ 1. Analyze the target...                        │ │
│  │ 2. Generate report...                           │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Capabilities                                        │
│  Skills: [web-search] [code-analysis] [+Add]         │
│  MCP Servers: [github] [+Add]                        │
│                                                      │
│  [Save Draft]  [Freeze Version]  [Test Run ▶]        │
└─────────────────────────────────────────────────────┘
```

**graph 模式：**
```
┌─────────────────────────────────────────────────────┐
│ Edit Draft (v4)  [definition_kind: graph]            │
│─────────────────────────────────────────────────────│
│ ┌──────────┐ ┌─────────────────────────────────────┐ │
│ │Components│ │                                     │ │
│ │          │ │    [Start] ──→ [Analyzer] ──→       │ │
│ │ ○ LLM   │ │                    │                 │ │
│ │ ○ Tool  │ │              [Router]                │ │
│ │ ○ Branch│ │              ↙     ↘                 │ │
│ │ ○ Human │ │    [Report]      [Scan]              │ │
│ │          │ │         ↘       ↙                   │ │
│ │          │ │          [End]                       │ │
│ │          │ │                                     │ │
│ └──────────┘ └─────────────────────────────────────┘ │
│ [Save] [Freeze] [Test Run ▶]  [Properties ▸]        │
└─────────────────────────────────────────────────────┘
```

这里直接复用现有的 `AgentBuilder.tsx` + `BuilderCanvas.tsx` + 全部 84 个 graph builder 文件。

### 3. Run 详情 + 执行可视化 `/runs/[runId]`

```
┌─────────────────────────────────────────────────────┐
│ Run #run-12  [Agent: SecurityBot]  [●running]        │
│─────────────────────────────────────────────────────│
│ Trigger: mission  │ Goal: Scan target.com            │
│ Release: v3 #2    │ Attempt: 1                       │
│─────────────────────────────────────────────────────│
│                                                      │
│  ┌─ Execution Timeline ────────────────────────────┐ │
│  │ 14:32:01  ● started                             │ │
│  │ 14:32:03  ◆ tool_call: web_search("target.com") │ │
│  │ 14:32:05  ◇ tool_result: {status: 200, ...}     │ │
│  │ 14:32:08  ◆ tool_call: nmap_scan(...)            │ │
│  │ 14:32:15  ◇ tool_result: {ports: [...]}          │ │
│  │ 14:32:18  ■ llm_response: "Found 3 open ports"  │ │
│  │ 14:32:20  ◆ tool_call: generate_report(...)      │ │
│  │ ...                                              │ │
│  └──────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─ Execution Tree ────────┐ ┌─ Detail Panel ──────┐ │
│  │ ▼ Run #12               │ │ Event: tool_call     │ │
│  │   ▼ Execution #1        │ │ Tool: web_search     │ │
│  │     ├ tool_call          │ │ Input: {"q": "..."}  │ │
│  │     ├ tool_result        │ │ Output: {200, ...}   │ │
│  │     ├ tool_call    ← ●  │ │ Duration: 2.1s       │ │
│  │     └ ...                │ │ [View Raw JSON]      │ │
│  └──────────────────────────┘ └──────────────────────┘ │
│                                                      │
│  Artifacts: [report.pdf] [scan-results.json]         │
│  [Cancel Run]  [Retry]  [Send Message]               │
└─────────────────────────────────────────────────────┘
```

复用现有的 `ExecutionTree.tsx`、`ExecutionTimeline.tsx`、`ExecutionDetailPanel.tsx`、`JsonView.tsx` 等组件。

### 4. Mission 看板 `/missions`

保持现有 DnD 看板不变，但：
- Agent 选择器从 `AgentProfile` 切换到新 `Agent` 模型
- Dispatch 按钮触发 `AgentRun` 而非直接创建 `Execution`
- Mission 详情面板显示关联的 Runs 列表
- 每个 Run 可点击跳转到 `/runs/[runId]` 查看执行详情

## 现有资产复用计划

| 现有资产 | 位置 | 复用方式 |
|---------|------|---------|
| Graph Builder (84 files) | `/workspace/[wid]/[aid]/` | 整体搬迁到 `/components/graph-builder/`，在 `/agents/[id]/edit` 中按 definition_kind=graph 加载 |
| Execution 可视化 (9 files) | 同上 `/components/execution/` | 搬迁到 `/components/execution/`，在 `/runs/[id]` 和 Agent Monitor 中复用 |
| Mission 看板 | `/components/missions/` | 保留，修复 AgentProfile → Agent 引用 |
| Copilot Panel | 同上 `/components/copilot/` | 搬迁到 `/components/copilot/`，在 Agent Edit 中复用 |

## 需要删除的遗留路由

| 路由 | 原因 |
|------|------|
| `/workspace/[wid]/[aid]` | Graph Builder 吸收进 `/agents/[id]/edit` |
| `/workspace/[wid]/settings/members` | 移入 `/settings/workspace` |
| `/workspace/[wid]` | 不再需要独立 workspace 页面 |
| `/discover` | 空壳 placeholder |

## 需要新建的页面

| 页面 | 用途 |
|------|------|
| `/agents/[id]/runs` | Agent 维度的运行历史 |
| `/agents/[id]/monitor` | Agent 实时监控（可选，Phase 2） |
| `/executions/[id]` | Execution 详情（事件流 + artifacts） |

## 需要修复的页面

| 页面 | 问题 | 修复 |
|------|------|------|
| `/missions` | 引用 `useAgentNameMap` from `agentProfiles`（已删除） | 改为从 `agents` hooks 导入 |
| `/skills/creator` | 内嵌 graph 执行逻辑，引用旧模型 | 适配新 AgentRun 模型 |
| `/agents/[id]/edit` | graph 模式只显示 placeholder | 接入 Graph Builder 组件 |

## 实施优先级

### P0 — 自洽性修复（必须做，否则页面崩溃）
1. 修复 `/missions` 页面的 `agentProfiles` 引用
2. 修复 `/skills/creator` 的旧模型引用
3. 在 Agent layout 添加 "Runs" tab

### P1 — 核心体验完善
4. 搬迁 Graph Builder 到 `/components/graph-builder/`，接入 `/agents/[id]/edit`
5. 搬迁 Execution 可视化到 `/components/execution/`，接入 `/runs/[id]`
6. 新建 `/agents/[id]/runs` 页面
7. Agent 概览页补充 active release + recent runs 摘要

### P2 — 遗留清理
8. 删除 `/workspace/` 路由
9. 删除 `/discover` 路由
10. 清理所有 TODO cleanup 标记

### P3 — 增强功能
11. Agent 实时监控面板
12. Execution 对比视图
13. Agent 模板市场
