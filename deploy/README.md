# Deploy

部署只保留两个入口：

## 1. Docker Compose 一键部署

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# 全本地：PostgreSQL + Redis + Rust orchestrator
docker compose --profile local-redis --profile rust-orchestrator up -d --build

```

这一个 Compose 文件会直接 build 并启动：

- `db`：PostgreSQL
- `redis`：Redis（仅在启用 `local-redis` profile 时启动；使用云 Redis 时改 `deploy/.env` 的 `REDIS_URL`）
- `skillspector`：内部 Skill 安全扫描服务，API 在创建、更新、导入和文件变更时调用
- `api`：后端 API，端口 `8000`
- `orchestrator-rs`：Rust 版调度 / gRPC / sandbox 生命周期，gRPC 端口 `9090`
- `worker`：Redis Stream 消费 / 批量事件落库
- `frontend`：前端，端口 `3000`

访问：

- 前端：`http://localhost:3000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

`deploy/.env` 中的 `BACKEND_URL` 会注入前端为 `NEXT_PUBLIC_API_URL`，`FRONTEND_URL`
会注入为 `NEXT_PUBLIC_APP_URL`；上线时这两个值必须改成浏览器能访问的真实 HTTPS 地址。

常用命令：

```bash
docker compose ps
docker compose logs -f api orchestrator-rs worker
docker compose down
```

Python orchestrator 源码已移除；本地和容器化部署都使用 `rust-orchestrator`
profile。也可以通过 `ORCHESTRATOR_RS_FULL_IMAGE` 指向预构建镜像。

如果使用云 Redis，不要启用 `local-redis` profile；把 `deploy/.env` 里的 `REDIS_URL` 改成云 Redis 内网地址即可：

```bash
docker compose --profile rust-orchestrator up -d --build
```

Skill 安全扫描默认开启。`deploy/.env` 里的 `SKILLSPECTOR_SOURCE_PATH` 默认指向与 JoySafeter 同级的 `../../SkillSpector`，生产构建时要确保该源码目录存在，或预先构建并推送 `SKILLSPECTOR_FULL_IMAGE`。草稿写入路径在扫描器故障时会记录 `failed`/`scanning` 状态并允许保存；运行时只会打包 `approved` 且扫描状态为 `passed`/`warning`、内容未漂移的技能。

单独构建 Rust orchestrator 镜像：

```bash
cd ..
docker build \
  -f deploy/docker/orchestrator-rs.Dockerfile \
  -t joysafeter-orchestrator-rs:latest \
  .
```

启用 `rust-orchestrator` profile 时，Compose 会 build 并使用 `joysafeter-orchestrator-rs:latest`。如果已另行提供可用源码或预构建镜像，可设置：

```bash
ORCHESTRATOR_RS_FULL_IMAGE=registry.example.com/joysafeter-orchestrator-rs:v0.3.2 \
docker compose --profile rust-orchestrator build orchestrator-rs
```

## 2. 本地测试一键启动

如果想在本机直接跑后端/前端，只让 Docker 提供 PostgreSQL/Redis：

```bash
cd deploy
./local-test.sh
```

脚本会自动：

- 创建缺失的 `.env`
- 启动 `db` / `redis`
- 执行数据库迁移
- 本地启动 `api` / `orchestrator` / `worker`
- 本地启动前端 `bun run dev`

按 `Ctrl+C` 停止本地进程。PostgreSQL/Redis 用下面命令停止：

```bash
cd deploy
docker compose down
```

## 镜像工具

普通部署不需要单独用它，直接 `docker compose up -d --build` 即可。只有需要构建/推送镜像时再用：

```bash
cd deploy
./deploy.sh build
./deploy.sh build --all
./deploy.sh push
./deploy.sh pull
```

## 注意

- Python 版 orchestrator 暴露 `8001 /health`；实验 Rust 版 orchestrator 当前只暴露 gRPC `9090`。
- `orchestrator` 会挂载 Docker socket 创建 sandbox，生产只能放在可信机器。
- 如果 sandbox 需要跨机器回连，修改 `deploy/.env` 里的 `JOYSAFETER_GRPC_PUBLIC_URL`。

当前仓库只保留 `deploy/docker-compose.yml` 这一份 Compose 文件。云 Redis / 云 PostgreSQL 场景仍使用同一文件，通过 `deploy/.env` 覆盖 `POSTGRES_*`、`REDIS_URL`、镜像名、端口和 `JOYSAFETER_GRPC_PUBLIC_URL`。
