# JoySafeter Backend

JoySafeter 的后端服务（FastAPI），提供 API、鉴权、多租户、技能系统、任务调度、沙箱编排与事件落库能力。

> 说明：本文件只保留 **后端本地开发** 的最短路径；Docker/生产部署请统一以 `deploy/` 文档为准，避免重复与不一致。

## 快速开始（本地开发）

### 1) 安装依赖（uv）

```bash
cd backend
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv sync
```

> PyPI 镜像（可选）：通过环境变量 `UV_INDEX_URL` 或在 `.env` 中设置。项目默认使用清华镜像以加速下载。

### 2) 配置环境变量

```bash
cp env.example .env
# 按需修改 .env
```

### 3) 准备数据库并迁移

如果要一键启动本地测试环境，直接运行：

```bash
cd ../deploy
./local-test.sh
```

如果只想手动启动后端，请先自行准备 PostgreSQL/Redis，然后执行迁移：

```bash
cd backend
alembic upgrade head
```

### 4) 启动后端

```bash
cd backend
uv run uvicorn app.joysafeter_api.main:app --reload --host 0.0.0.0 --port 8000
```

## 三服务启动方式

本地开发默认仍可使用 `JOYSAFETER_SERVICE_ROLE=all` 单进程兼容模式。生产或压测时使用同一套代码拆成三个显式服务角色：

```bash
# API：HTTP、WebSocket、管理接口
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --host 0.0.0.0 --port 8000

# Orchestrator：gRPC AgentBridge、scheduler、sandbox/task lifecycle
JOYSAFETER_SERVICE_ROLE=orchestrator \
JOYSAFETER_INSTANCE_ID=orchestrator-001 \
ORCHESTRATOR_HTTP_HOST=127.0.0.1 \
JOYSAFETER_GRPC_HOST=0.0.0.0 \
JOYSAFETER_GRPC_PORT=9090 \
uv run uvicorn app.joysafeter_orchestrator.main:app --host 127.0.0.1 --port 8001 --workers 1

# Worker：Redis Stream consumer、批量事件落库
JOYSAFETER_SERVICE_ROLE=worker \
WORKER_HTTP_HOST=127.0.0.1 \
uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1
```

入口说明：

- 显式三服务入口：`app.joysafeter_api.main:app`、`app.joysafeter_orchestrator.main:app`、`app.joysafeter_worker.main:app`。
- 旧单体兼容入口：`app.main:app`，会根据 `JOYSAFETER_SERVICE_ROLE` 决定是否同时启动 orchestrator/worker 逻辑；新部署建议直接使用显式三服务入口。
- 单机云虚拟机部署建议只对公网暴露 API；Orchestrator/Worker HTTP 监听 `127.0.0.1:8001/8002`，Orchestrator gRPC 监听 `0.0.0.0:9090` 供沙箱容器访问，并通过云安全组/防火墙禁止公网访问 `9090`。

注意事项：

- `orchestrator` 不建议使用 `uvicorn --workers N`；需要扩容时启动多个 orchestrator 实例，并为每个实例配置唯一 `JOYSAFETER_INSTANCE_ID`。
- 三个服务共享同一套 PostgreSQL / Redis；服务之间通过 DB 状态和 Redis 唤醒/协调通信。
- 三服务模式建议开启 `JOYSAFETER_EVENT_STREAM_ENABLED=true`，让 orchestrator 把高频 JoySafeter event 写入 Redis Stream，再由 `worker` 批量消费落库。
- `JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB=true` 时，如果 orchestrator 写 Redis Stream 失败，会自动降级为本地 DB 落库，避免事件直接丢失。
- worker 只有在批量落库成功后才 ACK Redis Stream；未 ACK 的 pending 消息会在 `JOYSAFETER_EVENT_STREAM_PENDING_IDLE_MS` 后被其他 worker 自动认领恢复。

Docker Compose 可启动完整本地三服务栈：

```bash
cd deploy
docker compose --profile local-redis --profile python-orchestrator up -d db redis api orchestrator worker frontend
```

## 项目结构

```
app/
├── joysafeter_api/          # API 服务：HTTP routes、WebSocket、API startup hooks、API service facade
│   ├── api/                 # /api/v1 REST 路由（canonical 路径）
│   ├── websocket/           # /ws/notifications
│   ├── app.py               # API app 组装：挂载 API / WebSocket
│   ├── main.py              # API ASGI 入口 app.joysafeter_api.main:app
│   ├── services.py          # API-facing service facade
│   └── startup.py           # API 专属初始化
├── joysafeter_orchestrator/       # Orchestrator 服务：gRPC gateway、scheduler、sandbox/task lifecycle
│   ├── grpc/                # orchestrator gRPC server + protobuf
│   ├── kernel/              # queue、scheduler、task/sandbox controller、task runner
│   ├── events/              # JoySafeter event bus、mapping、Redis Stream publisher
│   ├── runtime/             # Claude/Codex/mock runtime adapters
│   ├── sandbox/             # Docker/Daytona/E2B sandbox providers
│   ├── lifespan.py          # orchestrator 内核启动/关闭
│   ├── main.py              # Orchestrator ASGI 入口 app.joysafeter_orchestrator.main:app
│   └── services.py          # orchestrator-facing service facade
├── joysafeter_worker/       # Worker 服务：Redis Stream consumer、批量事件落库
│   ├── events/              # batch writer + stream consumer
│   ├── lifecycle.py         # worker loops start/stop
│   ├── main.py              # Worker ASGI 入口 app.joysafeter_worker.main:app
│   ├── services.py          # worker-facing service facade
│   └── startup.py           # worker 专属初始化/关闭
├── joysafeter_shared/       # 跨服务共享基础设施（runtime/common/utils/storage/templates）
├── joysafeter_domain/       # 领域层真实实现（models/repositories/schemas/services/contracts/ports/state_machines）
└── main.py                  # 旧单进程兼容入口 app.main:app
```

> 完整架构文档：[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | [中文版](../docs/ARCHITECTURE_CN.md)

## API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 常用命令

### 数据库迁移

```bash
# 创建迁移
alembic revision --autogenerate -m "description"

# 应用迁移
alembic upgrade head

# 回滚 1 个版本
alembic downgrade -1
```

### 测试

```bash
uv sync --dev
pytest
pytest --cov=app
```

## 部署入口（统一文档）

- 一键启动 / 场景化脚本 / 生产部署：[`deploy/README.md`](../deploy/README.md)

## License

Apache 2.0
