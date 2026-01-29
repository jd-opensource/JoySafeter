# LoopBack 边使用说明

## 概述

LoopBack 边是用于循环工作流中的特殊边类型，用于表示从循环体返回到循环条件节点的连接。这种边在视觉上使用紫色虚线样式，以区别于普通边和条件边。

## 前端使用

### 1. 自动检测 LoopBack 边

当用户连接 `loop_condition_node` 时，系统会自动检测并标记 LoopBack 边：

```typescript
// 在 builderStore.ts 的 onConnect 中
if (sourceType === 'loop_condition_node') {
  // 如果 route_key 是 'continue_loop' 且满足以下条件之一，则标记为 loop_back：
  // 1. source == target（自循环）
  // 2. target 节点在 source 节点左边（向后连接）
  if (defaultRouteKey === 'continue_loop' && connection.source === connection.target) {
    edgeType = 'loop_back'
  } else if (defaultRouteKey === 'continue_loop') {
    const sourceNode = nodes.find((n) => n.id === connection.source)
    const targetNode = nodes.find((n) => n.id === connection.target)
    if (sourceNode && targetNode && targetNode.position.x < sourceNode.position.x) {
      edgeType = 'loop_back'
    }
  }
}
```

### 2. 手动设置 LoopBack 边

用户也可以在边的属性面板中手动设置边类型为 "Loop Back"：

```typescript
// EdgePropertiesPanel.tsx
<SelectItem value="loop_back">Loop Back</SelectItem>
```

### 3. 视觉样式

LoopBack 边使用 `LoopBackEdge` 组件渲染，具有以下特征：

- **颜色**：紫色 (#9333ea)
- **线宽**：2.5px
- **样式**：虚线 (strokeDasharray: "5,5")
- **路径**：使用 Manhattan Routing（正交路径），只包含水平和垂直段
- **可拖拽控制点**：支持调整垂直通道和左右段的偏移量

## 后端处理

### 1. 数据存储

LoopBack 边的信息存储在 `GraphEdge.data` 字段中：

```python
{
  "edge_type": "loop_back",
  "route_key": "continue_loop",  # 对于循环条件节点，必须是 continue_loop
  "source_handle_id": "...",  # 可选
  "label": "...",  # 可选
  "offsetY": 0,  # LoopBack 边的垂直偏移（前端使用）
  "leftOffsetX": 0,  # LoopBack 边的左段偏移（前端使用）
  "rightOffsetX": 0,  # LoopBack 边的右段偏移（前端使用）
}
```

### 2. 图构建

在 `langgraph_model_builder.py` 中，LoopBack 边被识别为 `continue_loop` 路由：

```python
def _build_conditional_edges_for_loop(self, ...):
    for edge in self.edges:
        if edge.source_node_id == loop_node.id:
            edge_data = edge.data or {}
            route_key = edge_data.get("route_key", "default")
            edge_type = edge_data.get("edge_type", "normal")

            # 验证：continue_loop 边应该是 loop_back 类型
            if route_key == "continue_loop" and edge_type not in ["loop_back", "conditional", "normal"]:
                logger.warning(...)

            # 映射 continue_loop 和 exit_loop
            if route_key in ["continue_loop", "exit_loop"]:
                conditional_map[route_key] = target_name
```

### 3. 循环体识别

后端通过 `_identify_loop_bodies()` 方法识别循环体节点：

```python
def _identify_loop_bodies(self) -> Dict[str, str]:
    """识别循环体节点。

    通过分析图结构，找到所有循环条件节点的 continue_loop 边指向的节点。
    """
    loop_bodies = {}

    for loop_node in self.nodes:
        if self._get_node_type(loop_node) == "loop_condition_node":
            loop_node_name = self._get_node_name(loop_node)

            # 找到 continue_loop 边指向的节点（循环体）
            for edge in self.edges:
                if edge.source_node_id == loop_node.id:
                    edge_data = edge.data or {}
                    if edge_data.get("route_key") == "continue_loop":
                        target_node = self._node_map.get(edge.target_node_id)
                        if target_node:
                            target_node_name = self._get_node_name(target_node)
                            loop_bodies[target_node_name] = loop_node_name

    return loop_bodies
```

## 典型循环工作流结构

```
[Loop Condition] --continue_loop--> [Loop Body] --loop_back--> [Loop Condition]
                |
                --exit_loop--> [Exit Node]
```

### 节点说明

1. **Loop Condition Node**：循环条件节点
   - 类型：`loop_condition_node`
   - 配置：`conditionType` (forEach/while/doWhile), `condition`, `maxIterations`
   - 出边：
     - `continue_loop` → Loop Body（通常是 loop_back 类型）
     - `exit_loop` → Exit Node

2. **Loop Body Node**：循环体节点
   - 类型：通常是 `agent` 或其他可执行节点
   - 入边：来自 Loop Condition 的 `continue_loop` 边
   - 出边：返回到 Loop Condition 的边（自动标记为 loop_back）

3. **Exit Node**：退出节点
   - 类型：通常是 `agent` 或其他可执行节点
   - 入边：来自 Loop Condition 的 `exit_loop` 边

## 数据流

### 保存流程

1. 前端用户在画布上创建循环工作流
2. 系统自动检测或用户手动设置 LoopBack 边
3. 保存时，边的 `data` 字段（包括 `edge_type: "loop_back"`）被保存到数据库

```typescript
// 前端保存
await agentService.saveGraph({
  nodes: [...],
  edges: [
    {
      source: "loop_condition_id",
      target: "loop_body_id",
      data: {
        edge_type: "loop_back",
        route_key: "continue_loop",
      }
    }
  ]
})
```

```python
# 后端保存（graph_service.py）
edge_create_data = {
    "graph_id": graph_id,
    "source_node_id": source_node_id,
    "target_node_id": target_node_id,
    "data": edge_data_payload,  # 包含 edge_type, route_key 等
}
```

### 加载流程

1. 后端从数据库加载边数据（包括 `data` 字段）
2. 根据 `edge_type` 设置正确的样式和 ReactFlow 类型
3. 前端恢复边的视觉样式和元数据

```python
# 后端加载（graph_service.py）
edge_data = edge.data or {}
edge_type = edge_data.get("edge_type", "normal")

if edge_type == "loop_back":
    edge_style = {
        "stroke": "#9333ea",
        "strokeWidth": 2.5,
        "strokeDasharray": "5,5",
    }
    edge_type_for_reactflow = "loop_back"
```

## 注意事项

1. **LoopBack 边必须是 `continue_loop` 路由**：只有从 Loop Condition 到 Loop Body 的 `continue_loop` 边才应该标记为 `loop_back`。

2. **自动检测的局限性**：自动检测基于节点位置（target 在 source 左边），可能不适用于所有情况。用户可以在属性面板中手动调整。

3. **后端兼容性**：后端接受 `loop_back`、`conditional` 或 `normal` 类型的 `continue_loop` 边，但建议使用 `loop_back` 以保持一致性。

4. **循环体识别**：后端通过 `route_key == "continue_loop"` 来识别循环体，而不是通过 `edge_type`。`edge_type` 主要用于前端显示。

## 修复的问题

### 问题 1：后端未保存边的 data 字段

**修复前**：
```python
edge_create_data = {
    "graph_id": graph_id,
    "source_node_id": source_node_id,
    "target_node_id": target_node_id,
    # 缺少 data 字段
}
```

**修复后**：
```python
edge_data_payload = edge_data.get("data", {}) or {}

edge_create_data = {
    "graph_id": graph_id,
    "source_node_id": source_node_id,
    "target_node_id": target_node_id,
    "data": edge_data_payload,  # 保存边的元数据
}
```

### 问题 2：后端未恢复边的 data 字段

**修复前**：
```python
frontend_edge = {
    "source": source_id,
    "target": target_id,
    # 缺少 data 字段和样式设置
    "style": {...},  # 固定样式
}
```

**修复后**：
```python
edge_data = edge.data or {}
edge_type = edge_data.get("edge_type", "normal")

# 根据 edge_type 设置样式
if edge_type == "loop_back":
    edge_style = {...}
    edge_type_for_reactflow = "loop_back"
# ...

frontend_edge = {
    "source": source_id,
    "target": target_id,
    "type": edge_type_for_reactflow,
    "style": edge_style,
    "data": edge_data,  # 恢复边的元数据
}
```

## 总结

LoopBack 边是循环工作流的重要组成部分，用于：

1. **视觉区分**：通过紫色虚线样式，清晰标识循环回边
2. **数据完整性**：保存和恢复边的类型信息，确保前后端一致性
3. **用户体验**：自动检测和手动设置相结合，提供灵活的工作流构建方式

现在，LoopBack 边的数据可以正确保存到数据库，并在加载时正确恢复，确保循环工作流的完整性和一致性。
