# Deploy

部署只保留两个入口：

## 1. Docker Compose 一键部署

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# Python orchestrator
docker compose --profile python-orchestrator up -d --build

# 或者：Rust orchestrator
docker compose --profile rust-orchestrator up -d --build
```

这一个 Compose 文件会直接 build 并启动：

- `db`：PostgreSQL
- `redis`：Redis
- `skillspector`：内部 Skill 安全扫描服务，API 在创建、更新、导入和文件变更时调用
- `api`：后端 API，端口 `8000`
- `orchestrator`：Python 版调度 / gRPC / sandbox 生命周期，gRPC 端口 `9090`，HTTP health 端口 `8001`
- `orchestrator-rs`：Rust 版调度 / gRPC / sandbox 生命周期，gRPC 端口 `9090`
- `worker`：后台任务 / reaper / 事件落库
- `frontend`：前端，端口 `3000`

访问：

- 前端：`http://localhost:3000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

常用命令：

```bash
docker compose ps
docker compose logs -f api orchestrator worker
docker compose down
```

两个 orchestrator 版本不能同时启动，因为都会使用 `joysafeter-orchestrator` 容器名和 `9090` 端口。

Skill 安全扫描默认开启。`deploy/.env` 里的 `SKILLSPECTOR_SOURCE_PATH` 默认指向与 JoySafeter 同级的 `../../SkillSpector`，生产构建时要确保该源码目录存在，或预先构建并推送 `SKILLSPECTOR_FULL_IMAGE`。扫描失败时默认 fail-closed，写入会被拒绝。

单独构建 Rust orchestrator 镜像：

```bash
cd ..
docker build \
  -f deploy/docker/orchestrator-rs.Dockerfile \
  -t joysafeter-orchestrator-rs:latest \
  .
```

启用 `rust-orchestrator` profile 时，Compose 会 build 并使用 `joysafeter-orchestrator-rs:latest`。如果要推到私有仓库，可设置：

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

- Python 版 orchestrator 暴露 `8001 /health`；Rust 版 orchestrator 当前只暴露 gRPC `9090`。
- `orchestrator` 会挂载 Docker socket 创建 sandbox，生产只能放在可信机器。
- 如果 sandbox 需要跨机器回连，修改 `deploy/.env` 里的 `JOYSAFETER_GRPC_PUBLIC_URL`。
## Remote Docker Compose Deployment

Use `docker-compose.remote.yml` when PostgreSQL and Redis are cloud services and only JoySafeter services run on the VM.

### Services

- `frontend`: Next.js production server, default host port `3000`.
- `api`: JoySafeter API service, default host port `8000`.
- `orchestrator`: Rust orchestrator gRPC service, default host port `9090`.
- `worker`: Python worker/event consumer, health port bound to `127.0.0.1:8002`.
- `db-init`: one-shot Alembic migration job, enabled only with `--profile init`.

### First Deploy

```bash
cd deploy
cp .env.remote.example .env.remote
# Edit .env.remote and replace all CHANGE_ME values.

# Run DB migrations against cloud PostgreSQL.
docker compose --env-file .env.remote -f docker-compose.remote.yml --profile init up db-init

# Start all runtime services.
docker compose --env-file .env.remote -f docker-compose.remote.yml up -d --build

# Check status and logs.
docker compose --env-file .env.remote -f docker-compose.remote.yml ps
docker compose --env-file .env.remote -f docker-compose.remote.yml logs -f api orchestrator worker frontend
```

### Required External Services

- Cloud PostgreSQL must be reachable from the VM and configured through `DATABASE_URL` plus `POSTGRES_*` fields.
- Cloud Redis must be reachable from the VM and configured through `REDIS_URL`; use `rediss://` if the provider requires TLS.
- Sandbox Docker images must exist on the VM or be pullable by Docker:
  - `joysafeter-claudecode:latest`
  - `joysafeter-codex:latest`

### Important Networking Notes

- `JOYSAFETER_GRPC_PUBLIC_URL` is the address sandbox containers use to connect back to `orchestrator:9090`.
  On Linux VMs, set it to the VM private IP, for example `http://10.0.0.12:9090`.
- The orchestrator mounts `/var/run/docker.sock` so it can create sandbox containers. Deploy it only on trusted hosts and firewall `9090` to trusted networks.
- Put Nginx/Caddy/SLB in front of `frontend:3000` and `api:8000` for HTTPS public access.
