# Development Guide

This document provides detailed instructions for setting up and running the JoySafeter in development mode.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 20+** with [bun](https://bun.sh)
- **PostgreSQL 15+**
- **Redis** (required for task wakeups and event stream mode; `deploy/local-test.sh` starts it)
- **Docker** (optional, for containerized development)

## Quick Start

### 0. Install Pre-commit Hooks

在提交代码前，使用后端开发环境安装 Git hooks：

```bash
cd backend
uv sync --dev
uv run pre-commit install --install-hooks
```

执行后，每次 `git commit` 将自动运行代码校验。手动全量检查：

```bash
backend/.venv/bin/python -m pre_commit run --all-files
```

### 1. One-command local test

```bash
cd deploy
./local-test.sh
```

This starts PostgreSQL, Redis, Python `api`, Rust `orchestrator-rs`, Python `worker`, and the
frontend for local testing. The orchestrator process is the Rust binary under
`backend/app/joysafeter_orchestrator_rs`.

### 2. Start Backend Manually

For manual local development, run the Python API, Rust orchestrator, and Python worker as
separate processes.

```bash
cd backend

# Create and activate virtual environment
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
uv sync --dev

# Configure environment
cp env.example .env
# Edit .env with your settings
# Note: UV uses Tsinghua mirror by default (configured in uv.toml)
# You can customize via UV_INDEX_URL environment variable

# Run database migrations
alembic upgrade head

# Start API
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000.

In additional terminals, start the Rust orchestrator and worker:

```bash
cd backend/app/joysafeter_orchestrator_rs
JOYSAFETER_GRPC_HOST=0.0.0.0 JOYSAFETER_GRPC_PORT=9090 cargo run --release

cd backend
JOYSAFETER_SERVICE_ROLE=worker \
uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1
```

#### PyPI 镜像源配置 (PyPI Mirror Configuration)

项目默认使用清华大学镜像源 (`https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`) 以加速依赖安装。配置方式：

1. **环境变量** (优先级最高):
   ```bash
   export UV_INDEX_URL=https://pypi.org/simple  # 使用官方源
   ```

2. **`.env` 文件**: 在 `.env` 中设置 `UV_INDEX_URL` 变量

3. **配置文件**:
   - 编辑 `backend/pyproject.toml` 中的 `[tool.uv]` 部分 (推荐)
   - 编辑 `backend/uv.toml` 中的 `[index]` 部分

The project uses Tsinghua mirror by default. You can customize it via:
- Environment variable: `UV_INDEX_URL` (highest priority)
- `.env` file: Set `UV_INDEX_URL` variable
- Configuration file: `pyproject.toml` or `uv.toml`

### 3. Start Frontend

```bash
cd frontend

# Install dependencies
bun install

# Configure environment
cp env.example .env.local
# Edit .env.local with your settings

# Start development server
bun run dev
```

Frontend will be available at http://localhost:3000

## Development Workflow

### Running Tests

```bash
# Backend tests
cd backend
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html

# Frontend tests
cd frontend
bun run test
```

### Code Formatting & Linting

```bash
# Backend
cd backend
ruff check .        # Lint
ruff format .       # Format
mypy app            # Type check

# Frontend
cd frontend
bun run lint        # ESLint
bun run type-check  # TypeScript
```

### Using Pre-commit Hooks

项目使用 pre-commit hooks 统一执行通用文件检查、后端 Ruff 和前端 lint/type/format 检查。

#### 安装 Pre-commit Hooks

在仓库根目录执行（需已安装 uv）：

```bash
cd backend
uv sync --dev
uv run pre-commit install --install-hooks
```

#### 检查内容

**后端检查：**
- **Ruff Lint** - 自动修复可修复的代码问题
- **Ruff Format** - 检查代码格式
- **Ruff Check (严格模式)** - 强制检查，不允许任何 lint 错误 (`uv run ruff check .`)
- **MyPy** - Python 类型检查

**前端检查：**
- **ESLint** - JavaScript/TypeScript 代码检查 (`bun run lint`)

**通用检查：**
- 行尾空白检查
- 文件末尾换行检查
- YAML/JSON 格式检查
- 大文件检查
- 合并冲突检查
- 私钥检测

#### 使用说明

**手动运行检查：**

```bash
# 检查所有文件
backend/.venv/bin/python -m pre_commit run --all-files

# 检查特定 hook
backend/.venv/bin/python -m pre_commit run ruff --all-files
backend/.venv/bin/python -m pre_commit run frontend-lint --all-files
```

**跳过 Hooks（不推荐）：**

如果确实需要跳过 hooks（例如紧急修复），可以使用：

```bash
git commit --no-verify -m "emergency fix"
```

**注意：** 跳过 hooks 会绕过代码质量检查，可能导致 CI 失败。

#### 故障排除

**问题：`uv run ruff check` 找不到命令**

解决方案：
1. 确保已安装 uv：`curl -LsSf https://astral.sh/uv/install.sh | sh`
2. 确保 backend 目录下有虚拟环境：`cd backend && uv venv`
3. 确保已安装依赖：`cd backend && uv sync --dev`

**问题：`bun run lint` 找不到命令**

解决方案：
1. 确保已安装 bun：`curl -fsSL https://bun.sh/install | bash`
2. 确保 frontend 目录下已安装依赖：`cd frontend && bun install`

#### 更新 Hooks

```bash
# 更新 hooks 到最新版本
backend/.venv/bin/python -m pre_commit autoupdate

# 然后重新安装
backend/.venv/bin/python -m pre_commit install --install-hooks
```

### Database Migrations

```bash
cd backend

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## Architecture Overview

The runtime is split into Python `api`, Rust `orchestrator-rs`, and Python `worker` services.
`JOYSAFETER_SERVICE_ROLE` selects only the Python service role (`api` or `worker`). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

```
JoySafeter/
├── backend/app/
│   ├── joysafeter_api/            # API service: REST routers, SSE, WS notifications, auth
│   ├── joysafeter_orchestrator_rs/# Rust orchestrator: gRPC AgentBridge, scheduler, sandbox lifecycle, event bus
│   ├── joysafeter_worker/         # Worker: Redis Stream consumer → event persistence
│   ├── joysafeter_domain/         # SQLAlchemy models, schemas, services, state machines
│   └── joysafeter_shared/         # Cross-service foundation (config, llm, security, storage, cache)
│
├── frontend/          # Next.js App Router UI (product surface under /managed/**)
│   ├── app/           # App Router pages
│   ├── components/    # React components
│   ├── lib/           # Utilities, API clients
│   └── stores/        # Zustand state stores
│
├── proto/             # AgentBridge gRPC contract (joysafeter.proto)
├── sandbox-runner/    # Rust workspace: types / runtime / runner / ctl
├── skills/            # Pre-built skill packs
└── deploy/            # Docker Compose + deployment configs
```

## Environment Variables

环境变量按"唯一真相源"原则管理：

| 文件 | 角色 | 说明 |
|------|------|------|
| `backend/env.example` | 后端唯一真相源 | 所有后端变量的完整定义、默认值与注释 |
| `frontend/env.example` | 前端唯一真相源 | 所有前端变量的完整定义、默认值与注释 |
| `deploy/.env.example` | 部署差异覆盖层 | 仅列出与开发默认值不同的覆盖项和部署专属配置 |

新增变量只需改对应的 `env.example`，`deploy/.env.example` 只在部署需要不同默认值时才添加。

### Key Backend Variables

| Variable | Description |
|----------|-------------|
| `JOYSAFETER_SERVICE_ROLE` | Python service role: `api` or `worker`; the orchestrator is the Rust binary |
| `POSTGRES_HOST` | PostgreSQL host address |
| `POSTGRES_PORT` | PostgreSQL port |
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | PostgreSQL database name |
| `REDIS_URL` | Redis connection URL (event streams, pub/sub, task queue) |
| `SECRET_KEY` | JWT signing key |
| `CREDENTIAL_ENCRYPTION_KEY` | AES-256-GCM key for encrypting Secrets and Vault credentials |
| `DEBUG` | Enable debug mode |
| `CORS_ORIGINS` | Allowed CORS origins |

### Key Frontend Variables

完整列表见 `frontend/env.example`。以下为常用变量：

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Optional backend API URL override; defaults to `http://localhost:8000` in `lib/api-client.ts` |
| `NEXT_PUBLIC_APP_URL` | Public frontend URL used for generated links in Docker/production |
| `NEXT_PUBLIC_MAX_UPLOAD_FILE_BYTES` | Browser-side upload size limit; keep aligned with backend `JOYSAFETER_MAX_UPLOAD_FILE_BYTES` |
| `NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED` | Shows the email/password signup entry point in the auth UI; backend auth policy still applies |
| `NEXT_PUBLIC_CSP_*` | CSP security policy: `NECESSARY_DOMAIN`, `CONNECT_SRC_EXTRA`, `FRAME_SRC_EXTRA`, `REPORT_URI`, `WHITELIST`, `ALLOW_EMBED`, `ENABLE_CSP_IN_DEV`, `FORCE_HTTPS` |
| `SSO_DEFAULT_PROVIDER` | Auto-redirect to this SSO provider on the login page |
| `DISABLE_REGISTRATION` / `EMAIL_VERIFICATION_ENABLED` | Frontend server auth UI flags; backend enforcement still comes from backend auth config |

## Troubleshooting

### Database Connection Issues

1. Ensure PostgreSQL is running
2. Check `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` in `.env`
3. Verify database exists: `createdb joysafeter`

### Frontend Build Errors

1. Clear Next.js cache: `rm -rf .next`
2. Reinstall dependencies: `rm -rf node_modules && bun install`
3. Check Node.js version: `node --version` (should be 20+)

### Import Errors

1. Ensure virtual environment is activated
2. Run `uv sync` to install all dependencies
3. Check Python version: `python --version` (should be 3.12+)

## IDE Setup

### VS Code

Recommended extensions:
- Python (Microsoft)
- Pylance
- ESLint
- Prettier
- Tailwind CSS IntelliSense

### PyCharm

1. Set Python interpreter to `.venv/bin/python`
2. Enable Django/FastAPI support
3. Configure Ruff as external tool

## Getting Help

- Check [GitHub Issues](https://github.com/jd-opensource/JoySafeter/issues)
- Read the [Contributing Guide](CONTRIBUTING.md)
- Review [API Documentation](http://localhost:8000/docs)
