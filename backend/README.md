# JoySafeter Backend

JoySafeter 的后端服务（FastAPI + LangGraph），提供 API、鉴权、多租户、技能系统、执行引擎等能力。

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

> 推荐：直接用 Docker 启动中间件（PostgreSQL + Redis），避免本地安装依赖。

```bash
cd ../deploy
./scripts/minimal.sh
```

然后在另一个终端执行迁移：

```bash
cd backend
alembic upgrade head
```

### 4) 启动后端

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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
- 生产 IP/URL 配置最佳实践：[`deploy/PRODUCTION_IP_GUIDE.md`](../deploy/PRODUCTION_IP_GUIDE.md)

## License

Apache 2.0
