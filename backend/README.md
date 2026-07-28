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

Python 进程只承载 API 与 worker；orchestrator 已迁移到 Rust。生产或压测时使用显式服务角色：

```bash
# API：HTTP、WebSocket、管理接口
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --host 0.0.0.0 --port 8000

# Orchestrator：gRPC AgentBridge、scheduler、sandbox/task lifecycle
JOYSAFETER_INSTANCE_ID=orchestrator-001 \
JOYSAFETER_GRPC_HOST=0.0.0.0 \
JOYSAFETER_GRPC_PORT=9090 \
cargo run --manifest-path app/joysafeter_orchestrator_rs/Cargo.toml --release

# Worker：Redis Stream consumer、批量事件落库
JOYSAFETER_SERVICE_ROLE=worker \
WORKER_HTTP_HOST=127.0.0.1 \
uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1
```

入口说明：

- 显式 Python 入口：`app.joysafeter_api.main:app`、`app.joysafeter_worker.main:app`。
- Rust orchestrator 入口：`app/joysafeter_orchestrator_rs`。
- 单机云虚拟机部署建议只对公网暴露 API；Worker HTTP 监听 `127.0.0.1:8002`，Orchestrator gRPC 监听 `0.0.0.0:9090` 供沙箱容器访问，并通过云安全组/防火墙禁止公网访问 `9090`。

注意事项：

- Rust orchestrator 需要扩容时启动多个实例，并为每个实例配置唯一 `JOYSAFETER_INSTANCE_ID`。
- 三个服务共享同一套 PostgreSQL / Redis；服务之间通过 DB 状态和 Redis 唤醒/协调通信。
- 三服务模式建议开启 `JOYSAFETER_EVENT_STREAM_ENABLED=true`，让 orchestrator 把高频 JoySafeter event 写入 Redis Stream，再由 `worker` 批量消费落库。
- `JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB=true` 时，如果 orchestrator 写 Redis Stream 失败，会自动降级为本地 DB 落库，避免事件直接丢失。
- worker 只有在批量落库成功后才 ACK Redis Stream；未 ACK 的 pending 消息会在 `JOYSAFETER_EVENT_STREAM_PENDING_IDLE_MS` 后被其他 worker 自动认领恢复。

Docker Compose 可启动完整本地三服务栈：

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` 只做 Docker/Compose/env/SkillSpector/socket/端口预检，不启动容器；
`local` 会自动按 Docker daemon CPU 架构选择平台、运行数据库迁移并启动完整栈。

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
├── joysafeter_orchestrator_rs/    # Rust orchestrator：gRPC、scheduler、sandbox/task lifecycle
│   ├── src/grpc/            # orchestrator gRPC server + protobuf
│   ├── src/kernel/          # queue、scheduler、task/sandbox controller、task runner
│   ├── src/events/          # JoySafeter event bus、mapping、Redis Stream publisher
│   ├── src/runtime/         # Claude/Codex/mock runtime adapters
│   └── src/sandbox/         # Docker/Daytona/E2B sandbox providers
├── joysafeter_worker/       # Worker 服务：Redis Stream consumer、批量事件落库
│   ├── events/              # batch writer + stream consumer
│   ├── lifecycle.py         # worker loops start/stop
│   ├── main.py              # Worker ASGI 入口 app.joysafeter_worker.main:app
│   ├── services.py          # worker-facing service facade
│   └── startup.py           # worker 专属初始化/关闭
├── joysafeter_shared/       # 跨服务共享基础设施（runtime/common/utils/storage/templates）
└── joysafeter_domain/       # 领域层真实实现（models/repositories/schemas/services/contracts/ports/state_machines）
```

> 完整架构文档：[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | [中文版](../docs/ARCHITECTURE_CN.md)

## API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Triggers 触发器

触发器让 Agent **自动运行**：按 cron 周期或一次性时间（`type=cron`），或被入站签名 webhook（`type=webhook`）触发。所有触发器统一走 `/api/v1/triggers`（旧的 `/schedules` 已下线）。cron 触发由 worker 内的 scheduler 以 `FOR UPDATE SKIP LOCKED` 认领执行，内置重试/退避，连续失败达到阈值会自动禁用（dead-letter）。

### 端点一览

| 方法 & 路径 | 说明 |
|---|---|
| `POST /api/v1/triggers` | 创建（`type` = `cron` \| `webhook`） |
| `GET /api/v1/triggers?type=cron` | 列出（可按 `type` 过滤） |
| `GET /api/v1/triggers/{id}` | 详情 |
| `PATCH /api/v1/triggers/{id}` | 更新（改 `enabled` 即启停；重新启用会清除 dead-letter 并重算下次运行） |
| `DELETE /api/v1/triggers/{id}` | 删除 |
| `POST /api/v1/triggers/{id}/run` | 手动“立即运行”（用 `Idempotency-Key` 头去重） |
| `GET /api/v1/triggers/{id}/runs` | 运行历史 |
| `POST /api/v1/triggers/{id}/webhook` | 入站签名 webhook 触发（限流 60/min） |
| `POST /api/v1/triggers/{id}/test` | Owner 测试触发（禁用状态也能验证） |
| `GET /api/v1/triggers/{id}/webhook-sample` | 返回带正确 HMAC 签名的 cURL 示例 |

### 创建 cron 触发器

```bash
curl -X POST http://localhost:8000/api/v1/triggers \
  -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "daily-report",
    "type": "cron",
    "agent_id": "<agent-uuid>",
    "prompt_template": "生成今天的巡检报告",
    "cron_expr": "0 9 * * *",
    "timezone": "Asia/Shanghai",
    "concurrency_policy": "forbid",
    "session_mode": "fresh"
  }'
```

- cron 触发必须提供 `cron_expr`（标准 5 字段）**或** 一次性 `run_at`（未来时间），二选一。
- `concurrency_policy`：`allow`（默认）/ `forbid`（上次还在跑就跳过）/ `replace`（取消旧的再跑）。
- `session_mode`：`fresh`（每次新会话）/ `reuse`（空闲则复用）/ `pinned`（投递到指定 `pinned_session_id`）/ `keyed`（按渲染出的 `session_key` 分桶，每键一个会话）。

### 创建 webhook 触发器

```bash
curl -X POST http://localhost:8000/api/v1/triggers \
  -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "on-alert",
    "type": "webhook",
    "agent_id": "<agent-uuid>",
    "prompt_template": "处理告警：{{ body.alert.name }}",
    "secret_ref": "<vault-key>",
    "auth_methods": ["hmac"]
  }'
```

- 外部系统 `POST /api/v1/triggers/{id}/webhook`，用 `secret_ref` 指向的密钥做 HMAC-SHA256 签名（头 `X-JoySafeter-Signature`）；也支持 `bearer` / `token`。
- 用 `GET /api/v1/triggers/{id}/webhook-sample` 拿到可直接跑的带签名 cURL 示例；上线前用 `POST /{id}/test` 验证。
- prompt 模板可引用载荷变量，如 `{{ body.alert.name }}`、`{{ fired_at }}`、`{{ cron.cron_expr }}`。

> 前端在 `/managed/triggers` 提供统一的 Cron / Webhook 标签页界面。

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
