# JoySafeter Installation Guide

Below you will find comprehensive setup instructions depending on your deployment needs.

## Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- Python 3.12+ and Node.js 20+ (only for local development)
- PostgreSQL/Redis are included in Docker deployment

## Recommended: Docker Three-Service Run

```bash
cd deploy
cp .env.example .env
cd ../backend && cp env.example .env
cd ../frontend && cp env.example .env
cd ../deploy
docker compose up -d --build
```

Access points:

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

The backend runs as `api`, `orchestrator`, and `worker`. For cloud PostgreSQL/Redis, image building, and troubleshooting, see [deploy/README.md](deploy/README.md).

## Using Pre-built Docker Images

```bash
cd deploy
cp .env.example .env
export DOCKER_REGISTRY=docker.io/jdopensource
docker compose up -d
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

# Start server
uv run uvicorn app.main:app --reload --port 8000
```

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
