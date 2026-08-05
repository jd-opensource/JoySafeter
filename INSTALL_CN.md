# JoySafeter 安装

JoySafeter 当前尚未正式上线。完整栈统一使用 Docker Compose 部署。

## 环境要求

- Docker 20.10+
- Docker Compose 2+
- 完整本地栈建议至少 4 核 CPU、8 GB 内存
- 仅宿主机开发模式需要 Python 3.12+、Rust 和 Bun

## 首次本地部署

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`local` 会构建核心镜像，启动 PostgreSQL 与 Redis，执行数据库迁移，并启动 frontend、API、worker、Rust orchestrator、Envoy 和 SkillSpector。

访问地址：

- 前端：`http://localhost:3000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

## 快速重启或更新

本地已有镜像后：

```bash
cd deploy
./deploy.sh up
```

`up` 不构建镜像，也不准备 SkillSpector 源码，但仍执行环境预检和数据库迁移。

## 部署预构建镜像

```bash
cd deploy
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
./deploy.sh up
```

非本地开发环境必须使用不可变版本 tag。

## 日常运维

```bash
cd deploy
./deploy.sh status
./deploy.sh logs api worker
./deploy.sh restart frontend
./deploy.sh down
```

## 宿主机开发

需要直接运行 Python、Rust 和前端进程时，使用 [`DEVELOPMENT.md`](DEVELOPMENT.md)，或执行：

```bash
cd deploy
./local-test.sh
```

## 后续文档

- 部署模式与故障排查：[`deploy/README.md`](deploy/README.md)
- 运行时架构：[`docs/ARCHITECTURE_CN.md`](docs/ARCHITECTURE_CN.md)
- 上线前门禁：[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)
