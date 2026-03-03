# JoySafeter 安装指南

以下是全面的部署说明。根据您的需求，选择适合您的部署方案。

## 环境要求

| 依赖 | 版本 |
|------|------|
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| Python | 3.12+（本地开发需要） |
| Node.js | 20+（本地开发需要） |
| PostgreSQL | 15+（不使用 Docker 时需要） |
| Redis | 7+（不使用 Docker 时需要） |

## 方案一：一键运行（推荐）

```bash
# 一键初始化环境 & 本地构建镜像 & 自动启动
sh deploy/quick-start.sh
```

## 方案二：手动部署

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

## 使用预构建的 Docker 镜像

我们在 GitHub Container Registry 提供了预构建的 Docker 镜像，您可以直接使用：

```bash
# 拉取镜像
docker pull docker.io/jdopensource/joysafeter-backend:latest
docker pull docker.io/jdopensource/joysafeter-frontend:latest
docker pull docker.io/jdopensource/joysafeter-mcp:latest

# 或者使用 docker-compose 搭配预构建镜像
cd deploy
export DOCKER_REGISTRY=docker.io/jdopensource
docker-compose -f docker-compose.yml up -d
```

**可用镜像：**
- `docker.io/jdopensource/joysafeter-backend:latest` - 后端 API 服务
- `docker.io/jdopensource/joysafeter-frontend:latest` - 前端 Web 应用
- `docker.io/jdopensource/joysafeter-mcp:latest` - 包含安全工具的 MCP 服务

所有镜像均支持多架构（amd64, arm64）。

## 其他配置方式

### 方式 1：交互式安装

使用安装向导来配置您的环境：

```bash
cd deploy

# 交互式安装
./install.sh

# 或快速安装用于开发
./install.sh --mode dev --non-interactive
```

安装完成后，使用针对特定场景的脚本运行服务：

```bash
# 开发环境
./scripts/dev.sh

# 生产环境
./scripts/prod.sh

# 测试环境
./scripts/test.sh

# 极简运行（仅中间件）
./scripts/minimal.sh

# 本地开发（后端和前端直接本地运行）
./scripts/dev-local.sh
```

### 方式 2：手动执行 Docker Compose

为希望获得完全控制权的高级用户准备：

```bash
cd deploy

# 1. 创建配置文件
cp .env.example .env
cd ../backend && cp env.example .env

# 2. 启动中间件（PostgreSQL + Redis）
cd ../deploy
./scripts/start-middleware.sh

# 3. 启动全量服务
docker-compose up -d
```

### 方式 3：环境检查

在启动之前，您可以检查您的环境情况：

```bash
cd deploy
./scripts/check-env.sh
```

这将验证：
- Docker 安装状态
- Docker Compose 版本
- 端口占用情况
- 配置文件
- 磁盘空间

## 手动安装（本地开发）

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

## 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
