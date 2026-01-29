# Development Guide

This document provides detailed instructions for setting up and running the JoySafeter in development mode.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 20+** with npm, pnpm, or bun
- **PostgreSQL 15+**
- **Redis** (optional, for caching)
- **Docker** (optional, for containerized development)

## Quick Start

### 0. Install Pre-commit Hooks（必须）

在提交代码前，**必须**在仓库根目录执行以下脚本，将 pre-commit 与后端 UV 环境绑定并安装 Git hooks：

```bash
# 在仓库根目录执行（需已安装 uv）
./scripts/setup-pre-commit.sh
```

执行后，每次 `git commit` 将自动运行代码校验。手动全量检查：`./scripts/run-pre-commit.sh` 或 `backend/.venv/bin/python -m pre_commit run --all-files`。

### 1. Start Database Services

Using Docker (recommended):

```bash
cd backend/docker
./start.sh
```

Or manually start PostgreSQL and Redis on your system.

### 2. Start Backend

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

# Start development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at http://localhost:8000

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
bun install  # or: npm install / pnpm install

# Configure environment
cp env.example .env.local
# Edit .env.local with your settings

# Start development server
bun run dev  # or: npm run dev
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
npm run test
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
npm run lint        # ESLint
npm run type-check  # TypeScript
```

### Using Pre-commit Hooks

项目使用 pre-commit hooks 来确保代码质量。在提交代码之前，会自动运行代码检查。pre-commit 与后端 UV 环境绑定，请通过 Quick Start 中的 **安装 Pre-commit Hooks（必须）** 步骤完成安装。

#### 安装 Pre-commit Hooks

在仓库根目录执行（需已安装 uv）：

```bash
./scripts/setup-pre-commit.sh
```

该脚本会执行：`cd backend && uv sync --dev`、`uv run pre-commit install --install-hooks` 等，无需单独安装全局 pre-commit。

#### 检查内容

**后端检查：**
- **Ruff Lint** - 自动修复可修复的代码问题
- **Ruff Format** - 检查代码格式
- **Ruff Check (严格模式)** - 强制检查，不允许任何 lint 错误 (`uv run ruff check .`)
- **MyPy** - Python 类型检查

**前端检查：**
- **ESLint** - JavaScript/TypeScript 代码检查 (`pnpm run lint`)

**通用检查：**
- 行尾空白检查
- 文件末尾换行检查
- YAML/JSON 格式检查
- 大文件检查
- 合并冲突检查
- 私钥检测

#### 使用说明

**正常提交流程：**

当你执行 `git commit` 时，pre-commit hooks 会自动运行：

```bash
git add .
git commit -m "your message"
```

如果检查失败，提交会被阻止。你需要：
1. 修复报告的错误
2. 重新添加文件 (`git add .`)
3. 再次提交

**手动运行检查：**

```bash
# 检查所有文件（使用后端 UV 环境）
backend/.venv/bin/python -m pre_commit run --all-files

# 检查暂存的文件（在仓库根目录，需已通过上述脚本安装 hook）
pre-commit run

# 检查特定 hook
pre-commit run ruff --all-files
pre-commit run frontend-lint --all-files
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

**问题：`pnpm run lint` 找不到命令**

解决方案：
1. 确保已安装 pnpm：`npm install -g pnpm`
2. 确保 frontend 目录下已安装依赖：`cd frontend && pnpm install`

**问题：Hooks 运行太慢**

解决方案：
- Hooks 默认只检查更改的文件
- 如果需要跳过某些检查，可以临时使用 `--no-verify`
- 考虑优化检查配置，排除不需要检查的文件

#### 更新 Hooks

```bash
# 更新 hooks 到最新版本
backend/.venv/bin/python -m pre_commit autoupdate

# 然后重新安装
backend/.venv/bin/python -m pre_commit install --install-hooks
```

更多详细信息请参考 [Pre-commit Setup Guide](.pre-commit-setup.md)。

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

```
agent-platform/
├── backend/           # FastAPI backend
│   ├── app/
│   │   ├── api/       # REST API routes
│   │   ├── core/      # Core business logic (agents, graphs)
│   │   ├── models/    # SQLAlchemy database models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # Business services
│   │   └── utils/     # Utilities
│   ├── alembic/       # Database migrations
│   └── tests/         # Test suite
│
├── frontend/          # Next.js frontend
│   ├── app/           # App Router pages
│   ├── components/    # React components
│   ├── lib/           # Utilities, API clients
│   ├── stores/        # Zustand state stores
│   └── services/      # API service layer
│
└── deploy/            # Deployment configurations
```

## Environment Variables

See `backend/env.example` and `frontend/env.example` for all available configuration options.

### Key Backend Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | PostgreSQL host address |
| `POSTGRES_PORT` | PostgreSQL port |
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | PostgreSQL database name |
| `SECRET_KEY` | JWT signing key |
| `DEBUG` | Enable debug mode |
| `CORS_ORIGINS` | Allowed CORS origins |

### Key Frontend Variables

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend API URL |
| `BETTER_AUTH_SECRET` | Auth secret key |

## Troubleshooting

### Database Connection Issues

1. Ensure PostgreSQL is running
2. Check `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` in `.env`
3. Verify database exists: `createdb joysafeter`

### Frontend Build Errors

1. Clear Next.js cache: `rm -rf .next`
2. Reinstall dependencies: `rm -rf node_modules && npm install`
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
