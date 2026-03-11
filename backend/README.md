# JoySafeter - Backend

基于 **LangChain 1.0** 和 **LangGraph 1.0** 的智能体平台后端服务。

## 🛠️ 技术栈

- **Web 框架**: FastAPI
- **ASGI 服务器**: Uvicorn
- **数据库**: PostgreSQL + SQLAlchemy 2.0 (异步)
- **数据库迁移**: Alembic
- **包管理**: uv
- **AI 框架**: LangChain 1.0 + LangGraph 1.0

## 📦 安装

### 1. 安装 uv (如果未安装)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 创建虚拟环境并安装依赖

```bash
cd backend

# 创建虚拟环境
uv venv

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows

# 安装依赖
# 默认使用清华大学镜像源 (配置在 uv.toml 中)
# Default uses Tsinghua mirror (configured in uv.toml)
uv sync
```

**PyPI 镜像源配置**

项目默认使用清华大学镜像源 (`https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`) 以加速依赖下载。您可以通过以下方式自定义：

1. **环境变量** (优先级最高):
   ```bash
   export UV_INDEX_URL=https://pypi.org/simple  # 使用官方源
   export UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple  # 使用清华源
   ```

2. **`.env` 文件**: 在 `.env` 中设置 `UV_INDEX_URL` 变量

3. **配置文件**:
   - 编辑 `pyproject.toml` 中的 `[tool.uv]` 部分 (推荐)
   - 编辑 `uv.toml` 中的 `[index]` 部分

**PyPI Mirror Configuration**

The project uses Tsinghua mirror by default. You can customize it via:
- Environment variable: `UV_INDEX_URL` (highest priority)
- `.env` file: Set `UV_INDEX_URL` variable
- Configuration file: `pyproject.toml` or `uv.toml`

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的配置
# 可选的: 设置 UV_INDEX_URL 自定义 PyPI 镜像源
# Optional: Set UV_INDEX_URL to customize PyPI mirror
```

### 4. 初始化数据库

```bash
# 创建 PostgreSQL 数据库
createdb joysafeter

# 运行迁移
alembic upgrade head
```

## 🚀 运行

### ⚠️ 重要提示

**必须使用 `uv run` 来运行，确保使用正确的虚拟环境！**

### 开发模式

```bash
#使用 uv run
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 生产模式

```bash
# 使用 uv run
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# 或使用 uvloop (更高性能)
uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --loop uvloop \
    --http httptools
```

## 📚 API 文档

启动服务后访问:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc



### 统一响应格式

```json
{
  "success": true,
  "code": 200,
  "message": "Success",
  "data": { ... },
  "timestamp": "2024-12-04T00:00:00Z"
}
```

### 分页响应格式

```json
{
  "success": true,
  "code": 200,
  "message": "Success",
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20,
    "pages": 5
  },
  "timestamp": "2024-12-04T00:00:00Z"
}
```

## 🔧 数据库迁移

### 创建迁移

```bash
alembic revision --autogenerate -m "描述"
```

### 运行迁移

```bash
alembic upgrade head
```

### 回滚迁移

```bash
alembic downgrade -1
```

## 🧪 测试

```bash
# 安装开发依赖
uv sync --dev

# 运行测试
pytest

# 带覆盖率
pytest --cov=app
```


### Docker 部署（推荐）

详尽的 Docker 部署与场景化启动说明请参考：
- 项目部署总览：`deploy/README.md`
- 生产环境与前后端 URL/IP 配置最佳实践：`deploy/PRODUCTION_IP_GUIDE.md`

常用命令速查：

```bash
# 一键开发快速启动（自动初始化 .env 与数据库）
cd deploy && ./quick-start.sh

# 开发场景（包含构建与初始化）
cd deploy && ./scripts/dev.sh

# 仅启动中间件（PostgreSQL + Redis），用于本地直接运行后端/前端
cd deploy && ./scripts/minimal.sh
# 或：cd deploy && ./scripts/start-middleware.sh

# 生产场景（服务器）：使用预构建镜像
cd deploy && ./scripts/prod.sh
# 跳过 MCP 服务：cd deploy && ./scripts/prod.sh --skip-mcp
# 手动 Compose：cd deploy && docker-compose -f docker-compose.prod.yml up -d
```

生产环境安全提示：
- 在 `backend/.env` 中设置强随机的 `SECRET_KEY`
- 在 `backend/.env` 中设置强随机且固定不变的 `CREDENTIAL_ENCRYPTION_KEY`（用于加密模型凭据；未配置或变更将导致重启后历史凭据无法解密）
- 关闭 `DEBUG`
- 通过反向代理启用 HTTPS 与合理的防火墙规则（数据库、Redis、MCP 端口不对公网暴露）

### 部署架构

```
                    ┌─────────┐
                    │  Nginx  │
                    │ (LB)    │
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
    │  App 1  │    │  App 2  │    │  App N  │
    │ (8000)  │    │ (8000)  │    │ (8000)  │
    └────┬────┘    └────┬────┘    └────┬────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         ┌────▼────┐          ┌────▼────┐
         │ Postgres │          │  Redis  │
         │ (状态)   │          │ (缓存)  │
         └─────────┘          └─────────┘
```
## 📄 License

Apache 2.0
