# Skill Creator Agent — Design Spec

## Overview

为 JoySafeter 平台新增 **Skill Creator Agent** 功能：用户通过独立的对话界面与 AI Agent 交互，Agent 在 Docker 沙箱中自动生成 SKILL.md + 辅助文件并验证，用户预览确认后同步到数据库。

## Goals

1. 用户通过自然语言对话即可创建/修改完整的 Skill 包（SKILL.md + scripts/references/assets）
2. Agent 在隔离沙箱中生成和验证 Skill，确保质量
3. 用户预览确认后才写入 DB，保证用户控制权
4. 复用现有 Chat SSE 架构和 Sandbox 基础设施，最小化代码改动
5. 在 Dashboard 首页提供显眼入口

## Non-Goals

- Skill 市场/分享功能
- 实时在线编辑器（预览面板只读）
- 自动发布到其他用户

---

## Architecture

### 整体流程

```
用户在前端 Skill Creator 页面发起对话
    │
    ▼
POST /v1/chat/stream (mode="skill_creator")
    │  → GraphService 创建专用 Skill Creator Graph
    │  → SandboxManager 确保沙箱运行
    │  → 预加载 skill-creator Skill 到沙箱
    │  → (若 edit_skill_id) 预加载目标 Skill 到沙箱
    ▼
Agent 在沙箱中执行:
    1. 多轮对话理解用户需求
    2. 调用 init_skill.py 初始化目录结构
    3. 编写 SKILL.md + 辅助文件 (scripts/, references/, assets/)
    4. 调用 quick_validate.py 验证
    5. 调用 preview_skill tool 输出结构化结果
    ▼
SSE 流式返回生成过程
    │  前端捕获 preview_skill 的 tool_end 事件
    ▼
前端展示 Skill 预览面板 (文件树 + 内容高亮)
    │  用户确认 "保存到库"
    ▼
前端调用 POST /v1/skills (新建) 或 PUT /v1/skills/{id} (修改)
    │  → SkillService 解析 SKILL.md frontmatter → 写入 DB
    │  → 自动触发 OpenClaw sync
    ▼
完成
```

### 关键设计决策

1. **DB 同步由前端发起** — Agent 不直接写 DB，而是通过 `preview_skill` tool 返回文件内容，前端在用户确认后调用现有 Skills API。保证用户对最终结果的控制权。

2. **复用现有 Chat 流** — 不新建 API 路由，通过 `mode="skill_creator"` 参数让 `/v1/chat/stream` 选择专用 Graph 模板。复用 SSE、Agent 调度、沙箱管理全套基础设施。

3. **复用现有 skill-creator Skill** — 平台已内置 `skill-creator` Skill（含 `init_skill.py`、`package_skill.py`、`quick_validate.py`），Agent 直接使用这些工具。

4. **preview_skill 作为 builtin tool** — 结构化输出 Skill 文件内容和验证结果，前端可直接解析渲染。

---

## Backend Changes

### 1. Chat API 扩展

**文件**: `backend/app/api/v1/chat.py`, `backend/app/schemas/chat.py`

Request body 新增可选字段：

```python
mode: Optional[str] = None          # "skill_creator" 时使用专用 Graph
edit_skill_id: Optional[str] = None  # 修改已有 Skill 时传入
```

处理逻辑：
- `mode="skill_creator"` 且 `graph_id=None` → 调用 `GraphService.create_skill_creator_graph()`
- 若有 `edit_skill_id` → 通过 `SkillSandboxLoader` 预加载该 Skill 到沙箱

### 2. Skill Creator Graph 模板

**文件**: `backend/app/core/graph/graph_builder_factory.py`

新增 `create_skill_creator_graph()` 方法：
- 创建单节点 DeepAgents Graph
- System Prompt 注入 `skill-creator` Skill 完整内容 + Skill 创建流程指令
- 预加载 `skill-creator` Skill 到沙箱
- 注册 `preview_skill` builtin tool

### 3. preview_skill Tool

**文件**: `backend/app/core/tools/` 下新增

功能：从沙箱 `/workspace/skills/{skill_name}/` 读取所有文件，返回结构化 JSON。

```python
# 输入
skill_name: str  # 沙箱中的 skill 目录名

# 输出
{
    "skill_name": "my-skill",
    "files": [
        {
            "path": "SKILL.md",
            "content": "---\nname: my-skill\n...",
            "file_type": "markdown",
            "size": 1234
        },
        {
            "path": "scripts/scan.py",
            "content": "import nmap\n...",
            "file_type": "python",
            "size": 567
        }
    ],
    "validation": {
        "valid": true,
        "errors": [],
        "warnings": ["Description is close to max length"]
    }
}
```

验证逻辑复用 `backend/app/core/skill/validators.py` 中的现有校验函数。

### 4. 不新增的内容

- 不新增 API 路由 — 复用 `/v1/chat/stream` 和 `/v1/skills`
- 不新增 DB 模型 — 复用 `Skill` + `SkillFile` 表
- 不修改 SkillService — 现有 `create_skill` / `update_skill` 已完整支持

---

## Frontend Changes

### 1. Dashboard 入口

在首页 Dashboard 的模式选择区域新增 "Skill Creator" 卡片，与 Rapid Mode / Deep Mode 并列：

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Rapid Mode  │  │  Deep Mode   │  │ Skill Creator│
│  快速对话     │  │  可视化编排   │  │  AI创建/维护  │
│  智能体编排   │  │  工作流构建   │  │  智能体技能   │
└──────────────┘  └──────────────┘  └──────────────┘
```

点击跳转到 `/skills/creator`。

### 2. Skill Creator 页面

**路由**: `/skills/creator`（可选 `?edit={skill_id}`）

**布局**: 左右分栏

```
┌──────────────────────┬──────────────────────────┐
│                      │                          │
│   Chat 对话区域       │   Skill 预览面板          │
│   (复用 Chat 组件)    │   (文件树 + 内容预览)     │
│                      │                          │
│                      │  ┌─ my-skill/            │
│  用户: 帮我创建一个    │  │  SKILL.md ✓           │
│  网络扫描的 Skill     │  │  scripts/             │
│                      │  │    scan.py ✓           │
│  Agent: 好的...      │  ├──────────────────────  │
│                      │  │ [文件内容高亮预览]      │
│  [输入框]            │  ├──────────────────────  │
│                      │  │ [保存到库]  [重新生成]  │
└──────────────────────┴──────────────────────────┘
```

### 3. 组件结构

| 组件 | 职责 |
|------|------|
| `SkillCreatorPage` | 页面容器，管理对话 + 预览状态 |
| `SkillCreatorChat` | 封装现有 Chat 组件，传入 `mode="skill_creator"` |
| `SkillPreviewPanel` | 右侧面板：文件树 + 文件内容预览 |
| `SkillFileTree` | Skill 文件目录树 |
| `SkillFileViewer` | 单文件内容查看，语法高亮 |
| `SkillSaveDialog` | 保存确认对话框 |

### 4. 数据流

1. 用户发消息 → `POST /v1/chat/stream` (mode=skill_creator)
2. SSE 事件流实时渲染到 Chat 区
3. 收到 `tool_end` 事件且 tool=`preview_skill` → 解析 JSON → 更新预览面板
4. 用户点击 "保存到库" → SkillSaveDialog 展示确认
5. 确认 → `POST /v1/skills` (新建) 或 `PUT /v1/skills/{id}` (编辑)

### 5. 其他入口

- Skills 列表页：新增 "AI 创建" 按钮 → `/skills/creator`
- Skill 详情页：新增 "AI 修改" 按钮 → `/skills/creator?edit={skill_id}`

---

## Error Handling

| 场景 | 处理方式 |
|------|----------|
| 沙箱启动失败 | SSE `error` 事件，前端 toast 提示 |
| SKILL.md 格式不合法 | Agent 调用 `quick_validate.py` 自检并自动修复 |
| Skill name 重复 | `POST /v1/skills` 返回 409，前端提示改名或选择覆盖 |
| 用户中途关闭 | 沙箱文件保留，可重新发起 |
| preview_skill 读取空目录 | 返回 validation.valid=false，前端提示未完成 |

## Security

- Agent 只能操作沙箱 `/workspace/skills/` 目录
- `preview_skill` tool 只读，不写 DB
- DB 写入必须经前端用户确认 → 走现有 Skills API（含权限校验）
- 沙箱有 CPU/内存限制（1 CPU, 512MB RAM）

---

## File Change Summary

### Backend (~5 files)

| File | Change |
|------|--------|
| `backend/app/schemas/chat.py` | 新增 `mode`, `edit_skill_id` 字段 |
| `backend/app/api/v1/chat.py` | 处理 `mode="skill_creator"` 逻辑 |
| `backend/app/core/graph/graph_builder_factory.py` | 新增 `create_skill_creator_graph()` |
| `backend/app/core/tools/preview_skill.py` | 新增 `preview_skill` builtin tool |
| `backend/app/core/agent/midware/` | 可能微调 skill 预加载逻辑 |

### Frontend (~6-8 new files)

| File | Type |
|------|------|
| `SkillCreatorPage` | 页面组件 |
| `SkillCreatorChat` | 对话区封装 |
| `SkillPreviewPanel` | 预览面板 |
| `SkillFileTree` | 文件树 |
| `SkillFileViewer` | 文件查看 |
| `SkillSaveDialog` | 保存确认 |
| Dashboard 入口卡片 | 入口组件 |
| 路由配置 | 更新 |
