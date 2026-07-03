# JoySafeter 安装指南

以下是全面的部署说明。根据您的需求，选择适合您的部署方案。

## 环境要求

- Docker 20.10+ 与 Docker Compose 2.0+
- Python 3.12+ 与 Node.js 20+（仅本地开发需要）
- PostgreSQL/Redis 在 Docker 部署场景下会自动包含

## 推荐：Docker Compose 部署

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# 全本地：PostgreSQL + Redis + Python orchestrator
docker compose --profile local-redis --profile python-orchestrator up -d --build
```

访问地址：

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

后端是同一份代码，通过 `JOYSAFETER_SERVICE_ROLE` 拆成三个服务并作为独立容器部署：`api`、
`orchestrator`、`worker`，同时配套 PostgreSQL、Redis、Envoy（每沙箱出站代理）与
skillspector（Skill 安全扫描服务）。本地 Redis 只有启用 `local-redis` profile 时才会启动；如使用云 Redis，
不要启用该 profile，改 `deploy/.env` 的 `REDIS_URL` 即可。快速开始支持路径是 `python-orchestrator`
profile。当前 checkout 中 `rust-orchestrator` 仍是实验入口：其 Dockerfile 依赖
`backend/app/joysafeter_orchestrator_rs`，但该源码目录当前不存在。生产、云数据库/云 Redis、镜像
构建等场景请以 [deploy/README.md](deploy/README.md) 为准。

## 使用预构建的 Docker 镜像

```bash
cd deploy
cp .env.example .env
# 将镜像相关变量指向已发布的镜像仓库，再带 profile 启动。
docker compose --profile local-redis --profile python-orchestrator up -d
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

# 启动服务（单进程，JOYSAFETER_SERVICE_ROLE=all 在一个进程内运行三种角色）
uv run uvicorn app.main:app --reload --port 8000
```

> 若需按服务拆分运行（与 compose 部署一致），请分别用各自的入口启动 ——
> `app.joysafeter_api.main:app`、`app.joysafeter_orchestrator.main:app`、
> `app.joysafeter_worker.main:app`，并相应设置 `JOYSAFETER_SERVICE_ROLE`。
> 详见 [DEVELOPMENT.md](DEVELOPMENT.md)。

</details>

<details>
<summary><strong>前端安装</strong></summary>

```bash
cd frontend

# 安装依赖
bun install

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
