# JoySafeter 安装

JoySafeter 当前只维护一条完整安装路径：**Docker Compose + `deploy/deploy.sh`**。
宿主机 Python、Rust、Bun 进程仅用于开发，不作为部署方式。

## 环境要求

- Docker Engine 或 Docker Desktop
- Docker Compose v2
- Git
- 建议至少 4 核 CPU、8 GB 内存
- 支持 `linux/amd64` 与 `linux/arm64`

## 首次安装

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` 检查 Docker、Compose、端口、环境文件和目标架构，不启动服务。
`local` 会准备环境文件，生成并同步稳定密钥与数据库密码，构建核心服务与默认 Claude Code runtime，
执行数据库迁移并启动完整栈。已有有效密钥不会被覆盖。

启动后访问：

- 前端：`http://localhost:3000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

## 后续操作

```bash
cd deploy
./deploy.sh up                 # 使用已有镜像启动或更新
./deploy.sh status             # 查看状态
./deploy.sh logs api worker    # 查看日志
./deploy.sh down               # 停止服务，保留数据卷
```

## 文档入口

- 构建、镜像发布和部署：[`deploy/README.md`](deploy/README.md)
- 宿主机开发与测试：[`DEVELOPMENT.md`](DEVELOPMENT.md)
- 上线前门禁：[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)

脚本参数以 `./deploy.sh --help` 为准，其他文档不重复维护完整参数表。
