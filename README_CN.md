<!-- Logo 图片占位符 - 当 docs/assets/logo.png 可用时添加 -->
<!-- <p align="center">
  <img src="docs/assets/logo.png" alt="JoySafeter" width="120" />
</p> -->

<h1 align="center">JoySafeter</h1>

<p align="center">
  <strong>3分钟生成生产级 Agent 的平台 | 信息安全 SOTA 效果的数字员工</strong>
</p>

<p align="center">
  企业级智能安全体编排平台，基于 LangGraph 构建可视化工作流
</p>

<p align="center">
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-1.0+-FF6F00?logo=chainlink&logoColor=white" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.122+-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-Protocol-purple" alt="MCP Protocol"></a>
</p>

<p align="center">
  <a href="./README.md">English</a> | 简体中文
</p>

<p align="center">
  <a href="#功能特性">功能特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#路线图">路线图</a> •
  <a href="#文档">文档</a> •
  <a href="#贡献指南">贡献指南</a>
</p>

<!-- 截图占位符 - 当 docs/assets/screenshot-builder.png 可用时添加 -->
<!-- <p align="center">
  <img src="docs/assets/screenshot-builder.png" alt="Agent 构建器截图" width="800" />
</p> -->

## 目录

- [为什么选择 JoySafeter？](#为什么选择-joysafeter)
- [功能特性](#功能特性)
- [架构设计](#架构设计)
- [最近更新日志](#最近更新日志)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [路线图](#路线图)
- [竞品对比](#竞品对比)
- [文档](#文档)
- [贡献指南](#贡献指南)
- [许可证](#许可证)
- [致谢](#致谢)

---

## 为什么选择 JoySafeter？

> **JoySafeter 不仅是一个提效工具，更是安全能力的「操作系统」**
> 它通过可视化的智能编排，将割裂的安全工具统合为协同的 AI 军团，将个人的专家经验沉淀为组织的数字资产，率先在行业内定义了 **AI 驱动安全运营（AISecOps）** 的新范式。

### 项目背景

通用 LLM 在安全等专业领域准确率不足，且对安全任务的理解不深入，安全场景无法通过单 Agent 来解决，导致大模型在信息安全领域难以落地。信息安全场景对抗性强且安全趋势持续变化，如何在 Agent 运行过程中持续积累安全经验让 Agent 越用越聪明，是整个行业面临的挑战。

JoySafeter 通过 Multi-Agent 协作、认知进化引擎、场景化战力速配，实现了安全能力的规模化运营。

<table>
<tr>
<td width="50%">

### 面向企业安全团队

- **可视化开发** — 无代码 Agent 构建器，快速原型验证
- **200+ 安全工具** — 预集成 Nmap、Nuclei、Trivy 等主流工具
- **治理与审计** — 全链路执行追踪与可观测性
- **多租户隔离** — 基于角色的工作区隔离

</td>
<td width="50%">

### 面向 AI 安全研究者

- **图编排工作流** — 支持循环、条件、并行的复杂控制流
- **记忆进化** — 长短期记忆机制，持续学习积累
- **MCP 协议** — 模型上下文协议，无限工具扩展性
- **DeepAgents 模式** — 多层级 Agent 协作编排

</td>
</tr>
</table>

---

## 双模式驱动，满足不同场景需求

JoySafeter 提供两种工作模式，适配从快速验证到深度定制的全场景需求：

<table>
<tr>
<td width="50%">

### ⚡ 快速模式（Rapid Mode）

**一句话定位**：描述需求 → 平台自动编排 Skills → 自动组队 → 分钟级发布

**核心价值**：
- 🚀 **零门槛启动**：自然语言描述需求，AI 自动理解并编排
- 🎯 **智能速配**：平台自动匹配最优 Skills 组合，构建专业 Agent 团队
- ⏱️ **分钟级交付**：从需求到可运行 Agent，3-5 分钟完成部署
- 🔄 **开箱即用**：内置 10+ 核心安全场景模板，一键启用

**适用场景**：
- 快速安全评估与漏洞扫描
- 标准化安全检测流程
- 新手快速上手验证
- 紧急安全事件响应

</td>
<td width="50%">

### 🎨 深度模式（Deep Mode）

**一句话定位**：可视化编排 → 调试 → 可观测 → 持续迭代，打造专业团队协作模式

**核心价值**：
- 🏗️ **可视化编排**：拖拽式构建复杂工作流，11 种节点类型，支持循环、条件、并行
- 🔍 **全链路调试**：实时执行追踪、状态可视化、断点调试，精准定位问题
- 📊 **企业级可观测**：Langfuse 集成，完整的执行链路追踪与性能分析
- 🔄 **持续迭代优化**：版本控制、A/B 测试、记忆进化，让 Agent 越用越聪明

**适用场景**：
- 复杂多步骤安全研究任务
- 定制化安全检测流程
- 企业级安全运营平台
- 专业安全团队协作

</td>
</tr>
</table>

---

## 功能特性

### 核心价值主张

<table>
<tr>
<td align="center" width="25%">
<h4>智能团队编排</h4>
<strong>自动化构建 Multi-Agent 作战分队</strong><br/>
实现任务的智能拆解与协同攻坚，将复杂安全任务分解为专业化 Agent 团队协作
</td>
<td align="center" width="25%">
<h4>认知进化引擎</h4>
<strong>持续学习的安全智能体</strong><br/>
基于长短期记忆机制，自动沉淀攻防实战中的"隐性知识"，实现安全能力的持续自我迭代与进化
</td>
<td align="center" width="25%">
<h4>场景化战力速配</h4>
<strong>开箱即用的实战场景库</strong><br/>
预置渗透测试、APK深度挖掘、MCP合规扫描等场景，复刻 DeepResearch 工作流精度达 95%+
</td>
<td align="center" width="25%">
<h4>技能矩阵中台</h4>
<strong>模块化安全能力复用</strong><br/>
预置 10+ 核心安全 Skills 及 200+ 工具链，实现安全能力的模块化复用与积木式组装
</td>
</tr>
</table>

### 技术能力矩阵

<table>
<tr>
<td align="center" width="25%">
<h4>可视化编排引擎</h4>
<sub>ReactFlow 驱动的拖拽式工作流构建器，11 种节点类型，支持复杂控制流</sub>
</td>
<td align="center" width="25%">
<h4>MCP 工具协议</h4>
<sub>模型上下文协议，无缝集成 200+ 安全工具和自定义 API</sub>
</td>
<td align="center" width="25%">
<h4>渐进式技能系统</h4>
<sub>Token 高效的技能披露机制，按需加载，支持 200+ 技能扩展</sub>
</td>
<td align="center" width="25%">
<h4>实时流式通信</h4>
<sub>SSE 服务端推送，全链路实时可观测，提供执行状态、性能指标、错误追踪的完整视图</sub>
</td>
</tr>
<tr>
<td align="center" width="25%">
<h4>企业级可观测性</h4>
<sub>Langfuse 集成，完整的执行链路追踪、监控和性能分析能力</sub>
</td>
<td align="center" width="25%">
<h4>多租户工作区</h4>
<sub>细粒度权限控制和 RBAC，支持企业级工作区隔离与协作</sub>
</td>
<td align="center" width="25%">
<h4>人机协作机制</h4>
<sub>工作流中断和恢复，人工审批检查点，支持复杂决策流程</sub>
</td>
<td align="center" width="25%">
<h4>沙箱执行环境</h4>
<sub>安全的 Python 代码执行环境，支持自定义函数节点与动态代码生成</sub>
</td>
</tr>
</table>

### 创新技术亮点

#### 1. 可视化编排引擎

基于 **ReactFlow** 的拖拽式界面：
- **11 种节点类型**: Agent、控制流、动作、数据、聚合
- **实时预览**: 构建时实时查看图结构
- **自动布局**: 自动节点定位和边路由
- **边配置**: 条件边、循环回边、路由键
- **验证**: 实时图结构验证

**核心能力：**
- 企业级可视化工作流设计，无需编码即可构建复杂安全任务流程
- 强大的控制流引擎，支持循环迭代、条件分支、并行执行与结果聚合
- DeepAgents 模式可视化，Manager-Worker 星型拓扑架构，实现多智能体协同
- 上下文变量管理与状态传递，支持复杂工作流的状态共享
- 图版本控制与部署管理，支持工作流的版本回滚与历史追踪

#### 2. DeepAgents 多智能体协作

**Manager-Worker 星型拓扑**实现复杂任务分解：

- **自动检测**: 系统自动检测 `useDeepAgents` 配置
- **星型拓扑**: Manager 直接连接到所有 SubAgents（非链式）
- **共享后端**: Docker 后端在多个 Agent 间共享，优化资源使用
- **技能预加载**: 执行前将技能预加载到 `/workspace/skills/`
- **任务委托**: Manager 使用 `task()` 工具协调 SubAgents

**应用场景：**
- 复杂多步骤安全研究任务，需要专业 Agent 团队协同攻坚
- 大规模安全分析工作流，涉及多个专业领域的深度分析
- 并行任务处理与结果聚合，提升整体执行效率
- 分层决策与任务委派场景，实现智能化的任务分发与协调

#### 3. 渐进式技能披露

**Token 高效的技能系统**，减少上下文窗口使用：

| 组件 | 功能 |
|------|------|
| **SkillService** | 技能 CRUD、权限控制、标签分类管理 |
| **SkillsMiddleware** | Agent 中间件，自动注入技能描述到系统提示（使用 deepagents SkillsMiddleware） |
| **SkillSandboxLoader** | 执行前将技能预加载到 Docker 后端 |
| **FilesystemMiddleware** | Agent 通过文件系统直接读取 `/workspace/skills/{skill_name}/` 目录下的技能文件 |
| **渐进披露** | 先展示技能摘要，需要时再加载完整内容，节省 Token 消耗 |

**核心优势：**
- **Token 高效优化**: 渐进式技能披露机制，仅在需要时加载完整技能内容，大幅降低上下文窗口占用
- **企业级可扩展性**: 支持 200+ 技能扩展而不会导致上下文溢出，满足大规模安全能力矩阵需求
- **高性能访问**: 技能预加载到 Docker 后端，实现毫秒级技能内容访问，提升 Agent 执行效率
- **动态能力发现**: Agent 可动态发现和使用技能，实现安全能力的灵活组合与按需调用

#### 4. 长短期记忆系统

跨会话的**持久化记忆**，实现持续学习：

- **记忆类型**: Fact（事实）、Procedure（过程）、Episodic（情景）、Semantic（语义）
- **检索方法**: Last N、First N、Agentic 检索
- **记忆中间件**: 自动记忆注入和存储
- **基于主题的组织**: 记忆按主题组织，高效检索
- **重要性评分**: 记忆按重要性和相关性排序

**记忆流程：**
1. **模型前记忆注入**: 智能检索相关记忆并注入到系统提示，为 Agent 提供上下文感知能力
2. **模型后记忆沉淀**: 自动将用户输入和 Agent 响应存储为新记忆，实现知识资产的持续积累
3. **持续进化学习**: 记忆系统随时间不断优化，Agent 性能持续提升，实现安全能力的自我迭代

#### 5. 可扩展中间件架构

**策略模式**实现易于扩展的中间件：

- **优先级系统**: 按优先级顺序执行中间件（0-100）
- **错误隔离**: 失败的中间件不影响其他中间件
- **策略解析器**: 易于添加新的中间件类型
- **向后兼容**: 新功能不影响现有代码

**内置中间件：**
- **SkillMiddleware**（优先级: 50）: 智能技能注入中间件，自动将技能描述注入到 Agent 系统提示中
- **MemoryMiddleware**（优先级: 50）: 记忆检索与存储中间件，实现跨会话的持久化记忆管理
- **TaggingMiddleware**（优先级: 100）: 可观测性与监控中间件，提供全链路执行追踪与性能分析能力

#### 6. AI Copilot 图构建助手

**智能助手**辅助图构建：

- **拓扑分析**: 分析当前图结构
- **智能推荐**: 建议节点和连接
- **DeepAgents 指导**: 为多智能体工作流提供架构指导
- **自动定位**: 计算最优节点位置
- **验证**: 验证图结构并建议改进

**核心能力：**
- 自然语言驱动的图创建，将需求描述自动转换为可视化工作流
- 多智能体团队设计智能辅助，提供架构指导与角色分配建议
- 工作流拓扑分析与优化建议，提升执行效率与资源利用率
- 最佳实践自动执行，确保工作流设计符合行业标准与安全规范

### 技术亮点

#### 1. 高级路由系统

**灵活的控制流**，支持多种路由模式：

- **条件路由**: 二元条件（true/false）
- **多规则路由**: 带优先级规则的路由器节点
- **循环控制**: forEach、while、doWhile 模式
- **并行执行**: Fan-Out/Fan-In 与聚合器
- **Command 模式**: 可选的 Command 对象支持，用于显式路由

**边配置：**
- **普通边**: 顺序流
- **条件边**: 基于路由的分支
- **循环回边**: 带状态隔离的循环控制

#### 2. SSE 实时通信

**标准化事件信封**实现可靠的流式输出：

```typescript
interface StreamEventEnvelope {
  type: 'content' | 'tool_start' | 'tool_end' | 'status' | 'error' | 'done';
  node_name: string;      // 当前执行的节点
  run_id: string;         // 按执行运行分组事件
  timestamp: number;      // 事件时间戳
  thread_id: string;      // 对话线程
  data: any;              // 事件特定数据
}
```

**特性：**
- **run_id 分组**: 将同一执行运行的事件分组
- **node_name 追踪**: 显示哪个 Agent/节点正在执行
- **增量更新**: 基于 Delta 的内容更新
- **错误处理**: 优雅的错误传播

#### 3. MCP 工具集成

**原生 MCP 协议支持**，预集成 200+ 工具：

- **工具注册表**: 统一的工具管理和注册
- **多服务器支持**: 连接到多个 MCP 服务器
- **工具分类**: 网络扫描、Web 安全、二进制分析、容器安全、云安全、攻击策略、知识库
- **自定义工具**: 使用自定义工具实现扩展
- **工具发现**: 从 MCP 服务器自动发现工具

**工具执行：**
- 直接 MCP 协议通信
- 工具结果缓存和错误处理
- 支持异步工具执行
- 工具元数据和文档

### 安全能力矩阵

| 分类 | 工具数量 | 核心能力 |
|------|----------|----------|
| **网络扫描** | 15+ | Nmap、Masscan、ZMap、端口发现 |
| **Web 安全** | 14+ | SQLi、XSS、SSRF、认证测试 |
| **漏洞扫描** | 5+ | Nuclei、Nikto、CVE 检测 |
| **二进制分析** | 14+ | Ghidra、radare2、angr、JEB APK 分析 |
| **容器安全** | 7+ | Trivy、Clair、Docker 镜像扫描 |
| **云安全** | 4+ | Prowler、ScoutSuite、AWS/GCP 审计 |
| **攻击策略** | 90+ | 攻击链生成、风险评估 |
| **知识库** | 115+ | 安全知识 YAML 模式 |

---

## 架构设计

详细的架构设计，包括核心模块、工作流程和数据流，请参考 [架构设计文档](docs/ARCHITECTURE_CN.md)。

---



## 最近更新日志

### 核心能力 (Core Capabilities)
- **元认知超能力 (Meta-Cognitive Superpowers)** (`57fdac5`): 引入了包括头脑风暴 (Brainstorming)、战略规划 (Writing Plans) 和执行 (Executing Plans) 在内的结构化推理能力。通过将 "思考过程" 形式化为可执行的语义技能，将 Agent 从简单的任务执行提升到解决复杂问题的层面。
- **可扩展技能协议 (Extensible Skill Protocol)** (`cada4d3`): 确立了包含 "渐进式披露 (Progressive Disclosure)" 架构的 `SKILL.md` 标准。该机制通过按需动态加载技能元数据、指令和资源，极大优化了上下文窗口 (Context Window) 的利用率，使 Agent 成为一个能力无限扩展的平台。

### 系统架构 (System Architecture)
- **多租户沙箱引擎 (Multi-Tenant Sandbox Engine)** (`7aa24c8`): 实现了代码执行环境的严格用户级隔离。这一企业级安全特性保证了数据主权，彻底防止了并发用户会话之间的状态泄露。
- **白盒可观测性 (Glass-Box Observability)** (`f5a8a16`): 集成了基于 Langfuse 的深度执行追踪可视化。用户现在可以实时观察 Agent 的决策过程和状态流转，为 Agent 的 "思维过程" 提供了完全的透明度。

### 优化与基础设施 (Optimization & Infrastructure)
- **安全运行时迁移** (`420da8f`): 废弃了遗留的不安全执行路径，强制所有动态代码操作使用新的沙箱架构，提升了系统的整体安全性。
- **企业身份集成** (`9583309`): 标准化了单点登录 (SSO) 协议，修正了命名规范并增加了对 `jd` 提供商的支持，确保了企业身份管理的无缝集成。
- **核心内核升级** (`4390ae5`): 将 `deepagents` 核心库升级至 v0.3.11，引入了最新的稳定性改进和性能优化。
---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js 16, React 19, TypeScript | 服务端渲染, App Router |
| **UI 组件** | Radix UI, Tailwind CSS, Framer Motion | 无障碍、动画组件 |
| **状态管理** | Zustand, TanStack Query | 客户端与服务端状态 |
| **图可视化** | React Flow | 交互式节点编辑器 |
| **后端** | FastAPI, Python 3.12+ | 异步 API，OpenAPI 文档 |
| **AI 框架** | LangChain 1.2+, LangGraph 1.0+, DeepAgents | Agent 编排与工作流 |
| **MCP 集成** | mcp 1.20+, fastmcp 2.14+ | 工具协议支持 |
| **数据库** | PostgreSQL, SQLAlchemy 2.0 | 异步 ORM，数据库迁移 |
| **缓存** | Redis | 会话缓存与限流 |
| **可观测性** | Langfuse, Loguru | 追踪与结构化日志 |

---

## 快速开始

### 环境要求

| 依赖 | 版本 |
|------|------|
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| Python | 3.12+（本地开发需要） |
| Node.js | 20+（本地开发需要） |
| PostgreSQL | 15+（不使用 Docker 时需要） |
| Redis | 7+（不使用 Docker 时需要） |

### 一键部署（Docker）- 推荐

### 方案一：一键运行

```bash
# 一键初始化环境 & 本地构建镜像 & 自动启动
sh deploy/quick-start.sh
```

### 方案二：手动部署

```bash
cd deploy

# 1. 编译镜像
sh deploy.sh build --all

# 2. 初始化环境变量
cp ../frontend/env.example ../frontend/.env
cp ../backend/env.example ../backend/.env

# 重要！！配置 TAVILY_API_KEY 搜索所用 key（自行注册 https://www.tavily.com/）
# 请将 tvly-* 替换为您实际的 API Key
echo 'TAVILY_API_KEY=tvly-*' >> ../backend/.env

# 3. 初始化数据库
docker compose --profile init up

# 4. 启动服务
docker compose -f docker-compose.yml up

# 关闭服务
docker compose -f docker-compose.yml down

docker compose logs 
```

### 手动安装

<details>
<summary><strong>后端安装</strong></summary>

```bash
cd backend

# 安装 uv 包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建环境并安装依赖
uv venv && source .venv/bin/activate
uv sync

# 配置环境变量
cp env.example .env
# 编辑 .env 文件配置参数

# 初始化数据库
createdb joysafeter
alembic upgrade head

# 启动服务
uv run uvicorn app.main:app --reload --port 8000
```

</details>

<details>
<summary><strong>前端安装</strong></summary>

```bash
cd frontend

# 安装依赖
bun install  # 或: npm install

# 配置环境变量
cp env.example .env.local

# 启动开发服务器
bun run dev
```

</details>

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

---

## 路线图

### 已完成

- [x] 基于 LangGraph 的图编排引擎
- [x] 可视化 Agent 构建器（11 种节点类型）
- [x] MCP 工具协议集成
- [x] 200+ 安全工具 handlers
- [x] Multi-Agent 编排 (DeepAgents)
- [x] 长短期记忆系统
- [x] 技能系统 (Skill System)
  - 渐进式技能披露机制
  - SkillsMiddleware 技能注入中间件（使用 deepagents SkillsMiddleware）
  - 直接文件系统访问加载技能（Agent 通过 FilesystemMiddleware 从 `/workspace/skills/` 读取）
- [x] 可扩展中间件架构（日志、标签、上下文增强）
- [x] 沙箱执行自定义 Python 代码
- [x] SSE 实时流式输出
- [x] 多租户工作区隔离
- [x] Langfuse 可观测性集成
- [x] Docker 部署方案
- [x] RBAC 权限控制
- [x] API Key 管理

### 进行中

- [ ] 单元测试补充（目标 80%+）
- [ ] API 文档完善
- [ ] 中英文用户指南
- [ ] 开发者文档

### 计划中

- [ ] MCP 工具市场
- [ ] 多模型支持扩展（Claude, Gemini, 开源模型）
- [ ] 中间件缓存机制
- [ ] 图编译性能优化
- [ ] 企业案例展示
- [ ] 社区插件生态

---

## 竞品对比

| 特性 | JoySafeter | Dify | Flowise | n8n | Coze |
|------|------------|------|---------|-----|------|
| **安全专注** | 原生支持 | - | - | - | - |
| **LangGraph 原生** | 是 | 否 | 否 | 否 | 否 |
| **Multi-Agent (DeepAgents)** | 是 | 有限 | 否 | 否 | 有限 |
| **MCP 协议** | 是 | 否 | 否 | 否 | 否 |
| **200+ 安全工具** | 是 | 否 | 否 | 否 | 否 |
| **技能系统** | 是 | 否 | 否 | 否 | 否 |
| **记忆进化** | 是 | 基础 | 基础 | 否 | 基础 |
| **开源协议** | Apache 2.0 | Apache 2.0 | Apache 2.0 | Fair-code | 闭源 |
| **私有化部署** | 是 | 是 | 是 | 是 | 否 |
| **循环/并行控制** | 高级 | 基础 | 基础 | 是 | 有限 |
| **企业级 RBAC** | 是 | 是 | 有限 | 是 | 是 |

---
=
---

## 文档

| 文档 | 说明 |
|------|------|
| [分层架构图](docs/layered-architecture.md) | 从展示层到基础设施层的完整7层架构概览 |
| [图构建器架构](docs/GRAPH_BUILDER_ARCHITECTURE.md) | 完整的系统设计、数据流和节点类型参考 |
| [中间件架构](docs/middleware-architecture-complete.md) | 使用策略模式的可扩展中间件系统 |
| [MCP 技能集成](docs/mcp-skills-integration.md) | MCP 工具转技能及集成指南 |
| [SSE 协议迁移](docs/sse-protocol-migration.md) | 实时流式协议和事件结构 |
| [LangGraph 改进总结](docs/langgraph-improvements-summary.md) | 状态分离和 Command 模式增强 |
| [后端指南](backend/README.md) | API 参考与后端配置 |
| [前端指南](frontend/README.md) | 组件库与状态管理 |
| [Docker 部署指南](deploy/README.md) | 完整的部署指南，包含安装脚本、场景说明和故障排查 |
| [开发指南](DEVELOPMENT.md) | 本地开发环境搭建和工作流程 |
| [贡献指南](CONTRIBUTING.md) | 如何参与项目贡献 |
| [Pre-commit 设置](.pre-commit-setup.md) | 代码质量检查与 Git Hooks 配置 |
| [安全策略](SECURITY.md) | 安全策略与漏洞报告 |
| [行为准则](CODE_OF_CONDUCT.md) | 社区行为规范 |

---

## 贡献指南

我们欢迎社区贡献！详情请查看 [贡献指南](CONTRIBUTING.md)。

```bash
# Fork 并克隆
git clone https://github.com/jd-opensource/JoySafeter.git

# 创建功能分支
git checkout -b feature/amazing-feature

# 提交更改
git commit -m 'feat: add amazing feature'

# 推送并创建 PR
git push origin feature/amazing-feature
```
---

## 许可证

本项目采用 **Apache License 2.0** 开源协议 — 详见 [LICENSE](LICENSE) 文件。

> **注意：** 本项目包含不同许可证的第三方组件，详见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。

---

## 致谢

<table>
<tr>
<td align="center"><a href="https://github.com/langchain-ai/langchain"><img src="https://avatars.githubusercontent.com/u/126733545?s=64" width="48"/><br/><sub>LangChain</sub></a></td>
<td align="center"><a href="https://github.com/langchain-ai/langgraph"><img src="https://avatars.githubusercontent.com/u/126733545?s=64" width="48"/><br/><sub>LangGraph</sub></a></td>
<td align="center"><a href="https://fastapi.tiangolo.com/"><img src="https://fastapi.tiangolo.com/img/icon-white.svg" width="48"/><br/><sub>FastAPI</sub></a></td>
<td align="center"><a href="https://nextjs.org/"><img src="https://assets.vercel.com/image/upload/v1662130559/nextjs/Icon_dark_background.png" width="48"/><br/><sub>Next.js</sub></a></td>
<td align="center"><a href="https://www.radix-ui.com/"><img src="https://avatars.githubusercontent.com/u/75042455?s=64" width="48"/><br/><sub>Radix UI</sub></a></td>
</tr>
</table>

---

<p align="center">
  <sub>由 JoySafeter 团队用 ❤️ 打造</sub>
</p>

---

<p align="center">
  <sub>如需咨询商业方案，请联系京东科技解决方案团队，联系方式：<a href="mailto:org.ospo1@jd.com">org.ospo1@jd.com</a></sub>
</p>
