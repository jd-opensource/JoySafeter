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
└── .env.example                     # 环境变量配置示例
```

## 快速开始

### 方式一：一键快速启动（推荐新手）

最简单的启动方式，自动完成所有配置：

```bash
cd deploy

# 一键启动（自动检查环境、创建配置、启动服务）
./quick-start.sh
```

访问地址：
- 前端: http://localhost:3000
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 方式二：交互式安装（推荐）

使用安装向导，根据场景选择配置：

```bash
cd deploy

# 交互式安装
./install.sh

# 或快速安装开发环境
./install.sh --mode dev --non-interactive
```

安装完成后，使用场景化脚本启动：

```bash
# 开发场景
./scripts/dev.sh

# 生产场景
./scripts/prod.sh

# 测试场景
./scripts/test.sh

# 最小化场景（仅中间件）
./scripts/minimal.sh

# 本地开发（后端和前端在本地运行）
./scripts/dev-local.sh
```

### 方式三：手动配置（高级用户）

如果需要完全控制配置过程：

```bash
cd deploy

# 1. 创建 Docker Compose 端口映射配置文件（必需）
cp .env.example .env
# 根据需要修改 .env 文件中的端口配置，避免端口冲突

# 2. 创建后端应用环境变量文件（必需）
cd ../backend
cp env.example .env
# 配置数据库连接、JWT 密钥等应用配置

# 3. 启动中间件（PostgreSQL + Redis）并初始化数据库
# 注意：Redis 是必需组件，必须启动
cd ../deploy
./scripts/start-middleware.sh

# 4. 启动完整服务
docker-compose up -d
```

## 部署场景说明

项目支持多种部署场景，根据实际需求选择：

### 开发场景 (dev)

**适用场景**：
- 本地开发调试
- 需要代码热重载
- 需要频繁修改代码

**特性**：
- ✅ 代码挂载（可直接编辑代码）
- ✅ 热重载（修改代码后自动重启）
- ✅ 详细日志输出
- ✅ 支持调试

**启动方式**：
```bash
./scripts/dev.sh
# 或
docker-compose up -d
```

### 生产场景 (prod)

**适用场景**：
- 生产环境部署
- 使用预构建镜像
- 需要优化性能

**特性**：
- ✅ 使用预构建镜像（快速启动）
- ✅ 优化配置（性能优化）
- ✅ 生产级日志
- ⚠️ 需要配置镜像仓库

**启动方式**：
```bash
./scripts/prod.sh
# 或
docker-compose -f docker-compose.prod.yml up -d
```

**前置要求**：
1. 已构建并推送镜像到仓库
2. 已配置 `deploy/.env` 中的镜像仓库地址
3. 已修改 `backend/.env` 中的 `SECRET_KEY`（生产环境必须）

### 测试场景 (test)

**适用场景**：
- 功能测试
- 快速验证
- CI/CD 环境

**特性**：
- ✅ 快速启动
- ✅ 最小化配置
- ✅ 适合自动化测试

**启动方式**：
```bash
./scripts/test.sh
```

### 最小化场景 (minimal)

**适用场景**：
- 本地开发（后端和前端在本地运行）
- 仅需要数据库和缓存服务
- 测试数据库连接

**特性**：
- ✅ 仅启动 PostgreSQL 和 Redis（两者都是必需组件）
- ✅ 数据库已初始化
- ✅ 资源占用最小

**启动方式**：
```bash
./scripts/minimal.sh
# 或
./scripts/start-middleware.sh
```

### 本地开发场景 (dev-local)

**适用场景**：
- 本地开发调试
- 需要直接运行后端和前端代码
- 需要完整的开发工具支持

**特性**：
- ✅ 仅启动中间件容器
- ✅ 后端和前端在本地运行
- ✅ 支持 IDE 调试
- ✅ 支持代码热重载

**启动方式**：
```bash
./scripts/dev-local.sh
```

然后在新终端启动后端和前端：
```bash
# 启动后端
cd backend
uv venv && source .venv/bin/activate
uv sync
alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 启动前端（新终端）
cd frontend
bun install
bun run dev
```

## 镜像构建和管理

`deploy.sh` 是统一的镜像构建和推送脚本，支持多架构构建、镜像推送和拉取。

### 基本用法

```bash
# 构建前后端镜像（默认：linux/amd64,linux/arm64）
./deploy.sh build

# 构建所有镜像（包括 backend, frontend, init）
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

# 只构建初始化镜像
./deploy.sh build --init-only

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

### 1. Docker Compose 端口映射配置（deploy/.env）⭐ 必需

**重要**：`docker-compose.yml` 中的端口映射变量（如 `BACKEND_PORT_HOST`）必须在 `deploy/.env` 文件中定义，这样 Docker Compose 在启动时才能正确解析端口映射。

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
BACKEND_HOST=localhost  # 后端服务主机名（用于前端连接，容器内访问时使用 "backend"）
FRONTEND_PORT_HOST=3000
FRONTEND_HOSTNAME=localhost  # 前端服务主机名（用于后端 CORS 配置）
FRONTEND_URL=http://localhost:3000  # 前端完整 URL（用于健康检查等）

# 数据库端口映射
POSTGRES_PORT_HOST=5432

# Redis 端口映射（必需）
# 注意：Redis 是系统必需组件，用于缓存和会话管理
REDIS_PORT_HOST=6379

# MCP Server 端口映射
DEMO_MCP_SERVER_PORT=8001
SCANNER_MCP_PORT=8002
JEB_MCP_PORT=8008
MCP_PORT_3=8003
MCP_PORT_4=8004
MCP_PORT_5=8005

# 构建配置（可选）
PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

**作用**：这些变量用于 Docker Compose 解析 `docker-compose.yml` 文件，控制容器端口到宿主机的映射。

### 2. 应用环境变量配置（backend/.env）⭐ 必需

在 `backend/.env` 中配置应用运行时需要的环境变量：

```bash
# PostgreSQL 配置
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=joysafeter
POSTGRES_HOST=db                    # 容器内使用服务名 "db"
POSTGRES_PORT=5432                  # 容器内端口（固定为 5432）

# Redis 配置（可选）
# 注意：Redis 是系统必需组件，后端服务依赖 Redis 才能正常运行
# 在 Docker Compose 环境中，如果不配置 REDIS_URL，将自动使用默认值 redis://redis:6379/0
# 如果需要使用外部 Redis 或自定义配置（如密码、不同端口等），请配置 REDIS_URL
# 格式: redis://[:密码@]主机:端口/数据库编号
# REDIS_URL=redis://redis:6379/0

# 应用服务器配置
BACKEND_HOST=0.0.0.0                # 应用监听地址（容器内）
BACKEND_PORT=8000                   # 应用监听端口（容器内，固定为 8000）

# JWT 密钥（生产环境必须修改）
SECRET_KEY=your-secret-key-change-in-production-CHANGE-THIS-IN-PRODUCTION

# 其他应用配置...
```

**作用**：这些变量用于容器内部应用运行时的配置，如数据库连接、JWT 密钥等。

### 配置区别说明

| 配置项 | deploy/.env | backend/.env |
|--------|-------------|--------------|
| **用途** | Docker Compose 端口映射解析 | 容器内应用运行时配置 |
| **生效时机** | Docker Compose 启动时 | 容器内应用启动时 |
| **端口变量** | `*_PORT_HOST`（宿主机端口） | `*_PORT`（容器内端口） |
| **必需性** | ⭐ 必需（端口映射） | ⭐ 必需（应用配置） |

**重要提示**：
- 两个文件中的端口变量用途不同，不要混淆
- `deploy/.env` 中的 `*_PORT_HOST` 控制宿主机端口映射
- `backend/.env` 中的 `*_PORT` 是容器内应用监听的端口（通常不需要修改）
- `REDIS_URL` 在 Docker Compose 环境中是可选的，如果不配置，将自动使用默认值 `redis://redis:6379/0`

## 数据库管理

### 初始化数据库

数据库初始化会在 `./scripts/start.sh` 中自动执行，也可以手动运行：

```bash
# 使用中间件配置初始化
docker-compose -f docker-compose-middleware.yml --profile init run --rm db-init

# 使用完整服务配置初始化
docker-compose --profile init run --rm db-init
```

### 数据库脚本

位于 `backend/scripts/db/`：

- `init-db.py` - 初始化数据库（创建表结构）
- `clean-db.py` - 清理数据（保留表结构）
- `wait-for-db.py` - 等待数据库就绪

### 手动操作数据库

```bash
# 进入数据库容器
docker-compose exec db psql -U postgres -d joysafeter

# 查看数据库状态
docker-compose exec db pg_isready -U postgres
```

## 服务管理

### 查看服务状态

```bash
# 查看所有服务状态
docker-compose ps

# 查看中间件状态
docker-compose -f docker-compose-middleware.yml ps

# 查看服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db
docker-compose logs -f redis
```

### 停止和清理

```bash
# 停止服务（保留数据）
docker-compose down

# 停止并删除数据卷（⚠️ 会删除所有数据）
docker-compose down -v

# 停止中间件
docker-compose -f docker-compose-middleware.yml down
```

### 重启服务

```bash
# 重启单个服务
docker-compose restart backend

# 重启所有服务
docker-compose restart
```

## 多架构构建说明

`deploy.sh` 默认使用 Docker Buildx 进行多架构构建，支持：

- `linux/amd64` - Intel/AMD 64位
- `linux/arm64` - ARM 64位（Apple Silicon, ARM 服务器）
- `linux/arm/v7` - ARM 32位

### 多架构构建注意事项

1. **本地构建多架构镜像**：使用 `--push` 选项才能保存所有架构的镜像到仓库
2. **本地测试**：不使用 `--push` 时，只会构建第一个架构的镜像用于本地测试
3. **Buildx 要求**：多架构构建需要 Docker Buildx，脚本会自动初始化

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

### 常见问题

#### 1. 环境检查失败

**问题**：运行 `./scripts/check-env.sh` 时出现错误

**解决方案**：
```bash
# 检查 Docker 是否运行
docker info

# 检查 Docker Compose 是否安装
docker compose version
# 或
docker-compose --version

# 检查端口占用
lsof -i :8000  # 检查后端端口
lsof -i :3000  # 检查前端端口
lsof -i :5432  # 检查数据库端口
```

#### 2. 数据库连接失败

**问题**：后端无法连接到数据库

**解决方案**：
```bash
# 检查数据库容器状态
docker-compose ps db

# 查看数据库日志
docker-compose logs db

# 检查网络连接
docker-compose exec backend ping db

# 检查数据库配置
# 确保 backend/.env 中 POSTGRES_HOST=db（容器内使用服务名）
# 确保 deploy/.env 中 POSTGRES_PORT_HOST 正确映射
```

#### 3. 端口冲突

**问题**：端口已被占用

**解决方案**：
```bash
# 方法一：使用环境检查工具查找可用端口
./scripts/check-env.sh

# 方法二：修改 deploy/.env 中的端口映射
POSTGRES_PORT_HOST=5433    # 改为其他端口
REDIS_PORT_HOST=6380       # 改为其他端口
BACKEND_PORT_HOST=8001     # 改为其他端口
FRONTEND_PORT_HOST=3001    # 改为其他端口

# 修改后重启服务
docker-compose down
docker-compose up -d
```

#### 4. 镜像构建失败

**问题**：构建 Docker 镜像时失败

**解决方案**：
```bash
# 查看详细构建日志
./deploy.sh build --backend-only 2>&1 | tee build.log

# 使用国内镜像源加速
./deploy.sh build --mirror huawei --pip-mirror aliyun

# 清理构建缓存后重试
docker builder prune
./deploy.sh build
```

#### 5. 服务启动失败

**问题**：服务无法正常启动

**解决方案**：
```bash
# 查看服务日志
docker-compose logs -f [service_name]

# 查看所有服务状态
docker-compose ps

# 重启服务
docker-compose restart [service_name]

# 完全重建服务
docker-compose down
docker-compose up -d --build
```

#### 6. 配置文件缺失

**问题**：提示配置文件不存在

**解决方案**：
```bash
# 使用安装脚本自动创建
./install.sh

# 或手动创建
cp .env.example .env
cd ../backend && cp env.example .env
```

#### 7. 数据库初始化失败

**问题**：数据库初始化脚本执行失败

**解决方案**：
```bash
# 检查数据库是否就绪
docker-compose exec db pg_isready -U postgres

# 手动运行初始化脚本
docker-compose --profile init run --rm db-init

# 如果失败，查看详细日志
docker-compose logs db-init
```

#### 8. 前端无法连接后端

**问题**：前端页面无法访问后端 API

**解决方案**：
```bash
# 检查后端服务是否运行
docker-compose ps backend

# 检查后端日志
docker-compose logs backend

# 检查 CORS 配置
# 确保 backend/.env 中 CORS_ORIGINS 包含前端地址
# 确保 deploy/.env 中 FRONTEND_URL 正确

# 检查网络连接
curl http://localhost:8000/health  # 测试后端健康检查
```

### 日志查看

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db

# 查看最近 100 行日志
docker-compose logs --tail=100 backend

# 查看特定时间段的日志
docker-compose logs --since 30m backend
```

### 服务状态检查

```bash
# 查看所有服务状态
docker-compose ps

# 查看服务健康状态
docker-compose ps --format json | jq '.[] | {name: .Name, status: .State, health: .Health}'

# 检查服务资源使用
docker stats

# 进入容器调试
docker-compose exec backend bash
docker-compose exec frontend sh
```

### 清理和重置

```bash
# 停止所有服务（保留数据）
docker-compose down

# 停止并删除数据卷（⚠️ 会删除所有数据）
docker-compose down -v

# 清理未使用的镜像和容器
docker system prune -a

# 完全重置（停止所有服务、删除数据、清理镜像）
docker-compose down -v
docker system prune -a --volumes
```

## 使用新脚本（推荐）

### 安装和配置

```bash
cd deploy

# 方式一：交互式安装（推荐）
./install.sh

# 方式二：快速安装开发环境
./install.sh --mode dev --non-interactive

# 方式三：快速安装生产环境
./install.sh --mode prod --non-interactive
```

### 环境检查

```bash
# 检查部署前置条件
./scripts/check-env.sh
```

### 快速启动

```bash
# 一键启动完整服务（自动处理配置）
./quick-start.sh

# 跳过安装步骤
./quick-start.sh --skip-install
```

### 场景化启动

```bash
# 开发场景
./scripts/dev.sh

# 生产场景
./scripts/prod.sh

# 测试场景
./scripts/test.sh

# 最小化场景（仅中间件）
./scripts/minimal.sh

# 本地开发场景（后端和前端在本地运行）
./scripts/dev-local.sh
```

## 常用命令速查

### 安装和配置

```bash
# 使用安装脚本（推荐）
cd deploy && ./install.sh

# 手动配置
cp .env.example .env                    # 创建端口映射配置
cd ../backend && cp env.example .env    # 创建应用配置
```

### 启动服务

```bash
# 使用新脚本（推荐）
./quick-start.sh                        # 一键启动
./scripts/dev.sh                        # 开发场景
./scripts/prod.sh                       # 生产场景
./scripts/minimal.sh                    # 最小化场景

# 传统方式
./scripts/start-middleware.sh            # 启动中间件
docker-compose up -d                    # 启动完整服务
docker-compose -f docker-compose.prod.yml up -d  # 生产环境
```

### 构建镜像

```bash
./deploy.sh build                       # 构建前后端
./deploy.sh build --all                 # 构建所有镜像
./deploy.sh push                        # 构建并推送
./deploy.sh pull                        # 拉取镜像
```

### 查看状态和日志

```bash
# 环境检查
./scripts/check-env.sh                  # 检查环境

# 服务状态
docker-compose ps                       # 查看服务状态

# 查看日志
docker-compose logs -f                  # 所有服务日志
docker-compose logs -f backend          # 后端日志
docker-compose logs -f frontend         # 前端日志
docker-compose logs --tail=100 backend  # 最近 100 行
```

### 数据库操作

```bash
# 初始化数据库
docker-compose --profile init run --rm db-init

# 进入数据库
docker-compose exec db psql -U postgres -d joysafeter

# 查看数据库状态
docker-compose exec db pg_isready -U postgres
```

### 服务管理

```bash
# 停止服务
docker-compose down                     # 停止服务（保留数据）
docker-compose down -v                  # 停止并删除数据
./scripts/stop-middleware.sh            # 停止中间件

# 重启服务
docker-compose restart                  # 重启所有服务
docker-compose restart backend          # 重启后端

# 进入容器
docker-compose exec backend bash        # 进入后端容器
docker-compose exec frontend sh         # 进入前端容器
```

### 清理

```bash
# 清理未使用的资源
docker system prune                     # 清理未使用的容器和镜像
docker system prune -a                  # 清理所有未使用的资源

# 完全重置
docker-compose down -v                  # 停止并删除数据卷
docker system prune -a --volumes       # 清理所有资源
```

## 生产环境部署

### 1. 构建生产镜像

```bash
./deploy.sh push --registry your-registry.com/namespace --tag v1.0.0
```

### 2. 配置生产环境变量

在服务器上配置以下环境变量文件：

#### deploy/.env（必需）
```bash
# 端口映射配置（根据实际部署环境调整）
BACKEND_PORT_HOST=8000
BACKEND_HOST=your-domain.com  # 或使用内网 IP
FRONTEND_PORT_HOST=3000
FRONTEND_HOSTNAME=your-domain.com
FRONTEND_URL=https://your-domain.com
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379
# ... 其他端口配置
```

#### backend/.env（必需）
```bash
# 数据库配置
POSTGRES_USER=postgres
POSTGRES_PASSWORD=strong_password_here
POSTGRES_DB=joysafeter
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Redis 配置（可选）
# 在 Docker Compose 环境中，如果不配置 REDIS_URL，将自动使用默认值 redis://redis:6379/0
# 如果需要使用外部 Redis 或自定义配置，请配置 REDIS_URL
# REDIS_URL=redis://redis:6379/0

# 应用配置
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
SECRET_KEY=your-strong-secret-key-here  # ⚠️ 必须修改为强随机字符串
DEBUG=false
ENVIRONMENT=production

# CORS 配置
CORS_ORIGINS=["https://your-domain.com"]
FRONTEND_URL=https://your-domain.com

# 其他生产环境配置...
```

#### frontend/.env（可选）
```bash
NEXT_PUBLIC_API_URL=https://api.your-domain.com
# 其他前端配置...
```

### 3. 使用生产配置启动

```bash
cd deploy
docker-compose -f docker-compose.prod.yml up -d
```

### 4. 配置反向代理（推荐）

使用 Nginx 或 Traefik 作为反向代理，配置 SSL 证书：

```nginx
# Nginx 配置示例
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 安全建议

- ✅ 使用强密码和 JWT 密钥
- ✅ 启用 HTTPS（SSL/TLS）
- ✅ 配置防火墙规则，限制端口访问
- ✅ 定期更新镜像和依赖
- ✅ 配置日志轮转和监控
- ✅ 使用 Docker secrets 或密钥管理服务存储敏感信息

## 相关文档

- [Backend README](../backend/README.md) - 后端配置和 API 文档
- [项目主 README](../README.md) - 项目整体介绍和架构说明
