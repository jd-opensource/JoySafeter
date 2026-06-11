# JoySafeter 安装指南

以下是全面的部署说明。根据您的需求，选择适合您的部署方案。

## 环境要求

- Docker 20.10+ 与 Docker Compose 2.0+
- Python 3.12+ 与 Node.js 20+（仅本地开发需要）
- PostgreSQL/Redis 在 Docker 部署场景下会自动包含

## 推荐：Docker 三服务启动

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy
docker compose up -d --build
```

访问地址：

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

后端容器拆分为 `api`、`orchestrator`、`worker`。生产、云数据库/云 Redis、镜像构建等场景请以 [deploy/README.md](deploy/README.md) 为准。

## 使用预构建的 Docker 镜像

```bash
cd deploy
cp .env.example .env
export DOCKER_REGISTRY=docker.io/jdopensource
docker compose up -d
```

所有镜像均支持多架构（amd64, arm64）。

## 本地测试一键启动

```bash
cd deploy
./local-test.sh
```

停止：

```bash
docker compose down
```

## 环境检查

```bash
cd deploy
docker compose config
```

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
