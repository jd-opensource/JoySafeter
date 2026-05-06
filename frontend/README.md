# JoySafeter Frontend

JoySafeter 的前端应用（Next.js），提供可视化编排与交互式 Web UI。

> 说明：本文件只保留 **前端本地开发** 的最短路径；Docker/生产部署请统一以 `deploy/` 文档为准，避免重复与不一致。

## 快速开始（本地开发）

### 1) 安装依赖

```bash
cd frontend
bun install
```

### 2) 配置环境变量

```bash
cp env.example .env.local
# 按需修改 .env.local（例如 NEXT_PUBLIC_API_URL）
```

### 3) 启动开发服务器

```bash
bun run dev
```

访问：http://localhost:3000

## 架构概述

### 路由结构（App Router）

```
app/
├── (auth)/                       # 认证页面（登录、注册、验证、重置密码）
├── dashboard/                    # 仪表盘
├── agents/[agentId]/             # Agent 详情：编辑、版本、发布、任务、会话
├── executions/[executionId]/     # 执行详情 + 实时追踪
├── tasks/                        # 任务管理
├── skills/                       # 技能市场 + 创建器
├── tools/                        # 工具管理
├── memory/                       # 记忆管理
├── openclaw/                     # OpenClaw 看板
└── settings/                     # 模型、成员、沙箱、Token
```

### 核心模块

| 模块             | 路径                   | 职责                                                                       |
| ---------------- | ---------------------- | -------------------------------------------------------------------------- |
| **API 客户端**   | `lib/api-client.ts`    | 统一 REST 请求（URL 构建、CSRF、401 自动刷新、ErrorDescriptor 提取）       |
| **WebSocket 层** | `lib/ws/`              | BaseWsClient 抽象类 + ExecutionWsClient / NotificationWsClient             |
| **状态管理**     | `stores/`              | Zustand 客户端 Store（执行追踪、侧边栏、编辑器等）                         |
| **服务端状态**   | hooks + TanStack Query | 缓存 + 失效（agents、skills、models 等）                                   |
| **错误消费**     | `ApiError` class       | 镜像后端 ErrorDescriptor：`source`、`retryable`、`userAction` 驱动 UI 行为 |

> 完整架构文档：[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | [中文版](../docs/ARCHITECTURE_CN.md)

## 常用脚本

```bash
bun run dev
bun run build
bun run start
bun run lint
bun run type-check
bun run test
```

## 部署入口（统一文档）

- 一键启动 / 场景化脚本 / 生产部署：[`deploy/README.md`](../deploy/README.md)
- 生产 IP/URL 配置最佳实践：[`deploy/PRODUCTION_IP_GUIDE.md`](../deploy/PRODUCTION_IP_GUIDE.md)

## 相关链接

- 后端：[`backend/README.md`](../backend/README.md)
- Next.js: https://nextjs.org/docs

## License

Apache 2.0
