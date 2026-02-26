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

## 🔄 One Person Security Dept SDK 更新（Git Subtree）

`claude-agent-sdk-python` 已 vendored 到以下目录：

`backend/app/one_person_security_dept/claude_agent_sdk_python/claude-agent-sdk-python`

推荐通过 `git subtree` 更新，不影响现有开发者工作流。

```bash
# 1) 一次性设置 upstream remote
make security-sdk-subtree-setup

# 2) 先预览更新（建议）
make security-sdk-subtree-dry-run REF=v0.1.43

# 3) 实际更新到指定 tag/branch
make security-sdk-subtree-update REF=v0.1.43
# 或
make security-sdk-subtree-update REF=main
```

也可直接运行脚本：

```bash
./scripts/update-security-sdk-subtree.sh --ref v0.1.43
```

## 🔄 One Person Security Dept OpenClaw 更新（Git Subtree）

`openclaw` 已 vendored 到以下目录：

`backend/app/one_person_security_dept/openclaw`

同样推荐通过 `git subtree` 更新：

```bash
# 1) 一次性设置 upstream remote
make openclaw-subtree-setup

# 2) 先预览更新（建议）
make openclaw-subtree-dry-run REF=v2026.2.24

# 3) 实际更新到指定 tag/branch
make openclaw-subtree-update REF=v2026.2.24
# 或
make openclaw-subtree-update REF=main
```

也可直接运行脚本：

```bash
./scripts/update-openclaw-subtree.sh --ref v2026.2.24
```


### Docker 部署 (推荐)

```bash
# 开发环境
docker-compose up -d postgres redis

# 生产环境 (多实例)
docker-compose --profile production up -d --scale app=4
```

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
