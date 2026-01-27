# Development Guide

This document provides detailed instructions for setting up and running the JoySafeter in development mode.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 20+** with npm, pnpm, or bun
- **PostgreSQL 15+**
- **Redis** (optional, for caching)
- **Docker** (optional, for containerized development)

## Quick Start

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

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install

# Run on all files
pre-commit run --all-files
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

