# JoySafeter Frontend

JoySafeter 的前端应用（Next.js App Router），提供托管 Agent 的创建、运行、资源管理与组织/项目管理 UI。

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
# 本地默认连接 http://localhost:8000；需要改后端地址时可设置 NEXT_PUBLIC_API_URL
```

`env.example` 是前端所有环境变量的唯一完整定义（含默认值与注释）。部署时 `deploy/.env.example` 只覆盖需要修改的差异项。

### 3) 启动开发服务器

```bash
bun run dev
```

访问：http://localhost:3000

## 架构概述

### 路由结构（App Router）

```
app/
├── page.tsx                      # 登录态分流：已登录 → /managed/quickstart，未登录 → /signin
├── (auth)/                       # 登录、注册、邮箱验证、重置密码
└── managed/                      # 当前产品主界面
    ├── quickstart/               # 自然语言快速创建 Agent
    ├── agents/                   # Agent 列表、详情、编辑、版本
    ├── sessions/                 # 会话列表、会话详情、SSE 事件流
    ├── environments/             # 沙箱镜像与网络配置
    ├── credentials/              # 统一凭据界面：模型、服务与 MCP 凭据组
    ├── files/                    # 上传文件资源
    ├── skills/                   # Skill 导入、编辑、版本、安全扫描、AI authoring
    ├── memory-stores/            # 记忆库与版本
    ├── settings/                 # 组织设置
    ├── projects/                 # 项目管理
    ├── members/                  # 成员管理
    └── api-keys/                 # 项目级 API keys
```

### 核心模块

| 模块             | 路径                   | 职责                                                                       |
| ---------------- | ---------------------- | -------------------------------------------------------------------------- |
| **API 客户端**   | `lib/api-client.ts`    | 统一 REST 请求（URL 构建、CSRF、401 自动刷新、ErrorDescriptor 提取）       |
| **WebSocket 层** | `lib/ws/`              | BaseWsClient 抽象类 + NotificationWsClient；会话事件主要走 SSE             |
| **状态管理**     | `stores/`              | Zustand 客户端 Store（认证、项目上下文、侧边栏）                           |
| **服务端状态**   | hooks + TanStack Query | 缓存 + 失效（projects、quickstart、skills、session resources 等）          |
| **错误消费**     | `ApiError` class       | 镜像后端 ErrorDescriptor：`source`、`retryable`、`userAction` 驱动 UI 行为 |

### 环境变量要点

所有前端环境变量在 `env.example` 中统一定义（唯一真相源）。以下为常用变量速查：

- `NEXT_PUBLIC_API_URL`：可选。覆盖后端 API 根地址；未设置时前端默认使用 `http://localhost:8000`。
- `NEXT_PUBLIC_APP_URL`：可选。公开前端地址，Docker/生产环境用于链接拼接。
- `NEXT_PUBLIC_MAX_UPLOAD_FILE_BYTES`：可选。浏览器侧上传大小上限，建议与后端 `JOYSAFETER_MAX_UPLOAD_FILE_BYTES` 一致。
- `NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED`：可选。控制登录页是否显示邮箱/密码注册入口；后端仍以认证配置为准。
- `NEXT_PUBLIC_CSP_*`：CSP 安全策略相关（`NECESSARY_DOMAIN`、`CONNECT_SRC_EXTRA`、`FRAME_SRC_EXTRA`、`REPORT_URI`、`WHITELIST`、`ALLOW_EMBED`、`ENABLE_CSP_IN_DEV`、`FORCE_HTTPS`）。
- `DISABLE_REGISTRATION` / `EMAIL_VERIFICATION_ENABLED`：可选。前端服务端用于注册页与邮箱验证 UI；后端强制策略仍看 `backend/.env`。

部署时 `deploy/.env.example` 只覆盖与开发默认值不同的变量（如 `NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED=false`），无需重复声明所有变量。

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

## 构建与部署

- 完整安装、镜像构建和部署：[`deploy/README.md`](../deploy/README.md)
- 宿主机开发与测试：[`DEVELOPMENT.md`](../DEVELOPMENT.md)

## 相关链接

- 后端：[`backend/README.md`](../backend/README.md)
- Next.js: https://nextjs.org/docs

## License

Apache 2.0
