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

访问地址：

| 服务 | 默认地址 |
| --- | --- |
| Frontend | `http://localhost:3000` |
| API | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |
| Orchestrator gRPC | `localhost:9090`，仅内部使用 |

## 编译与构建

```bash
cd deploy

./deploy.sh build                    # 核心服务镜像
./deploy.sh build --all              # 核心服务 + Claude Code/Codex runtime
./deploy.sh build --all --arch amd64 # 指定目标架构
```

默认目标架构来自 Docker daemon。完整镜像集不在一次命令中同时构建多个架构；CI 应分别构建
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

```bash
./deploy.sh build --claudecode-only --arch amd64
```

Apple Silicon 使用 `--arch arm64`。`local` 会自动构建默认 Claude Code runtime。

### Sandbox 无法创建

确认 `deploy/.env` 中的 `DOCKER_SOCKET_PATH` 指向 Docker daemon 可见的 socket。Docker Desktop、
Colima 和原生 Linux 通常使用 `/var/run/docker.sock`。

完整命令参数以以下输出为准：

```bash
./deploy.sh --help
```
