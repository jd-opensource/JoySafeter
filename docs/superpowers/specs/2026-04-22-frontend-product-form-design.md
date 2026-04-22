# 前端产品形态 + 概念模型 + 权限设计（完整版）

Date: 2026-04-22
Status: Approved Direction

## 一、概念模型（唯一真相）

### 5 个核心概念，每个只做一件事

| 概念 | 回答的问题 | 类比 |
|------|-----------|------|
| **Agent** | 这是什么？ | GitHub Repo |
| **AgentVersion** | 它怎么定义的？ | Git Commit |
| **AgentRelease** | 哪个版本在跑？ | Docker Image Tag |
| **Task** | 人想让它做什么？ | GitHub Issue |
| **Run** | 机器实际做了什么？ | CI/CD Pipeline Run |

### 概念关系

```
Agent (身份)
 ├── AgentVersion (定义快照, 多个)
 │    └── AgentRelease (可运行单元, 多个)
 │         └── Run (执行实例, 多个)
 │              └── Execution (执行尝试, 含重试)
 │                   ├── ExecutionEvent (事件流)
 │                   └── Artifact (产出物)
 ├── Thread (对话, 多个)
 │    └── Message (消息)
 └── Task (任务, 多个)
      └── Run (关联, 一个 Task 可触发多次 Run)
```

### Mission → Task 重命名 + 语义重定义

| 维度 | 旧 Mission | 新 Task |
|------|-----------|---------|
| 本质 | 独立的项目管理对象 | Agent 的工作项 |
| 状态 | 手动拖拽 6 档 | 自动同步 Run 状态 + 人工标记 |
| 归属 | workspace 级别 | **Agent 级别**（每个 Task 必须绑定一个 Agent） |
| 触发 | dispatch 创建 Execution | dispatch 创建 Run |
| 完成 | 人手动标 done | Run succeeded → 自动标 done，人可 reopen |

**状态自动同步规则：**

```
Task 创建                    → backlog
Task 分配 Agent + dispatch   → in_progress（自动创建 Run）
  Run queued/running         → in_progress（保持）
  Run succeeded              → done（自动）
  Run failed                 → needs_review（自动，人决定重试或关闭）
  Run cancelled              → backlog（回退，人决定下一步）
人手动操作                    → 可以 reopen done 的 Task，可以手动标 cancelled
```

**关键变化：Task 必须绑定 Agent。** 不再有 `assignee_type: member` 的情况——这是 Agent 平台，不是项目管理工具。人的任务用其他工具管理。

### DB 变更（Mission → Task）

```sql
-- 重命名表
ALTER TABLE missions RENAME TO tasks;

-- 字段变更
ALTER TABLE tasks DROP COLUMN assignee_type;           -- 不再区分 agent/member
ALTER TABLE tasks RENAME COLUMN assignee_id TO agent_id;  -- 直接关联 Agent
ALTER TABLE tasks ADD CONSTRAINT fk_tasks_agent FOREIGN KEY (agent_id) REFERENCES agents(id);
ALTER TABLE tasks DROP COLUMN current_execution_id;    -- 已在 Phase 4 删除
ALTER TABLE tasks RENAME COLUMN objective TO goal;     -- 统一术语

-- 新增字段
ALTER TABLE tasks ADD COLUMN latest_run_id UUID REFERENCES agent_runs(id);  -- 最新 Run 指针

-- 状态枚举变更
-- 旧: backlog, todo, in_progress, in_review, done, cancelled
-- 新: backlog, in_progress, done, needs_review, cancelled
```

## 二、前端信息架构

### 用户心智模型：3 层

```
┌─────────────────────────────────────────────────────────┐
│                    身份层 (What)                          │
│  "我有哪些 Agent？它们是什么？怎么构建？"                    │
│  /agents  →  /agents/[id]  →  /agents/[id]/edit          │
│                                /agents/[id]/versions      │
│                                /agents/[id]/releases      │
├─────────────────────────────────────────────────────────┤
│                    驱动层 (Do)                            │
│  "让 Agent 做事：分配任务、对话、直接运行"                    │
│  /agents/[id]/tasks    (该 Agent 的任务看板)               │
│  /agents/[id]/threads  (该 Agent 的对话)                   │
│  /tasks                (全局任务看板)                      │
├─────────────────────────────────────────────────────────┤
│                    观测层 (See)                           │
│  "Agent 做得怎么样？内部怎么执行的？"                        │
│  /agents/[id]/runs     (该 Agent 的运行历史)               │
│  /runs                 (全局运行中心)                      │
│  /runs/[id]            (Run 详情 + 执行可视化)             │
└─────────────────────────────────────────────────────────┘
```

### Sidebar 导航

```
Sidebar
├── 🤖 Agents          → /agents              # 核心入口
├── 📋 Tasks           → /tasks               # 全局任务看板（原 Missions）
├── ▶️ Runs            → /runs                # 全局运行中心
├── ──────────
├── 🧩 Skills          → /skills              # 技能库
├── 🔧 Tools           → /tools               # MCP/工具
├── 🧠 Memory          → /memory              # 知识库
├── ──────────
└── ⚙️ Settings        → /settings            # 设置
```

### Agent 详情页 Tab 结构

```
/agents/[agentId]/
  Overview | Edit | Versions | Releases | Tasks | Threads | Runs
  (概览)   (构建)  (版本)    (发布)     (任务)  (对话)    (运行)
```

**Tab 分组逻辑：**
- 前 4 个 = 身份层（定义 Agent 是什么）
- 中间 2 个 = 驱动层（让 Agent 做事）
- 最后 1 个 = 观测层（看 Agent 做了什么）

## 三、权限模型

### Workspace 级别 4 档角色

```
viewer  → 看所有页面，不能操作
member  → 看 + 操作（创建、编辑、发布、运行、分配任务）
admin   → 看 + 操作 + 管理（删除 Agent、管理成员、管理设置）
owner   → 全部（转让 workspace、删除 workspace）
```

### 权限矩阵

| 操作 | viewer | member | admin | owner |
|------|--------|--------|-------|-------|
| 查看 Agent 列表/详情 | ✓ | ✓ | ✓ | ✓ |
| 查看 Run/Execution 详情 | ✓ | ✓ | ✓ | ✓ |
| 查看 Task 看板 | ✓ | ✓ | ✓ | ✓ |
| 创建/编辑 Agent | | ✓ | ✓ | ✓ |
| 冻结版本/发布 Release | | ✓ | ✓ | ✓ |
| 创建 Task/分配 Agent | | ✓ | ✓ | ✓ |
| 触发 Run/对话 | | ✓ | ✓ | ✓ |
| Cancel/Retry Run | | ✓ | ✓ | ✓ |
| 删除/归档 Agent | | | ✓ | ✓ |
| 管理 Workspace 成员 | | | ✓ | ✓ |
| 管理 Skills/Tools/Models | | | ✓ | ✓ |
| 删除 Workspace | | | | ✓ |

### 前端权限 Hook

```typescript
// hooks/use-workspace-permission.ts
export function useWorkspacePermission() {
  const role = useCurrentWorkspaceRole()  // viewer | member | admin | owner
  return {
    canView:   true,  // 所有角色都能看
    canOperate: role !== 'viewer',
    canManage:  role === 'admin' || role === 'owner',
    canOwn:     role === 'owner',
    role,
  }
}

// 组件中使用
const { canOperate, canManage } = useWorkspacePermission()
<Button disabled={!canOperate}>Run Now</Button>
{canManage && <Button variant="destructive">Delete Agent</Button>}
```

## 四、模块化架构（支持扩展）

### Agent 能力扩展点

新模型通过 3 个正交维度支持未来扩展，互不干扰：

```
definition_kind (怎么定义)     runtime_kind (怎么运行)      trigger_source (怎么触发)
├── prompt                    ├── sandbox (Docker)         ├── task (任务分配)
├── graph                     ├── hosted (托管)            ├── chat (对话)
├── code                      ├── external (外部)          ├── api (API 调用)
├── hybrid                    └── [future: k8s, ...]      ├── scheduler (定时)
└── [future: workflow, ...]                                └── [future: webhook, ...]
```

**添加新的 Agent 构建方式：**
1. 后端：在 `definition_kind` 枚举加一个值
2. 前端：在 `/agents/[id]/edit` 的 switch 里加一个编辑器组件
3. 不影响发布、运行、任务、对话任何流程

**添加新的运行时：**
1. 后端：在 `runtime_kind` 枚举加一个值 + 实现 RuntimeProvider
2. 前端：在 Release 发布对话框的 runtime_kind 选择器加一个选项
3. 不影响 Agent 定义、任务、对话任何流程

**添加新的触发方式：**
1. 后端：在 `trigger_source` 枚举加一个值 + 实现触发入口
2. 前端：在 Agent 概览页加一个触发按钮
3. 不影响 Agent 定义、发布、运行可视化任何流程

### 前端模块边界

```
frontend/
├── app/
│   ├── agents/           # 身份层 — Agent CRUD + 构建
│   ├── tasks/            # 驱动层 — 任务看板（原 missions）
│   ├── runs/             # 观测层 — 运行中心 + 执行可视化
│   ├── skills/           # 能力配置 — 技能管理
│   ├── tools/            # 能力配置 — MCP/工具
│   ├── memory/           # 能力配置 — 知识库
│   └── settings/         # 系统设置
├── components/
│   ├── agents/           # Agent 卡片、表单、状态指示器
│   ├── editors/          # 编辑器组件（按 definition_kind 分）
│   │   ├── prompt-editor.tsx
│   │   ├── graph-builder/ # 从 workspace/[wid]/[aid]/ 搬迁的 84 个文件
│   │   └── code-editor.tsx
│   ├── execution/        # 执行可视化（从 workspace 搬迁的 9 个文件）
│   │   ├── execution-tree.tsx
│   │   ├── execution-timeline.tsx
│   │   └── execution-detail-panel.tsx
│   ├── tasks/            # 任务看板组件（原 missions/）
│   ├── threads/          # 对话组件
│   └── ui/               # 基础 UI 组件（不动）
├── services/             # API 调用层（按领域分）
├── hooks/queries/        # React Query hooks（按领域分）
├── types/                # TypeScript 类型（按领域分）
└── stores/               # Zustand stores（最小化，大部分用 React Query）
```

## 五、与重构代码的自洽性检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| Agent 表 + API + 前端 | ✅ 完成 | Phase 1 已实现 |
| AgentVersion 表 + API + 前端 | ✅ 完成 | Phase 1 已实现 |
| AgentRelease 表 + API + 前端 | ✅ 完成 | Phase 2 已实现 |
| Thread/Message 表 + API + 前端 | ✅ 完成 | Phase 3 已实现 |
| AgentRun 表 + API + 前端 | ✅ 完成 | Phase 4 已实现 |
| Execution/Event 表 + API + 前端 | ✅ 完成 | Phase 4 已实现 |
| Artifact 表 + API | ✅ 完成 | Phase 5 已实现 |
| Mission → Task 重命名 | ❌ 待做 | 需要新的迁移 + 代码重命名 |
| Task 状态自动同步 Run | ❌ 待做 | 需要 service 层逻辑 |
| Task 绑定 Agent（去掉 assignee_type） | ❌ 待做 | 需要迁移 + schema 变更 |
| Graph Builder 搬迁到公共组件 | ❌ 待做 | 84 个文件搬迁 |
| Execution 可视化搬迁 | ❌ 待做 | 9 个文件搬迁 |
| Agent Edit 接入 Graph Builder | ❌ 待做 | definition_kind=graph 时加载 |
| Run 详情接入 Execution 可视化 | ❌ 待做 | 复用搬迁后的组件 |
| /missions → /tasks 路由重命名 | ❌ 待做 | 前端路由 + sidebar |
| Agent layout 添加 Tasks/Runs tab | ❌ 待做 | layout.tsx 更新 |
| 删除遗留路由 (/workspace, /discover) | ❌ 待做 | 删除文件 |
| 修复 missions 页面 agentProfiles 引用 | ❌ 待做 | 改为 agents hooks |
| useWorkspacePermission hook | ❌ 待做 | 新建 |

## 六、实施顺序

### Phase A：概念对齐（Mission → Task）
1. DB 迁移：missions → tasks，字段重命名
2. 后端：model/schema/service/API 重命名
3. 前端：路由 /missions → /tasks，组件重命名
4. Task 状态自动同步 Run 逻辑

### Phase B：组件搬迁 + 接入
5. Graph Builder 84 文件搬迁到 /components/editors/graph-builder/
6. Execution 可视化 9 文件搬迁到 /components/execution/
7. /agents/[id]/edit 接入 Graph Builder（definition_kind=graph）
8. /runs/[id] 接入 Execution 可视化

### Phase C：页面补全 + 清理
9. Agent layout 添加 Tasks/Runs tab
10. 新建 /agents/[id]/tasks 页面（Agent 维度的任务看板）
11. 新建 /agents/[id]/runs 页面（Agent 维度的运行历史）
12. 创建 useWorkspacePermission hook，全局接入
13. 删除遗留路由（/workspace, /discover）
14. 清理所有 TODO cleanup 标记
