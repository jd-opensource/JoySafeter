# Deploy

部署只保留两个入口：

## 1. Docker Compose 一键部署

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

docker compose up -d --build
```

这一个 Compose 文件会直接 build 并启动：

- `db`：PostgreSQL
- `redis`：Redis
- `api`：后端 API，端口 `8000`
- `orchestrator`：调度 / gRPC / sandbox 生命周期，gRPC 端口 `9090`
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

可选 MCP：

```bash
docker compose --profile mcp up -d mcpserver
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

- `orchestrator` 会挂载 Docker socket 创建 sandbox，生产只能放在可信机器。
- 如果 sandbox 需要跨机器回连，修改 `deploy/.env` 里的 `JOYSAFETER_GRPC_PUBLIC_URL`。
