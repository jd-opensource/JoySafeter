# Frontend Observation Trace Viewer Design

> 完全重写前端测试阶段 UI：删除旧 `components/execution/`，新建 Langfuse 对齐的 observation trace viewer，消费后端 `channel: "observation"` WebSocket 事件。

## 1. 目标

在 AgentBuilder 中替换现有测试运行 UI，用 observation-first 的 trace viewer 实时展示 LLM 交互链路。支持实时流式构建和历史回看两种模式。

## 2. 核心决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 方案 | 独立新模块 `components/observation/` | 完全重写，不 fork 旧代码 |
| 状态管理 | 5 个独立 React Context（对齐 Langfuse） | 正交关切分离，避免不必要重渲染 |
| 虚拟化 | `@tanstack/react-virtual`（已有依赖） | 支持 10,000+ 节点 |
| 树构建 | 迭代式 4 阶段拓扑排序（对齐 Langfuse） | 无递归，bottom-up cost 聚合 O(1) |
| WS 接入 | 复用 `executionWsClient`，hook 层按 `channel` 过滤 | 不改 WS 基础设施 |
| 旧组件 | 删除 `components/execution/` 整个目录 | threads/tasks 降级到 `components/executions/` |
| 选择状态 | URL query params 同步（对齐 Langfuse） | 可分享、可刷新 |

## 3. 模块结构

```
frontend/components/observation/
├── index.ts
├── ObservationPanel.tsx              # 顶层：Provider 嵌套 + resizable 布局
├── contexts/
│   ├── ObservationDataContext.tsx     # 树数据 + nodeMap + 搜索项
│   ├── ObservationSelectionContext.tsx # URL 同步选择/折叠/搜索
│   ├── ObservationViewPrefsContext.tsx # localStorage 显示偏好
│   └── ObservationJsonExpansionContext.tsx # sessionStorage JSON 展开
├── components/
│   ├── ObservationTree.tsx           # 组合虚拟化树 + NodeWrapper + SpanContent
│   ├── ObservationNodeWrapper.tsx    # 树 chrome（缩进/连接线/折叠按钮）
│   ├── ObservationSpanContent.tsx    # 节点内容（名称/耗时/tokens/cost/heatmap）
│   ├── ObservationTimeline.tsx       # Gantt 视图容器
│   ├── TimelineBar.tsx              # 单个 Gantt 条
│   ├── TimelineScale.tsx            # 时间轴刻度头
│   ├── ObservationDetailPanel.tsx    # 右侧详情路由（按 type 渲染）
│   ├── IOPreview.tsx                # pretty/json 切换
│   └── ItemBadge.tsx                # 图标+颜色 per observation type
├── hooks/
│   └── useObservationStream.ts      # WebSocket 订阅 channel="observation"
├── lib/
│   ├── types.ts                     # ObservationNode, FlatItem, TraceSummary
│   ├── tree-building.ts             # 迭代式 4 阶段算法
│   ├── tree-flattening.ts           # 迭代 DFS 展平
│   ├── timeline-calculations.ts     # 像素偏移/宽度/刻度计算
│   ├── constants.ts                 # 图标/颜色映射
│   └── helpers.ts                   # heatMapTextColor 等
└── __tests__/
    ├── tree-building.test.ts
    └── timeline-calculations.test.ts
```

## 4. TypeScript 类型

```typescript
// lib/types.ts

export type ObservationType =
  | "SPAN" | "EVENT" | "GENERATION" | "AGENT" | "TOOL"
  | "CHAIN" | "RETRIEVER" | "EMBEDDING" | "EVALUATOR" | "GUARDRAIL";

export type ObservationLevel = "DEBUG" | "DEFAULT" | "WARNING" | "ERROR";

export interface ObservationNode {
  id: string;
  parentObservationId: string | null;
  type: ObservationType;
  name: string;
  level: ObservationLevel;
  statusMessage: string | null;
  startTime: Date;
  endTime: Date | null;
  completionStartTime: Date | null;

  input: unknown;
  output: unknown;
  metadata: Record<string, unknown> | null;

  // GENERATION 专用
  model?: string;
  usageDetails?: Record<string, number>;
  costDetails?: Record<string, number>;
  toolCalls?: Array<{ id: string; name: string; arguments: unknown }>;
  toolCallNames?: string[];

  // 树结构（构建时计算）
  children: ObservationNode[];
  depth: number;
  childrenDepth: number;

  // 聚合（bottom-up 构建时计算，O(1) 访问）
  totalCost: number;
  startTimeSinceTrace: number;       // ms from trace start
  startTimeSinceParentStart: number | null;

  // 用量
  inputUsage?: number | null;
  outputUsage?: number | null;
  totalUsage?: number | null;
}

export interface ObservationFlatItem {
  node: ObservationNode;
  depth: number;
  isExpanded: boolean;
  hasChildren: boolean;
  isLastChild: boolean;
  treeLines: boolean[];   // 祖先链中哪些层级需要画连接线
}

export interface TraceSummary {
  traceId: string;
  status: "running" | "complete" | "error";
  totalTokens: number;
  totalCost: number;
  durationMs: number | null;
}

// WebSocket frame
export interface WsObservationFrame {
  channel: "observation";
  trace_id: string;
  seq: number;
  event: "span_open" | "span_update" | "span_close" | "record" | "trace_complete";
  observation: Record<string, unknown>;
}
```

## 5. Context 架构

### 5.1 Provider 嵌套顺序

```
ObservationViewPrefsProvider (localStorage)
  └── ObservationDataProvider (树数据)
        └── ObservationSelectionProvider (URL 同步)
              └── ObservationJsonExpansionProvider (sessionStorage)
                    └── ObservationContent (布局 + 视图)
```

### 5.2 ObservationDataContext

```typescript
interface ObservationDataValue {
  roots: ObservationNode[];
  nodeMap: Map<string, ObservationNode>;
  searchItems: ObservationSearchItem[];
  traceSummary: TraceSummary | null;
  isExecuting: boolean;
  traceStartTime: Date | null;

  // 增量更新（实时模式）
  handleObservationEvent: (frame: WsObservationFrame) => void;
}
```

两种模式：
- 实时模式：`useObservationStream` 推送 frame → `handleObservationEvent` 增量更新
- 回看模式：`useQuery` 加载扁平列表 → `buildTraceTree` 一次性构建

### 5.3 ObservationSelectionContext

```typescript
interface ObservationSelectionValue {
  selectedNodeId: string | null;
  collapsedNodes: Set<string>;
  searchQuery: string;
  viewMode: "tree" | "timeline";

  selectNode: (id: string | null) => void;
  toggleCollapse: (id: string) => void;
  expandAll: () => void;
  collapseAll: (nodeIds: string[]) => void;
  setSearchQuery: (query: string) => void;
  setViewMode: (mode: "tree" | "timeline") => void;
}
```

`selectedNodeId` 和 `viewMode` 同步到 URL query params（`?observation=<id>&view=timeline`）。

### 5.4 ObservationViewPrefsContext

localStorage 持久化：

| Key | Default | 说明 |
|---|---|---|
| `obs:showDuration` | `true` | 显示耗时 badge |
| `obs:showCostTokens` | `true` | 显示 cost/token badge |
| `obs:colorCodeMetrics` | `true` | heatmap 颜色编码 |
| `obs:jsonViewPref` | `"pretty"` | pretty / json |

## 6. 树构建算法（对齐 Langfuse）

迭代式 4 阶段，无递归：

```
Phase 1 — prepareObservations
  排序 by startTime，清理孤儿 parentObservationId

Phase 2 — buildDependencyGraph
  Pass 1: 创建 ProcessingNode entries
  Pass 2: 构建 parent→children ID 数组
  Pass 3: BFS 计算 depth
  Pass 4: 设置 inDegree，收集叶子节点

Phase 3 — buildTreeNodesBottomUp
  拓扑排序（叶子优先）
  处理子节点在父节点之前 → bottom-up cost 聚合
  O(1) dequeue（index pointer，不用 shift）
  计算 startTimeSinceTrace, childrenDepth, totalCost

Phase 4 — 包装
  返回 { roots, nodeMap, searchItems }
```

增量模式（实时）：
- `span_open` / `record` → 创建节点，挂到 parent.children，重算 flatItems
- `span_close` → 更新 endTime/output，propagateAggregates 沿祖先链向上
- `trace_complete` → 冻结，设置 traceSummary

## 7. 视图组件

### 7.1 ObservationPanel（顶层）

```
┌──────────────────────────────────────────────────────────┐
│ [🔍 搜索] [Tree | Timeline]   tokens: 1,540  cost: $0.02 │
├───────────────────────────┬──────────────────────────────┤
│  ObservationTree          │  ObservationDetailPanel      │
│  或 ObservationTimeline   │                              │
│                           │  (选中节点详情)               │
│  react-resizable-panels   │                              │
│  左右分割 55:45           │                              │
└───────────────────────────┴──────────────────────────────┘
```

### 7.2 ObservationTree

- `@tanstack/react-virtual`，行高 37px，overscan 500
- 每行 = `ObservationNodeWrapper` + `ObservationSpanContent`
- `ObservationNodeWrapper`：缩进 20px × depth，垂直/水平连接线，折叠按钮
- `ObservationSpanContent`：ItemBadge + name + duration badge + token badge + cost badge + heatmap 颜色
- 执行中自动滚动到最新节点
- 键盘导航：↑↓ 选择，←→ 折叠/展开

### 7.3 ObservationTimeline

- 左列 180px（名称 + ItemBadge）
- 右区 Gantt 条形图：SCALE_WIDTH=900px
- `TimelineScale`：5-tick 时间刻度头
- `TimelineBar`：`left = (startTimeSinceTrace / traceDuration) × SCALE_WIDTH`，`width = (duration / traceDuration) × SCALE_WIDTH`，最小 10px
- 运行中节点脉冲动画
- 虚拟化行高 42px

### 7.4 ObservationDetailPanel

按 type 路由：

| type | 渲染 |
|---|---|
| GENERATION | IOPreview (pretty: ChatML 消息渲染 / json) + model + usage 表格 + cost |
| TOOL | tool name + arguments JSON + result JSON |
| EVENT | name + metadata 表格 |
| AGENT | 节点名称 + 子树统计 |
| CHAIN/SPAN | input/output JSON |

通用：顶部 type badge + name + duration，Tabs: Preview / Raw JSON

### 7.5 IOPreview

两种模式（仅挂载当前模式，避免双 DOM）：
- `pretty`：解析 ChatML 消息格式，渲染对话气泡 + tool call 卡片
- `json`：JSON 树查看器

### 7.6 ItemBadge（对齐 Langfuse）

| Type | Icon (Lucide) | Color |
|---|---|---|
| GENERATION | `Fan` | `text-muted-magenta` |
| AGENT | `Bot` | `text-purple-600` |
| TOOL | `Wrench` | `text-orange-600` |
| EVENT | `CircleDot` | `text-muted-green` |
| SPAN | `MoveHorizontal` | `text-muted-blue` |
| CHAIN | `Link` | `text-pink-600` |
| RETRIEVER | `Search` | `text-teal-600` |
| EMBEDDING | `Layers3` | `text-amber-600` |
| GUARDRAIL | `ShieldCheck` | `text-red-600` |
| EVALUATOR | `WandSparkles` | `text-primary-accent` |

ERROR level 节点加红色左边框。

### 7.7 Heatmap 颜色（对齐 Langfuse）

```typescript
function heatMapTextColor(value: number, min: number, max: number): string {
  const ratio = (value - min) / (max - min);
  if (ratio >= 0.75) return "text-dark-red";
  if (ratio >= 0.50) return "text-dark-yellow";
  return "";
}
```

应用于 duration 和 cost 文本。

## 8. WebSocket 接入

复用 `lib/ws/executions/executionWsClient.ts`，不修改其核心逻辑。

```typescript
// hooks/useObservationStream.ts
export function useObservationStream(executionId: string | null) {
  // 订阅 executionWsClient
  // callback 中过滤 frame.channel === "observation"
  // 转发给 ObservationDataContext.handleObservationEvent
}
```

observation frame 通过同一 WS 连接到达，与 execution event 混合传输，hook 层按 `channel` 字段分流。

## 9. 调试运行触发

### Builder 接入

```
AgentBuilder.tsx
  ├── BuilderCanvas
  ├── PropertiesPanel
  └── DebugPanel (新)
        ├── DebugToolbar        # "调试"按钮 + prompt 输入 + 历史 trace 下拉
        └── ObservationPanel    # 从 components/observation/ 导入
```

`DebugPanel` 调用 `POST /api/v1/executions/debug`，获取 `execution_id`，传给 `ObservationPanel`。

### 历史回看

`GET /api/v1/traces?agent_version_id=...` 列出历史 trace。
`GET /api/v1/traces/{traceId}/observations` 加载扁平列表 → `buildTraceTree` 一次性构建。

## 10. 删除 + 迁移

### 删除

| 路径 | 说明 |
|---|---|
| `components/execution/` 整个目录 | 旧 trace viewer |
| `editors/graph-builder/stores/execution/executionStore.ts` | 旧执行 store |
| `editors/graph-builder/lib/tree-building.ts` | 旧树构建 |

### 保留

| 路径 | 说明 |
|---|---|
| `components/executions/` | 简单事件流 viewer（threads/tasks 继续用） |
| `hooks/use-execution-stream.ts` | threads/tasks 的 WS hook |
| `lib/ws/executions/` | WS 基础设施 |

### 引用迁移

| 引用旧组件的文件 | 改动 |
|---|---|
| Builder 内引用 `ExecutionPanelNew` | 改为 `DebugPanel` + `ObservationPanel` |
| Builder 内引用 `executionStore` | 删除引用 |
| `app/executions/[executionId]/page.tsx` | 改用 `components/executions/execution-viewer.tsx` |
| threads 页面引用 `ExecutionPanelNew` | 改用 `components/executions/execution-viewer.tsx` |

## 11. v1 显式不做

| 功能 | 说明 |
|---|---|
| Agent Graph View (DAG) | 需要额外 API + ReactFlow |
| Score/Annotation | 调试场景不需要 |
| Log View | 按时间排列的日志视图 |
| JSON Beta viewer | 虚拟化 JSON 查看器 |
| 内联评论 | 不做 |
| Level 过滤 | v1 显示所有 level |
| Web Worker 解析 | v1 主线程解析，大 trace 时再优化 |
