# Deploy - Docker 部署配置

项目 Docker 构建和部署的统一入口。

## 目录结构

```
deploy/
├── docker/                          # Dockerfile 统一存放
│   ├── backend.Dockerfile
│   └── frontend.Dockerfile
├── scripts/
│   ├── check-env.sh                 # 环境检查工具
│   ├── dev.sh                       # 开发场景启动
│   ├── dev-local.sh                 # 本地开发启动
│   ├── prod.sh                      # 生产场景启动
│   ├── test.sh                      # 测试场景启动
│   ├── minimal.sh                   # 最小化场景启动
│   ├── start-middleware.sh          # 启动中间件服务
│   └── stop-middleware.sh           # 停止中间件服务
├── docker-compose.yml               # 完整服务（开发环境）
├── docker-compose.prod.yml          # 生产环境
├── docker-compose-middleware.yml    # 中间件（db + redis）
├── install.sh                       # 统一安装脚本
├── quick-start.sh                   # 快速启动脚本
├── deploy.sh                        # 镜像构建和推送脚本
├── PRODUCTION_IP_GUIDE.md           # 生产环境 & 指定前后端 IP/域名 最佳实践
└── .env.example                     # 环境变量配置示例
```

## 推荐阅读

- [生产环境 & 指定前后端 IP/域名 最佳实践](./PRODUCTION_IP_GUIDE.md)

## 快速开始

### 方式一：一键启动（推荐）

```bash
cd deploy
./quick-start.sh
```

访问地址：
- 前端: http://localhost:3000
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 方式二：场景化脚本（推荐）

```bash
cd deploy

# 开发场景
./scripts/dev.sh

# 生产场景（服务器）：使用预构建镜像
./scripts/prod.sh
# 跳过 MCP：./scripts/prod.sh --skip-mcp

# 测试场景
./scripts/test.sh

# 最小化场景（仅中间件：db + redis，可选 MCP）
./scripts/minimal.sh
# 启动 MCP：./scripts/minimal.sh --with-mcp

# 本地开发（后端/前端在本地跑，容器只启中间件）
./scripts/dev-local.sh
```

### 方式三：手动 Compose（高级）

> 建议优先使用脚本（会处理初始化/检查/参数），手动方式仅用于排障或特殊定制。

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../deploy
docker-compose up -d
```

## 部署场景说明

> 场景的“单一入口”是 `deploy/scripts/*.sh`。命令行参数与细节请直接查看脚本源码或 `--help`（如支持）。

| 场景 | 脚本 | 适用场景 | 说明 |
|------|------|----------|------|
| dev | `./scripts/dev.sh` | 本地 Docker 全量开发 | 前后端容器化运行，适合快速联调 |
| prod | `./scripts/prod.sh` | 服务器生产部署 | 默认使用预构建镜像（可 `--skip-mcp`） |
| test | `./scripts/test.sh` | CI/快速验证 | 最小化依赖，适合自动化 |
| minimal | `./scripts/minimal.sh` | 本地跑后端/前端 | 只启中间件（db+redis），可选 MCP |
| dev-local | `./scripts/dev-local.sh` | 本地代码 + 容器中间件 | IDE 友好，后端/前端本地启动 |

本地代码启动（配合 `dev-local` 或 `minimal`）：
- 后端：见 [`backend/README.md`](../backend/README.md)
- 前端：见 [`frontend/README.md`](../frontend/README.md)

## 镜像构建（进阶）

镜像构建、`deploy.sh`、多架构构建说明已拆分到：[`ADVANCED_BUILD.md`](./ADVANCED_BUILD.md)

### 基本用法

```bash
# 构建前后端镜像（默认：linux/amd64,linux/arm64）
./deploy.sh build

# 构建所有镜像（包括 backend, frontend, openclaw）
# 注意：MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest
./deploy.sh build --all

# 构建并推送到仓库
./deploy.sh push

# 拉取最新镜像
./deploy.sh pull
```

### 构建选项

```bash
# 只构建后端镜像
./deploy.sh build --backend-only

# 只构建前端镜像
./deploy.sh build --frontend-only

# 只构建 OpenClaw 镜像
./deploy.sh build --openclaw-only

# 构建所有镜像 (包含 backend, frontend, openclaw)
./deploy.sh build --all

# 禁用 Docker 构建缓存
./deploy.sh build --no-cache

# 注意：MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest
# 如需拉取 MCP 镜像，使用: ./deploy.sh pull

# 构建指定架构
./deploy.sh build --arch amd64 --arch arm64

# 构建时指定前端 API 地址
./deploy.sh build --api-url http://api.example.com

# 指定镜像仓库和标签
./deploy.sh build --registry your-registry.com/namespace --tag v1.0.0
```

### 国内镜像源加速

```bash
# 使用华为云镜像源加速基础镜像和 pip
./deploy.sh build --mirror huawei --pip-mirror aliyun

# 支持的镜像源选项：
# --mirror: aliyun, tencent, huawei, docker-cn
# --pip-mirror: aliyun, tencent, huawei, jd
```

### 构建脚本环境变量

可以通过环境变量覆盖 `deploy.sh` 脚本的默认配置：

```bash
# 镜像仓库配置
export DOCKER_REGISTRY="your-registry.com/namespace"
export BACKEND_IMAGE="agent-platform-backend"
export FRONTEND_IMAGE="agent-platform-frontend"
export OPENCLAW_IMAGE="joysafeter-openclaw"
export IMAGE_TAG="v1.0.0"

# 构建平台配置
export BUILD_PLATFORMS="linux/amd64,linux/arm64"

# 前端 API 地址
export NEXT_PUBLIC_API_URL="http://api.example.com"

# pip 镜像源
export PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
```

## 运行时环境变量配置

项目需要配置两个环境变量文件，它们有不同的用途：

### 1. Docker Compose 变量配置（deploy/.env）⭐ 必需

`deploy/.env` 是 **Docker Compose 解析 `${VAR}`** 时读取的配置（同时也会作为脚本的默认配置来源）。

**重要**：在本项目的 `docker-compose*.yml` 中，除了端口映射外，还有一部分容器环境变量也使用了 `${VAR}`（例如 `POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB`、`REDIS_URL` 等）。因此它不只是“端口映射”，也是 Compose 场景下的关键运行参数来源之一（属于历史机制，保留现状）。

#### 创建配置文件

```bash
cd deploy
cp .env.example .env
```

#### 配置说明

`deploy/.env` 文件包含以下配置：

```bash
# 服务端口映射配置（宿主机端口）
BACKEND_PORT_HOST=8000
FRONTEND_PORT_HOST=3000
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379

# 前后端集成（极度重要）
# 必须为用户在浏览器中访问前端的真实公网绝对 URL，结尾不要加斜杠
FRONTEND_URL=http://localhost:3000

# 前端访问后端的公共 URL（供前端和浏览器访问）
BACKEND_URL=http://localhost:8000

# 数据库/缓存（Compose 解析期变量：会被 docker-compose*.yml 用到）
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=joysafeter
REDIS_URL=redis://redis:6379/0

# MCP Server 端口映射
DEMO_MCP_SERVER_PORT=8001
SCANNER_MCP_PORT=8002
JEB_MCP_PORT=8008
MCP_PORT_3=8003
MCP_PORT_4=8004
MCP_PORT_5=8005

# 构建加速（可选）
PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

**作用**：
- `*_PORT_HOST`：控制容器端口到宿主机的映射
- `FRONTEND_URL/BACKEND_URL`：用于前后端集成（OAuth 回调、邮件内链、前端 API 地址注入等）
- `POSTGRES_* / REDIS_URL`：用于 Compose 场景下数据库/缓存的初始化与连接（由 `docker-compose*.yml` 的 `${VAR}` 引用决定）

### 2. 应用环境变量配置（backend/.env）⭐ 必需

`backend/.env` 是 **后端应用进程** 读取的配置（Pydantic Settings 会加载 `backend/.env`）。

在 Docker Compose 场景下，`docker-compose*.yml` 还会通过 `environment:` 对部分变量进行覆盖（例如 `POSTGRES_HOST=db` 等），所以你通常只需要在这里配置 **应用自身的必需项**。

```bash
# JWT 密钥（生产环境必须修改）
SECRET_KEY=your-secret-key-change-in-production-CHANGE-THIS-IN-PRODUCTION

# 运行模式（可选）
DEBUG=false
ENVIRONMENT=production

# 其他应用配置...
# 其他应用配置...
```

**作用**：这些变量用于后端应用运行时配置（认证密钥、功能开关、可观测性等）。

### 配置区别说明

| 配置项 | deploy/.env | backend/.env |
|--------|-------------|--------------|
| **用途** | Docker Compose 解析 `${VAR}`（端口、镜像、部分运行参数） | 后端应用进程读取（应用配置为主） |
| **生效时机** | Compose 解析与容器创建时 | 后端进程启动时（`backend/.env`） |
| **端口变量** | `*_PORT_HOST`（宿主机端口映射） | `BACKEND_PORT`（容器内监听端口，通常无需改） |
| **必需性** | ⭐ 必需 | ⭐ 必需（至少要有 `SECRET_KEY`） |

**重要提示**：
- 不要混淆 **Compose 解析期 `${VAR}`** 与 **容器内 env_file**：两者读取来源不同。
- 如果你在 `deploy/.env` 改了 `POSTGRES_PASSWORD` 等，生效与否取决于对应 `docker-compose*.yml` 是否用 `${POSTGRES_PASSWORD}` 进行了解析。

## 数据库 / 服务管理

- 数据库初始化与手动操作：[`DATABASE.md`](./DATABASE.md)
- 查看状态/日志/重启/停止：[`SERVICE_MANAGEMENT.md`](./SERVICE_MANAGEMENT.md)

## 多架构构建（进阶）

多架构构建说明已包含在：[`ADVANCED_BUILD.md`](./ADVANCED_BUILD.md)

## 环境检查工具

使用环境检查工具可以快速检查部署前置条件：

```bash
cd deploy

# 运行环境检查
./scripts/check-env.sh
```

检查内容包括：
- ✅ Docker 安装和运行状态
- ✅ Docker Compose 版本
- ✅ 端口占用情况
- ✅ 配置文件存在性
- ✅ 磁盘空间

## 故障排查

- 故障排查与日志/重置指引：[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md)

## 常用命令速查

```bash
cd deploy

# 交互式安装/生成配置
./install.sh

# 环境检查
./scripts/check-env.sh

# 一键启动（推荐新手）
./quick-start.sh

# 开发/生产/测试/最小化
./scripts/dev.sh
./scripts/prod.sh
./scripts/test.sh
./scripts/minimal.sh

# 查看状态/日志
docker-compose ps
docker-compose logs -f
```

## 生产部署（入口）

生产部署请以这里为准：[`PRODUCTION_IP_GUIDE.md`](./PRODUCTION_IP_GUIDE.md)

该文档包含：
- 前后端 URL / IP / 域名的正确配置方式（`FRONTEND_URL` / `BACKEND_URL`）
- 反向代理 / HTTPS 建议
- 生产安全项（`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、端口暴露策略等）

## 相关文档

- [Backend README](../backend/README.md) - 后端配置和 API 文档
- [项目主 README](../README.md) - 项目整体介绍和架构说明
