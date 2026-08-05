# JoySafeter 部署

当前项目尚未正式上线。部署目标是：**本地闭环简单、重复部署快速、上线前配置显式**。

## 最短路径

### 首次从源码部署

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`local` 会完成环境准备、核心镜像构建、PostgreSQL/Redis 启动、数据库迁移和完整服务启动。
缺少本地 SkillSpector 源码时，脚本默认检出 `v2.5.1`；可通过 `SKILLSPECTOR_REPO_REF` 覆盖。

### 日常快速启动或更新

```bash
cd deploy
./deploy.sh up
```

`up` 复用 `deploy/.env` 中配置的现有镜像，不重新构建，也不准备 SkillSpector 源码；它仍会执行环境预检和数据库迁移，适合重启、配置调整或镜像已提前准备好的场景。

### 使用镜像仓库部署

```bash
cd deploy
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
./deploy.sh up
```

`pull` 会拉取 backend、frontend、orchestrator-rs 和 SkillSpector，并把完整镜像名写入 `deploy/.env`。固定版本 tag，不要在正式环境依赖 `latest`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `./deploy.sh doctor` | 准备 env 并检查 Docker、架构、端口、Compose 和 Docker socket |
| `./deploy.sh local` | 从源码构建核心镜像并启动完整本地栈 |
| `./deploy.sh up` | 复用现有镜像，执行迁移后快速启动或更新 |
| `./deploy.sh status` | 查看服务状态 |
| `./deploy.sh logs [service...]` | 跟随全部或指定服务日志 |
| `./deploy.sh restart [service...]` | 重启全部或指定服务 |
| `./deploy.sh down` | 停止服务并保留数据卷 |
| `./deploy.sh build [options]` | 构建镜像 |
| `./deploy.sh push [options]` | 构建并推送镜像 |
| `./deploy.sh pull [options]` | 拉取镜像并同步 `deploy/.env` |

完整参数以脚本为准：

```bash
./deploy.sh --help
```

## 服务与端口

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| frontend | `http://localhost:3000` | Web 界面 |
| api | `http://localhost:8000` | HTTP API |
| API docs | `http://localhost:8000/docs` | OpenAPI UI |
| orchestrator-rs | `localhost:9090` | 内部 gRPC，不应暴露公网 |
| worker | `localhost:8002` | 健康检查端口 |
| PostgreSQL | `localhost:5432` | 本地 profile 默认启用 |
| Redis | `localhost:6379` | 本地 profile 默认启用 |

运行时拓扑、职责和数据流见 [`../docs/ARCHITECTURE_CN.md`](../docs/ARCHITECTURE_CN.md)。

## 配置

首次运行会按示例文件补齐：

- `deploy/.env`
- `backend/.env`
- `frontend/.env`

优先修改 `deploy/.env`。常用配置包括：

```dotenv
BACKEND_PORT_HOST=8000
FRONTEND_PORT_HOST=3000
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379
JOYSAFETER_GRPC_PORT_HOST=9090

BACKEND_FULL_IMAGE=joysafeter-backend:latest
FRONTEND_FULL_IMAGE=joysafeter-frontend:latest
ORCHESTRATOR_RS_FULL_IMAGE=joysafeter-orchestrator-rs:latest
SKILLSPECTOR_FULL_IMAGE=joysafeter-skillspector:latest
```

Apple Silicon、amd64 服务器或远程 Docker daemon 通常由脚本自动识别。需要强制架构时：

```bash
./deploy.sh local --arch arm64
./deploy.sh up --arch amd64
```

## 部署模式

### 本地完整栈

使用 `local` 或 `up`。脚本启用 `local-redis` 与 `rust-orchestrator` profiles，并自动运行迁移。

### 云 PostgreSQL / Redis

在 `deploy/.env` 设置 `POSTGRES_*` 与 `REDIS_URL`。不要启用 `local-redis` profile；迁移和启动可直接使用同一 Compose 文件：

```bash
docker compose --profile rust-orchestrator --profile init run --rm db-init
docker compose --profile rust-orchestrator up -d --no-build
```

### 高可用

多实例约束与扩容建议见 [`HA.md`](./HA.md)。在项目上线前，必须完成 [`../docs/PRODUCTION_READINESS.md`](../docs/PRODUCTION_READINESS.md) 中的发布门禁。

## 上线前最低要求

- 使用不可变版本 tag，并记录镜像与 Git SHA 的对应关系。
- PostgreSQL、Redis、对象存储和密钥服务使用独立持久化方案。
- API 与 frontend 仅通过 HTTPS 暴露；gRPC、Docker socket 和数据库不暴露公网。
- 验证数据库迁移、备份恢复、回滚和数据卷恢复流程。
- 为 API、worker、orchestrator-rs、SkillSpector 和数据库配置监控告警。
- 在目标 CPU 架构上执行一次完整部署和 Agent 任务冒烟测试。

## 故障排查

### 环境或 Compose 配置异常

```bash
./deploy.sh doctor
```

### 镜像不存在

`up` 不构建镜像。先执行以下任一方式：

```bash
./deploy.sh local
# 或
./deploy.sh pull --registry registry.example.com/your-org --tag <version>
```

### 数据库表缺失

本地 Redis：

```bash
docker compose --profile local-redis --profile rust-orchestrator --profile init run --rm db-init
```

云 Redis：

```bash
docker compose --profile rust-orchestrator --profile init run --rm db-init
```

### 端口冲突

修改 `deploy/.env` 中对应的 `*_PORT_HOST`。`doctor` 会报告常用端口监听情况。

### Sandbox 无法创建

确认 `DOCKER_SOCKET_PATH` 指向 Docker daemon 侧 socket。Docker Desktop、Colima 和原生 Linux 通常使用：

```dotenv
DOCKER_SOCKET_PATH=/var/run/docker.sock
```

### Agent 任务缺少运行镜像

核心服务镜像不包含 Agent runtime 镜像。按需构建或拉取：

```bash
./deploy.sh build --claudecode-only --arch arm64
./deploy.sh pull --runtime-only --registry registry.example.com/your-org --tag <version>
```

仓库只维护 `deploy/docker-compose.yml` 一份 Compose 定义，避免多套部署文件漂移。
