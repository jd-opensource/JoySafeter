# JoySafeter 安装指南

以下是全面的部署说明。根据您的需求，选择适合您的部署方案。

## 环境要求

- Docker 20.10+ 与 Docker Compose 2.0+
- Python 3.12+ 与 Node.js 20+（仅本地开发需要）
- PostgreSQL/Redis 在 Docker 部署场景下会自动包含

## 推荐：Docker Compose 部署

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` 会创建缺失的 env 文件，并检查 Docker、Compose、Docker daemon CPU 架构、
SkillSpector 源码、Docker socket、端口和 Compose 配置；它不启动容器。`local` 会重复
这些检查，启动 PostgreSQL/Redis/SkillSpector，等待本地 Redis 就绪，执行数据库迁移，然后启动完整本地栈。

访问地址：

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

后端运行时拆分为 Python `api`、Rust `orchestrator-rs`、Python `worker` 三个服务，同时配套
PostgreSQL、Redis、Envoy（每沙箱出站代理）与 SkillSpector（Skill 安全扫描服务）。Python
orchestrator profile 已移除；本地和容器化部署都通过 `deploy.sh local` 使用 `rust-orchestrator`
profile。生产、云数据库/云 Redis、镜像构建等场景请以 [deploy/README.md](deploy/README.md) 为准。
服务职责、运行时拓扑、数据流和部署方案选择见 [docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)。

## 使用预构建的 Docker 镜像

```bash
cd deploy
./deploy.sh doctor

# pull 成功后会把 BACKEND_FULL_IMAGE、FRONTEND_FULL_IMAGE、
# ORCHESTRATOR_RS_FULL_IMAGE、SKILLSPECTOR_FULL_IMAGE 写入 deploy/.env。
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
docker compose --profile local-redis --profile rust-orchestrator up -d --no-build
```

这些核心部署镜像均支持多架构（amd64, arm64）。

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
./deploy.sh doctor
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

# 启动 API
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --reload --host 0.0.0.0 --port 8000
```

> 若需与 Compose 运行时一致，还要启动 Rust orchestrator 和 worker：
>
> ```bash
> cd backend/app/joysafeter_orchestrator_rs
> JOYSAFETER_GRPC_HOST=0.0.0.0 JOYSAFETER_GRPC_PORT=9090 cargo run --release
>
> cd backend
> JOYSAFETER_SERVICE_ROLE=worker \
> uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1
> ```
>
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

## 问题解答

- 先运行 `cd deploy && ./deploy.sh doctor`。它会验证 `./deploy.sh local` 依赖的 env、平台、
  Docker socket、端口、SkillSpector 和 Compose 配置。
- Apple Silicon 或 Colima 环境建议让 `deploy.sh local` 自动识别 Docker daemon 架构；也可以用
  `./deploy.sh local --arch arm64` 强制指定。
- 如果绕过脚本手工启动 Compose 后发现数据库表缺失，且使用本地 Redis，运行
  `docker compose --profile local-redis --profile rust-orchestrator --profile init run --rm db-init`。
- 如果使用云 Redis，不启用 `local-redis` profile，并在 `deploy/.env` 设置 `REDIS_URL`；云
  Redis 迁移使用 `docker compose --profile rust-orchestrator --profile init run --rm db-init`。云
  PostgreSQL 同理覆盖 `POSTGRES_*` 变量。
