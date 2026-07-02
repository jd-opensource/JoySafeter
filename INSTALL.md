# JoySafeter Installation Guide

Below you will find comprehensive setup instructions depending on your deployment needs.

## Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- Python 3.12+ and Node.js 20+ (only for local development)
- PostgreSQL/Redis are included in Docker deployment

## Recommended: Docker Compose

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy

# Choose the orchestrator implementation by profile:
docker compose --profile python-orchestrator up -d --build
# or the Rust orchestrator:
# docker compose --profile rust-orchestrator up -d --build
```

Access points:

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

The backend is one codebase split into three services by `JOYSAFETER_SERVICE_ROLE` and
deployed as separate containers: `api`, `orchestrator`, and `worker`, alongside PostgreSQL,
Redis, Envoy (per-sandbox egress proxy), and skillspector (skill security scanner). You must
pick exactly one orchestrator profile — the Python and Rust orchestrators share the same
container name and gRPC port `9090`, so they cannot run at the same time. For cloud
PostgreSQL/Redis, image building, and troubleshooting, see [deploy/README.md](deploy/README.md).

## Using Pre-built Docker Images

```bash
cd deploy
cp .env.example .env
# Point the image variables at the published registry, then start with a profile.
docker compose --profile python-orchestrator up -d
```

## Local Test One-Command Startup

```bash
cd deploy
./local-test.sh
```


## Environment Check

```bash
cd deploy
docker compose config
```

## Manual Setup

<details>
<summary><strong>Backend Setup</strong></summary>

```bash
cd backend

# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create environment and install dependencies
uv venv && source .venv/bin/activate
uv sync

# Configure environment
cp env.example .env
# Edit .env with your settings

# Initialize database
createdb joysafeter
alembic upgrade head

# Start server (single-process, all three roles via JOYSAFETER_SERVICE_ROLE=all)
uv run uvicorn app.main:app --reload --port 8000
```

> For a split, multi-service run (matching the compose deployment) start each role with its
> own entrypoint — `app.joysafeter_api.main:app`, `app.joysafeter_orchestrator.main:app`,
> `app.joysafeter_worker.main:app` — and set `JOYSAFETER_SERVICE_ROLE` accordingly.
> See [DEVELOPMENT.md](DEVELOPMENT.md).

</details>

<details>
<summary><strong>Frontend Setup</strong></summary>

```bash
cd frontend

# Install dependencies
bun install  # or: npm install

# Configure environment
cp env.example .env.local

# Start development server
bun run dev
```

</details>

## Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
