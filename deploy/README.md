# JoySafeter 构建与部署

`deploy/deploy.sh` 是完整栈的唯一构建和部署入口。当前支持边界：

- 使用 `deploy/docker-compose.yml` 启动完整栈。
- 每次命令只处理一个目标架构：`amd64` 或 `arm64`。
- `local` 面向首次本地安装，`up` 面向已有镜像的重复启动。
- `deploy/k8s/` 仅用于 orchestrator 开发验证，不是完整生产部署方案。
- 宿主机开发统一使用 [`local-test.sh`](./local-test.sh)，说明见 [`../DEVELOPMENT.md`](../DEVELOPMENT.md)。

## 首次本地部署

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`local` 会完成以下步骤：

1. 创建缺失的 `deploy/.env`、`backend/.env` 和 `frontend/.env`。
2. 生成并同步 `SECRET_KEY`、`JOYSAFETER_VAULT_ENCRYPTION_KEY` 和数据库密码；已有有效密钥不会被替换。
   Vault 密钥缺失或格式无效时后端会拒绝启动，系统不会降级为明文凭据存储。
3. 自动识别 Docker daemon 的 `amd64` 或 `arm64` 架构。
4. 准备 SkillSpector 源码。
5. 构建 backend、frontend、orchestrator-rs、SkillSpector 和默认 Claude Code runtime。
6. 启动 PostgreSQL、Redis，执行 Alembic 迁移。
7. 启动完整 Compose 服务。

启动命令会等待 PostgreSQL、Redis、API、Worker、Rust orchestrator、Envoy 和前端通过
健康检查后才返回成功。任一关键服务未就绪时，命令返回非零并输出服务状态及关键日志，
不会再把 crash-looping 的控制平面报告为启动成功。

访问地址：

| 服务 | 默认地址 |
| --- | --- |
| Frontend | `http://localhost:3000` |
| API | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |
| Orchestrator gRPC | `localhost:9090`，供 sandbox 容器访问 |

> Orchestrator gRPC 9090 默认绑定 `0.0.0.0`（由 `JOYSAFETER_GRPC_BIND_HOST` 控制），
> 该端口无内置认证。非单机环境务必用防火墙限制来源，或改绑 `127.0.0.1`。

## 编译与构建

```bash
cd deploy

./deploy.sh build                    # 核心服务镜像（backend/frontend/orchestrator-rs/skillspector）
./deploy.sh build --all              # 核心服务 + Claude Code/Codex/Pi runtime
./deploy.sh build --pi-only          # 单独构建某个 agent runtime（另有 --claudecode-only/--codex-only）
./deploy.sh build --runtime-only     # 一并构建 claudecode/codex/pi 三个 runtime
./deploy.sh build --all --arch amd64 # 指定目标架构（--arch amd64|arm64，或等价的 --platform linux/amd64）
```

`build`（不加参数）只出核心服务；agent runtime（claudecode/codex/pi）需用 `--all`、
`--runtime-only` 或对应 `--*-only` 显式构建，`local` 仅自动构建默认 Claude Code runtime。
`--native-only` 构建可选 Native runtime，需本地私有 tgz、仅单架构，不在正式发布范围内。
默认目标架构来自 Docker daemon，完整镜像集不在一次命令中同时构建多个架构；CI 应分别构建
`amd64`、`arm64`，再合并镜像 manifest。

## 发布镜像

在构建机上使用不可变 tag，并显式指定目标架构：

```bash
cd deploy
./deploy.sh push --all \
  --registry registry.example.com/your-org \
  --tag <version-or-git-sha> \
  --arch amd64
```

另一目标架构使用独立构建任务执行相同命令。正式发布的 manifest、签名、SBOM 和漏洞扫描由
CI release workflow 负责，不在本地脚本中重复实现。

## 部署已发布镜像

在目标主机执行：

```bash
cd deploy
./deploy.sh doctor
./deploy.sh pull --all \
  --registry registry.example.com/your-org \
  --tag <version-or-git-sha> \
  --arch amd64
./deploy.sh up --arch amd64
```

`pull` 会把镜像名同步到 `deploy/.env`；`up` 不重新构建，但会执行预检和数据库迁移。

## 配置唯一来源

| 文件 | 用途 |
| --- | --- |
| `backend/env.example` | 后端变量、默认值和说明 |
| `frontend/env.example` | 前端变量、默认值和说明 |
| `deploy/.env.example` | Compose、镜像和部署差异配置 |

首次运行会生成对应 `.env` 文件。新增变量应先进入所属组件的 `env.example`，只有部署默认值
不同或 Compose 专用时才写入 `deploy/.env.example`。

## 日常运维

```bash
./deploy.sh status
./deploy.sh logs
./deploy.sh logs api worker
./deploy.sh restart frontend
./deploy.sh down
```

`down` 保留命名数据卷。如需清空本地数据，明确执行：

```bash
docker compose down -v
```

## 常见问题

### `up` 提示镜像不存在

`up` 不构建镜像。首次本地安装执行 `./deploy.sh local`；镜像部署先执行 `./deploy.sh pull`。

### 端口冲突

修改 `deploy/.env` 中对应的 `*_PORT_HOST`，再执行 `./deploy.sh doctor`。

### Sandbox runtime 不存在

agent runtime 未随核心 `build` 构建。参见上文[「编译与构建」](#编译与构建)，按需执行
`--claudecode-only` / `--codex-only` / `--pi-only`（Apple Silicon 加 `--arch arm64`）。

### 遗留 `DATABASE_URL`

本地 Compose 的数据库配置唯一来源是 `deploy/.env` 中的 `POSTGRES_*` 参数。若检测到旧版
内置 PostgreSQL `DATABASE_URL`，`doctor`、`local` 和 `up` 会自动删除该字段并输出脱敏
告警。外部数据库也必须通过 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、
`POSTGRES_PASSWORD` 和 `POSTGRES_DB` 配置；非空外部 `DATABASE_URL` 会被明确拒绝。

### Sandbox 无法创建

确认 `deploy/.env` 中的 `DOCKER_SOCKET_PATH` 指向 Docker daemon 可见的 socket。Docker Desktop、
Colima 和原生 Linux 通常使用 `/var/run/docker.sock`。

完整命令参数以以下输出为准：

```bash
./deploy.sh --help
```
