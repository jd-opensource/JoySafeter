# Deploy

部署只保留两个入口：

## 1. Docker Compose 一键部署

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`deploy.sh doctor` 会创建缺失的 `deploy/.env`、`backend/.env`、`frontend/.env`，所以它不是
只读命令；但它不会启动容器。`deploy.sh local` 会按 Docker daemon 的 CPU 架构自动选择平台，例如 Colima
arm64 会使用 `linux/arm64`，远程 amd64 Docker daemon 会使用 `linux/amd64`。
脚本会创建缺失的 `.env`，并把 compose 构建所需的基础镜像切到 Docker
Official Images 的多架构镜像源，避免单架构镜像在 arm64 上误走 amd64/QEMU。
它还会在缺失时自动克隆 NVIDIA SkillSpector 到 `.deps/SkillSpector`，预检
Docker socket / Compose 配置 / 常用端口，等待本地 Redis 就绪，并在启动完整服务前运行数据库迁移。
`doctor` 只做环境准备和预检，不启动容器；`local` 会执行完整部署。

`deploy.sh local` 会先用脚本控制的 Buildx 路径构建核心镜像，再用这个 Compose 文件启动：

- `db`：PostgreSQL
- `redis`：Redis（仅在启用 `local-redis` profile 时启动；使用云 Redis 时改 `deploy/.env` 的 `REDIS_URL`）
- `skillspector`：内部 Skill 安全扫描服务，API 在创建、更新、导入和文件变更时调用
- `joysafeter-envoy`：沙箱出站白名单和 gRPC 回连通道。没有 profile，任何 `up` 都会启动；它会空闲等待 orchestrator 写入 bootstrap 配置，所以 `docker compose ps` 里看到它 running 但暂时不转发流量是正常的
- `api`：后端 API，端口 `8000`
- `orchestrator-rs`：Rust 版调度 / gRPC / sandbox 生命周期，gRPC 端口 `9090`
- `worker`：Redis Stream 消费 / 批量事件落库
- `frontend`：前端，端口 `3000`

`deploy.sh local` 只构建并启动上面这些控制面服务，不会构建 agent 运行镜像（`joysafeter-claudecode` / `joysafeter-codex` / `joysafeter-native`）。默认 `JOYSAFETER_SANDBOX_IMAGE=joysafeter-claudecode:latest` 缺失时脚本只告警、不阻断：控制面能起来，但真实 agent 任务会因拉不到运行镜像而失败。跑第一个 agent 前先构建或拉取运行镜像：

```bash
./deploy.sh build --claudecode-only --arch arm64   # 或 --arch amd64
# 或使用预构建镜像
./deploy.sh pull --runtime-only --registry registry.example.com/your-org --tag v0.3.2
```

## 协同拓扑和职责

本项目当前不是 Python 单体，也不是 API 直接执行 Agent。生产运行时按下面的协同边界拆分：

| 层 | 组件 | 职责 | 扩容/替换边界 |
|---|---|---|---|
| 入口层 | `frontend` | Next.js UI，连接 API 和 SSE | 可独立横向扩容；只依赖 `BACKEND_URL` / `FRONTEND_URL` |
| 控制面 | `api` | Auth/RBAC、REST、任务创建、Skill 写入扫描、SSE 回放/实时桥接 | 可横向扩容；必须共享同一 PostgreSQL / Redis |
| 调度面 | `orchestrator-rs` | DB 权威调度、任务租约、sandbox 生命周期、runner gRPC、事件发射 | 可多实例，但每个实例必须有唯一 `JOYSAFETER_INSTANCE_ID` |
| 执行面 | sandbox container + `sandbox-runner` | 在隔离容器内运行 Claude/Codex/native harness，所有出站经 Envoy | 按 session/task 动态创建；镜像由 agent runtime 镜像变量控制 |
| 持久化面 | `worker` | 消费 Redis Stream，批量写入 `joysafeter_session_events`，写后再发布实时事件 | 可横向扩容；依赖 Redis consumer group 和 Postgres advisory lock 去重 |
| 安全面 | `skillspector` | Skill 内容静态扫描；运行时闸门仍由 JoySafeter Skill 逻辑执行 | CPU 密集，可用 `SKILLSPECTOR_WORKERS` / `SKILLSPECTOR_CPUS` 调整 |
| 状态层 | PostgreSQL | task/session/sandbox/skill/auth/event log 权威状态 | 本地用 `db`；生产建议云 PostgreSQL / 托管 PostgreSQL |
| 协调层 | Redis | task wakeup list、event Stream、Pub/Sub、命令 relay、ownership heartbeat | 本地用 `local-redis`；生产建议云 Redis / 托管 Redis |
| 网络隔离 | Envoy | 每沙箱出站白名单和 gRPC 回连通道 | 生产要把 Docker socket 和 Envoy 配置放在可信宿主机 |

关键规则：

- API 只创建任务和发出 Redis 唤醒，不直接运行 harness，不直接创建 sandbox。
- Orchestrator 从 PostgreSQL 认领 pending task；Redis list 只是唤醒信号，不是调度权威。
- Runner 只在 sandbox 内执行，并通过 gRPC `AgentBridge` 回连 orchestrator。
- Worker 是事件可靠落库主路径；浏览器实时流可先收到 Pub/Sub，刷新后以 Postgres 事件日志回放为准。
- SkillSpector 给出扫描 verdict；Skill 是否能被打包运行由 JoySafeter 的审批、扫描状态和内容漂移检查共同决定。

## 核心数据流

```text
Browser
  -> frontend
  -> api: POST /api/v1/sessions/{id}/events
  -> PostgreSQL: create task/session state
  -> Redis list: wake up orchestrator
  -> orchestrator-rs: claim task from PostgreSQL, create/reuse sandbox
  -> sandbox-runner: SetupSandbox + StartTask over gRPC
  -> harness: Claude/Codex/native executes tools/MCP/skills
  -> orchestrator-rs: runner events over gRPC
  -> Redis Stream: durable event path
  -> worker: batch persist events into PostgreSQL with seq/dedup
  -> Redis Pub/Sub: live fan-out
  -> api SSE: replay from DB, then live events
  -> Browser
```

更完整的拓扑图、序列图、通道表和故障归属见
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) / [`docs/ARCHITECTURE_CN.md`](../docs/ARCHITECTURE_CN.md)。

访问：

- 前端：`http://localhost:3000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

`deploy/.env` 中的 `BACKEND_URL` 会在容器运行时注入前端为 `NEXT_PUBLIC_API_URL`，`FRONTEND_URL`
会注入为 `NEXT_PUBLIC_APP_URL`；上线时这两个值必须改成浏览器能访问的真实 HTTPS 地址。

环境变量按"唯一真相源"管理：`backend/env.example` 定义后端所有变量，`frontend/env.example` 定义前端所有变量，`deploy/.env.example` 只列出部署差异覆盖项。新增变量只需改对应的 `env.example`。

常用命令：

```bash
docker compose ps
docker compose logs -f api orchestrator-rs worker
docker compose down
```

`deploy.sh` 支持的部署/镜像模式：

| 命令 | 作用 | 是否启动容器 |
|---|---|---|
| `./deploy.sh doctor` | 准备 env、探测 CPU 架构、检查 Docker/Compose/SkillSpector/socket/端口/Compose 配置 | 否 |
| `./deploy.sh local` | 完整本地 Compose 部署：基础服务、迁移、API/Rust orchestrator/worker/frontend | 是 |
| `./deploy.sh build` | 构建核心部署镜像：backend、frontend、orchestrator-rs、skillspector | 否 |
| `./deploy.sh build --all` | 构建核心部署镜像与 agent runtime 镜像 | 否 |
| `./deploy.sh push` | 构建并推送核心部署镜像到 `DOCKER_REGISTRY` | 否 |
| `./deploy.sh pull` | 从 `DOCKER_REGISTRY` 拉取核心部署镜像 | 否 |

常用参数：

| 参数 | 适用命令 | 说明 |
|---|---|---|
| `--arch arm64` / `--arch amd64` | `local`、`build`、`push` | 强制目标平台；不传时 `local` 按 Docker daemon 自动识别 |
| `--platform linux/amd64,linux/arm64` | `build`、`push` | 构建多架构 manifest |
| `--backend-only` / `--frontend-only` / `--orchestrator-only` / `--skillspector-only` | `build`、`push`、`pull` | 只处理单类核心部署镜像 |
| `--runtime-only` / `--claudecode-only` / `--codex-only` / `--native-only` | `build`、`push`、`pull` | 只处理 agent runtime 镜像 |
| `--api-url URL` | `build`、`push` | （已废弃）前端 API 地址现在通过容器环境变量运行时注入 |
| `--no-cache` | `build`、`push` | 禁用 Docker 构建缓存 |
| `--mirror MIRROR` | `build`、`push` | 只用于手工镜像构建；本地 `local` 默认使用 `public.ecr.aws/docker/library/` 多架构基础镜像 |
| `--pip-mirror MIRROR` | `build`、`push` | 切换 Python 包下载镜像 |

健康检查：

```bash
curl http://localhost:8000/health
curl -I http://localhost:8000/docs
curl -I http://localhost:3000
```

如果要手工指定平台：

```bash
./deploy.sh local --arch arm64
./deploy.sh local --arch amd64
```

如果跳过脚本直接运行 compose，确保 `deploy/.env` 中至少包含：

```dotenv
DOCKER_DEFAULT_PLATFORM=linux/arm64
BASE_IMAGE_REGISTRY=public.ecr.aws/docker/library/
RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm
RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim
DB_IMAGE=public.ecr.aws/docker/library/postgres:15
REDIS_IMAGE=public.ecr.aws/docker/library/redis:alpine3.22
SKILLSPECTOR_SOURCE_PATH=../.deps/SkillSpector
```

Python orchestrator 源码已移除；本地和容器化部署都使用 `rust-orchestrator`
profile。也可以通过 `ORCHESTRATOR_RS_FULL_IMAGE` 指向预构建镜像。

如果使用云 Redis，不要启用 `local-redis` profile；把 `deploy/.env` 里的 `REDIS_URL` 改成云 Redis 内网地址即可：

```bash
./deploy.sh doctor
./deploy.sh build --arch arm64   # 或 --arch amd64
docker compose --profile rust-orchestrator up -d --no-build
```

`doctor` 会先写入 `DOCKER_DEFAULT_PLATFORM` 和多架构镜像默认值；随后手工运行 compose 时会复用 `deploy/.env`。

Skill 安全扫描默认开启。`deploy/.env` 里的 `SKILLSPECTOR_SOURCE_PATH` 默认指向 `.deps/SkillSpector`，`deploy.sh local` 会在缺失时自动从 NVIDIA 仓库克隆；生产构建时要确保该源码目录存在，或预先构建并推送 `SKILLSPECTOR_FULL_IMAGE`。草稿写入路径在扫描器故障时会记录 `failed`/`scanning` 状态并允许保存；运行时只会打包 `approved` 且扫描状态为 `passed`/`warning`、内容未漂移的技能。

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
- 本地启动 Python `api` / Rust `orchestrator-rs` / Python `worker`
- 本地启动前端 `bun run dev`

按 `Ctrl+C` 停止本地进程。PostgreSQL/Redis 用下面命令停止：

```bash
cd deploy
docker compose down
```

## 镜像工具

普通本地部署使用 `local`，它会自动处理 CPU 架构和本地 `.env`。只有需要单独构建/推送/拉取镜像时再用 `build` / `push` / `pull`。默认处理核心部署镜像：backend、frontend、orchestrator-rs、skillspector；agent runtime 镜像用 `--runtime-only` 或 `--all` 纳入。

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
./deploy.sh build
./deploy.sh build --all
./deploy.sh push
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
```

`pull` 成功后会同步 `deploy/.env` 中被拉取镜像对应的变量，后续 `docker compose up --no-build` 会使用本次拉取的镜像。核心部署镜像支持多架构 buildx push。agent runtime 镜像依赖按架构生成的 runner 二进制和 Dockerfile，当前脚本只支持单架构构建；构建 runtime 时显式指定 `--arch amd64` 或 `--arch arm64`。如果 `push --all` 或 `--runtime-only` 触发多架构 runtime 构建，脚本会在任何镜像构建/推送前拒绝执行，避免出现只推送一部分镜像的发布状态。

## 部署方案选择

| 方案 | 命令 / 做法 | 适用场景 | 注意事项 |
|---|---|---|---|
| 全本地 Compose | `./deploy.sh doctor && ./deploy.sh local` | 新用户、本机验证、单机 demo | 会启动 PostgreSQL/Redis/SkillSpector/Envoy/API/orchestrator/worker/frontend；不构建 agent 运行镜像，跑真实 agent 前需先 `build --claudecode-only` 或 `pull --runtime-only` |
| 宿主机本地开发 | `./local-test.sh` | 开发 API/Rust/Worker/Frontend，数据库和 Redis 仍用 Docker | Python/Node/Rust 进程跑在宿主机；普通用户不要把它当生产部署 |
| 云 Redis / 本地 PostgreSQL | `./deploy.sh build --arch <arch>` 后手工 `docker compose --profile rust-orchestrator up -d --no-build` | Redis 已托管，其他服务仍在单机 | 不启用 `local-redis` profile，设置 `REDIS_URL` |
| 云 Redis + 云 PostgreSQL | 同一 compose 文件，覆盖 `REDIS_URL` 和 `POSTGRES_*` | 单机应用服务 + 托管中间件 | 手工运行 `db-init` 或按发布流程执行迁移 |
| 预构建镜像部署 | `./deploy.sh pull --registry ... --tag ...` 后 `up --no-build` | 生产/准生产，不希望线上机器编译 | `pull` 会写入 `deploy/.env`；镜像 tag 要显式，不要依赖 `latest` 做可审计发布 |
| 多实例 orchestrator | 启动多个 `orchestrator-rs` 实例 | 更高并发 sandbox 调度 | 每实例必须设置唯一 `JOYSAFETER_INSTANCE_ID`，共享 PostgreSQL/Redis |
| 多 worker | 扩容 `worker` | 高事件量持久化 | 依赖 Redis consumer group + Postgres advisory lock；先观察 DB 写入能力 |
| 多 API / frontend | 扩容 `api` / `frontend` | 高用户流量或多入口 | API 实例需共享 Redis Pub/Sub；前端只需指向同一 API URL |

生产最小建议：

- PostgreSQL 和 Redis 使用托管服务或独立高可用实例。
- API / frontend 可放在反向代理后，只暴露 HTTPS。
- `orchestrator-rs` 的 `9090` gRPC 和 Docker socket 所在宿主机不要暴露到公网。
- 用预构建镜像部署，并固定 `BACKEND_FULL_IMAGE`、`FRONTEND_FULL_IMAGE`、`ORCHESTRATOR_RS_FULL_IMAGE`、`SKILLSPECTOR_FULL_IMAGE`。
- 根据 CPU 调整 `SKILLSPECTOR_WORKERS` / `SKILLSPECTOR_CPUS`，避免扫描挤占 orchestrator 和 worker。

## 2026-08-15 凭据升级门禁

从 `joysafeter-v2-ha` 升级到包含 `20260815_000001`（密文 envelope）和
`20260815_000002`（JSON 公共 ID 修复）的版本时，不得在应用实例仍写入凭据或
环境/会话快照的情况下直接执行 `alembic upgrade head`：

1. 确认数据库备份可恢复。
2. 保留旧环境的 `JOYSAFETER_VAULT_ENCRYPTION_KEY`，禁止自动生成替代密钥。
3. 停止 API、worker、orchestrator 和旧 HA 实例的凭据写入。
4. 使用包含新迁移的 backend 镜像执行 `alembic upgrade head`。
5. `alembic current` 必须显示 `20260815_000002 (head)`。
6. 执行 Helm README 中的密文 envelope 和 credential 公共 ID 两组结构检查，结果都必须为 0 行。
7. 启动 API/orchestrator，验证 credential 列表和实际 runner 凭据注入后再扩容。
8. 轮换历史上以明文存储的 API Key 和 Auth Token。

迁移会完整验证每一条旧 `enc:` 和当前 `enc:v1:` 密文。任何错误密钥、损坏密文、
未知 envelope 或非字符串 JSON 值都会中止并回滚，操作人员不得通过手工添加
`enc:v1:` 前缀绕过验证。

## 问题解答 / Troubleshooting

### `doctor` 和 `local` 有什么区别？

`doctor` 只做环境准备和预检，不启动容器，适合先确认 Docker、Compose、CPU 架构、SkillSpector 源码、Docker socket、端口和 Compose 配置是否闭合。它会补齐缺失的 env 文件并可能克隆 `.deps/SkillSpector`，所以不是只读命令。
`local` 会在这些预检通过后启动基础服务、执行数据库迁移，再启动完整本地栈。

### 为什么默认镜像源是 `public.ecr.aws/docker/library/`？

本地部署默认需要 Docker Official Images 的多架构 manifest。此前部分镜像源在 arm64 Docker daemon 下会解析成 amd64 单架构镜像，导致 QEMU 构建、`ring` 编译崩溃或构建极慢。`public.ecr.aws/docker/library/` 当前用于规避这个平台断层。
`--mirror huawei` 等参数只建议用于你明确验证过目标基础镜像架构的手工镜像构建；不要用它覆盖本地 `local` 的多架构默认值。

### 怎么确认当前使用的是哪个 CPU 架构？

运行：

```bash
cd deploy
./deploy.sh doctor
```

输出里的 `自动检测 Docker 架构` 是部署脚本实际采用的平台。强制指定时使用：

```bash
./deploy.sh local --arch arm64
./deploy.sh local --arch amd64
```

### SkillSpector 源码缺失怎么办？

`./deploy.sh doctor` 和 `./deploy.sh local` 会在缺失时自动克隆 NVIDIA SkillSpector 到仓库根目录的 `.deps/SkillSpector`，并写入：

```dotenv
SKILLSPECTOR_SOURCE_PATH=../.deps/SkillSpector
```

如果需要使用自己的 checkout，修改 `deploy/.env` 的 `SKILLSPECTOR_SOURCE_PATH` 即可。

### Docker socket 应该怎么配置？

orchestrator-rs 需要访问 Docker daemon socket 来创建 sandbox sibling containers。脚本会自动探测当前 Docker context。对 Colima / Docker Desktop 这类 VM 型 Docker daemon，Compose 的 bind mount 源路径由 daemon 解析，通常应使用 daemon 侧路径：

```dotenv
DOCKER_SOCKET_PATH=/var/run/docker.sock
```

原生 Linux Docker daemon 通常也是：

```dotenv
DOCKER_SOCKET_PATH=/var/run/docker.sock
```

不要把 macOS 宿主机侧的 `~/.colima/<profile>/docker.sock` 直接写进这里；那是 Docker client 连接 Colima 的转发 socket，不是 sibling container 应挂载的 daemon 侧 socket。

### 端口被占用怎么办？

`doctor` 会提示常用端口占用风险。可以在 `deploy/.env` 修改：

```dotenv
FRONTEND_PORT_HOST=3000
BACKEND_PORT_HOST=8000
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379
JOYSAFETER_GRPC_PORT_HOST=9090
WORKER_HEALTH_PORT_HOST=8002
```

### 数据库表缺失或 Alembic 迁移没跑怎么办？

`./deploy.sh local` 会自动运行 `db-init`。如果你绕过脚本手工运行 compose，需要自己执行迁移。
使用本地 Redis 时：

```bash
docker compose --profile local-redis --profile rust-orchestrator --profile init run --rm db-init
```

使用云 Redis 时不要启用 `local-redis` profile：

```bash
docker compose --profile rust-orchestrator --profile init run --rm db-init
```

### 云 Redis / 云 PostgreSQL 怎么用？

使用云 Redis 时不要启用 `local-redis` profile，并在 `deploy/.env` 设置 `REDIS_URL`。云 PostgreSQL 同理，覆盖 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`、`POSTGRES_SSL`。

生产环境建议直接使用预构建镜像并显式 tag。启动时先用 `deploy.sh pull` 拉取并写入 `deploy/.env`，再用 `up --no-build`，避免误触本地构建：

```bash
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
docker compose --profile rust-orchestrator up -d --no-build
```

## 注意

- Python orchestrator 已移除；Rust `orchestrator-rs` 当前只暴露 gRPC `9090`，API/Worker 仍有 HTTP healthcheck。
- `orchestrator` 会挂载 Docker socket 创建 sandbox，生产只能放在可信机器。
- 如果 sandbox 需要跨机器回连，修改 `deploy/.env` 里的 `JOYSAFETER_GRPC_PUBLIC_URL`。

当前仓库只保留 `deploy/docker-compose.yml` 这一份 Compose 文件。云 Redis / 云 PostgreSQL 场景仍使用同一文件，通过 `deploy/.env` 覆盖 `POSTGRES_*`、`REDIS_URL`、镜像名、端口和 `JOYSAFETER_GRPC_PUBLIC_URL`。
